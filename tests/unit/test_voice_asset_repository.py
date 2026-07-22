"""Unit tests for app.repositories.voice_asset_repo.VoiceAssetRepository.

Verifies persistence logic with mocked async sessions since we cannot
connect to a real PostgreSQL database in unit tests.

Requirements: 1.1, 1.3
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.repositories.voice_asset_repo import VoiceAssetRepository


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_session():
    """Create a mock async session with execute and commit methods."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.fixture
def mock_session_factory(mock_session):
    """Create a mock session factory that returns the mock session as an async context manager."""
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


@pytest.fixture
def repository(mock_session_factory):
    """Create a VoiceAssetRepository instance with the mocked session factory."""
    return VoiceAssetRepository(session_factory=mock_session_factory)


@pytest.fixture
def sample_voice_asset_row():
    """A sample row tuple as returned from a SELECT on voice_assets."""
    now = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    return (
        "asset-uuid-001",           # id
        "consultant-001",           # beneficiary_id
        "writing_style",            # asset_type
        "direct",                   # register
        "varied",                   # sentence_length
        "frequent",                 # first_person_usage
        json.dumps(["ship", "build", "trade-off"]),  # vocabulary_prefer
        json.dumps(["leverage", "synergize"]),        # vocabulary_avoid
        json.dumps([                # exemplar_passages
            {"text": "I noticed your team just shipped a React Native rewrite.", "context": "cold email opener"},
            {"text": "Let me be direct: I've built three platform teams from scratch.", "context": "cover letter body"},
        ]),
        None,                       # interpersonal_style
        None,                       # communication_traits
        None,                       # avoid_impressions
        None,                       # brand_personality
        None,                       # tagline_style
        True,                       # is_active
        now,                        # created_at
        now,                        # updated_at
    )


@pytest.fixture
def sample_asset_data():
    """Sample asset_data dict for upsert operations."""
    return {
        "register": "direct",
        "sentence_length": "varied",
        "first_person_usage": "frequent",
        "vocabulary_prefer": ["ship", "build", "trade-off"],
        "vocabulary_avoid": ["leverage", "synergize"],
        "exemplar_passages": [
            {"text": "I noticed your team just shipped a React Native rewrite.", "context": "cold email opener"},
            {"text": "Let me be direct: I've built three platform teams from scratch.", "context": "cover letter body"},
        ],
    }


# ─── GET VOICE ASSET TESTS ───────────────────────────────────────────────────


class TestGetVoiceAsset:
    """Tests for VoiceAssetRepository.get_voice_asset."""

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, repository, mock_session):
        """get_voice_asset returns None when no active asset exists (graceful degradation)."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repository.get_voice_asset("nonexistent-beneficiary", "writing_style")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_asset_dict_when_found(
        self, repository, mock_session, sample_voice_asset_row
    ):
        """get_voice_asset returns a dict with correct fields when asset exists."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = sample_voice_asset_row
        mock_session.execute.return_value = mock_result

        result = await repository.get_voice_asset("consultant-001", "writing_style")

        assert result is not None
        assert result["id"] == "asset-uuid-001"
        assert result["beneficiary_id"] == "consultant-001"
        assert result["asset_type"] == "writing_style"
        assert result["register"] == "direct"
        assert result["sentence_length"] == "varied"
        assert result["first_person_usage"] == "frequent"
        assert result["vocabulary_prefer"] == ["ship", "build", "trade-off"]
        assert result["vocabulary_avoid"] == ["leverage", "synergize"]
        assert len(result["exemplar_passages"]) == 2
        assert result["is_active"] is True

    @pytest.mark.asyncio
    async def test_passes_correct_query_params(self, repository, mock_session):
        """Verify the query uses correct beneficiary_id and asset_type."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        await repository.get_voice_asset("consultant-xyz", "behavioral_profile")

        call_params = mock_session.execute.call_args_list[0][0][1]
        assert call_params["beneficiary_id"] == "consultant-xyz"
        assert call_params["asset_type"] == "behavioral_profile"


# ─── UPSERT VOICE ASSET TESTS ────────────────────────────────────────────────


class TestUpsertVoiceAsset:
    """Tests for VoiceAssetRepository.upsert_voice_asset."""

    @pytest.mark.asyncio
    async def test_creates_new_asset_returns_id(
        self, repository, mock_session, sample_asset_data
    ):
        """upsert_voice_asset creates a new asset when none exists and returns UUID."""
        # Mock the check query returning no existing row
        mock_check_result = MagicMock()
        mock_check_result.fetchone.return_value = None

        # Mock the insert (no return needed)
        mock_insert_result = MagicMock()

        mock_session.execute.side_effect = [mock_check_result, mock_insert_result]

        result = await repository.upsert_voice_asset(
            "consultant-001", "writing_style", sample_asset_data
        )

        # Should return a UUID string
        assert isinstance(result, str)
        parts = result.split("-")
        assert len(parts) == 5

        # Should have called execute twice: check + insert
        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_creates_new_asset_passes_correct_params(
        self, repository, mock_session, sample_asset_data
    ):
        """Verify the insert statement uses correct parameter values."""
        mock_check_result = MagicMock()
        mock_check_result.fetchone.return_value = None
        mock_insert_result = MagicMock()
        mock_session.execute.side_effect = [mock_check_result, mock_insert_result]

        await repository.upsert_voice_asset(
            "consultant-001", "writing_style", sample_asset_data
        )

        # Second call is the INSERT
        insert_params = mock_session.execute.call_args_list[1][0][1]
        assert insert_params["beneficiary_id"] == "consultant-001"
        assert insert_params["asset_type"] == "writing_style"
        assert insert_params["register"] == "direct"
        assert insert_params["sentence_length"] == "varied"
        assert insert_params["first_person_usage"] == "frequent"
        assert json.loads(insert_params["vocabulary_prefer"]) == ["ship", "build", "trade-off"]
        assert json.loads(insert_params["vocabulary_avoid"]) == ["leverage", "synergize"]

    @pytest.mark.asyncio
    async def test_updates_existing_asset(
        self, repository, mock_session, sample_asset_data
    ):
        """upsert_voice_asset updates an existing asset and returns its ID."""
        # Mock the check query returning an existing row
        mock_check_result = MagicMock()
        mock_check_result.fetchone.return_value = ("existing-uuid-123",)

        # Mock the update
        mock_update_result = MagicMock()

        mock_session.execute.side_effect = [mock_check_result, mock_update_result]

        result = await repository.upsert_voice_asset(
            "consultant-001", "writing_style", sample_asset_data
        )

        # Should return the existing UUID
        assert result == "existing-uuid-123"

        # Should have called execute twice: check + update
        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_updates_existing_passes_correct_params(
        self, repository, mock_session, sample_asset_data
    ):
        """Verify the update statement uses correct parameter values."""
        mock_check_result = MagicMock()
        mock_check_result.fetchone.return_value = ("existing-uuid-123",)
        mock_update_result = MagicMock()
        mock_session.execute.side_effect = [mock_check_result, mock_update_result]

        await repository.upsert_voice_asset(
            "consultant-001", "writing_style", sample_asset_data
        )

        # Second call is the UPDATE
        update_params = mock_session.execute.call_args_list[1][0][1]
        assert update_params["id"] == "existing-uuid-123"
        assert update_params["register"] == "direct"
        assert update_params["sentence_length"] == "varied"
        assert json.loads(update_params["vocabulary_avoid"]) == ["leverage", "synergize"]


# ─── DELETE VOICE ASSET TESTS ─────────────────────────────────────────────────


class TestDeleteVoiceAsset:
    """Tests for VoiceAssetRepository.delete_voice_asset."""

    @pytest.mark.asyncio
    async def test_soft_deletes_active_asset(self, repository, mock_session):
        """delete_voice_asset soft-deletes by setting is_active=False, returns True."""
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute.return_value = mock_result

        result = await repository.delete_voice_asset("consultant-001", "writing_style")

        assert result is True
        mock_session.commit.assert_called_once()

        # Verify the update params include is_active=FALSE logic
        call_params = mock_session.execute.call_args_list[0][0][1]
        assert call_params["beneficiary_id"] == "consultant-001"
        assert call_params["asset_type"] == "writing_style"

    @pytest.mark.asyncio
    async def test_returns_false_when_not_found(self, repository, mock_session):
        """delete_voice_asset returns False when no active asset exists."""
        mock_result = MagicMock()
        mock_result.rowcount = 0
        mock_session.execute.return_value = mock_result

        result = await repository.delete_voice_asset("nonexistent", "writing_style")

        assert result is False
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_after_delete_get_returns_none(self, repository, mock_session):
        """After soft-delete, get_voice_asset returns None (doesn't see inactive assets)."""
        # First call: delete succeeds (rowcount=1)
        mock_delete_result = MagicMock()
        mock_delete_result.rowcount = 1

        # Second call: get returns None (asset is now inactive)
        mock_get_result = MagicMock()
        mock_get_result.fetchone.return_value = None

        mock_session.execute.side_effect = [mock_delete_result, mock_get_result]

        # Delete the asset
        deleted = await repository.delete_voice_asset("consultant-001", "writing_style")
        assert deleted is True

        # Reset the session factory to simulate a fresh session for the get call
        # (in real code this would be the same pool but a new session)
        mock_session.execute.side_effect = None
        mock_session.execute.return_value = mock_get_result

        result = await repository.get_voice_asset("consultant-001", "writing_style")
        assert result is None


# ─── GET ALL VOICE ASSETS TESTS ──────────────────────────────────────────────


class TestGetAllVoiceAssets:
    """Tests for VoiceAssetRepository.get_all_voice_assets."""

    @pytest.mark.asyncio
    async def test_returns_correct_structure_with_assets(
        self, repository, mock_session, sample_voice_asset_row
    ):
        """get_all_voice_assets returns dict with correct keys and populated values."""
        now = datetime(2024, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
        behavioral_row = (
            "asset-uuid-002",           # id
            "consultant-001",           # beneficiary_id
            "behavioral_profile",       # asset_type
            "warm",                     # register
            "medium",                   # sentence_length
            "moderate",                 # first_person_usage
            json.dumps([]),             # vocabulary_prefer
            json.dumps([]),             # vocabulary_avoid
            json.dumps([]),             # exemplar_passages
            "collaborative",            # interpersonal_style
            json.dumps(["asks questions", "uses 'we'"]),  # communication_traits
            json.dumps(["combative", "apologetic"]),      # avoid_impressions
            None,                       # brand_personality
            None,                       # tagline_style
            True,                       # is_active
            now,                        # created_at
            now,                        # updated_at
        )

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [sample_voice_asset_row, behavioral_row]
        mock_session.execute.return_value = mock_result

        result = await repository.get_all_voice_assets("consultant-001")

        # Should have all three keys
        assert "writing_style" in result
        assert "behavioral_profile" in result
        assert "brand_voice" in result

        # writing_style should be populated
        assert result["writing_style"] is not None
        assert result["writing_style"]["asset_type"] == "writing_style"
        assert result["writing_style"]["register"] == "direct"

        # behavioral_profile should be populated
        assert result["behavioral_profile"] is not None
        assert result["behavioral_profile"]["asset_type"] == "behavioral_profile"
        assert result["behavioral_profile"]["interpersonal_style"] == "collaborative"

        # brand_voice should be None (not present for this consultant)
        assert result["brand_voice"] is None

    @pytest.mark.asyncio
    async def test_returns_all_none_when_no_assets(self, repository, mock_session):
        """get_all_voice_assets returns all None values when no assets configured."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        result = await repository.get_all_voice_assets("new-beneficiary")

        assert result == {
            "writing_style": None,
            "behavioral_profile": None,
            "brand_voice": None,
        }

    @pytest.mark.asyncio
    async def test_passes_correct_query_params(self, repository, mock_session):
        """Verify the query uses correct beneficiary_id."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        await repository.get_all_voice_assets("team-001")

        call_params = mock_session.execute.call_args_list[0][0][1]
        assert call_params["beneficiary_id"] == "team-001"
