"""Unit tests for PreparePipeline — voice asset wiring into the prepare phase.

Verifies that:
- Voice assets are fetched before generation
- voice_asset and behavioral_profile are passed to generate_materials()
- voice_asset and behavioral_profile are passed to ReviewPipelineStage
- voice_applied tag is persisted on the pipeline_record
- Graceful degradation when voice fetch fails

Requirements: 2.1, 3.1, 4.1
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.prepare_pipeline import PreparePipeline
from app.core.personalization_engine import EnrichmentData, PersonalizationResult


@pytest.fixture
def mock_personalization_engine():
    """Mock PersonalizationEngine with generate_materials returning a result."""
    engine = AsyncMock()
    engine.generate_materials = AsyncMock(
        return_value=PersonalizationResult(
            content="Generated content with voice",
            quality_score=75,
            fields_used=["industry"],
            fields_available_unused=[],
            tone_applied="direct",
            hooks_referenced=[],
            is_low_quality=False,
            voice_applied=True,
            flags=[],
        )
    )
    return engine


@pytest.fixture
def mock_review_pipeline_stage():
    """Mock ReviewPipelineStage."""
    stage = AsyncMock()
    stage.process_after_generation = AsyncMock(
        return_value={
            "revised_content": "Reviewed content",
            "review_status": "reviewed",
            "reasoning_log": None,
            "quality_score": 80,
            "grounding_result": None,
        }
    )
    return stage


@pytest.fixture
def mock_voice_repo():
    """Mock VoiceAssetRepository with voice assets."""
    repo = AsyncMock()
    repo.get_all_voice_assets = AsyncMock(
        return_value={
            "writing_style": {
                "id": "ws-001",
                "beneficiary_id": "consultant-1",
                "asset_type": "writing_style",
                "register": "direct",
                "sentence_length": "varied",
                "first_person_usage": "frequent",
                "vocabulary_prefer": ["ship", "build"],
                "vocabulary_avoid": ["leverage", "synergize"],
                "exemplar_passages": [
                    {
                        "text": "I noticed your team just shipped a rewrite — bold move.",
                        "context": "cold email opener",
                    },
                    {
                        "text": "Let me be direct: I've built three platform teams from scratch.",
                        "context": "cover letter body",
                    },
                ],
                "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "updated_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            },
            "behavioral_profile": {
                "id": "bp-001",
                "beneficiary_id": "consultant-1",
                "asset_type": "behavioral_profile",
                "interpersonal_style": "collaborative",
                "communication_traits": ["asks questions", "uses 'we'"],
                "avoid_impressions": ["combative", "apologetic"],
                "created_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "updated_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
            },
            "brand_voice": None,
        }
    )
    return repo


@pytest.fixture
def mock_session_factory():
    """Mock async session factory for persisting voice_applied."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    factory = MagicMock()
    factory.return_value = session
    return factory


@pytest.fixture
def sample_enrichment():
    """Sample enrichment data."""
    return EnrichmentData(
        industry="fintech",
        tech_stack=["Python", "React"],
        company_size=200,
    )


class TestPreparePipelineVoiceFetching:
    """Tests for voice asset fetching before generation."""

    @pytest.mark.asyncio
    async def test_fetches_voice_assets_before_generation(
        self,
        mock_personalization_engine,
        mock_review_pipeline_stage,
        mock_voice_repo,
        mock_session_factory,
        sample_enrichment,
    ):
        """Voice assets are fetched via VoiceAssetRepository before generate_materials."""
        pipeline = PreparePipeline(
            personalization_engine=mock_personalization_engine,
            review_pipeline_stage=mock_review_pipeline_stage,
            voice_asset_repo=mock_voice_repo,
            session_factory=mock_session_factory,
        )

        await pipeline.run(
            enrichment=sample_enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            opportunity_description="Test opportunity",
            pipeline_record_id="pr-001",
        )

        mock_voice_repo.get_all_voice_assets.assert_called_once_with("consultant-1")

    @pytest.mark.asyncio
    async def test_passes_voice_asset_to_generate_materials(
        self,
        mock_personalization_engine,
        mock_review_pipeline_stage,
        mock_voice_repo,
        mock_session_factory,
        sample_enrichment,
    ):
        """voice_asset and behavioral_profile are passed to generate_materials()."""
        pipeline = PreparePipeline(
            personalization_engine=mock_personalization_engine,
            review_pipeline_stage=mock_review_pipeline_stage,
            voice_asset_repo=mock_voice_repo,
            session_factory=mock_session_factory,
        )

        await pipeline.run(
            enrichment=sample_enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            opportunity_description="Test opportunity",
            pipeline_record_id="pr-001",
        )

        call_kwargs = mock_personalization_engine.generate_materials.call_args.kwargs
        assert call_kwargs["voice_asset"] is not None
        assert call_kwargs["behavioral_profile"] is not None
        # Verify the voice asset was converted from dict to domain object
        assert call_kwargs["voice_asset"].register.value == "direct"
        assert call_kwargs["behavioral_profile"].interpersonal_style == "collaborative"

    @pytest.mark.asyncio
    async def test_passes_voice_asset_to_review_stage(
        self,
        mock_personalization_engine,
        mock_review_pipeline_stage,
        mock_voice_repo,
        mock_session_factory,
        sample_enrichment,
    ):
        """voice_asset and behavioral_profile are passed to ReviewPipelineStage."""
        pipeline = PreparePipeline(
            personalization_engine=mock_personalization_engine,
            review_pipeline_stage=mock_review_pipeline_stage,
            voice_asset_repo=mock_voice_repo,
            session_factory=mock_session_factory,
        )

        await pipeline.run(
            enrichment=sample_enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            opportunity_description="Test opportunity",
            pipeline_record_id="pr-001",
        )

        call_kwargs = mock_review_pipeline_stage.process_after_generation.call_args.kwargs
        assert call_kwargs["voice_asset"] is not None
        assert call_kwargs["behavioral_profile"] is not None
        assert call_kwargs["voice_asset"].register.value == "direct"


class TestPreparePipelineVoiceAppliedPersistence:
    """Tests for persisting voice_applied tag on pipeline_record."""

    @pytest.mark.asyncio
    async def test_persists_voice_applied_true(
        self,
        mock_personalization_engine,
        mock_review_pipeline_stage,
        mock_voice_repo,
        mock_session_factory,
        sample_enrichment,
    ):
        """voice_applied=True is persisted when voice asset was applied."""
        pipeline = PreparePipeline(
            personalization_engine=mock_personalization_engine,
            review_pipeline_stage=mock_review_pipeline_stage,
            voice_asset_repo=mock_voice_repo,
            session_factory=mock_session_factory,
        )

        result = await pipeline.run(
            enrichment=sample_enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            opportunity_description="Test opportunity",
            pipeline_record_id="pr-001",
        )

        assert result["voice_applied"] is True
        # Verify the session was used to persist
        session = mock_session_factory.return_value
        session.execute.assert_called_once()
        session.commit.assert_called_once()
        # Check the SQL parameters
        call_args = session.execute.call_args
        params = call_args[0][1]
        assert params["voice_applied"] is True
        assert params["pipeline_record_id"] == "pr-001"

    @pytest.mark.asyncio
    async def test_persists_voice_applied_false_when_no_voice(
        self,
        mock_personalization_engine,
        mock_review_pipeline_stage,
        mock_session_factory,
        sample_enrichment,
    ):
        """voice_applied=False is persisted when no voice asset available."""
        # Engine returns voice_applied=False when no voice asset
        mock_personalization_engine.generate_materials.return_value = PersonalizationResult(
            content="Generated without voice",
            quality_score=60,
            fields_used=["industry"],
            fields_available_unused=[],
            tone_applied="director",
            hooks_referenced=[],
            is_low_quality=False,
            voice_applied=False,
            flags=[],
        )

        # No voice repo → no voice assets
        pipeline = PreparePipeline(
            personalization_engine=mock_personalization_engine,
            review_pipeline_stage=mock_review_pipeline_stage,
            voice_asset_repo=None,
            session_factory=mock_session_factory,
        )

        result = await pipeline.run(
            enrichment=sample_enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            opportunity_description="Test opportunity",
            pipeline_record_id="pr-001",
        )

        assert result["voice_applied"] is False
        # Still persists the tag
        session = mock_session_factory.return_value
        params = session.execute.call_args[0][1]
        assert params["voice_applied"] is False


class TestPreparePipelineGracefulDegradation:
    """Tests for graceful degradation when voice fetch fails."""

    @pytest.mark.asyncio
    async def test_proceeds_without_voice_on_fetch_error(
        self,
        mock_personalization_engine,
        mock_review_pipeline_stage,
        mock_session_factory,
        sample_enrichment,
    ):
        """Pipeline proceeds without voice when VoiceAssetRepository raises."""
        # Engine returns voice_applied=False when no voice asset passed
        mock_personalization_engine.generate_materials.return_value = PersonalizationResult(
            content="Generated without voice (degraded)",
            quality_score=60,
            fields_used=["industry"],
            fields_available_unused=[],
            tone_applied="director",
            hooks_referenced=[],
            is_low_quality=False,
            voice_applied=False,
            flags=[],
        )

        failing_repo = AsyncMock()
        failing_repo.get_all_voice_assets = AsyncMock(
            side_effect=TimeoutError("DB connection timed out")
        )

        pipeline = PreparePipeline(
            personalization_engine=mock_personalization_engine,
            review_pipeline_stage=mock_review_pipeline_stage,
            voice_asset_repo=failing_repo,
            session_factory=mock_session_factory,
        )

        result = await pipeline.run(
            enrichment=sample_enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            opportunity_description="Test opportunity",
            pipeline_record_id="pr-001",
        )

        # Should still generate and complete
        assert result["voice_applied"] is False
        assert result["voice_asset"] is None
        assert result["behavioral_profile"] is None

        # generate_materials was called with None voice args
        call_kwargs = mock_personalization_engine.generate_materials.call_args.kwargs
        assert call_kwargs["voice_asset"] is None
        assert call_kwargs["behavioral_profile"] is None

    @pytest.mark.asyncio
    async def test_proceeds_without_voice_when_no_repo(
        self,
        mock_personalization_engine,
        mock_review_pipeline_stage,
        mock_session_factory,
        sample_enrichment,
    ):
        """Pipeline works when voice_asset_repo is None (no repo configured)."""
        mock_personalization_engine.generate_materials.return_value = PersonalizationResult(
            content="Generated without voice",
            quality_score=60,
            fields_used=["industry"],
            fields_available_unused=[],
            tone_applied="director",
            hooks_referenced=[],
            is_low_quality=False,
            voice_applied=False,
            flags=[],
        )

        pipeline = PreparePipeline(
            personalization_engine=mock_personalization_engine,
            review_pipeline_stage=mock_review_pipeline_stage,
            voice_asset_repo=None,
            session_factory=mock_session_factory,
        )

        result = await pipeline.run(
            enrichment=sample_enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            opportunity_description="Test opportunity",
            pipeline_record_id="pr-001",
        )

        assert result["voice_applied"] is False
        mock_personalization_engine.generate_materials.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_persist_without_pipeline_record_id(
        self,
        mock_personalization_engine,
        mock_review_pipeline_stage,
        mock_voice_repo,
        mock_session_factory,
        sample_enrichment,
    ):
        """voice_applied is not persisted when no pipeline_record_id provided."""
        pipeline = PreparePipeline(
            personalization_engine=mock_personalization_engine,
            review_pipeline_stage=mock_review_pipeline_stage,
            voice_asset_repo=mock_voice_repo,
            session_factory=mock_session_factory,
        )

        await pipeline.run(
            enrichment=sample_enrichment,
            beneficiary_id="consultant-1",
            material_type="email",
            prospect=MagicMock(),
            beneficiary=MagicMock(),
            opportunity_description="Test opportunity",
            pipeline_record_id=None,  # No record ID
        )

        # Session should not be used
        session = mock_session_factory.return_value
        session.execute.assert_not_called()
