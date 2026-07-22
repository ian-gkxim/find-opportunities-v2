"""Unit tests for GapAnalyzer.enforce_batch_cap().

Tests requirement 1.3:
- WHILE processing a nightly batch, THE Gap_Analyzer SHALL bound LLM extraction
  calls to a configurable maximum per run (default 200 opportunities), processing
  the most recent opportunities first and carrying the remainder to the next cycle.
"""

import uuid
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.core.gap_analyzer import GapAnalysisConfig, GapAnalyzer


@pytest.fixture
def analyzer_with_mock_db() -> tuple[GapAnalyzer, AsyncMock]:
    """Create a GapAnalyzer with a mocked db session and a small cap."""
    config = GapAnalysisConfig(max_extractions_per_cycle=3)
    mock_db = AsyncMock()
    analyzer = GapAnalyzer(
        config=config,
        llm_router=None,
        schema_registry=None,
        db_session=mock_db,
        redis_client=None,
        ws_manager=None,
    )
    return analyzer, mock_db


# Named tuple to simulate DB row results
RecordRow = namedtuple("RecordRow", ["id", "updated_at"])


class TestEnforceBatchCap:
    """Tests for enforce_batch_cap()."""

    @pytest.mark.asyncio
    async def test_returns_all_when_within_cap(self, analyzer_with_mock_db):
        """When eligible count <= cap, all IDs returned without DB query."""
        analyzer, mock_db = analyzer_with_mock_db

        eligible = [str(uuid.uuid4()) for _ in range(3)]
        result = await analyzer.enforce_batch_cap(eligible)

        assert result == eligible
        # No DB query needed when within cap
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_input(self, analyzer_with_mock_db):
        """Empty input returns empty output."""
        analyzer, mock_db = analyzer_with_mock_db

        result = await analyzer.enforce_batch_cap([])

        assert result == []
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_selects_top_n_by_recency(self, analyzer_with_mock_db):
        """When exceeding cap, selects the N most recent records."""
        analyzer, mock_db = analyzer_with_mock_db

        # Create 5 IDs (cap is 3)
        now = datetime.now(timezone.utc)
        ids = [uuid.uuid4() for _ in range(5)]
        # DB returns them ordered by updated_at DESC (most recent first)
        ordered_rows = [
            RecordRow(id=ids[4], updated_at=now - timedelta(hours=1)),
            RecordRow(id=ids[3], updated_at=now - timedelta(hours=2)),
            RecordRow(id=ids[2], updated_at=now - timedelta(hours=3)),
            RecordRow(id=ids[1], updated_at=now - timedelta(hours=4)),
            RecordRow(id=ids[0], updated_at=now - timedelta(hours=5)),
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = ordered_rows
        mock_db.execute.return_value = mock_result

        eligible = [str(id_) for id_ in ids]
        result = await analyzer.enforce_batch_cap(eligible)

        # Should select the 3 most recent
        assert len(result) == 3
        assert result == [str(ids[4]), str(ids[3]), str(ids[2])]

    @pytest.mark.asyncio
    async def test_inserts_remainder_into_queue(self, analyzer_with_mock_db):
        """Remainder records are inserted into gap_extraction_queue."""
        analyzer, mock_db = analyzer_with_mock_db

        now = datetime.now(timezone.utc)
        ids = [uuid.uuid4() for _ in range(5)]
        ordered_rows = [
            RecordRow(id=ids[i], updated_at=now - timedelta(hours=i + 1))
            for i in range(5)
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = ordered_rows
        mock_db.execute.return_value = mock_result

        eligible = [str(id_) for id_ in ids]
        await analyzer.enforce_batch_cap(eligible)

        # execute is called twice: once for SELECT, once for INSERT
        assert mock_db.execute.call_count == 2
        # commit is called for the queue insert
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_queue_insert_when_within_cap(self):
        """No queue insertion when eligible count is exactly at cap."""
        config = GapAnalysisConfig(max_extractions_per_cycle=5)
        mock_db = AsyncMock()
        analyzer = GapAnalyzer(
            config=config,
            llm_router=None,
            schema_registry=None,
            db_session=mock_db,
            redis_client=None,
            ws_manager=None,
        )

        eligible = [str(uuid.uuid4()) for _ in range(5)]
        result = await analyzer.enforce_batch_cap(eligible)

        assert len(result) == 5
        mock_db.execute.assert_not_called()
        mock_db.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_respects_configured_cap(self):
        """The batch cap uses the configured max_extractions_per_cycle."""
        config = GapAnalysisConfig(max_extractions_per_cycle=2)
        mock_db = AsyncMock()
        analyzer = GapAnalyzer(
            config=config,
            llm_router=None,
            schema_registry=None,
            db_session=mock_db,
            redis_client=None,
            ws_manager=None,
        )

        now = datetime.now(timezone.utc)
        ids = [uuid.uuid4() for _ in range(4)]
        ordered_rows = [
            RecordRow(id=ids[i], updated_at=now - timedelta(hours=i + 1))
            for i in range(4)
        ]

        mock_result = MagicMock()
        mock_result.all.return_value = ordered_rows
        mock_db.execute.return_value = mock_result

        eligible = [str(id_) for id_ in ids]
        result = await analyzer.enforce_batch_cap(eligible)

        # With cap=2, should select only 2
        assert len(result) == 2
