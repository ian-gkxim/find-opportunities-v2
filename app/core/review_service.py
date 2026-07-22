"""Review Service — fresh-context LLM critique orchestrator.

Dispatches independent reviewer passes over generated outreach materials,
applies structured edits deterministically, and manages bounded review cycles
with graceful degradation on LLM failure.

Requirements: 1.1, 3.1, 3.5
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.core.voice_asset import BehavioralProfileAsset, VoiceAsset

from app.core.review_models import (
    CritiqueCategory,
    CritiqueParseError,
    CritiqueResponse,
    CycleLog,
    DraftMaterial,
    EditOutcome,
    EditReason,
    EditSkipReason,
    NarrativeFinding,
    ReasoningLog,
    ReviewLLMError,
    ReviewResult,
    ReviewStatus,
    StructuredEdit,
)


class ReviewService:
    """Orchestrates fresh-context LLM critique of drafted materials.

    The Review_Service sits between the Personalization_Engine's material
    generation and the claim-grounding-verification step. It dispatches
    structured critiques via the LLM_Router and applies machine-applicable
    edits with bounded cycle control.

    Dependencies:
        llm_router: LLM_Router for provider-agnostic LLM dispatch
        schema_registry: SchemaRegistry for review technique configuration
        review_repository: ReviewRepository for persistence of reasoning logs
        personalization_engine: PersonalizationEngine for quality score recomputation
    """

    CRITIQUE_TIMEOUT: float = 60.0  # seconds per LLM attempt
    MAX_RETRIES: int = 2  # additional retry attempts after first failure
    DISPATCH_DEADLINE: float = 10.0  # must dispatch within 10s of draft completion
    BATCH_CONCURRENCY: int = 3  # max concurrent critique requests

    def __init__(
        self,
        llm_router: object,  # LLMRouter from app.integrations.llm_router
        schema_registry: object,  # SchemaRegistry from app.core.schema_registry
        review_repository: object,  # ReviewRepository from app.repositories
        personalization_engine: object,  # PersonalizationEngine from app.core
    ) -> None:
        self._llm = llm_router
        self._schema = schema_registry
        self._db = review_repository
        self._personalization = personalization_engine
        self._semaphore = asyncio.Semaphore(self.BATCH_CONCURRENCY)

    # ─── PUBLIC INTERFACE ─────────────────────────────────────────────────────

    async def review_material(
        self,
        draft_material: DraftMaterial,
        prospect: object,
        beneficiary: object,
        enrichment: object,
        opportunity_description: str,
        voice_asset: VoiceAsset | None = None,
        behavioral_profile: BehavioralProfileAsset | None = None,
    ) -> ReviewResult:
        """Execute review cycle(s) on a single draft material.

        Looks up the review technique via SchemaRegistry, then executes
        1..max_review_cycles iterations. Each cycle dispatches a fresh-context
        critique, applies structured edits, optionally dispatches narrative
        revision, recomputes quality score, and records a CycleLog.

        Preconditions:
            - draft_material.content is non-empty
            - enrichment is the prospect's current EnrichmentRecord
            - prepare_technique has a review_technique reference in schema

        Postconditions:
            - Returns ReviewResult with status in {reviewed, unreviewed, review_failed}
            - reasoning_log is persisted to database
            - Material transitions to post-prepare pipeline state

        Args:
            draft_material: The generated material to critique.
            prospect: The target prospect (company/contact).
            beneficiary: The beneficiary whose assets ground the critique.
            enrichment: The prospect's enrichment record.
            opportunity_description: Description of the opportunity being pursued.
            voice_asset: Optional Voice_Asset for voice-mismatch detection during review.
            behavioral_profile: Optional Behavioral_Profile_Asset for tone checks.

        Returns:
            ReviewResult with revised content, status, and full reasoning log.
        """
        started_at = datetime.now(timezone.utc)

        # Look up review technique config via SchemaRegistry
        review_technique = self._schema.get_review_technique_for_prepare(
            draft_material.prepare_technique_id
        )
        if review_technique is None:
            # No review technique configured — skip review (no-op)
            completed_at = datetime.now(timezone.utc)
            reasoning_log = ReasoningLog(
                material_id=draft_material.id,
                prepare_technique_id=draft_material.prepare_technique_id,
                review_technique_id="none",
                cycles=[],
                total_cycles_executed=0,
                max_cycles_configured=0,
                final_review_status=ReviewStatus.REVIEWED,
                started_at=started_at,
                completed_at=completed_at,
            )
            return ReviewResult(
                material_id=draft_material.id,
                revised_content=draft_material.content,
                review_status=ReviewStatus.REVIEWED,
                reasoning_log=reasoning_log,
                quality_score_final=draft_material.quality_score,
                total_edits_applied=0,
            )

        max_cycles = min(review_technique.max_review_cycles, 3)  # Hard cap at 3
        categories = [CritiqueCategory(cat) for cat in review_technique.critique_categories]

        # Extract beneficiary assets for grounding checks
        beneficiary_assets = self._extract_beneficiary_assets(beneficiary)

        current_text = draft_material.content
        current_quality_score = draft_material.quality_score
        cycles: list[CycleLog] = []
        total_edits_applied = 0

        try:
            for cycle_num in range(1, max_cycles + 1):
                cycle_start = time.monotonic()
                quality_before = current_quality_score

                # 1. Dispatch critique
                critique = await self._dispatch_critique(
                    current_text,
                    opportunity_description,
                    enrichment,
                    beneficiary,
                    categories,
                    material_id=draft_material.id,
                    voice_asset=voice_asset,
                    behavioral_profile=behavioral_profile,
                )

                # 2. Apply structured edits
                current_text, edit_outcomes = self._apply_structured_edits(
                    current_text, critique.structured_edits, beneficiary_assets
                )

                edits_applied = sum(1 for o in edit_outcomes if o.applied)
                edits_skipped = sum(
                    1
                    for o in edit_outcomes
                    if not o.applied
                    and o.skip_reason == EditSkipReason.AMBIGUOUS_OR_STALE_TARGET
                )
                edits_discarded = sum(
                    1
                    for o in edit_outcomes
                    if not o.applied
                    and o.skip_reason == EditSkipReason.UNGROUNDED_SUGGESTION
                )
                total_edits_applied += edits_applied

                # 3. Dispatch narrative revision if there are findings
                current_text = await self._dispatch_narrative_revision(
                    current_text, critique.narrative_findings
                )

                # 4. Recompute quality score
                current_quality_score = self._compute_quality_score(
                    current_text, draft_material
                )

                # 5. Record cycle log
                duration_ms = int((time.monotonic() - cycle_start) * 1000)
                cycle_log = CycleLog(
                    cycle_number=cycle_num,
                    edits_applied=edits_applied,
                    edits_skipped=edits_skipped,
                    edits_discarded=edits_discarded,
                    narrative_findings_by_category={
                        cat: len(findings)
                        for cat, findings in critique.narrative_findings.items()
                    },
                    quality_score_before=quality_before,
                    quality_score_after=current_quality_score,
                    duration_ms=duration_ms,
                    skipped_edits=[
                        o
                        for o in edit_outcomes
                        if not o.applied
                        and o.skip_reason == EditSkipReason.AMBIGUOUS_OR_STALE_TARGET
                    ],
                    discarded_edits=[
                        o
                        for o in edit_outcomes
                        if not o.applied
                        and o.skip_reason == EditSkipReason.UNGROUNDED_SUGGESTION
                    ],
                )
                cycles.append(cycle_log)

            # All cycles complete — assemble result
            final_status = ReviewStatus.REVIEWED

        except ReviewLLMError:
            # Total critique failure — graceful degradation
            final_status = ReviewStatus.UNREVIEWED
            current_text = draft_material.content  # Revert to original
            if hasattr(self._db, "mark_unreviewed"):
                await self._db.mark_unreviewed(draft_material.id)

        completed_at = datetime.now(timezone.utc)

        reasoning_log = ReasoningLog(
            material_id=draft_material.id,
            prepare_technique_id=draft_material.prepare_technique_id,
            review_technique_id=review_technique.id,
            cycles=cycles,
            total_cycles_executed=len(cycles),
            max_cycles_configured=max_cycles,
            final_review_status=final_status,
            started_at=started_at,
            completed_at=completed_at,
        )

        # Persist reasoning log
        if hasattr(self._db, "save_reasoning_log"):
            await self._db.save_reasoning_log(reasoning_log)

        return ReviewResult(
            material_id=draft_material.id,
            revised_content=current_text,
            review_status=final_status,
            reasoning_log=reasoning_log,
            quality_score_final=current_quality_score,
            total_edits_applied=total_edits_applied,
        )

    async def review_batch(
        self,
        materials: list[DraftMaterial],
        prospect: object,
        beneficiary: object,
        enrichment: object,
        opportunity_description: str,
        voice_asset: VoiceAsset | None = None,
        behavioral_profile: BehavioralProfileAsset | None = None,
    ) -> list[ReviewResult]:
        """Process a batch of materials with bounded concurrency (max 3).

        Uses asyncio.Semaphore to limit concurrent critique requests,
        preventing LLM API quota exhaustion during bulk prepare runs.

        Args:
            materials: List of draft materials to review.
            prospect: The target prospect for all materials.
            beneficiary: The beneficiary whose assets ground the critique.
            enrichment: The prospect's enrichment record.
            opportunity_description: Description of the opportunity.
            voice_asset: Optional Voice_Asset for voice-mismatch detection.
            behavioral_profile: Optional Behavioral_Profile_Asset for tone checks.

        Returns:
            List of ReviewResult, one per input material (order preserved).
        """
        tasks = [
            self._review_with_semaphore(
                m, prospect, beneficiary, enrichment, opportunity_description,
                voice_asset=voice_asset, behavioral_profile=behavioral_profile,
            )
            for m in materials
        ]
        return await asyncio.gather(*tasks)

    # ─── CONCURRENCY CONTROL ─────────────────────────────────────────────────

    async def _review_with_semaphore(
        self,
        draft_material: DraftMaterial,
        prospect: object,
        beneficiary: object,
        enrichment: object,
        opportunity_description: str,
        voice_asset: VoiceAsset | None = None,
        behavioral_profile: BehavioralProfileAsset | None = None,
    ) -> ReviewResult:
        """Acquire semaphore before dispatching critique.

        Ensures at most BATCH_CONCURRENCY (3) critique requests are
        in-flight simultaneously.
        """
        async with self._semaphore:
            return await self.review_material(
                draft_material, prospect, beneficiary, enrichment, opportunity_description,
                voice_asset=voice_asset, behavioral_profile=behavioral_profile,
            )

    # ─── CRITIQUE DISPATCH ────────────────────────────────────────────────────

    async def _dispatch_critique(
        self,
        material_text: str,
        opportunity_description: str,
        enrichment: object,
        beneficiary: object,
        categories: list[CritiqueCategory],
        material_id: str = "unknown",
        voice_asset: VoiceAsset | None = None,
        behavioral_profile: BehavioralProfileAsset | None = None,
    ) -> CritiqueResponse:
        """Dispatch fresh-context critique to LLM_Router with retry logic.

        Sends the critique prompt (built via _build_fresh_context_prompt) to
        the LLM with a 60-second timeout. Retries up to MAX_RETRIES times on
        timeout, error, or parse failure. Raises ReviewLLMError after all
        attempts are exhausted.

        Preconditions:
            - Context contains ONLY: material text, opportunity description,
              enrichment record, beneficiary profile assets
            - Does NOT include drafting pass conversation/prompt/reasoning

        Postconditions:
            - Returns CritiqueResponse with all four categories populated
            - Raises ReviewLLMError after MAX_RETRIES+1 total attempts exhausted

        Args:
            material_text: The current material content to critique.
            opportunity_description: Description of the opportunity.
            enrichment: Prospect's enrichment record.
            beneficiary: Beneficiary with profile assets.
            categories: The critique categories to evaluate.
            material_id: Identifier for error reporting context.
            voice_asset: Optional Voice_Asset for voice-mismatch detection.
            behavioral_profile: Optional Behavioral_Profile_Asset for tone checks.

        Returns:
            Parsed CritiqueResponse from the reviewer LLM.

        Raises:
            ReviewLLMError: After all retry attempts are exhausted.
        """
        prompt = self._build_fresh_context_prompt(
            material_text, opportunity_description, enrichment, beneficiary, categories,
            voice_asset=voice_asset, behavioral_profile=behavioral_profile,
        )

        total_attempts = self.MAX_RETRIES + 1  # 3 total attempts (1 initial + 2 retries)
        last_error: Exception | None = None

        for attempt in range(total_attempts):
            try:
                raw_response = await self._llm.dispatch_critique(
                    prompt, timeout=self.CRITIQUE_TIMEOUT
                )
                return self._parse_critique_response(raw_response, material_id)
            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
                # Parse failure — counts toward retry limit
                last_error = e
                continue
            except CritiqueParseError as e:
                # Structured parse failure from _parse_critique_response
                last_error = e
                continue
            except Exception as e:
                # Timeout or API error — retry
                last_error = e
                continue

        # All attempts exhausted
        raise ReviewLLMError(
            message=f"Critique dispatch failed after {total_attempts} attempts: {last_error}",
            material_id=material_id,
            attempts=total_attempts,
        )

    def _parse_critique_response(
        self, raw: dict, material_id: str = "unknown"
    ) -> CritiqueResponse:
        """Parse raw LLM JSON response into a CritiqueResponse dataclass.

        Validates structure and converts nested dicts into StructuredEdit and
        NarrativeFinding dataclass instances. Raises CritiqueParseError if the
        response does not match the expected schema.

        Args:
            raw: Parsed JSON dict from the LLM response.
            material_id: Identifier for error context.

        Returns:
            Validated CritiqueResponse with all four categories populated.

        Raises:
            CritiqueParseError: If the response structure is invalid.
        """
        try:
            # Extract and convert structured_edits
            raw_edits = raw.get("structured_edits")
            if not isinstance(raw_edits, list):
                raise CritiqueParseError(
                    message="Missing or invalid 'structured_edits' field: expected a list",
                    material_id=material_id,
                    attempts=0,
                )

            structured_edits: list[StructuredEdit] = []
            for edit_dict in raw_edits:
                structured_edits.append(
                    StructuredEdit(
                        target_material_id=edit_dict["target_material_id"],
                        old_string=edit_dict["old_string"],
                        new_string=edit_dict["new_string"],
                        reason=EditReason(edit_dict["reason"]),
                        category=CritiqueCategory(edit_dict["category"]),
                    )
                )

            # Extract and convert narrative_findings
            raw_findings = raw.get("narrative_findings")
            if not isinstance(raw_findings, dict):
                raise CritiqueParseError(
                    message="Missing or invalid 'narrative_findings' field: expected a dict",
                    material_id=material_id,
                    attempts=0,
                )

            # Validate all four CritiqueCategory keys are present
            required_categories = {cat.value for cat in CritiqueCategory}
            present_categories = set(raw_findings.keys())
            missing = required_categories - present_categories
            if missing:
                raise CritiqueParseError(
                    message=f"narrative_findings missing required categories: {sorted(missing)}",
                    material_id=material_id,
                    attempts=0,
                )

            narrative_findings: dict[CritiqueCategory, list[NarrativeFinding]] = {}
            for category in CritiqueCategory:
                category_findings = raw_findings.get(category.value, [])
                if not isinstance(category_findings, list):
                    raise CritiqueParseError(
                        message=f"narrative_findings['{category.value}'] must be a list",
                        material_id=material_id,
                        attempts=0,
                    )
                findings_list: list[NarrativeFinding] = []
                for finding_dict in category_findings:
                    findings_list.append(
                        NarrativeFinding(
                            category=category,
                            description=finding_dict["description"],
                            flagged_passage=finding_dict.get("flagged_passage"),
                        )
                    )
                narrative_findings[category] = findings_list

            return CritiqueResponse(
                structured_edits=structured_edits,
                narrative_findings=narrative_findings,
            )

        except CritiqueParseError:
            raise
        except (KeyError, ValueError, TypeError) as e:
            raise CritiqueParseError(
                message=f"Failed to parse critique response: {e}",
                material_id=material_id,
                attempts=0,
            ) from e

    # ─── EDIT APPLICATION ─────────────────────────────────────────────────────

    def _apply_structured_edits(
        self,
        material_text: str,
        edits: list[StructuredEdit],
        beneficiary_assets: set[str],
    ) -> tuple[str, list[EditOutcome]]:
        """Apply edits sequentially, validating each against current text.

        Rules:
            1. old_string must match exactly once in current material text
            2. If zero or >1 matches: skip with AMBIGUOUS_OR_STALE_TARGET
            3. If edit introduces content not in beneficiary assets: discard
               with UNGROUNDED_SUGGESTION
            4. Applied edits modify the running text for subsequent edits

        Args:
            material_text: The current material content.
            edits: Ordered list of structured edits to apply.
            beneficiary_assets: Set of grounded asset strings for validation.

        Returns:
            Tuple of (revised_text, list of EditOutcome for telemetry).
        """
        current_text = material_text
        outcomes: list[EditOutcome] = []

        for edit in edits:
            # Count occurrences of old_string in current text
            count = current_text.count(edit.old_string)

            if count != 1:
                # Zero or multiple matches: skip with AMBIGUOUS_OR_STALE_TARGET
                outcomes.append(
                    EditOutcome(
                        edit=edit,
                        applied=False,
                        skip_reason=EditSkipReason.AMBIGUOUS_OR_STALE_TARGET,
                    )
                )
                continue

            # Check if new_string introduces ungrounded content
            if self._is_ungrounded(edit.new_string, edit.old_string, beneficiary_assets):
                outcomes.append(
                    EditOutcome(
                        edit=edit,
                        applied=False,
                        skip_reason=EditSkipReason.UNGROUNDED_SUGGESTION,
                    )
                )
                continue

            # Apply the edit (exactly 1 match guaranteed)
            current_text = current_text.replace(edit.old_string, edit.new_string, 1)
            outcomes.append(EditOutcome(edit=edit, applied=True))

        return current_text, outcomes

    def _is_ungrounded(
        self,
        new_string: str,
        old_string: str,
        beneficiary_assets: set[str],
    ) -> bool:
        """Check if a replacement introduces content not grounded in beneficiary assets.

        Extracts words from new_string that are not present in old_string, then
        checks whether any significant new terms (longer than 3 characters and
        not common English filler words) are absent from all beneficiary assets.

        A term is considered grounded if it appears as a substring in any
        beneficiary asset string (case-insensitive).

        Args:
            new_string: The proposed replacement text.
            old_string: The original text being replaced.
            beneficiary_assets: Set of grounded asset strings from the beneficiary profile.

        Returns:
            True if the edit introduces ungrounded content, False otherwise.
        """
        if not beneficiary_assets:
            # If no assets to check against, cannot verify grounding — allow edit
            return False

        # Common English filler words that don't constitute substantive claims
        common_words = {
            "the", "and", "for", "are", "but", "not", "you", "all", "can",
            "had", "her", "was", "one", "our", "out", "has", "have", "been",
            "from", "they", "will", "with", "this", "that", "what", "when",
            "make", "like", "time", "very", "your", "just", "know", "take",
            "come", "more", "some", "than", "them", "want", "give", "most",
            "only", "over", "such", "also", "into", "year", "back", "then",
            "about", "would", "there", "their", "which", "could", "other",
            "after", "these", "where", "those", "being", "while", "through",
            "should", "each", "well", "does", "much", "many", "both",
        }

        # Tokenize: extract words (lowercased) from both strings
        new_words = set(self._tokenize(new_string))
        old_words = set(self._tokenize(old_string))

        # Words introduced by the edit (not in old_string)
        introduced_words = new_words - old_words

        # Filter to significant words: longer than 3 chars and not common filler
        significant_new_words = {
            word for word in introduced_words
            if len(word) > 3 and word.lower() not in common_words
        }

        if not significant_new_words:
            # No significant new content introduced
            return False

        # Build a lowercase representation of all beneficiary assets for matching
        assets_lower = " ".join(asset.lower() for asset in beneficiary_assets)

        # Check if any significant new word is absent from all beneficiary assets
        for word in significant_new_words:
            if word.lower() not in assets_lower:
                return True

        return False

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        """Split text into word tokens, stripping punctuation.

        Args:
            text: The text to tokenize.

        Returns:
            List of lowercase word tokens.
        """
        import re
        return re.findall(r"[a-zA-Z0-9]+(?:[-'][a-zA-Z0-9]+)*", text.lower())

    # ─── NARRATIVE REVISION ───────────────────────────────────────────────────

    async def _dispatch_narrative_revision(
        self,
        material_text: str,
        findings: dict[CritiqueCategory, list[NarrativeFinding]],
    ) -> str:
        """Single LLM call to revise flagged passages based on Narrative_Findings.

        The prompt instructs targeted revision ONLY of flagged passages,
        preserving all other content verbatim. On failure after retries,
        returns original material text (graceful degradation).

        Args:
            material_text: The current material content after structured edits.
            findings: Narrative findings grouped by critique category.

        Returns:
            Revised material text, or original text on failure.
        """
        # Check if there are any actual findings to revise
        has_findings = any(
            len(items) > 0 for items in findings.values()
        )
        if not has_findings:
            return material_text

        # Build revision prompt
        prompt = self._build_revision_prompt(material_text, findings)

        # Try with retries, graceful degradation on failure
        for _attempt in range(self.MAX_RETRIES + 1):
            try:
                revised = await self._llm.dispatch_revision(
                    prompt, timeout=self.CRITIQUE_TIMEOUT
                )
                if revised and revised.strip():
                    return revised.strip()
            except Exception:
                continue

        # All attempts failed — graceful degradation: return original
        return material_text

    def _build_revision_prompt(
        self,
        material_text: str,
        findings: dict[CritiqueCategory, list[NarrativeFinding]],
    ) -> str:
        """Construct the revision prompt from material text and narrative findings.

        Includes clear instructions to revise ONLY flagged passages while
        preserving all other content verbatim.

        Args:
            material_text: The current material content.
            findings: Narrative findings grouped by critique category.

        Returns:
            Complete prompt string for the revision LLM.
        """
        findings_text: list[str] = []
        for category, items in findings.items():
            for finding in items:
                finding_entry = f"- [{category.value}] {finding.description}"
                if finding.flagged_passage:
                    finding_entry += (
                        f'\n  Flagged passage: "{finding.flagged_passage}"'
                    )
                findings_text.append(finding_entry)

        if not findings_text:
            return ""

        prompt = (
            "You are revising outreach material based on reviewer feedback.\n\n"
            "IMPORTANT INSTRUCTIONS:\n"
            "- Revise ONLY the specific passages flagged below\n"
            "- Preserve ALL other content exactly as-is (verbatim)\n"
            "- Do not add new claims, skills, or credentials not in the original\n"
            "- Return the COMPLETE revised material text\n\n"
            f"<current_material>\n{material_text}\n</current_material>\n\n"
            "<narrative_findings>\n"
            + "\n".join(findings_text)
            + "\n</narrative_findings>\n\n"
            "Return the complete revised material with only the flagged passages improved."
        )
        return prompt

    # ─── PROMPT CONSTRUCTION ──────────────────────────────────────────────────

    def _build_fresh_context_prompt(
        self,
        material_text: str,
        opportunity_description: str,
        enrichment: object,
        beneficiary: object,
        categories: list[CritiqueCategory],
        voice_asset: VoiceAsset | None = None,
        behavioral_profile: BehavioralProfileAsset | None = None,
    ) -> str:
        """Construct the critique prompt with strict context boundaries.

        Includes ONLY:
            - Draft material text (XML-tagged inline)
            - Opportunity description
            - Enrichment_Record (firmographics, technographics, intents, seniority)
            - Beneficiary profile assets
            - Voice_Asset reference (when present)

        Excludes:
            - Drafting pass conversation history
            - Drafting prompt/instructions
            - Drafting reasoning/chain-of-thought

        When voice_asset is provided, the TONE_STYLE category instructions
        are extended to include:
        - The full Voice_Asset definition (register, rhythm, vocabulary)
        - The Behavioral_Profile interpersonal style (if present)
        - Explicit instruction to flag voice mismatches

        The reviewer is instructed to:
        1. Check if the draft's register matches Voice_Asset.register
        2. Check sentence rhythm aligns with sentence_length preference
        3. Flag any vocabulary_avoid items found in the draft
        4. For behavioral profile: flag tone that contradicts the
           interpersonal_style
        5. Express mechanical fixes as StructuredEdits (reason=STYLE)
        6. Express subjective concerns as NarrativeFindings (category=TONE_STYLE)

        Args:
            material_text: The draft material to critique.
            opportunity_description: Description of the opportunity.
            enrichment: Prospect's enrichment record.
            beneficiary: Beneficiary with profile assets.
            categories: The critique categories to evaluate against.
            voice_asset: Optional sender voice definition for voice-mismatch
                detection. None if not configured.
            behavioral_profile: Optional behavioral profile with interpersonal
                style. None if not configured.

        Returns:
            Complete prompt string for the reviewer LLM.

        Validates: Requirements 3.1, 3.2
        """
        # ── Extract enrichment data ───────────────────────────────────────────
        enrichment_sections: dict[str, object] = {}
        if isinstance(enrichment, dict):
            enrichment_sections["firmographics"] = enrichment.get("firmographics", {})
            enrichment_sections["technographics"] = enrichment.get("technographics", {})
            enrichment_sections["intent_signals"] = enrichment.get("intent_signals", [])
            enrichment_sections["contact_seniority"] = enrichment.get("contact_seniority", "")
        else:
            enrichment_sections["firmographics"] = getattr(enrichment, "firmographics", {})
            enrichment_sections["technographics"] = getattr(enrichment, "technographics", {})
            enrichment_sections["intent_signals"] = getattr(enrichment, "intent_signals", [])
            enrichment_sections["contact_seniority"] = getattr(
                enrichment, "contact_seniority", ""
            )

        enrichment_str = json.dumps(enrichment_sections, default=str, indent=2)

        # ── Extract beneficiary assets ────────────────────────────────────────
        if isinstance(beneficiary, dict):
            beneficiary_assets = beneficiary.get("profile_assets", beneficiary)
        else:
            beneficiary_assets = getattr(beneficiary, "profile_assets", None)
            if beneficiary_assets is None:
                beneficiary_assets = getattr(beneficiary, "assets", beneficiary)

        beneficiary_str = json.dumps(beneficiary_assets, default=str, indent=2)

        # ── Build category list for instructions ──────────────────────────────
        category_descriptions = {
            CritiqueCategory.MISSED_KEYWORDS: (
                "missed_keywords — keywords or requirements from the opportunity "
                "that are absent or underemphasised in the draft"
            ),
            CritiqueCategory.COMPANY_ANGLES: (
                "company_angles — company-specific angles derivable from the "
                "Enrichment Record (firmographics, technographics, intent signals) "
                "that the draft fails to leverage"
            ),
            CritiqueCategory.REFRAMING: (
                "reframing — passive or generic statements that should be rewritten "
                "as action-oriented, specific claims"
            ),
            CritiqueCategory.TONE_STYLE: (
                "tone_style — tone or style issues (overly formal, too casual, "
                "inconsistent register, clichés)"
            ),
        }

        # ── Extend TONE_STYLE with voice instructions when voice_asset present ─
        voice_instructions_block = ""
        if voice_asset is not None:
            voice_critique_text = self._build_voice_critique_instructions(
                voice_asset, behavioral_profile
            )
            # Extend the TONE_STYLE category description
            category_descriptions[CritiqueCategory.TONE_STYLE] = (
                "tone_style — tone or style issues (overly formal, too casual, "
                "inconsistent register, clichés). ADDITIONALLY: check the draft "
                "against the sender's Voice_Asset definition below for voice "
                "compliance"
            )
            voice_instructions_block = f"""

<voice_asset_reference>
{voice_critique_text}
</voice_asset_reference>

Voice-mismatch reporting instructions:
- For MECHANICAL voice fixes (e.g., replacing a prohibited word, adjusting sentence \
length, fixing register): express as a StructuredEdit with reason="style" and \
category="tone_style". Quote the exact offending passage as old_string and provide \
the corrected replacement as new_string.
- For SUBJECTIVE voice concerns (e.g., overall register feels off, draft doesn't \
match exemplar tone, behavioral profile contradiction): express as a \
NarrativeFinding in the tone_style category. Describe the mismatch and quote the \
flagged passage (or use null if it's a holistic concern)."""

        categories_block = "\n".join(
            f"  - {category_descriptions[cat]}" for cat in categories
        )

        # ── Construct the prompt ──────────────────────────────────────────────
        prompt = f"""\
You are an independent reviewer evaluating outreach materials for quality, \
relevance, and grounding. You have NOT seen the drafting conversation, prompt \
template, or reasoning chain that produced this material. Evaluate it solely \
based on the context provided below.

<draft_material>
{material_text}
</draft_material>

<opportunity>
{opportunity_description}
</opportunity>

<enrichment_record>
{enrichment_str}
</enrichment_record>

<beneficiary_assets>
{beneficiary_str}
</beneficiary_assets>

Critique the draft material against these four categories:
{categories_block}
{voice_instructions_block}

Instructions:
- For each category, identify specific issues and suggest concrete improvements.
- For structured edits, quote the EXACT text from the draft as `old_string` and \
provide a replacement `new_string`. Classify the reason as one of: keyword_match, \
company_angle, reframing, style.
- For narrative findings, describe the issue and quote the flagged passage exactly \
(use null if the finding is about an omission).
- Report on ALL four categories even if no issues found. Return empty arrays for \
clean categories.
- Do NOT reference any drafting conversation, prompt instructions, or reasoning \
chain. Evaluate only based on the context provided.

Return your response as valid JSON matching this schema exactly:

```json
{{
  "structured_edits": [
    {{
      "target_material_id": "<material identifier>",
      "old_string": "<exact quote from draft>",
      "new_string": "<replacement text>",
      "reason": "<keyword_match | company_angle | reframing | style>",
      "category": "<missed_keywords | company_angles | reframing | tone_style>"
    }}
  ],
  "narrative_findings": {{
    "missed_keywords": [
      {{
        "description": "<description of the issue>",
        "flagged_passage": "<exact quote or null>"
      }}
    ],
    "company_angles": [],
    "reframing": [],
    "tone_style": []
  }}
}}
```

All four keys in `narrative_findings` MUST be present. Use empty arrays `[]` when \
a category has no findings."""

        return prompt

    # ─── HELPER METHODS ───────────────────────────────────────────────────────

    def _extract_beneficiary_assets(self, beneficiary: object) -> set[str]:
        """Extract asset strings from the beneficiary object for grounding checks.

        Handles both dict and object-style beneficiaries, extracting profile
        assets that represent grounded claims (skills, achievements, credentials,
        client names, metrics).

        Args:
            beneficiary: The beneficiary object or dict with profile assets.

        Returns:
            Set of asset strings for use in grounding validation.
        """
        assets: set[str] = set()

        if isinstance(beneficiary, dict):
            profile_assets = beneficiary.get("profile_assets", beneficiary)
        else:
            profile_assets = getattr(beneficiary, "profile_assets", None)
            if profile_assets is None:
                profile_assets = getattr(beneficiary, "assets", None)
            if profile_assets is None:
                return assets

        # Handle different profile_assets structures
        if isinstance(profile_assets, dict):
            for key, value in profile_assets.items():
                if isinstance(value, str):
                    assets.add(value)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            assets.add(item)
                        elif isinstance(item, dict):
                            # Extract string values from nested dicts
                            for v in item.values():
                                if isinstance(v, str):
                                    assets.add(v)
        elif isinstance(profile_assets, list):
            for item in profile_assets:
                if isinstance(item, str):
                    assets.add(item)
                elif isinstance(item, dict):
                    for v in item.values():
                        if isinstance(v, str):
                            assets.add(v)
        elif isinstance(profile_assets, str):
            assets.add(profile_assets)

        return assets

    def _compute_quality_score(self, text: str, draft_material: DraftMaterial) -> int:
        """Recompute quality score after edits have been applied.

        Uses a simple heuristic based on content length and structure as a
        placeholder. The full integration with the PersonalizationEngine's
        scoring model will come in a later task.

        The heuristic considers:
        - Content length relative to original (penalizes significant shrinkage)
        - Paragraph structure (rewards well-structured content)
        - Base score from the original draft material

        Args:
            text: The current (possibly revised) material text.
            draft_material: The original draft material for baseline comparison.

        Returns:
            Quality score as an integer 0-100.
        """
        base_score = draft_material.quality_score
        original_length = len(draft_material.content)

        if original_length == 0:
            return base_score

        # Length ratio: penalize significant content loss
        length_ratio = len(text) / original_length
        if length_ratio < 0.5:
            # Significant content loss — score drops
            length_penalty = -10
        elif length_ratio > 1.5:
            # Significant content bloat — small penalty
            length_penalty = -3
        else:
            # Reasonable length change — slight improvement assumed from edits
            length_penalty = 2

        # Paragraph structure bonus: well-structured content gets a small boost
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        structure_bonus = min(len(paragraphs), 5)  # Cap bonus at 5 points

        # Compute final score, clamped to 0-100
        computed = base_score + length_penalty + structure_bonus
        return max(0, min(100, computed))

    # ─── VOICE CRITIQUE ──────────────────────────────────────────────────────

    def _build_voice_critique_instructions(
        self,
        voice_asset: VoiceAsset,
        behavioral_profile: BehavioralProfileAsset | None,
    ) -> str:
        """Build the voice-specific critique instructions block.

        Constructs a text block appended to the TONE_STYLE category section
        that instructs the reviewer to check the draft against the sender's
        declared Voice_Asset and optional Behavioral_Profile_Asset.

        The block includes:
        - Voice compliance check (register, sentence_length, first_person_usage)
        - Vocabulary the sender prefers (flag if absent from draft)
        - Vocabulary the sender avoids (flag if present in draft)
        - Exemplar passages as reference for desired voice
        - Behavioral profile check section (when behavioral_profile is present)

        Args:
            voice_asset: The sender's structured voice definition.
            behavioral_profile: Optional behavioral profile with interpersonal
                style and avoid_impressions. None if not configured.

        Returns:
            Instruction text block for the reviewer LLM.

        Validates: Requirements 3.1
        """
        lines = [
            "VOICE COMPLIANCE CHECK:",
            f"The sender's declared register is: {voice_asset.register.value}",
            f"Sentence length preference: {voice_asset.sentence_length.value}",
            f"First-person usage: {voice_asset.first_person_usage.value}",
            "",
            "Vocabulary the sender PREFERS (flag if absent from draft):",
        ]
        for word in voice_asset.vocabulary_prefer:
            lines.append(f"  - {word}")
        lines.append("")
        lines.append("Vocabulary the sender AVOIDS (flag if present in draft):")
        for word in voice_asset.vocabulary_avoid:
            lines.append(f"  - {word}")
        lines.append("")
        lines.append("EXEMPLAR PASSAGES (the draft should sound like these):")
        for ex in voice_asset.exemplar_passages:
            lines.append(f'  "{ex.text}"')

        if behavioral_profile:
            lines.extend([
                "",
                "BEHAVIORAL PROFILE CHECK:",
                f"Interpersonal style: {behavioral_profile.interpersonal_style}",
                f"Communication traits: {', '.join(behavioral_profile.communication_traits)}",
                "Flag the draft if its tone contradicts this profile. Examples:",
            ])
            for avoid in behavioral_profile.avoid_impressions:
                lines.append(f"  - Flag if draft sounds: {avoid}")

        return "\n".join(lines)
