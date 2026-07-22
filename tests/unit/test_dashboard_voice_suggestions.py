"""Unit tests for Dashboard voice asset suggestion (Task 10.2).

Tests that:
- When no Voice_Asset is configured for a beneficiary, a suggestion is returned
- When a Voice_Asset exists, no suggestion is returned
- When the suggestion has been dismissed, it is not shown again
- The suggestion is non-blocking (does not appear in requires_action)
- Consultant gets writing_style suggestion, team gets brand_voice suggestion
- Dismiss endpoint stores dismissal and is idempotent

Requirements: 1.3
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.dashboard import (
    DismissSuggestionResponse,
    SuggestionEntry,
    VOICE_ASSET_SUGGESTION_KEY,
    _get_voice_asset_suggestions,
    dismiss_suggestion,
)


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _make_mock_session(
    has_voice_asset: bool = False,
    is_dismissed: bool = False,
) -> AsyncMock:
    """Create a mock async session for voice asset suggestion tests.

    The session.execute is called twice:
    1. First call: check dismissed_suggestions table
    2. Second call: check voice_assets table

    Args:
        has_voice_asset: If True, simulate an existing active voice asset.
        is_dismissed: If True, simulate the suggestion already being dismissed.
    """
    session = AsyncMock()

    # Track call count to return different results per query
    call_results = []

    # First call: dismissed_suggestions check
    dismissed_result = MagicMock()
    if is_dismissed:
        dismissed_result.fetchone.return_value = (1,)  # Found a row
    else:
        dismissed_result.fetchone.return_value = None  # Not dismissed
    call_results.append(dismissed_result)

    # Second call: voice_assets check (only reached if not dismissed)
    if not is_dismissed:
        voice_result = MagicMock()
        if has_voice_asset:
            voice_result.fetchone.return_value = (1,)  # Found a row
        else:
            voice_result.fetchone.return_value = None  # No voice asset
        call_results.append(voice_result)

    session.execute = AsyncMock(side_effect=call_results)
    return session


def _make_mock_session_with_db_error() -> AsyncMock:
    """Create a mock session that raises an exception (DB unavailable)."""
    session = AsyncMock()
    session.execute = AsyncMock(side_effect=Exception("DB unavailable"))
    return session


# ─── TEST: SUGGESTION SHOWN WHEN NO VOICE ASSET ──────────────────────────────


class TestVoiceAssetSuggestionShown:
    """Suggestion is shown when no Voice_Asset exists and not dismissed."""

    @pytest.mark.asyncio
    async def test_consultant_gets_writing_style_suggestion(self):
        """Consultant with no writing_style asset gets a suggestion."""
        session = _make_mock_session(has_voice_asset=False, is_dismissed=False)

        suggestions = await _get_voice_asset_suggestions(session, "consultant")

        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion.suggestion_key == VOICE_ASSET_SUGGESTION_KEY
        assert suggestion.stage == "understand"
        assert suggestion.beneficiary_id == "consultant"
        assert suggestion.asset_type == "writing_style"
        assert "writing" in suggestion.title.lower() or "voice" in suggestion.title.lower()

    @pytest.mark.asyncio
    async def test_team_gets_brand_voice_suggestion(self):
        """Team with no brand_voice asset gets a suggestion."""
        session = _make_mock_session(has_voice_asset=False, is_dismissed=False)

        suggestions = await _get_voice_asset_suggestions(session, "team")

        assert len(suggestions) == 1
        suggestion = suggestions[0]
        assert suggestion.suggestion_key == VOICE_ASSET_SUGGESTION_KEY
        assert suggestion.stage == "understand"
        assert suggestion.beneficiary_id == "team"
        assert suggestion.asset_type == "brand_voice"
        assert "brand" in suggestion.title.lower() or "voice" in suggestion.title.lower()

    @pytest.mark.asyncio
    async def test_suggestion_is_non_blocking(self):
        """Suggestion appears in suggestions list, not requires_action."""
        session = _make_mock_session(has_voice_asset=False, is_dismissed=False)

        suggestions = await _get_voice_asset_suggestions(session, "consultant")

        # Verify it's a SuggestionEntry, not an ActionItemEntry
        assert len(suggestions) == 1
        assert isinstance(suggestions[0], SuggestionEntry)


# ─── TEST: SUGGESTION NOT SHOWN WHEN VOICE ASSET EXISTS ──────────────────────


class TestVoiceAssetSuggestionHidden:
    """Suggestion is not shown when a Voice_Asset already exists."""

    @pytest.mark.asyncio
    async def test_no_suggestion_when_writing_style_exists(self):
        """Consultant with active writing_style gets no suggestion."""
        session = _make_mock_session(has_voice_asset=True, is_dismissed=False)

        suggestions = await _get_voice_asset_suggestions(session, "consultant")

        assert len(suggestions) == 0

    @pytest.mark.asyncio
    async def test_no_suggestion_when_brand_voice_exists(self):
        """Team with active brand_voice gets no suggestion."""
        session = _make_mock_session(has_voice_asset=True, is_dismissed=False)

        suggestions = await _get_voice_asset_suggestions(session, "team")

        assert len(suggestions) == 0


# ─── TEST: SUGGESTION DISMISSED (ONE-TIME BEHAVIOR) ──────────────────────────


class TestVoiceAssetSuggestionDismissed:
    """Suggestion is not shown once dismissed (one-time behavior)."""

    @pytest.mark.asyncio
    async def test_no_suggestion_when_dismissed(self):
        """Previously dismissed suggestion is not shown again."""
        session = _make_mock_session(has_voice_asset=False, is_dismissed=True)

        suggestions = await _get_voice_asset_suggestions(session, "consultant")

        assert len(suggestions) == 0

    @pytest.mark.asyncio
    async def test_dismissed_team_suggestion_not_shown(self):
        """Team suggestion is not shown when previously dismissed."""
        session = _make_mock_session(has_voice_asset=False, is_dismissed=True)

        suggestions = await _get_voice_asset_suggestions(session, "team")

        assert len(suggestions) == 0


# ─── TEST: UNKNOWN BENEFICIARY ───────────────────────────────────────────────


class TestVoiceAssetSuggestionUnknownBeneficiary:
    """Unknown beneficiary types get no suggestions."""

    @pytest.mark.asyncio
    async def test_unknown_beneficiary_returns_empty(self):
        """An unrecognized beneficiary type returns no suggestions."""
        session = _make_mock_session(has_voice_asset=False, is_dismissed=False)

        suggestions = await _get_voice_asset_suggestions(session, "unknown_type")

        assert len(suggestions) == 0


# ─── TEST: GRACEFUL DEGRADATION ──────────────────────────────────────────────


class TestVoiceAssetSuggestionGracefulDegradation:
    """Suggestions degrade gracefully when DB is unavailable."""

    @pytest.mark.asyncio
    async def test_db_error_returns_empty_suggestions(self):
        """When DB is unavailable, returns empty suggestions list (no error)."""
        session = _make_mock_session_with_db_error()

        suggestions = await _get_voice_asset_suggestions(session, "consultant")

        assert len(suggestions) == 0


# ─── TEST: DISMISS ENDPOINT ─────────────────────────────────────────────────


class TestDismissSuggestionEndpoint:
    """Dismiss endpoint stores dismissal and is idempotent."""

    @pytest.mark.asyncio
    async def test_dismiss_returns_success(self):
        """Dismiss endpoint returns confirmation response."""
        with patch("app.models.base.get_async_engine") as mock_engine_fn, \
             patch("app.models.base.get_async_session_factory") as mock_session_fn:
            mock_engine = AsyncMock()
            mock_engine.dispose = AsyncMock()
            mock_engine_fn.return_value = mock_engine

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock()
            mock_session.commit = AsyncMock()

            # Context manager mock
            mock_session_factory = MagicMock()
            mock_session_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_session_fn.return_value = mock_session_factory

            result = await dismiss_suggestion(
                suggestion_key=VOICE_ASSET_SUGGESTION_KEY,
                beneficiary="consultant",
            )

            assert result.suggestion_key == VOICE_ASSET_SUGGESTION_KEY
            assert result.beneficiary_id == "consultant"
            assert result.dismissed is True

    @pytest.mark.asyncio
    async def test_dismiss_handles_db_error_gracefully(self):
        """Dismiss endpoint returns success even when DB is unavailable."""
        with patch(
            "app.models.base.get_async_engine",
            side_effect=Exception("DB unavailable"),
        ):
            result = await dismiss_suggestion(
                suggestion_key=VOICE_ASSET_SUGGESTION_KEY,
                beneficiary="consultant",
            )

            # Still returns success (idempotent behavior)
            assert result.dismissed is True

    def test_suggestion_entry_model_fields(self):
        """SuggestionEntry model has all required fields."""
        entry = SuggestionEntry(
            suggestionKey="test_key",
            title="Test title",
            description="Test description",
            stage="understand",
            beneficiaryId="consultant",
            assetType="writing_style",
        )

        assert entry.suggestion_key == "test_key"
        assert entry.title == "Test title"
        assert entry.description == "Test description"
        assert entry.stage == "understand"
        assert entry.beneficiary_id == "consultant"
        assert entry.asset_type == "writing_style"

    def test_dismiss_response_model(self):
        """DismissSuggestionResponse model works correctly."""
        response = DismissSuggestionResponse(
            suggestionKey=VOICE_ASSET_SUGGESTION_KEY,
            beneficiaryId="team",
            dismissed=True,
        )

        assert response.suggestion_key == VOICE_ASSET_SUGGESTION_KEY
        assert response.beneficiary_id == "team"
        assert response.dismissed is True

    def test_voice_asset_suggestion_key_constant(self):
        """The suggestion key constant is defined."""
        assert VOICE_ASSET_SUGGESTION_KEY == "create_voice_asset"
