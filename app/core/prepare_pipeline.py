"""Prepare Pipeline — orchestrates material generation with voice asset integration.

Fetches voice assets for the beneficiary, passes them to PersonalizationEngine
for generation and ReviewPipelineStage for review, then persists the voice_applied
tag on the pipeline_record for A/B observability.

Requirements: 2.1, 3.1, 4.1
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


class PreparePipeline:
    """Orchestrates the full prepare phase: voice fetch → generate → review → persist.

    Integrates VoiceAssetRepository with PersonalizationEngine and
    ReviewPipelineStage, ensuring voice assets are fetched once and
    threaded through both generation and review phases.

    Graceful degradation: if voice asset fetching fails (timeout, DB error),
    the pipeline proceeds without voice (voice_applied=False).

    Dependencies:
        personalization_engine: PersonalizationEngine for material generation.
        review_pipeline_stage: ReviewPipelineStage for review + grounding.
        voice_asset_repo: VoiceAssetRepository for fetching voice definitions.
        session_factory: Async session factory for persisting voice_applied tag.
    """

    def __init__(
        self,
        personalization_engine: object,
        review_pipeline_stage: object,
        voice_asset_repo: object | None = None,
        session_factory: async_sessionmaker | None = None,
    ) -> None:
        """Initialize the PreparePipeline.

        Args:
            personalization_engine: PersonalizationEngine instance.
            review_pipeline_stage: ReviewPipelineStage instance.
            voice_asset_repo: Optional VoiceAssetRepository for voice fetching.
                If None, voice integration is skipped (graceful degradation).
            session_factory: Optional async session factory for persisting
                voice_applied on pipeline_records.
        """
        self._personalization_engine = personalization_engine
        self._review_stage = review_pipeline_stage
        self._voice_repo = voice_asset_repo
        self._session_factory = session_factory

    async def run(
        self,
        enrichment: object,
        beneficiary_id: str,
        material_type: str,
        prospect: object,
        beneficiary: object,
        opportunity_description: str,
        pipeline_record_id: str | None = None,
        contact_seniority: str | None = None,
        beneficiary_context: dict | None = None,
    ) -> dict[str, Any]:
        """Execute the full prepare pipeline: fetch voice → generate → review → persist.

        Steps:
        1. Fetch voice assets for the beneficiary via VoiceAssetRepository
        2. Call PersonalizationEngine.generate_materials() with voice_asset and
           behavioral_profile
        3. Pass generated material through ReviewPipelineStage.process_after_generation()
           with voice_asset and behavioral_profile for review-time voice checking
        4. Persist voice_applied tag on the pipeline_record

        Graceful degradation:
        - If voice_asset_repo is None or fetch fails, proceeds without voice
        - voice_applied=False when no voice asset available or fetch fails
        - voice_applied=True when voice asset was successfully applied

        Args:
            enrichment: EnrichmentData for the prospect.
            beneficiary_id: The beneficiary generating outreach.
            material_type: Type of material (cv, cover_letter, proposal, email).
            prospect: The target prospect.
            beneficiary: The beneficiary object with profile assets.
            opportunity_description: Description of the opportunity.
            pipeline_record_id: Optional pipeline record ID for persisting voice_applied.
            contact_seniority: Optional seniority of the target contact.
            beneficiary_context: Optional additional beneficiary context.

        Returns:
            Dict containing:
                - generation_result: PersonalizationResult from generate_materials()
                - review_result: Dict from ReviewPipelineStage.process_after_generation()
                - voice_applied: Boolean indicating if voice was applied
                - voice_asset: The fetched VoiceAsset dict or None
                - behavioral_profile: The fetched BehavioralProfileAsset dict or None

        Requirements: 2.1, 3.1, 4.1
        """
        # ── Step 1: Fetch voice assets ────────────────────────────────────────
        voice_asset = None
        behavioral_profile = None
        voice_asset_obj = None
        behavioral_profile_obj = None

        if self._voice_repo is not None:
            try:
                all_assets = await self._voice_repo.get_all_voice_assets(beneficiary_id)
                voice_asset = all_assets.get("writing_style")
                behavioral_profile = all_assets.get("behavioral_profile")

                # Convert dicts to domain objects if needed
                if voice_asset is not None:
                    voice_asset_obj = self._dict_to_voice_asset(voice_asset)
                if behavioral_profile is not None:
                    behavioral_profile_obj = self._dict_to_behavioral_profile(
                        behavioral_profile
                    )
            except Exception:
                # Graceful degradation: proceed without voice on any fetch error
                logger.warning(
                    "Failed to fetch voice assets for beneficiary '%s'; "
                    "proceeding without voice integration.",
                    beneficiary_id,
                    exc_info=True,
                )
                voice_asset = None
                behavioral_profile = None
                voice_asset_obj = None
                behavioral_profile_obj = None

        # ── Step 2: Generate materials with voice ─────────────────────────────
        generation_result = await self._personalization_engine.generate_materials(
            enrichment=enrichment,
            beneficiary_id=beneficiary_id,
            material_type=material_type,
            contact_seniority=contact_seniority,
            beneficiary_context=beneficiary_context,
            voice_asset=voice_asset_obj,
            behavioral_profile=behavioral_profile_obj,
        )

        voice_applied = generation_result.voice_applied

        # ── Step 3: Pass through review stage with voice ──────────────────────
        # Build a DraftMaterial-like object for the review stage
        from datetime import datetime, timezone

        from app.core.review_models import DraftMaterial

        draft_material = DraftMaterial(
            id=pipeline_record_id or "unknown",
            pipeline_record_id=pipeline_record_id or "unknown",
            prepare_technique_id="personalization",
            material_type=material_type,
            content=generation_result.content,
            quality_score=generation_result.quality_score,
            generated_at=datetime.now(timezone.utc),
        )

        review_result = await self._review_stage.process_after_generation(
            draft_material=draft_material,
            prospect=prospect,
            beneficiary=beneficiary,
            enrichment=enrichment,
            opportunity_description=opportunity_description,
            voice_asset=voice_asset_obj,
            behavioral_profile=behavioral_profile_obj,
        )

        # ── Step 4: Persist voice_applied tag on pipeline_record ──────────────
        if pipeline_record_id is not None and self._session_factory is not None:
            await self._persist_voice_applied(pipeline_record_id, voice_applied)

        return {
            "generation_result": generation_result,
            "review_result": review_result,
            "voice_applied": voice_applied,
            "voice_asset": voice_asset,
            "behavioral_profile": behavioral_profile,
        }

    async def _persist_voice_applied(
        self, pipeline_record_id: str, voice_applied: bool
    ) -> None:
        """Persist the voice_applied flag on the pipeline_record.

        Updates the pipeline_records table with the voice_applied boolean
        for A/B observability segmentation.

        Args:
            pipeline_record_id: UUID of the pipeline record to update.
            voice_applied: Whether voice was applied during generation.

        Requirements: 4.1
        """
        try:
            async with self._session_factory() as session:
                stmt = text("""
                    UPDATE pipeline_records
                    SET voice_applied = :voice_applied
                    WHERE id = :pipeline_record_id
                """)
                await session.execute(
                    stmt,
                    {
                        "voice_applied": voice_applied,
                        "pipeline_record_id": pipeline_record_id,
                    },
                )
                await session.commit()
                logger.info(
                    "Persisted voice_applied=%s on pipeline_record '%s'",
                    voice_applied,
                    pipeline_record_id,
                )
        except Exception:
            # Non-fatal: voice_applied tag is for analytics, not critical path
            logger.warning(
                "Failed to persist voice_applied on pipeline_record '%s'; "
                "analytics segmentation may be incomplete.",
                pipeline_record_id,
                exc_info=True,
            )

    @staticmethod
    def _dict_to_voice_asset(data: dict) -> object:
        """Convert a voice asset dict (from repository) to a VoiceAsset domain object.

        Args:
            data: Dict with voice asset fields from the database.

        Returns:
            VoiceAsset instance for use in PersonalizationEngine and ReviewService.
        """
        from app.core.voice_asset import (
            ExemplarPassage,
            FirstPersonUsage,
            SentenceLengthPreference,
            VoiceAsset,
            VoiceAssetType,
            VoiceRegister,
            WritingStyleAsset,
        )

        exemplar_passages = [
            ExemplarPassage(text=ep["text"], context=ep.get("context"))
            for ep in (data.get("exemplar_passages") or [])
        ]

        return WritingStyleAsset(
            id=str(data.get("id", "")),
            beneficiary_id=data.get("beneficiary_id", ""),
            asset_type=VoiceAssetType.WRITING_STYLE,
            register=VoiceRegister(data.get("register", "direct")),
            sentence_length=SentenceLengthPreference(
                data.get("sentence_length", "medium")
            ),
            first_person_usage=FirstPersonUsage(
                data.get("first_person_usage", "moderate")
            ),
            vocabulary_prefer=data.get("vocabulary_prefer") or [],
            vocabulary_avoid=data.get("vocabulary_avoid") or [],
            exemplar_passages=exemplar_passages,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    @staticmethod
    def _dict_to_behavioral_profile(data: dict) -> object:
        """Convert a behavioral profile dict to a BehavioralProfileAsset domain object.

        Args:
            data: Dict with behavioral profile fields from the database.

        Returns:
            BehavioralProfileAsset instance for tone guidance.
        """
        from app.core.voice_asset import BehavioralProfileAsset, VoiceAssetType

        return BehavioralProfileAsset(
            id=str(data.get("id", "")),
            beneficiary_id=data.get("beneficiary_id", ""),
            asset_type=VoiceAssetType.BEHAVIORAL_PROFILE,
            interpersonal_style=data.get("interpersonal_style", ""),
            communication_traits=data.get("communication_traits") or [],
            avoid_impressions=data.get("avoid_impressions") or [],
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
