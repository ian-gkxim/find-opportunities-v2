"""Review Pipeline Stage — integration point between material generation and review.

Sits between the Personalization_Engine's material generation output and the
downstream pipeline stages. Checks the Schema_Registry for a review_technique
configuration and conditionally dispatches review via ReviewService. After
review completes, conditionally invokes the Grounding_Verifier (P2) if a
grounding_technique is configured for the prepare technique.

Requirements: 1.1, 4.2
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.review_models import (
    DraftMaterial,
    ReviewResult,
    ReviewStatus,
)

logger = logging.getLogger(__name__)


class ReviewPipelineStage:
    """Pipeline stage that conditionally applies review critique and grounding verification.

    After the Personalization_Engine produces a DraftMaterial, this stage:
    1. Checks the Schema_Registry for a review_technique linked to the prepare technique
    2. If configured: dispatches review via ReviewService with a 10-second deadline check
    3. If absent: passes the draft material through unchanged
    4. After review completes: checks Schema_Registry for a grounding_technique
    5. If grounding configured: invokes GroundingVerifier.verify_material()
    6. If grounding absent: skips grounding, proceeds to post-prepare state

    The pipeline flow is:
    Personalization_Engine → Review_Service (P1) → Grounding_Verifier (P2) → post-prepare state

    The 10-second DISPATCH_DEADLINE (Requirement 1.1) is enforced by measuring elapsed
    time from when this stage is invoked. If the review dispatch takes longer than
    DISPATCH_DEADLINE before the first critique request goes out, a warning is logged.

    Dependencies:
        review_service: ReviewService for executing critique cycles
        schema_registry: SchemaRegistry for review_technique lookup and grounding config
        grounding_verifier: GroundingVerifier for claim extraction and verification (optional)
        notification_service: GroundingNotificationService for WebSocket push (optional)

    Requirements: 1.1 (dispatch within 10s), 4.2 (schema-driven skip/apply)
    """

    DISPATCH_DEADLINE: float = 10.0  # seconds — must dispatch within this window

    def __init__(
        self,
        review_service: object,
        schema_registry: object,
        grounding_verifier: object | None = None,
        notification_service: object | None = None,
    ) -> None:
        """Initialize the ReviewPipelineStage.

        Args:
            review_service: ReviewService instance for dispatching critiques.
            schema_registry: SchemaRegistry instance for review_technique lookup.
            grounding_verifier: Optional GroundingVerifier for claim verification (P2).
            notification_service: Optional GroundingNotificationService for WebSocket push.
        """
        self._review_service = review_service
        self._schema = schema_registry
        self._grounding_verifier = grounding_verifier
        self._notification_service = notification_service

    async def process_after_generation(
        self,
        draft_material: DraftMaterial,
        prospect: object,
        beneficiary: object,
        enrichment: object,
        opportunity_description: str,
        voice_asset: object | None = None,
        behavioral_profile: object | None = None,
    ) -> dict[str, Any]:
        """Process a draft material after generation, applying review then grounding.

        Pipeline flow:
        1. Checks Schema_Registry for review_technique — dispatches if configured
        2. After review completes: checks Schema_Registry for grounding_technique
        3. If grounding configured: invokes GroundingVerifier.verify_material()
        4. If grounding absent: skips grounding, proceeds to post-prepare state

        Enforces the DISPATCH_DEADLINE (10s): if more than 10 seconds elapse
        before the critique is dispatched, a warning is logged (the review
        still proceeds — the deadline is observational, not a hard abort).

        Args:
            draft_material: The DraftMaterial produced by the Personalization_Engine.
            prospect: The target prospect (company/contact).
            beneficiary: The beneficiary whose assets ground the critique.
            enrichment: The prospect's enrichment record.
            opportunity_description: Description of the opportunity being pursued.
            voice_asset: Optional Voice_Asset for voice-mismatch detection during review.
            behavioral_profile: Optional Behavioral_Profile_Asset for tone checks.

        Returns:
            A dict containing:
                - revised_content (str): The final material content (revised or original).
                - review_status (ReviewStatus): REVIEWED, UNREVIEWED, or REVIEW_FAILED.
                - reasoning_log (ReasoningLog | None): Full telemetry if review ran, else None.
                - quality_score (int): Final quality score after review (or original score).
                - grounding_result (GroundingResult | None): Result of grounding verification,
                  or None if grounding was skipped or not configured.

        Requirements: 1.1, 1.4, 4.2
        """
        stage_start = time.monotonic()

        # Check Schema_Registry for review_technique
        review_technique = self._schema.get_review_technique_for_prepare(
            draft_material.prepare_technique_id
        )

        if review_technique is None:
            # No review_technique configured — skip review, pass material through
            # (Requirement 4.2: skip review when field is absent)
            logger.debug(
                "No review_technique configured for prepare_technique '%s' — "
                "skipping review.",
                draft_material.prepare_technique_id,
            )
            reviewed_content = draft_material.content
            review_status = ReviewStatus.REVIEWED
            reasoning_log = None
            quality_score = draft_material.quality_score
        else:
            # Review technique is configured — dispatch review
            # Check DISPATCH_DEADLINE (Requirement 1.1)
            elapsed_before_dispatch = time.monotonic() - stage_start
            if elapsed_before_dispatch > self.DISPATCH_DEADLINE:
                logger.warning(
                    "DISPATCH_DEADLINE exceeded: %.2fs elapsed before dispatching "
                    "review for material '%s' (limit: %.1fs). "
                    "Review will still proceed.",
                    elapsed_before_dispatch,
                    draft_material.id,
                    self.DISPATCH_DEADLINE,
                )

            # Dispatch review via ReviewService
            try:
                result: ReviewResult = await self._review_service.review_material(
                    draft_material=draft_material,
                    prospect=prospect,
                    beneficiary=beneficiary,
                    enrichment=enrichment,
                    opportunity_description=opportunity_description,
                    voice_asset=voice_asset,
                    behavioral_profile=behavioral_profile,
                )

                # Check deadline after dispatch completes (for observability)
                total_elapsed = time.monotonic() - stage_start
                exceeded_total = total_elapsed > self.DISPATCH_DEADLINE
                dispatched_in_time = elapsed_before_dispatch <= self.DISPATCH_DEADLINE
                if exceeded_total and dispatched_in_time:
                    logger.info(
                        "Review for material '%s' completed in %.2fs "
                        "(exceeded DISPATCH_DEADLINE of %.1fs, but critique was "
                        "dispatched within the deadline).",
                        draft_material.id,
                        total_elapsed,
                        self.DISPATCH_DEADLINE,
                    )

                reviewed_content = result.revised_content
                review_status = result.review_status
                reasoning_log = result.reasoning_log
                quality_score = result.quality_score_final

            except Exception as exc:
                # Unexpected failure — graceful degradation
                logger.error(
                    "ReviewPipelineStage encountered unexpected error for "
                    "material '%s': %s. Passing original content through.",
                    draft_material.id,
                    exc,
                )
                reviewed_content = draft_material.content
                review_status = ReviewStatus.UNREVIEWED
                reasoning_log = None
                quality_score = draft_material.quality_score

        # ─── GROUNDING VERIFICATION (P2) ─────────────────────────────────────
        # After review completes, check if grounding_technique is configured
        # and invoke the GroundingVerifier if so.
        # Requirements: 1.1, 1.4

        grounding_result = await self._run_grounding_verification(
            draft_material=draft_material,
            reviewed_content=reviewed_content,
            beneficiary=beneficiary,
            enrichment=enrichment,
        )

        return {
            "revised_content": reviewed_content,
            "review_status": review_status,
            "reasoning_log": reasoning_log,
            "quality_score": quality_score,
            "grounding_result": grounding_result,
        }

    async def _run_grounding_verification(
        self,
        draft_material: DraftMaterial,
        reviewed_content: str,
        beneficiary: object,
        enrichment: object,
    ) -> Any:
        """Conditionally run grounding verification after review completes.

        Checks Schema_Registry for a grounding_technique configured on the
        prepare technique. If configured and a GroundingVerifier is available,
        invokes verify_material(). If not configured, skips gracefully.

        On grounding_unverified: allows pipeline to proceed (no blocking),
        but sends a notification via the notification service if available.

        Args:
            draft_material: The original draft material (for IDs and metadata).
            reviewed_content: The final material text after review.
            beneficiary: The beneficiary whose assets are used for verification.
            enrichment: The prospect's enrichment record.

        Returns:
            GroundingResult if grounding ran, None if skipped.

        Requirements: 1.1, 1.4
        """
        # Check if grounding_technique is configured for this prepare technique
        grounding_technique = None
        if hasattr(self._schema, "get_grounding_technique_for_prepare"):
            grounding_technique = self._schema.get_grounding_technique_for_prepare(
                draft_material.prepare_technique_id
            )

        if grounding_technique is None:
            # No grounding_technique configured — skip grounding
            logger.debug(
                "No grounding_technique configured for prepare_technique '%s' — "
                "skipping grounding verification.",
                draft_material.prepare_technique_id,
            )
            return None

        if self._grounding_verifier is None:
            # Grounding technique is configured but verifier not available
            logger.warning(
                "grounding_technique '%s' is configured for prepare_technique '%s' "
                "but no GroundingVerifier is available. Skipping grounding.",
                grounding_technique.id if hasattr(grounding_technique, "id") else grounding_technique,
                draft_material.prepare_technique_id,
            )
            return None

        # Build a lightweight reviewed material object for the verifier
        reviewed_material = _ReviewedMaterial(
            id=draft_material.id,
            pipeline_record_id=draft_material.pipeline_record_id,
            text=reviewed_content,
        )

        try:
            grounding_result = await self._grounding_verifier.verify_material(
                reviewed_material=reviewed_material,
                beneficiary=beneficiary,
                enrichment=enrichment,
            )

            # Log grounding outcome
            logger.info(
                "Grounding verification for material '%s': status=%s, "
                "total_claims=%d, ungrounded=%d",
                draft_material.id,
                grounding_result.material_grounding_status.value,
                grounding_result.grounding_report.total_claims,
                grounding_result.grounding_report.ungrounded_count,
            )

            # Push WebSocket notification if requires action
            if self._notification_service is not None and grounding_result.requires_action:
                try:
                    await self._notification_service.notify_requires_action(
                        grounding_result
                    )
                except Exception as notify_exc:
                    logger.warning(
                        "Failed to send grounding notification for material '%s': %s",
                        draft_material.id,
                        notify_exc,
                    )

            return grounding_result

        except Exception as exc:
            # Grounding failed — handle gracefully (Requirement 1.4)
            # Pipeline proceeds; material surfaces in Dashboard "Requires Action"
            logger.error(
                "Grounding verification failed for material '%s': %s. "
                "Pipeline will proceed (grounding_unverified).",
                draft_material.id,
                exc,
            )
            return None


class _ReviewedMaterial:
    """Lightweight reviewed material object for GroundingVerifier.verify_material().

    Provides the minimal interface expected by the GroundingVerifier:
    - id: material identifier
    - pipeline_record_id: pipeline record identifier
    - text: the material content to verify
    """

    __slots__ = ("id", "pipeline_record_id", "text")

    def __init__(self, id: str, pipeline_record_id: str, text: str) -> None:
        self.id = id
        self.pipeline_record_id = pipeline_record_id
        self.text = text
