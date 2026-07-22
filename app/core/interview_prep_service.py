"""Interview Prep Service — orchestrates generation and grounding of Interview_Prep_Packs.

Triggered by Interview state entry via ARQ worker dispatch. Follows the same
pattern as PersonalizationEngine but with state-entry trigger, single structured
LLM call for the entire pack, grounding limited to STAR talking points, and
single regeneration attempt on grounding failure.

Requirements: 1.1, 2.1, 2.2, 2.3, 3.2, 3.3
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.core.interview_prep_models import (
    GenerationContext,
    Interview_Prep_Pack,
    PackStatus,
    STAR_Talking_Point,
    InterviewPrepError,
    GenerationTimeoutError,
    DeadlineExceededError,
    PackValidationError,
    ContextAssemblyError,
)

if TYPE_CHECKING:
    from app.core.grounding_verifier import GroundingVerifier
    from app.core.schema_registry import SchemaRegistry


class InterviewPrepService:
    """Orchestrates interview preparation pack generation and grounding.

    Triggered by Interview state entry via ARQ worker dispatch.
    Follows the same pattern as PersonalizationEngine but with:
    - State-entry trigger (not material-prep stage)
    - Single structured LLM call for entire pack
    - Grounding limited to STAR talking points (Beneficiary claims)
    - Single regeneration attempt on grounding failure

    The service coordinates:
    1. Context assembly from pipeline record, submitted materials, enrichment,
       and profile assets.
    2. Structured LLM generation of the full Interview_Prep_Pack.
    3. Structural validation (question counts, STAR count, briefing length).
    4. Grounding verification of all STAR talking points via Grounding_Verifier.
    5. Single regeneration attempt for ungrounded claims with exclusion constraint.
    6. Persistence and WebSocket notification on completion.

    Total execution is bounded by a 120-second deadline. The LLM generation
    step has a 90-second timeout leaving a 30-second buffer for context assembly,
    validation, and grounding.
    """

    # ─── CLASS CONSTANTS ──────────────────────────────────────────────────────

    GENERATION_TIMEOUT: float = 90.0
    """Seconds allowed for a single LLM generation call (leaves 30s buffer)."""

    TOTAL_DEADLINE: float = 120.0
    """Seconds allowed for the entire generate_pack pipeline."""

    MAX_RETRIES: int = 2
    """Maximum generation retry attempts before marking pack as failed."""

    MAX_QUESTIONS: int = 15
    """Upper bound on likely interview questions generated."""

    MIN_QUESTIONS: int = 8
    """Lower bound on likely interview questions generated."""

    STAR_COUNT: int = 5
    """Exact number of STAR talking points required in every pack."""

    MAX_BRIEFING_WORDS: int = 400
    """Maximum word count for the company briefing section."""

    MAX_QUESTIONS_TO_ASK: int = 6
    """Upper bound on suggested questions for the Consultant to ask."""

    MIN_QUESTIONS_TO_ASK: int = 3
    """Lower bound on suggested questions for the Consultant to ask."""

    # ─── INITIALISATION ───────────────────────────────────────────────────────

    def __init__(
        self,
        llm_router,  # LLMRouter
        grounding_verifier: "GroundingVerifier",
        schema_registry: "SchemaRegistry",
        db_repo,  # InterviewPrepRepository
        event_publisher,  # EventPublisher
    ) -> None:
        """Initialise the InterviewPrepService with its dependencies.

        Args:
            llm_router: The LLM_Router instance for dispatching structured
                generation calls with timeout enforcement.
            grounding_verifier: The Grounding_Verifier for verifying
                Beneficiary-side claims in STAR talking points.
            schema_registry: The Schema_Registry for resolving prompt
                templates and technique configurations.
            db_repo: The InterviewPrepRepository for persisting packs
                and loading pipeline record context.
            event_publisher: The EventPublisher for sending WebSocket
                notifications on pack readiness.
        """
        self._llm = llm_router
        self._grounding = grounding_verifier
        self._schema = schema_registry
        self._db = db_repo
        self._publisher = event_publisher
        self._omission_notes: list[str] = []

    # ─── PUBLIC METHODS ───────────────────────────────────────────────────────

    async def generate_pack(
        self,
        pipeline_record_id: str,
    ) -> Interview_Prep_Pack:
        """Generate a complete Interview_Prep_Pack for a pipeline record.

        This is the main entry point invoked by the ARQ worker when a pipeline
        record enters the Interview state. It orchestrates the full generation
        pipeline: context assembly → LLM generation → validation → grounding →
        storage → notification.

        Preconditions:
            - pipeline_record exists and is in Interview state.
            - Opportunity type has interview_preparation technique attached.
            - Beneficiary has at least profile_assets loaded.

        Postconditions:
            - Returns Interview_Prep_Pack with status in
              {READY, READY_WITH_FLAGS, FAILED}.
            - Pack is stored in the database via InterviewPrepRepository.
            - WebSocket notification sent on completion.
            - Total execution within TOTAL_DEADLINE (120 seconds).
            - Grounding_Verifier called on all STAR talking points.
            - If ungrounded: single regeneration with exclusion constraint
              attempted before surfacing remaining flags.

        Args:
            pipeline_record_id: UUID of the pipeline record in Interview state.

        Returns:
            The generated Interview_Prep_Pack with final status.

        Raises:
            DeadlineExceededError: If total execution exceeds 120 seconds.
            ContextAssemblyError: If minimum required context cannot be loaded.
            InterviewPrepError: On unrecoverable generation failure after retries.
        """
        start_time = time.time()

        # Assemble context
        context = await self.assemble_context(pipeline_record_id)

        # Store initial pack record with status=generating
        now = datetime.now(tz=timezone.utc)
        pack = Interview_Prep_Pack(
            id=str(uuid.uuid4()),
            pipeline_record_id=pipeline_record_id,
            beneficiary_id=context.beneficiary_id,
            opportunity_type_id=context.opportunity_type_id,
            likely_questions=[],
            star_talking_points=[],
            company_briefing="",
            questions_to_ask=[],
            status=PackStatus.GENERATING,
            omission_notes=self._omission_notes,
            created_at=now,
            updated_at=now,
        )
        await self._db.save_pack(pack)

        try:
            # Check deadline before LLM generation
            elapsed = time.time() - start_time
            if elapsed >= self.TOTAL_DEADLINE:
                raise DeadlineExceededError(
                    pipeline_record_id=pipeline_record_id,
                )

            # Generate via LLM
            generated_pack = await self._generate_via_llm(context)

            # Update pack fields from generated content
            pack = Interview_Prep_Pack(
                id=pack.id,
                pipeline_record_id=pipeline_record_id,
                beneficiary_id=context.beneficiary_id,
                opportunity_type_id=context.opportunity_type_id,
                likely_questions=generated_pack.likely_questions,
                star_talking_points=generated_pack.star_talking_points,
                company_briefing=generated_pack.company_briefing,
                questions_to_ask=generated_pack.questions_to_ask,
                status=PackStatus.GROUNDING,
                omission_notes=self._omission_notes,
                created_at=pack.created_at,
                updated_at=datetime.now(tz=timezone.utc),
            )
            await self._db.update_pack_status(pack.id, PackStatus.GROUNDING)

            # Check deadline before grounding
            elapsed = time.time() - start_time
            if elapsed >= self.TOTAL_DEADLINE:
                raise DeadlineExceededError(
                    pipeline_record_id=pipeline_record_id,
                )

            # Ground talking points
            grounded_pack, remaining_flags = await self._ground_talking_points(
                pack, context
            )

            # Determine final status
            if remaining_flags:
                final_status = PackStatus.READY_WITH_FLAGS
            else:
                final_status = PackStatus.READY

            # Calculate generation duration
            generation_duration_ms = int((time.time() - start_time) * 1000)

            # Build final pack
            final_pack = Interview_Prep_Pack(
                id=pack.id,
                pipeline_record_id=pipeline_record_id,
                beneficiary_id=context.beneficiary_id,
                opportunity_type_id=context.opportunity_type_id,
                likely_questions=grounded_pack.likely_questions,
                star_talking_points=grounded_pack.star_talking_points,
                company_briefing=grounded_pack.company_briefing,
                questions_to_ask=grounded_pack.questions_to_ask,
                status=final_status,
                omission_notes=self._omission_notes,
                grounding_flags=remaining_flags,
                generation_duration_ms=generation_duration_ms,
                created_at=pack.created_at,
                updated_at=datetime.now(tz=timezone.utc),
            )

            # Persist completed pack
            await self._db.save_pack(final_pack)

            # Publish WebSocket notification
            await self._publisher.publish(
                event="pack_ready",
                data={
                    "pipeline_record_id": pipeline_record_id,
                    "pack_id": final_pack.id,
                    "status": final_status.value,
                    "has_flags": bool(remaining_flags),
                },
            )

            return final_pack

        except DeadlineExceededError:
            # Deadline exceeded — mark failed
            await self._db.update_pack_status(pack.id, PackStatus.FAILED)
            raise

        except (GenerationTimeoutError, PackValidationError, InterviewPrepError) as e:
            # Generation failed — mark as failed
            generation_duration_ms = int((time.time() - start_time) * 1000)
            await self._db.update_pack_status(pack.id, PackStatus.FAILED)

            # Publish failure notification
            await self._publisher.publish(
                event="pack_failed",
                data={
                    "pipeline_record_id": pipeline_record_id,
                    "pack_id": pack.id,
                    "error": str(e),
                },
            )

            raise

    async def assemble_context(
        self,
        pipeline_record_id: str,
    ) -> GenerationContext:
        """Assemble all available inputs for pack generation.

        Loads from the database:
            - Opportunity description from pipeline_record → prospect.
            - tailored_cv and tailored_cover_letter from submitted_materials.
            - Enrichment_Record for the prospect (company data, intent signals,
              technology stack).
            - Consultant's profile assets (resume, cover_letter, consultant_profiles).
            - Existing STAR example material from the Consultant's profile.

        If submitted materials are unavailable, proceeds with profile-only
        context and records the omission in the returned GenerationContext.

        Postconditions:
            - GenerationContext.opportunity_description is always non-empty.
            - GenerationContext.enrichment_record is always present.
            - GenerationContext.profile_assets has at least one entry.
            - Omission notes populated for any missing submitted materials.

        Args:
            pipeline_record_id: UUID of the pipeline record to load context for.

        Returns:
            A fully-assembled GenerationContext ready for LLM dispatch.

        Raises:
            ContextAssemblyError: If opportunity description, enrichment record,
                or all profile assets are missing (minimum context not met).
        """
        omission_notes: list[str] = []

        # Load pipeline record
        record = await self._db.get_pipeline_record(pipeline_record_id)
        if not record:
            raise ContextAssemblyError(
                f"Pipeline record '{pipeline_record_id}' not found",
                pipeline_record_id=pipeline_record_id,
                missing_inputs=["pipeline_record"],
            )

        # Load prospect and extract opportunity description
        prospect = await self._db.get_prospect(record.prospect_id)
        opportunity_description = prospect.description if prospect else ""

        if not opportunity_description:
            raise ContextAssemblyError(
                "Opportunity description is empty or missing",
                pipeline_record_id=pipeline_record_id,
                missing_inputs=["opportunity_description"],
            )

        # Load submitted materials (optional — graceful degradation)
        submitted = await self._db.get_submitted_materials(pipeline_record_id)
        tailored_cv = submitted.get("tailored_cv") if submitted else None
        tailored_cover_letter = (
            submitted.get("tailored_cover_letter") if submitted else None
        )

        if tailored_cv is None:
            omission_notes.append(
                "Submitted tailored CV unavailable — proceeding with profile assets only"
            )
        if tailored_cover_letter is None:
            omission_notes.append(
                "Submitted tailored cover letter unavailable — proceeding with profile assets only"
            )

        # Load enrichment record (required)
        enrichment_record = await self._db.get_enrichment_record(record.prospect_id)
        if not enrichment_record:
            raise ContextAssemblyError(
                "Enrichment record not found for prospect",
                pipeline_record_id=pipeline_record_id,
                missing_inputs=["enrichment_record"],
            )

        # Load intent signals from enrichment
        intent_signals = await self._db.get_intent_signals(record.prospect_id)

        # Load profile assets (required — at least one entry)
        profile_assets = await self._db.get_profile_assets(record.beneficiary_id)
        if not profile_assets:
            raise ContextAssemblyError(
                "No profile assets found for beneficiary",
                pipeline_record_id=pipeline_record_id,
                missing_inputs=["profile_assets"],
            )

        # Load existing STAR examples (optional)
        star_examples = await self._db.get_star_examples(record.beneficiary_id)

        # Store omission notes for generate_pack to include in the final pack
        self._omission_notes = omission_notes

        return GenerationContext(
            opportunity_description=opportunity_description,
            tailored_cv=tailored_cv,
            tailored_cover_letter=tailored_cover_letter,
            enrichment_record=enrichment_record,
            intent_signals=intent_signals or [],
            profile_assets=profile_assets,
            star_examples=star_examples,
            opportunity_type_id=record.opportunity_type_id,
            beneficiary_id=record.beneficiary_id,
        )

    async def regenerate_pack(
        self,
        pipeline_record_id: str,
    ) -> Interview_Prep_Pack:
        """Regenerate pack on demand (e.g. after profile update or rescheduled interview).

        Reassembles context (which may include new profile data since the
        original generation) and regenerates the full pack. The new pack
        replaces the existing pack in storage while retaining the previous
        version in history.

        Follows the same pipeline as generate_pack: context assembly →
        LLM generation → validation → grounding → storage → notification.

        Postconditions:
            - New pack stored with fresh created_at timestamp.
            - Previous pack version retained in history.
            - Same grounding flow applied as initial generation.
            - WebSocket notification sent on completion.

        Args:
            pipeline_record_id: UUID of the pipeline record to regenerate for.

        Returns:
            The newly generated Interview_Prep_Pack.

        Raises:
            DeadlineExceededError: If total execution exceeds 120 seconds.
            ContextAssemblyError: If minimum required context cannot be loaded.
            InterviewPrepError: On unrecoverable generation failure after retries.
        """
        import hashlib

        # Get existing pack to supersede
        existing_pack = await self._db.get_pack(pipeline_record_id)

        # Generate new pack using the same flow as generate_pack
        new_pack = await self.generate_pack(pipeline_record_id)

        # Mark old pack as superseded if it exists
        if existing_pack:
            await self._db.supersede_pack(existing_pack.id, new_pack.id)

        # Create history record
        # Build context hash from the assembled context for deduplication
        context_str = f"{pipeline_record_id}:{new_pack.created_at.isoformat()}"
        context_hash = hashlib.sha256(context_str.encode()).hexdigest()

        await self._db.save_history(
            pack_id=new_pack.id,
            trigger_reason="manual_regenerate",
            context_hash=context_hash,
        )

        return new_pack

    # ─── PRIVATE METHODS ──────────────────────────────────────────────────────

    async def _generate_via_llm(
        self,
        context: GenerationContext,
    ) -> Interview_Prep_Pack:
        """Dispatch structured generation to LLM_Router.

        Uses GENERATION evaluation type with the interview_prep prompt template
        resolved from Schema_Registry. The LLM is expected to return a single
        structured JSON response conforming to the Interview_Prep_Pack schema.

        Enforces GENERATION_TIMEOUT (90 seconds) on the LLM call. On timeout,
        raises GenerationTimeoutError which the caller may retry.

        Args:
            context: The assembled GenerationContext containing all inputs
                for the structured prompt.

        Returns:
            A parsed Interview_Prep_Pack (not yet validated or grounded).

        Raises:
            GenerationTimeoutError: If the LLM call exceeds 90 seconds.
            InterviewPrepError: On LLM dispatch failure or unparseable response.
        """
        from app.core.interview_prep_prompts import INTERVIEW_PREP_GENERATION_PROMPT

        # Build prompt from context
        profile_assets_text = "\n\n".join(
            f"--- {asset_id} ---\n{content}"
            for asset_id, content in context.profile_assets.items()
        )

        submitted_materials_section = ""
        if context.tailored_cv:
            submitted_materials_section += f"SUBMITTED CV:\n{context.tailored_cv}\n\n"
        if context.tailored_cover_letter:
            submitted_materials_section += (
                f"SUBMITTED COVER LETTER:\n{context.tailored_cover_letter}\n\n"
            )

        # Extract enrichment fields
        enrichment = context.enrichment_record
        industry = (
            enrichment.get("industry", "Unknown")
            if isinstance(enrichment, dict)
            else getattr(enrichment, "industry", "Unknown")
        )
        employee_count = (
            enrichment.get("employee_count", "Unknown")
            if isinstance(enrichment, dict)
            else getattr(enrichment, "employee_count", "Unknown")
        )
        tech_stack = (
            enrichment.get("tech_stack", [])
            if isinstance(enrichment, dict)
            else getattr(enrichment, "tech_stack", [])
        )
        intent_signals_text = (
            ", ".join(
                str(s.get("type", s) if isinstance(s, dict) else str(s))
                for s in context.intent_signals
            )
            or "None identified"
        )
        headquarters = (
            enrichment.get("headquarters", "Unknown")
            if isinstance(enrichment, dict)
            else getattr(enrichment, "headquarters", "Unknown")
        )

        tech_stack_text = (
            ", ".join(tech_stack) if isinstance(tech_stack, list) else str(tech_stack)
        )

        prompt = INTERVIEW_PREP_GENERATION_PROMPT.format(
            opportunity_description=context.opportunity_description,
            profile_assets_text=profile_assets_text,
            submitted_materials_section=submitted_materials_section,
            industry=industry,
            employee_count=employee_count,
            tech_stack=tech_stack_text,
            intent_signals=intent_signals_text,
            headquarters=headquarters,
        )

        # Dispatch to LLM with retry logic
        last_error: Exception | None = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await asyncio.wait_for(
                    self._llm.generate(
                        prompt=prompt,
                        evaluation_type="generation",
                    ),
                    timeout=self.GENERATION_TIMEOUT,
                )
                break
            except asyncio.TimeoutError:
                last_error = GenerationTimeoutError(
                    pipeline_record_id=context.beneficiary_id,
                    timeout_seconds=self.GENERATION_TIMEOUT,
                )
                if attempt == self.MAX_RETRIES:
                    raise last_error
                continue
            except Exception as e:
                last_error = InterviewPrepError(
                    f"LLM generation failed: {e}",
                    pipeline_record_id=context.beneficiary_id,
                    retryable=True,
                )
                if attempt == self.MAX_RETRIES:
                    raise last_error
                continue
        else:
            # All retries exhausted without break
            raise last_error  # type: ignore[misc]

        # Parse JSON response
        try:
            raw_text = (
                response
                if isinstance(response, str)
                else response.get("content", response.get("text", str(response)))
            )
            data = json.loads(raw_text)
        except (json.JSONDecodeError, TypeError, AttributeError) as e:
            raise InterviewPrepError(
                f"Failed to parse LLM response as JSON: {e}",
                pipeline_record_id=context.beneficiary_id,
                retryable=True,
            )

        # Build Interview_Prep_Pack from parsed data
        now = datetime.now(tz=timezone.utc)
        star_points = [
            STAR_Talking_Point(
                competency=sp.get("competency", ""),
                question=sp.get("question", ""),
                situation=sp.get("situation", ""),
                task=sp.get("task", ""),
                action=sp.get("action", ""),
                result=sp.get("result", ""),
                source_asset_refs=sp.get("source_asset_refs", []),
                is_gap_handled=sp.get("is_gap_handled", False),
                gap_note=sp.get("gap_note"),
            )
            for sp in data.get("star_talking_points", [])
        ]

        pack = Interview_Prep_Pack(
            id=str(uuid.uuid4()),
            pipeline_record_id="",  # set by caller
            beneficiary_id=context.beneficiary_id,
            opportunity_type_id=context.opportunity_type_id,
            likely_questions=data.get("likely_questions", []),
            star_talking_points=star_points,
            company_briefing=data.get("company_briefing", ""),
            questions_to_ask=data.get("questions_to_ask", []),
            status=PackStatus.GENERATING,
            created_at=now,
            updated_at=now,
        )

        # Validate pack structure
        errors = self._validate_pack_structure(pack)
        if errors:
            raise PackValidationError(
                pipeline_record_id=context.beneficiary_id,
                validation_errors=errors,
            )

        return pack

    def _validate_pack_structure(
        self,
        pack: Interview_Prep_Pack,
    ) -> list[str]:
        """Validate pack meets structural constraints defined in Requirements 2.1.

        Checks:
            - likely_questions count in [MIN_QUESTIONS, MAX_QUESTIONS] (8-15).
            - star_talking_points count == STAR_COUNT (exactly 5).
            - company_briefing word count <= MAX_BRIEFING_WORDS (400).
            - questions_to_ask count in [MIN_QUESTIONS_TO_ASK, MAX_QUESTIONS_TO_ASK] (3-6).
            - All STAR points reference at least one source_asset_ref.

        Args:
            pack: The Interview_Prep_Pack to validate.

        Returns:
            A list of validation error strings. An empty list indicates
            the pack is structurally valid.
        """
        errors = []
        if not (self.MIN_QUESTIONS <= len(pack.likely_questions) <= self.MAX_QUESTIONS):
            errors.append(
                f"likely_questions count {len(pack.likely_questions)} "
                f"not in [{self.MIN_QUESTIONS}, {self.MAX_QUESTIONS}]"
            )
        if len(pack.star_talking_points) != self.STAR_COUNT:
            errors.append(
                f"star_talking_points count {len(pack.star_talking_points)} != {self.STAR_COUNT}"
            )
        briefing_words = len(pack.company_briefing.split())
        if briefing_words > self.MAX_BRIEFING_WORDS:
            errors.append(
                f"company_briefing has {briefing_words} words, max {self.MAX_BRIEFING_WORDS}"
            )
        if not (self.MIN_QUESTIONS_TO_ASK <= len(pack.questions_to_ask) <= self.MAX_QUESTIONS_TO_ASK):
            errors.append(
                f"questions_to_ask count {len(pack.questions_to_ask)} "
                f"not in [{self.MIN_QUESTIONS_TO_ASK}, {self.MAX_QUESTIONS_TO_ASK}]"
            )
        for tp in pack.star_talking_points:
            if not tp.source_asset_refs:
                errors.append(
                    f"STAR point for '{tp.competency}' has no source_asset_refs"
                )
        return errors

    async def _ground_talking_points(
        self,
        pack: Interview_Prep_Pack,
        context: GenerationContext,
    ) -> tuple[Interview_Prep_Pack, list[str]]:
        """Run Grounding_Verifier on STAR talking points.

        Only Beneficiary-side claims are verified (STAR narratives drawn from
        the Consultant's profile). Company briefing and questions-to-ask are
        prospect-side content derived from the Enrichment_Record and are NOT
        subject to grounding verification.

        If ungrounded claims are found:
            1. Regenerate the affected talking points ONCE with an exclusion
               constraint (the ungrounded claim text is excluded from the
               regeneration prompt).
            2. Re-verify the regenerated points via Grounding_Verifier.
            3. Return the pack with any remaining grounding flags.

        Args:
            pack: The validated Interview_Prep_Pack whose STAR points need
                grounding verification.
            context: The GenerationContext used to regenerate affected points
                if ungrounded claims are found.

        Returns:
            A tuple of (updated_pack, remaining_grounding_flags) where
            remaining_grounding_flags is empty if all claims are grounded.
        """
        from app.core.interview_prep_prompts import INTERVIEW_PREP_REGENERATION_PROMPT

        # Extract STAR talking point text for verification
        talking_point_texts = []
        for tp in pack.star_talking_points:
            text = (
                f"Competency: {tp.competency}\n"
                f"Situation: {tp.situation}\n"
                f"Task: {tp.task}\n"
                f"Action: {tp.action}\n"
                f"Result: {tp.result}"
            )
            talking_point_texts.append(text)

        combined_text = "\n\n---\n\n".join(talking_point_texts)

        # Build lightweight adapter objects for GroundingVerifier.verify_material()
        class _MaterialProxy:
            def __init__(self, material_id: str, pipeline_record_id: str, text: str):
                self.id = material_id
                self.pipeline_record_id = pipeline_record_id
                self.text = text

        class _BeneficiaryProxy:
            def __init__(self, profile_assets: dict[str, str]):
                # GroundingVerifier expects baseline_assets and offerings_assets
                self.baseline_assets = profile_assets
                self.offerings_assets = {}

        material_proxy = _MaterialProxy(
            material_id=f"interview_prep_{pack.id}",
            pipeline_record_id=pack.pipeline_record_id,
            text=combined_text,
        )
        beneficiary_proxy = _BeneficiaryProxy(context.profile_assets)

        # Call Grounding_Verifier
        grounding_result = await self._grounding.verify_material(
            reviewed_material=material_proxy,
            beneficiary=beneficiary_proxy,
            enrichment=context.enrichment_record,
        )

        # Check if all claims are grounded
        ungrounded_claims = [
            claim
            for claim in grounding_result.grounding_report.claims
            if claim.grounding_status
            and claim.grounding_status.value == "ungrounded"
        ]

        if not ungrounded_claims:
            # All claims grounded — return pack unchanged
            return pack, []

        # Ungrounded claims found — regenerate affected talking points ONCE
        # Map ungrounded claims back to specific talking point indices
        flagged_indices: list[int] = []
        for i, tp in enumerate(pack.star_talking_points):
            tp_text = f"{tp.situation} {tp.task} {tp.action} {tp.result}".lower()
            for claim in ungrounded_claims:
                if claim.claim_text.lower() in tp_text or claim.source_span.lower() in tp_text:
                    flagged_indices.append(i)
                    break

        if not flagged_indices:
            # Claims don't map to specific talking points — flag all
            flagged_indices = list(range(len(pack.star_talking_points)))

        # Build regeneration prompt with exclusion constraint
        flagged_points_text = "\n\n".join(
            f"Point {i+1} ({pack.star_talking_points[i].competency}):\n"
            f"  Situation: {pack.star_talking_points[i].situation}\n"
            f"  Task: {pack.star_talking_points[i].task}\n"
            f"  Action: {pack.star_talking_points[i].action}\n"
            f"  Result: {pack.star_talking_points[i].result}"
            for i in flagged_indices
        )

        excluded_claims_text = "\n".join(
            f"- {claim.claim_text}" for claim in ungrounded_claims
        )

        profile_assets_text = "\n\n".join(
            f"--- {asset_id} ---\n{content}"
            for asset_id, content in context.profile_assets.items()
        )

        regen_prompt = INTERVIEW_PREP_REGENERATION_PROMPT.format(
            original_context=context.opportunity_description[:500],
            flagged_points=flagged_points_text,
            excluded_claims=excluded_claims_text,
            profile_assets_text=profile_assets_text,
        )

        # Attempt single regeneration
        try:
            response = await asyncio.wait_for(
                self._llm.generate(
                    prompt=regen_prompt,
                    evaluation_type="generation",
                ),
                timeout=self.GENERATION_TIMEOUT,
            )

            raw_text = (
                response
                if isinstance(response, str)
                else response.get("content", response.get("text", str(response)))
            )
            regenerated_data = json.loads(raw_text)

            # Replace flagged talking points with regenerated ones
            if isinstance(regenerated_data, list):
                regenerated_points = regenerated_data
            else:
                regenerated_points = regenerated_data.get("star_talking_points", [])

            updated_points = list(pack.star_talking_points)
            for idx, regen_idx in enumerate(flagged_indices):
                if idx < len(regenerated_points):
                    rp = regenerated_points[idx]
                    updated_points[regen_idx] = STAR_Talking_Point(
                        competency=rp.get(
                            "competency",
                            pack.star_talking_points[regen_idx].competency,
                        ),
                        question=rp.get(
                            "question",
                            pack.star_talking_points[regen_idx].question,
                        ),
                        situation=rp.get("situation", ""),
                        task=rp.get("task", ""),
                        action=rp.get("action", ""),
                        result=rp.get("result", ""),
                        source_asset_refs=rp.get("source_asset_refs", []),
                        is_gap_handled=rp.get("is_gap_handled", False),
                        gap_note=rp.get("gap_note"),
                    )

            # Re-verify regenerated points
            regen_texts = []
            for i in flagged_indices:
                tp = updated_points[i]
                text = (
                    f"Competency: {tp.competency}\n"
                    f"Situation: {tp.situation}\n"
                    f"Task: {tp.task}\n"
                    f"Action: {tp.action}\n"
                    f"Result: {tp.result}"
                )
                regen_texts.append(text)

            regen_combined = "\n\n---\n\n".join(regen_texts)

            regen_material_proxy = _MaterialProxy(
                material_id=f"interview_prep_{pack.id}_regen",
                pipeline_record_id=pack.pipeline_record_id,
                text=regen_combined,
            )

            re_verify_result = await self._grounding.verify_material(
                reviewed_material=regen_material_proxy,
                beneficiary=beneficiary_proxy,
                enrichment=context.enrichment_record,
            )

            # Check remaining ungrounded claims after re-verification
            remaining_ungrounded = [
                claim
                for claim in re_verify_result.grounding_report.claims
                if claim.grounding_status
                and claim.grounding_status.value == "ungrounded"
            ]

            remaining_flags = [claim.claim_text for claim in remaining_ungrounded]

            # Build updated pack with regenerated points and remaining flags
            updated_pack = Interview_Prep_Pack(
                id=pack.id,
                pipeline_record_id=pack.pipeline_record_id,
                beneficiary_id=pack.beneficiary_id,
                opportunity_type_id=pack.opportunity_type_id,
                likely_questions=pack.likely_questions,
                star_talking_points=updated_points,
                company_briefing=pack.company_briefing,
                questions_to_ask=pack.questions_to_ask,
                status=pack.status,
                omission_notes=pack.omission_notes,
                grounding_flags=remaining_flags,
                generation_duration_ms=pack.generation_duration_ms,
                created_at=pack.created_at,
                updated_at=pack.updated_at,
            )

            return updated_pack, remaining_flags

        except (asyncio.TimeoutError, json.JSONDecodeError, Exception):
            # Regeneration failed — surface original flags
            original_flags = [claim.claim_text for claim in ungrounded_claims]

            updated_pack = Interview_Prep_Pack(
                id=pack.id,
                pipeline_record_id=pack.pipeline_record_id,
                beneficiary_id=pack.beneficiary_id,
                opportunity_type_id=pack.opportunity_type_id,
                likely_questions=pack.likely_questions,
                star_talking_points=pack.star_talking_points,
                company_briefing=pack.company_briefing,
                questions_to_ask=pack.questions_to_ask,
                status=pack.status,
                omission_notes=pack.omission_notes,
                grounding_flags=original_flags,
                generation_duration_ms=pack.generation_duration_ms,
                created_at=pack.created_at,
                updated_at=pack.updated_at,
            )

            return updated_pack, original_flags
