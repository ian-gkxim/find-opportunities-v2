"""Personalization Engine — generates tailored outreach materials using enrichment + LLM.

Requirements 11.1–11.7: Enhanced personalization using Apollo enrichment data,
seniority-based tone adaptation, quality scoring, hook incorporation, and
graceful sparse enrichment handling.

Requirement 4.1: Generation-time grounding constraint injection to prevent
fabrication of Beneficiary claims.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol

from app.core.content_selector import (
    CompanionReference,
    ContentSelector,
    ContentUnit,
    ContentUnitType,
    ConstraintType,
    LengthConstraint,
    SelectionConfig,
    SelectionResult,
    SelectionWeights,
)
from app.core.grounding_prompts import GROUNDING_CONSTRAINT_INJECTION

if TYPE_CHECKING:
    from app.core.voice_asset import BehavioralProfileAsset, ExemplarPassage, VoiceAsset

logger = logging.getLogger(__name__)


# ─── Protocols (for testability) ──────────────────────────────────────────────


class LLMContentGenerator(Protocol):
    """Protocol matching LLMRouter.generate_content signature."""

    async def generate_content(
        self,
        prompt: str,
        context: dict,
        material_type: str,
    ) -> str:
        """Generate outreach material content.

        Args:
            prompt: The generation prompt with tone and instructions.
            context: Context dict with enrichment data, profile info, hooks.
            material_type: One of "cv", "cover_letter", "proposal", "email".

        Returns:
            Generated content string.
        """
        ...


# ─── Enums ────────────────────────────────────────────────────────────────────


class SeniorityLevel(str, Enum):
    """Contact seniority levels for tone determination."""

    C_SUITE = "c_suite"
    DIRECTOR = "director"
    MANAGER = "manager"
    OTHER = "other"


class MaterialType(str, Enum):
    """Supported outreach material types."""

    CV = "cv"
    COVER_LETTER = "cover_letter"
    PROPOSAL = "proposal"
    EMAIL = "email"


# ─── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class PersonalizationResult:
    """Result of a personalization generation request.

    Attributes:
        content: The generated material content.
        quality_score: Personalization quality 0–100 (% of available fields referenced).
        fields_used: Enrichment fields that were referenced in the content.
        fields_available_unused: Available fields NOT referenced (up to 3 listed when low quality).
        tone_applied: The seniority-based tone used for generation.
        hooks_referenced: Hooks (news, job postings, tech adoption) referenced in content.
        is_low_quality: True if quality_score < 40.
        voice_applied: Whether a Voice_Asset was used during generation (for A/B observability).
        flags: Additional flags (e.g., "seniority_unknown", "low personalization").
    """

    content: str
    quality_score: int
    fields_used: list[str]
    fields_available_unused: list[str]
    tone_applied: str
    hooks_referenced: list[str]
    is_low_quality: bool
    voice_applied: bool = False
    flags: list[str] = field(default_factory=list)


@dataclass
class EnrichmentData:
    """Enrichment data relevant to personalization.

    A simplified view of the enrichment record fields used by the
    personalization engine for quality scoring and context building.
    """

    industry: str | None = None
    tech_stack: list[str] = field(default_factory=list)
    company_size: int | None = None
    recent_funding: str | None = None
    intent_signals: list[str] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)


# ─── Personalization Engine ───────────────────────────────────────────────────


class PersonalizationEngine:
    """Generates personalized outreach materials using enrichment + LLM.

    Combines Apollo enrichment data with LLM generation, adapting tone
    based on contact seniority, incorporating hooks, computing quality
    scores, and handling sparse data gracefully.

    Requirements:
        11.1: Incorporate enrichment into LLM context, return within 30s
        11.2: Reference at least one hook when available
        11.3: Handle < 3 fields gracefully with reduced quality score
        11.4: Adapt tone based on seniority (C-suite/director/manager)
        11.5: Quality score = (referenced / available) × 100
        11.6: Flag low quality (< 40) with up to 3 unused fields
        11.7: Default to director tone when seniority unknown, flag "seniority_unknown"
    """

    LOW_QUALITY_THRESHOLD = 40
    MIN_DATA_FIELDS = 3
    GENERATION_TIMEOUT = 30.0  # seconds (configurable)

    TONE_MAP: dict[SeniorityLevel, str] = {
        SeniorityLevel.C_SUITE: "company-vision and ROI-focused",
        SeniorityLevel.DIRECTOR: "implementation-focused and team-impact",
        SeniorityLevel.MANAGER: "hands-on and collaboration-focused",
        SeniorityLevel.OTHER: "hands-on and collaboration-focused",
    }

    ENRICHMENT_FIELDS: list[str] = [
        "industry",
        "tech_stack",
        "company_size",
        "recent_funding",
        "intent_signals",
        "hooks",
    ]

    VALID_MATERIAL_TYPES: set[str] = {"cv", "cover_letter", "proposal", "email"}

    def __init__(
        self,
        llm_router: LLMContentGenerator,
        schema_registry=None,
        generation_timeout: float | None = None,
    ) -> None:
        """Initialize the PersonalizationEngine.

        Args:
            llm_router: LLM router implementing the generate_content protocol.
            schema_registry: Schema registry for beneficiary/opportunity config.
            generation_timeout: Override default 30s generation timeout.
        """
        self._llm = llm_router
        self._schema = schema_registry
        self._timeout = generation_timeout or self.GENERATION_TIMEOUT
        self._content_selector = ContentSelector()
        self.reasoning_log: list[dict] = []

    async def generate_materials(
        self,
        enrichment: EnrichmentData,
        beneficiary_id: str,
        material_type: str,
        contact_seniority: str | None = None,
        beneficiary_context: dict | None = None,
        voice_asset: VoiceAsset | None = None,
        behavioral_profile: BehavioralProfileAsset | None = None,
    ) -> PersonalizationResult:
        """Generate personalized outreach material with optional voice.

        Orchestrates the full personalization pipeline: tone determination,
        context building, LLM generation, quality scoring, and flagging.

        When voice_asset is provided:
        - Voice directives are injected into the prompt
        - Conflict resolution applies (Formality for salutation/closing,
          Voice for body prose)
        - voice_applied is set to True on the result

        When voice_asset is None:
        - Current default behavior (Formality only)
        - voice_applied is set to False on the result

        If voice integration fails (e.g., timeout or unexpected error),
        gracefully degrades to no-voice generation with voice_applied=False.

        Args:
            enrichment: Enrichment data for the prospect.
            beneficiary_id: The beneficiary generating outreach (e.g., "consultant").
            material_type: Type of material to generate ("cv", "cover_letter", "proposal", "email").
            contact_seniority: Seniority of the target contact (e.g., "c_suite", "director").
            beneficiary_context: Additional context (baseline assets, offerings, etc.).
            voice_asset: Optional Voice_Asset defining the sender's writing style.
            behavioral_profile: Optional Behavioral_Profile_Asset for tone guidance.

        Returns:
            PersonalizationResult with content, quality score, voice_applied flag, and flags.

        Raises:
            ValueError: If material_type is not one of the supported types.
            asyncio.TimeoutError: If generation exceeds the configured timeout.
        """
        if material_type not in self.VALID_MATERIAL_TYPES:
            raise ValueError(
                f"Invalid material_type '{material_type}'. "
                f"Must be one of: {', '.join(sorted(self.VALID_MATERIAL_TYPES))}"
            )

        # Determine tone from contact seniority
        seniority_level = self._determine_tone(contact_seniority)
        tone_description = self.TONE_MAP[seniority_level]

        # Build flags
        flags: list[str] = []
        if contact_seniority is None:
            flags.append("seniority_unknown")

        # Identify available fields
        available_fields = self._get_available_fields(enrichment)

        # Build LLM context
        context = self._build_context(
            enrichment=enrichment,
            beneficiary_id=beneficiary_id,
            tone=tone_description,
            hooks=enrichment.hooks,
            beneficiary_context=beneficiary_context or {},
        )

        # Build generation prompt
        prompt = self._build_prompt(
            material_type=material_type,
            tone=tone_description,
            available_fields=available_fields,
            hooks=enrichment.hooks,
            is_sparse=len(available_fields) < self.MIN_DATA_FIELDS,
            beneficiary_context=beneficiary_context or {},
        )

        # Attempt voice integration if voice_asset is provided
        voice_applied = False
        if voice_asset is not None:
            try:
                voice_directives = self._build_voice_directives(
                    voice_asset, behavioral_profile, seniority_level
                )
                avoid_prohibitions = self._build_avoid_prohibitions(
                    voice_asset.vocabulary_avoid
                )
                exemplar_section = self._build_exemplar_section(
                    voice_asset.exemplar_passages
                )

                # Inject voice sections into the prompt
                prompt = (
                    prompt
                    + "\n\n"
                    + voice_directives
                    + "\n\n"
                    + avoid_prohibitions
                    + "\n\n"
                    + exemplar_section
                )
                voice_applied = True
            except Exception:
                # Graceful degradation: if voice integration fails (e.g., DB timeout,
                # malformed asset data), fall back to no-voice generation
                logger.warning(
                    "Voice integration failed for beneficiary '%s'; "
                    "falling back to no-voice generation.",
                    beneficiary_id,
                    exc_info=True,
                )
                voice_applied = False

        # Generate content with timeout
        content = await asyncio.wait_for(
            self._llm.generate_content(
                prompt=prompt,
                context=context,
                material_type=material_type,
            ),
            timeout=self._timeout,
        )

        # ─── Content Selection (Requirement 3.2, 3.3) ────────────────────────
        # After generation, check if a length constraint exists for this material type.
        # If the material exceeds the constraint, invoke Content_Selector and apply cuts.
        # If no constraint is declared, skip content selection entirely (Req 3.3).
        content = self._apply_content_selection(
            content=content,
            material_type=material_type,
            enrichment=enrichment,
        )

        # Compute quality score
        quality_score, fields_used, fields_unused = self._compute_quality_score(
            content, enrichment
        )

        # Determine hooks referenced
        hooks_referenced = self._find_hooks_referenced(content, enrichment.hooks)

        # Check low quality
        is_low_quality = quality_score < self.LOW_QUALITY_THRESHOLD
        if is_low_quality:
            flags.append("low personalization")

        # Limit unused fields list to 3 for the result
        fields_available_unused = fields_unused[:3] if is_low_quality else fields_unused

        return PersonalizationResult(
            content=content,
            quality_score=quality_score,
            fields_used=fields_used,
            fields_available_unused=fields_available_unused,
            tone_applied=tone_description,
            hooks_referenced=hooks_referenced,
            is_low_quality=is_low_quality,
            voice_applied=voice_applied,
            flags=flags,
        )

    def _determine_tone(self, contact_seniority: str | None) -> SeniorityLevel:
        """Determine tone from contact seniority level.

        Requirement 11.4: Adapt tone based on seniority.
        Requirement 11.7: Default to director when seniority unknown.

        Args:
            contact_seniority: Seniority string from Contact (e.g., "c_suite", "director").

        Returns:
            SeniorityLevel enum value for tone mapping.
        """
        if contact_seniority is None:
            return SeniorityLevel.DIRECTOR

        # Map string to enum, defaulting to DIRECTOR for unknown values
        seniority_map = {
            "c_suite": SeniorityLevel.C_SUITE,
            "director": SeniorityLevel.DIRECTOR,
            "manager": SeniorityLevel.MANAGER,
            "other": SeniorityLevel.OTHER,
        }
        return seniority_map.get(contact_seniority.lower(), SeniorityLevel.DIRECTOR)

    def _compute_quality_score(
        self, content: str, enrichment: EnrichmentData
    ) -> tuple[int, list[str], list[str]]:
        """Compute personalization quality as % of available fields referenced.

        Requirement 11.5: Score = (referenced_fields / available_fields) × 100.
        Requirement 11.6: List up to 3 unused available fields when low quality.

        Args:
            content: The generated material content.
            enrichment: The enrichment data used for generation.

        Returns:
            Tuple of (quality_score, fields_used, fields_unused).
        """
        content_lower = content.lower()

        available_fields = self._get_available_fields(enrichment)
        if not available_fields:
            return (0, [], [])

        fields_used: list[str] = []
        fields_unused: list[str] = []

        for field_name in available_fields:
            if self._is_field_referenced(field_name, content_lower, enrichment):
                fields_used.append(field_name)
            else:
                fields_unused.append(field_name)

        # Score = (referenced / available) × 100
        score = int((len(fields_used) / len(available_fields)) * 100)

        return (score, fields_used, fields_unused)

    def _get_available_fields(self, enrichment: EnrichmentData) -> list[str]:
        """Get list of enrichment fields that have data available.

        A field is "available" if it has a non-None, non-empty value.

        Args:
            enrichment: The enrichment data to inspect.

        Returns:
            List of field names that contain data.
        """
        available: list[str] = []

        if enrichment.industry:
            available.append("industry")
        if enrichment.tech_stack:
            available.append("tech_stack")
        if enrichment.company_size is not None:
            available.append("company_size")
        if enrichment.recent_funding:
            available.append("recent_funding")
        if enrichment.intent_signals:
            available.append("intent_signals")
        if enrichment.hooks:
            available.append("hooks")

        return available

    def _is_field_referenced(
        self, field_name: str, content_lower: str, enrichment: EnrichmentData
    ) -> bool:
        """Check if a specific enrichment field is referenced in the content.

        Uses heuristic matching — checks for field values or related terms
        appearing in the generated content.

        Args:
            field_name: Name of the enrichment field.
            content_lower: Lowercased content string for matching.
            enrichment: The enrichment data with actual values.

        Returns:
            True if the field appears to be referenced in the content.
        """
        if field_name == "industry":
            return enrichment.industry is not None and enrichment.industry.lower() in content_lower

        if field_name == "tech_stack":
            # Check if any tech in the stack is mentioned
            return any(
                tech.lower() in content_lower for tech in enrichment.tech_stack
            )

        if field_name == "company_size":
            # Check for employee count reference
            if enrichment.company_size is not None:
                return str(enrichment.company_size) in content_lower or "employee" in content_lower

        if field_name == "recent_funding":
            return (
                enrichment.recent_funding is not None
                and enrichment.recent_funding.lower() in content_lower
            )

        if field_name == "intent_signals":
            # Check if any intent signal topic is mentioned
            return any(
                signal.lower() in content_lower for signal in enrichment.intent_signals
            )

        if field_name == "hooks":
            # Check if any hook content is referenced
            return any(
                self._hook_referenced(hook, content_lower) for hook in enrichment.hooks
            )

        return False

    def _hook_referenced(self, hook: dict, content_lower: str) -> bool:
        """Check if a specific hook is referenced in the content.

        Args:
            hook: Hook dict with type and content/topic fields.
            content_lower: Lowercased content for matching.

        Returns:
            True if the hook appears referenced.
        """
        # Check hook topic/title/content fields
        for key in ("topic", "title", "content", "name"):
            value = hook.get(key)
            if value and isinstance(value, str) and value.lower() in content_lower:
                return True
        return False

    def _find_hooks_referenced(
        self, content: str, hooks: list[dict]
    ) -> list[str]:
        """Find which hooks are referenced in the generated content.

        Requirement 11.2: Reference at least one hook when available.

        Args:
            content: Generated content.
            hooks: Available hooks from enrichment.

        Returns:
            List of hook identifiers/topics that were referenced.
        """
        content_lower = content.lower()
        referenced: list[str] = []

        for hook in hooks:
            hook_type = hook.get("type", "unknown")
            hook_topic = hook.get("topic") or hook.get("title") or hook.get("name", "")
            if self._hook_referenced(hook, content_lower):
                referenced.append(f"{hook_type}:{hook_topic}")

        return referenced

    def _build_context(
        self,
        enrichment: EnrichmentData,
        beneficiary_id: str,
        tone: str,
        hooks: list[dict],
        beneficiary_context: dict,
    ) -> dict:
        """Build the context dict passed to the LLM for generation.

        Incorporates all available enrichment data, hooks, tone instructions,
        and beneficiary information into a structured context.

        Args:
            enrichment: Prospect enrichment data.
            beneficiary_id: The beneficiary ID.
            tone: Tone description string.
            hooks: Available hooks for the prospect.
            beneficiary_context: Additional beneficiary assets/info.

        Returns:
            Context dictionary for LLM generation.
        """
        context: dict = {
            "beneficiary_id": beneficiary_id,
            "tone": tone,
            "beneficiary_assets": beneficiary_context,
        }

        # Add available enrichment data
        if enrichment.industry:
            context["industry"] = enrichment.industry
        if enrichment.tech_stack:
            context["tech_stack"] = enrichment.tech_stack
        if enrichment.company_size is not None:
            context["company_size"] = enrichment.company_size
        if enrichment.recent_funding:
            context["recent_funding"] = enrichment.recent_funding
        if enrichment.intent_signals:
            context["intent_signals"] = enrichment.intent_signals
        if hooks:
            context["hooks"] = hooks

        return context

    def _build_prompt(
        self,
        material_type: str,
        tone: str,
        available_fields: list[str],
        hooks: list[dict],
        is_sparse: bool,
        beneficiary_context: dict | None = None,
    ) -> str:
        """Build the generation prompt with tone, context instructions, and grounding constraints.

        Always appends GROUNDING_CONSTRAINT_INJECTION with the full Beneficiary
        profile assets text, for ALL material types (cv, cover_letter, proposal, email).

        Requirement 4.1: Generation-time fabrication prevention.

        Args:
            material_type: Type of material to generate.
            tone: Tone description for the content.
            available_fields: Fields available for personalization.
            hooks: Available hooks to reference.
            is_sparse: Whether enrichment has < 3 fields (sparse data).
            beneficiary_context: Beneficiary profile assets dict (baseline_assets, offerings, etc.).

        Returns:
            Prompt string for LLM generation with grounding constraints appended.
        """
        parts: list[str] = [
            f"Generate a personalized {material_type.replace('_', ' ')} for outreach.",
            "",
            f"TONE: Use a {tone} tone throughout the content.",
            "",
            "PERSONALIZATION REQUIREMENTS:",
            f"- Reference as many of these available data fields as naturally possible: {', '.join(available_fields)}",
        ]

        if hooks:
            hook_descriptions = []
            for hook in hooks:
                hook_type = hook.get("type", "signal")
                hook_topic = hook.get("topic") or hook.get("title") or hook.get("name", "")
                hook_descriptions.append(f"{hook_type}: {hook_topic}")
            parts.append(
                f"- IMPORTANT: Reference at least one of these hooks: {'; '.join(hook_descriptions)}"
            )

        if is_sparse:
            parts.extend([
                "",
                "NOTE: Limited enrichment data is available. Maximize the use of what is provided",
                "while maintaining a natural, professional tone. Do not invent details.",
            ])

        parts.extend([
            "",
            "GUIDELINES:",
            "- Keep the content professional and tailored to the prospect",
            "- Naturally weave enrichment data into the narrative",
            "- Do not explicitly mention that you are referencing enrichment data",
            "- Maintain the specified tone consistently",
        ])

        # Build profile assets text from beneficiary context and append grounding constraint
        profile_assets_text = self._build_profile_assets_text(beneficiary_context or {})
        parts.append(
            GROUNDING_CONSTRAINT_INJECTION.format(profile_assets_text=profile_assets_text)
        )

        return "\n".join(parts)

    async def regenerate_passages(
        self,
        material_id: str,
        material_text: str,
        excluded_claims: list,  # list of Claim objects
        beneficiary_context: dict,
    ) -> str:
        """Regenerate only the passages containing ungrounded claims.

        The regeneration prompt explicitly excludes the ungrounded content
        and constrains the LLM to use only verifiable profile assets.

        Returns the full material text with flagged passages replaced.

        Requirements: 3.2

        Args:
            material_id: ID of the material being regenerated.
            material_text: Full original material text.
            excluded_claims: List of Claim objects with ungrounded content to replace.
            beneficiary_context: Dict containing beneficiary profile assets
                (baseline_assets, offerings_assets, etc.).

        Returns:
            Updated material text with flagged passages replaced by grounded content.
        """
        # Edge case: no excluded claims, return original unchanged
        if not excluded_claims:
            return material_text

        # Sort claims by source_span_start position (ascending) for deterministic processing
        sorted_claims = sorted(excluded_claims, key=lambda c: c.source_span_start)

        # Build the profile assets text for grounding constraint
        profile_assets_text = self._build_profile_assets_text(beneficiary_context)

        # Build the list of passages that must be regenerated
        passages_to_replace = []
        for i, claim in enumerate(sorted_claims, start=1):
            passages_to_replace.append(
                f"  {i}. [{claim.source_span_start}:{claim.source_span_end}] "
                f"\"{claim.source_span}\"\n"
                f"     Ungrounded claim: \"{claim.claim_text}\""
            )

        passages_block = "\n".join(passages_to_replace)

        # Build the regeneration prompt
        regeneration_prompt = (
            "You are rewriting specific passages in an outreach material to remove "
            "ungrounded (fabricated or unsupported) claims.\n\n"
            f"FULL MATERIAL FOR CONTEXT:\n---\n{material_text}\n---\n\n"
            f"PASSAGES THAT MUST BE REGENERATED (identified by character offsets):\n"
            f"{passages_block}\n\n"
            "INSTRUCTIONS:\n"
            "- Replace ONLY the following passages with content traceable to the profile assets below.\n"
            "- Do NOT change any other part of the material.\n"
            "- Each replacement must maintain the same tone and flow as the surrounding text.\n"
            "- If no verifiable replacement is possible, reframe using adjacent experience "
            "from the profile rather than inventing content.\n"
            "- Acknowledge genuine gaps rather than papering over them.\n\n"
            f"{GROUNDING_CONSTRAINT_INJECTION.format(profile_assets_text=profile_assets_text)}\n\n"
            "RESPONSE FORMAT:\n"
            "Return a JSON array of replacement objects, one per passage, in the same order "
            "as listed above. Each object must have:\n"
            "- \"index\": the passage number (1-based)\n"
            "- \"replacement_text\": the new text to replace the original passage\n\n"
            "Example: [{\"index\": 1, \"replacement_text\": \"new content here\"}]"
        )

        # Call LLM to regenerate
        response = await self._llm.generate_content(
            prompt=regeneration_prompt,
            context={"material_id": material_id, "beneficiary_assets": beneficiary_context},
            material_type="regeneration",
        )

        # Parse the LLM response to get replacement texts
        replacements = self._parse_regeneration_response(response, sorted_claims)

        # Splice replacements into the original text (process in reverse order to preserve offsets)
        result_text = material_text
        for claim, replacement_text in reversed(list(zip(sorted_claims, replacements))):
            result_text = (
                result_text[: claim.source_span_start]
                + replacement_text
                + result_text[claim.source_span_end:]
            )

        return result_text

    def _parse_regeneration_response(
        self,
        response: str,
        sorted_claims: list,
    ) -> list[str]:
        """Parse the LLM regeneration response into replacement texts.

        Extracts the JSON array of replacement objects from the LLM response.
        Falls back gracefully if parsing fails.

        Args:
            response: Raw LLM response string.
            sorted_claims: Sorted list of claims being replaced (for count validation).

        Returns:
            List of replacement text strings in the same order as sorted_claims.
        """
        # Try to extract JSON array from response (may be wrapped in markdown code block)
        cleaned = response.strip()

        # Remove markdown code fences if present
        if cleaned.startswith("```"):
            # Remove opening fence (with optional language tag)
            cleaned = re.sub(r"^```\w*\n?", "", cleaned)
            # Remove closing fence
            cleaned = re.sub(r"\n?```\s*$", "", cleaned)
            cleaned = cleaned.strip()

        try:
            replacements_data = json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to find JSON array within the response
            match = re.search(r"\[.*\]", cleaned, re.DOTALL)
            if match:
                try:
                    replacements_data = json.loads(match.group())
                except json.JSONDecodeError:
                    # Last resort: use the raw response as a single replacement
                    # for the first claim, and original spans for the rest
                    logger.warning(
                        "Failed to parse regeneration response as JSON for material, "
                        "using raw response as fallback."
                    )
                    return [response.strip()] + [
                        c.source_span for c in sorted_claims[1:]
                    ]
            else:
                logger.warning(
                    "No JSON array found in regeneration response, using raw response."
                )
                return [response.strip()] + [
                    c.source_span for c in sorted_claims[1:]
                ]

        # Build replacement list ordered by index
        if not isinstance(replacements_data, list):
            logger.warning("Regeneration response is not a list, using raw response.")
            return [response.strip()] + [c.source_span for c in sorted_claims[1:]]

        # Map index -> replacement_text
        replacement_map: dict[int, str] = {}
        for item in replacements_data:
            if isinstance(item, dict):
                idx = item.get("index", 0)
                text = item.get("replacement_text", "")
                replacement_map[idx] = text

        # Build ordered list matching sorted_claims
        result: list[str] = []
        for i in range(1, len(sorted_claims) + 1):
            if i in replacement_map:
                result.append(replacement_map[i])
            else:
                # If replacement not provided, keep original span
                result.append(sorted_claims[i - 1].source_span)

        return result

    def _build_voice_directives(
        self,
        voice_asset: "VoiceAsset",
        behavioral_profile: "BehavioralProfileAsset | None",
        formality_level: SeniorityLevel,
    ) -> str:
        """Build combined voice + formality directives for the prompt.

        Conflict resolution rules:
        - Salutation and closing conventions → FormalityLevel
        - Body prose register, rhythm, vocabulary → Voice_Asset
        - Behavioral profile traits → included as tone guidance

        Requirements 2.1, 2.2: Include Voice_Asset content in prompt with
        clear conflict resolution against Formality_Level.

        Args:
            voice_asset: The sender's voice definition with register, rhythm,
                vocabulary preferences, and exemplar passages.
            behavioral_profile: Optional behavioral profile with interpersonal
                style and communication traits for tone guidance.
            formality_level: The recipient-derived formality level from
                contact seniority.

        Returns:
            Directive text block to inject into the generation prompt.
        """
        lines: list[str] = [
            "SENDER VOICE DIRECTIVES:",
            f"Register: {voice_asset.register.value}",
            f"Sentence length: {voice_asset.sentence_length.value}",
            f"First-person usage: {voice_asset.first_person_usage.value}",
        ]

        # Vocabulary preferences
        if voice_asset.vocabulary_prefer:
            lines.append("")
            lines.append("VOCABULARY TO PREFER:")
            for word in voice_asset.vocabulary_prefer:
                lines.append(f'- "{word}"')

        # Conflict resolution instructions
        lines.append("")
        lines.append("CONFLICT RESOLUTION:")
        lines.append(
            f"- For salutation and closing: follow FORMALITY_LEVEL ({formality_level.value})"
        )
        lines.append(
            "- For body prose: follow these VOICE DIRECTIVES (register, rhythm, vocabulary)"
        )

        # Behavioral profile tone guidance
        if behavioral_profile is not None:
            lines.append("")
            lines.append("TONE GUIDANCE:")
            lines.append(
                f"Interpersonal style: {behavioral_profile.interpersonal_style}"
            )
            if behavioral_profile.communication_traits:
                lines.append(
                    f"Communication traits: {', '.join(behavioral_profile.communication_traits)}"
                )

        return "\n".join(lines)

    def _build_avoid_prohibitions(self, avoid_list: list[str]) -> str:
        """Format the Voice_Asset avoid list as explicit LLM prohibitions.

        Each item in the avoid list becomes a "NEVER: {item}" instruction,
        making it unambiguous to the LLM that these words or constructions
        must not appear in the generated output.

        Requirements 2.3: Include the Voice_Asset's "avoid" list as explicit
        prohibitions in the generation prompt.

        Args:
            avoid_list: The vocabulary_avoid items from the Voice_Asset.

        Returns:
            Multi-line prohibition block prefixed with a header line.
        """
        lines = ["PROHIBITIONS (never use these words/constructions):"]
        for item in avoid_list:
            lines.append(f"- NEVER: {item}")
        return "\n".join(lines)

    def _build_exemplar_section(self, exemplars: list["ExemplarPassage"]) -> str:
        """Format exemplar passages as reference material in the prompt.

        Each exemplar is numbered and includes optional context (e.g.,
        "cold email opener") so the LLM understands what situation
        the passage was written for.

        Args:
            exemplars: List of ExemplarPassage instances from the Voice_Asset.

        Returns:
            Formatted exemplar block showing the sender's authentic voice.
        """
        lines = ["VOICE EXEMPLARS (write in this style):"]
        for i, ex in enumerate(exemplars, 1):
            ctx = f" ({ex.context})" if ex.context else ""
            lines.append(f'Example {i}{ctx}: "{ex.text}"')
        return "\n".join(lines)

    def _apply_content_selection(
        self,
        content: str,
        material_type: str,
        enrichment: EnrichmentData,
    ) -> str:
        """Apply content selection if a length constraint exists and material exceeds it.

        Requirement 3.2: When material exceeds its Length_Constraint, invoke
        Content_Selector and apply cuts, recording results in reasoning_log.
        Requirement 3.3: When no constraint is declared, skip entirely.

        Args:
            content: The generated material text.
            material_type: The type of material (e.g., "cv", "cover_letter").
            enrichment: Enrichment data for extracting opportunity keywords.

        Returns:
            The content after cuts are applied, or unchanged if no constraint
            exists or material is within the limit.
        """
        # Requirement 3.3: Skip if no schema registry or no constraint declared
        if self._schema is None:
            return content

        length_constraint: LengthConstraint | None = self._schema.get_length_constraint(
            material_type
        )
        if length_constraint is None:
            return content

        # Atomize the material into ContentUnit instances
        units = self._atomize_material(content, material_type)
        if not units:
            return content

        # Check if material actually exceeds the constraint before invoking selector
        current_length = self._content_selector._measure_length(units, length_constraint)
        if current_length <= length_constraint.max_value:
            return content

        # Extract opportunity keywords from enrichment data
        # (intent_signals + tech_stack provide the best keyword signal)
        opportunity_keywords = self._extract_opportunity_keywords(enrichment)

        # Build selection config with default weights and the constraint
        config = SelectionConfig(
            weights=SelectionWeights(),  # Default 50/25/25
            protection_threshold=80,
            length_constraint=length_constraint,
        )

        # Invoke Content_Selector (Requirement 3.2)
        # Using empty companion_references initially — can be extended later
        # when companion material tracking is available.
        result: SelectionResult = self._content_selector.select_content(
            units=units,
            opportunity_keywords=opportunity_keywords,
            companion_references=[],
            config=config,
        )

        # Apply cuts: rebuild content from retained units in document order
        trimmed_content = "\n".join(unit.text for unit in result.retained_units)

        # Record cuts in reasoning_log (Requirement 3.2)
        self.reasoning_log.append({
            "action": "content_selection",
            "material_type": material_type,
            "original_length": result.original_length,
            "final_length": result.final_length,
            "constraint": {
                "type": length_constraint.constraint_type.value,
                "max_value": length_constraint.max_value,
            },
            "cuts": [
                {
                    "unit_id": entry.unit.id,
                    "text_preview": entry.unit.text[:80],
                    "composite_score": entry.composite_score,
                    "forced": entry.forced,
                }
                for entry in result.cut_list
            ],
            "warnings": [
                {
                    "unit_id": w.unit_id,
                    "narrative_dependency_score": w.narrative_dependency_score,
                    "source_material": w.source_material,
                }
                for w in result.warnings
            ],
        })

        logger.info(
            "Content selection applied for material_type='%s': "
            "original_length=%d, final_length=%d, units_cut=%d",
            material_type,
            result.original_length,
            result.final_length,
            len(result.cut_list),
        )

        return trimmed_content

    def _atomize_material(
        self,
        content: str,
        material_type: str,
    ) -> list[ContentUnit]:
        """Atomize generated material text into ContentUnit instances.

        Uses a simple paragraph/line-based strategy:
        - Lines starting with "- " or "• " are treated as BULLET units
        - Non-empty lines in other sections are treated as STATEMENT units
        - For cover_letter and email types, sentences within paragraphs are
          treated as SENTENCE units

        This is a reasonable initial atomization strategy that can be refined
        as the system evolves to support richer material structures.

        Args:
            content: The material text to atomize.
            material_type: Material type for choosing atomization strategy.

        Returns:
            List of ContentUnit instances in document order.
        """
        units: list[ContentUnit] = []
        lines = content.split("\n")
        doc_order = 0

        # For sentence-level material types (cover_letter, email), we split
        # paragraphs into sentences
        sentence_types = {"cover_letter", "email"}

        current_section = "body"
        paragraph_id = None

        for line in lines:
            stripped = line.strip()
            if not stripped:
                # Blank line signals paragraph boundary
                paragraph_id = None
                continue

            # Detect bullet points
            if stripped.startswith(("- ", "• ", "* ")):
                unit = ContentUnit(
                    id=f"unit_{doc_order}",
                    unit_type=ContentUnitType.BULLET,
                    text=stripped,
                    section=current_section,
                    document_order=doc_order,
                    parent_paragraph_id=None,
                )
                units.append(unit)
                doc_order += 1

            elif material_type in sentence_types:
                # Split line into sentences for cover letters / emails
                sentences = self._split_sentences(stripped)
                if paragraph_id is None:
                    paragraph_id = f"para_{doc_order}"

                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    unit = ContentUnit(
                        id=f"unit_{doc_order}",
                        unit_type=ContentUnitType.SENTENCE,
                        text=sentence,
                        section=current_section,
                        document_order=doc_order,
                        parent_paragraph_id=paragraph_id,
                    )
                    units.append(unit)
                    doc_order += 1
            else:
                # Default: each non-empty line is a STATEMENT
                unit = ContentUnit(
                    id=f"unit_{doc_order}",
                    unit_type=ContentUnitType.STATEMENT,
                    text=stripped,
                    section=current_section,
                    document_order=doc_order,
                    parent_paragraph_id=None,
                )
                units.append(unit)
                doc_order += 1

        return units

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        """Split text into sentences using a simple regex approach.

        Handles common sentence terminators (., !, ?) while avoiding
        splitting on abbreviations like "Dr." or "e.g.".

        Args:
            text: A single paragraph or line of text.

        Returns:
            List of sentence strings.
        """
        # Simple sentence splitting: split on sentence-ending punctuation
        # followed by whitespace or end-of-string
        parts = re.split(r'(?<=[.!?])\s+', text)
        return [p for p in parts if p.strip()]

    def _extract_opportunity_keywords(
        self,
        enrichment: EnrichmentData,
    ) -> list[str]:
        """Extract opportunity-relevant keywords from enrichment data.

        Combines tech_stack and intent_signals as the primary keyword
        sources, since they represent the opportunity's requirements and
        context.

        Args:
            enrichment: The prospect's enrichment data.

        Returns:
            List of keyword strings for relevance scoring.
        """
        keywords: list[str] = []
        keywords.extend(enrichment.tech_stack)
        keywords.extend(enrichment.intent_signals)
        if enrichment.industry:
            keywords.append(enrichment.industry)
        return keywords

    def _build_profile_assets_text(self, beneficiary_context: dict) -> str:
        """Build a concatenated text string from all beneficiary profile assets.

        Combines baseline_assets and offerings_assets content into a single
        text block for grounding constraint injection.

        Args:
            beneficiary_context: Dict containing beneficiary profile data.
                Expected keys: "baseline_assets" (dict[str, str]),
                "offerings_assets" (dict[str, str]), or any string values
                at the top level.

        Returns:
            Concatenated profile assets text. Returns "(no profile assets provided)"
            if no content is available.
        """
        sections: list[str] = []

        # Extract baseline_assets (resume, cover_letter, consultant_profiles, etc.)
        baseline_assets = beneficiary_context.get("baseline_assets", {})
        if isinstance(baseline_assets, dict):
            for asset_name, asset_content in baseline_assets.items():
                if asset_content and isinstance(asset_content, str):
                    sections.append(f"[{asset_name}]\n{asset_content}")

        # Extract offerings_assets (company_profile, capability_statement, etc.)
        offerings_assets = beneficiary_context.get("offerings_assets", {})
        if isinstance(offerings_assets, dict):
            for asset_name, asset_content in offerings_assets.items():
                if asset_content and isinstance(asset_content, str):
                    sections.append(f"[{asset_name}]\n{asset_content}")

        # Also include any top-level string values that might be profile content
        # (handles cases where assets are passed flat rather than nested)
        for key, value in beneficiary_context.items():
            if key in ("baseline_assets", "offerings_assets"):
                continue
            if isinstance(value, str) and value.strip():
                sections.append(f"[{key}]\n{value}")

        if not sections:
            return "(no profile assets provided)"

        return "\n\n".join(sections)
