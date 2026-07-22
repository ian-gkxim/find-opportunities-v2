"""Unit tests for app.repositories.review_repository.ReviewRepository.

Verifies persistence logic with mocked async sessions since we cannot
connect to a real PostgreSQL database in unit tests.

Requirements: 3.2, 3.4
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.review_models import (
    CritiqueCategory,
    CycleLog,
    EditOutcome,
    EditReason,
    EditSkipReason,
    ReasoningLog,
    ReviewStatus,
    StructuredEdit,
)
from app.repositories.review_repository import ReviewRepository


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
    """Create a ReviewRepository instance with the mocked session factory."""
    return ReviewRepository(session_factory=mock_session_factory)


@pytest.fixture
def sample_cycle_log():
    """A sample CycleLog for testing."""
    return CycleLog(
        cycle_number=1,
        edits_applied=2,
        edits_skipped=1,
        edits_discarded=0,
        narrative_findings_by_category={
            CritiqueCategory.MISSED_KEYWORDS: 1,
            CritiqueCategory.COMPANY_ANGLES: 1,
            CritiqueCategory.REFRAMING: 0,
            CritiqueCategory.TONE_STYLE: 0,
        },
        quality_score_before=60,
        quality_score_after=75,
        duration_ms=3200,
        skipped_edits=[
            EditOutcome(
                edit=StructuredEdit(
                    target_material_id="mat-001",
                    old_string="old text",
                    new_string="new text",
                    reason=EditReason.KEYWORD_MATCH,
                    category=CritiqueCategory.MISSED_KEYWORDS,
                ),
                applied=False,
                skip_reason=EditSkipReason.AMBIGUOUS_OR_STALE_TARGET,
            )
        ],
        discarded_edits=[],
    )


@pytest.fixture
def sample_reasoning_log(sample_cycle_log):
    """A sample ReasoningLog with one cycle for testing."""
    return ReasoningLog(
        material_id="mat-001",
        prepare_technique_id="cv_and_cover_letter",
        review_technique_id="standard_material_review",
        cycles=[sample_cycle_log],
        total_cycles_executed=1,
        max_cycles_configured=2,
        final_review_status=ReviewStatus.REVIEWED,
        started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2024, 1, 1, 12, 0, 5, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_reasoning_log_two_cycles(sample_cycle_log):
    """A sample ReasoningLog with two cycles for testing."""
    cycle_2 = CycleLog(
        cycle_number=2,
        edits_applied=1,
        edits_skipped=0,
        edits_discarded=0,
        narrative_findings_by_category={
            CritiqueCategory.MISSED_KEYWORDS: 0,
            CritiqueCategory.COMPANY_ANGLES: 0,
            CritiqueCategory.REFRAMING: 1,
            CritiqueCategory.TONE_STYLE: 0,
        },
        quality_score_before=75,
        quality_score_after=82,
        duration_ms=2800,
    )
    return ReasoningLog(
        material_id="mat-002",
        prepare_technique_id="cold_email_composition",
        review_technique_id="email_review",
        cycles=[sample_cycle_log, cycle_2],
        total_cycles_executed=2,
        max_cycles_configured=2,
        final_review_status=ReviewStatus.REVIEWED,
        started_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        completed_at=datetime(2024, 1, 1, 12, 0, 10, tzinfo=timezone.utc),
    )


# ─── SAVE REASONING LOG TESTS ────────────────────────────────────────────────


class TestSaveReasoningLog:
    """Tests for ReviewRepository.save_reasoning_log."""

    @pytest.mark.asyncio
    async def test_save_reasoning_log_inserts_log_and_cycles(
        self, repository, mock_session, sample_reasoning_log
    ):
        """Verify session.execute is called once for the log + once per cycle, and commit is called."""
        await repository.save_reasoning_log(sample_reasoning_log)

        # 1 insert for the log + 1 insert per cycle (1 cycle)
        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_reasoning_log_inserts_multiple_cycles(
        self, repository, mock_session, sample_reasoning_log_two_cycles
    ):
        """Verify session.execute is called once for the log + once per cycle (2 cycles)."""
        await repository.save_reasoning_log(sample_reasoning_log_two_cycles)

        # 1 insert for the log + 2 inserts for cycles
        assert mock_session.execute.call_count == 3
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_reasoning_log_returns_uuid(
        self, repository, sample_reasoning_log
    ):
        """Verify save_reasoning_log returns a string UUID."""
        result = await repository.save_reasoning_log(sample_reasoning_log)

        assert isinstance(result, str)
        # UUID format: 8-4-4-4-12 hex chars
        parts = result.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12

    @pytest.mark.asyncio
    async def test_save_reasoning_log_passes_correct_params(
        self, repository, mock_session, sample_reasoning_log
    ):
        """Verify the log insert uses correct parameter values."""
        await repository.save_reasoning_log(sample_reasoning_log)

        # First call is the log insert
        first_call_params = mock_session.execute.call_args_list[0][0][1]
        assert first_call_params["material_id"] == "mat-001"
        assert first_call_params["prepare_technique_id"] == "cv_and_cover_letter"
        assert first_call_params["review_technique_id"] == "standard_material_review"
        assert first_call_params["total_cycles_executed"] == 1
        assert first_call_params["max_cycles_configured"] == 2
        assert first_call_params["final_review_status"] == "reviewed"


# ─── GET REASONING LOG TESTS ─────────────────────────────────────────────────


class TestGetReasoningLog:
    """Tests for ReviewRepository.get_reasoning_log."""

    @pytest.mark.asyncio
    async def test_get_reasoning_log_returns_none_when_not_found(
        self, repository, mock_session
    ):
        """Mock session to return no rows — should return None."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repository.get_reasoning_log("nonexistent-material")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_reasoning_log_returns_log_with_cycles(
        self, repository, mock_session
    ):
        """Mock session with valid data — should return a ReasoningLog with cycles."""
        started = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        completed = datetime(2024, 1, 1, 12, 0, 5, tzinfo=timezone.utc)

        # Mock the log row
        log_row = (
            "log-uuid-123",       # id
            "mat-001",            # material_id
            "cv_and_cover_letter",  # prepare_technique_id
            "standard_material_review",  # review_technique_id
            1,                    # total_cycles_executed
            2,                    # max_cycles_configured
            "reviewed",           # final_review_status
            started,              # started_at
            completed,            # completed_at
        )

        # Mock the cycle row
        cycle_row = (
            1,      # cycle_number
            2,      # edits_applied
            1,      # edits_skipped
            0,      # edits_discarded
            '{"missed_keywords": 1, "company_angles": 0, "reframing": 0, "tone_style": 0}',  # narrative_findings
            60,     # quality_score_before
            75,     # quality_score_after
            3200,   # duration_ms
            '[]',   # skipped_edits_detail
            '[]',   # discarded_edits_detail
        )

        # First execute returns log row, second returns cycles
        mock_log_result = MagicMock()
        mock_log_result.fetchone.return_value = log_row

        mock_cycles_result = MagicMock()
        mock_cycles_result.fetchall.return_value = [cycle_row]

        mock_session.execute.side_effect = [mock_log_result, mock_cycles_result]

        result = await repository.get_reasoning_log("mat-001")

        assert result is not None
        assert isinstance(result, ReasoningLog)
        assert result.material_id == "mat-001"
        assert result.prepare_technique_id == "cv_and_cover_letter"
        assert result.review_technique_id == "standard_material_review"
        assert result.total_cycles_executed == 1
        assert result.max_cycles_configured == 2
        assert result.final_review_status == ReviewStatus.REVIEWED
        assert result.started_at == started
        assert result.completed_at == completed
        assert len(result.cycles) == 1
        assert result.cycles[0].cycle_number == 1
        assert result.cycles[0].edits_applied == 2
        assert result.cycles[0].quality_score_before == 60
        assert result.cycles[0].quality_score_after == 75


# ─── MARK UNREVIEWED TESTS ───────────────────────────────────────────────────


class TestMarkUnreviewed:
    """Tests for ReviewRepository.mark_unreviewed."""

    @pytest.mark.asyncio
    async def test_mark_unreviewed_updates_existing(
        self, repository, mock_session
    ):
        """Mock rowcount=1 — should only execute the UPDATE, not INSERT."""
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_session.execute.return_value = mock_result

        await repository.mark_unreviewed("mat-001")

        # Only the UPDATE statement executed (no INSERT needed)
        assert mock_session.execute.call_count == 1
        mock_session.commit.assert_called_once()

        # Verify the UPDATE params include the correct status
        call_params = mock_session.execute.call_args_list[0][0][1]
        assert call_params["status"] == "unreviewed"
        assert call_params["material_id"] == "mat-001"

    @pytest.mark.asyncio
    async def test_mark_unreviewed_inserts_when_no_existing(
        self, repository, mock_session
    ):
        """Mock rowcount=0 — should execute UPDATE then INSERT."""
        mock_update_result = MagicMock()
        mock_update_result.rowcount = 0
        mock_insert_result = MagicMock()

        mock_session.execute.side_effect = [mock_update_result, mock_insert_result]

        await repository.mark_unreviewed("mat-001")

        # UPDATE + INSERT = 2 execute calls
        assert mock_session.execute.call_count == 2
        mock_session.commit.assert_called_once()

        # Verify the INSERT params for the minimal record
        insert_params = mock_session.execute.call_args_list[1][0][1]
        assert insert_params["material_id"] == "mat-001"
        assert insert_params["prepare_technique_id"] == "unknown"
        assert insert_params["review_technique_id"] == "unknown"
        assert insert_params["total_cycles_executed"] == 0
        assert insert_params["max_cycles_configured"] == 0
        assert insert_params["final_review_status"] == "unreviewed"


# ─── GET UNREVIEWED MATERIALS TESTS ──────────────────────────────────────────


class TestGetUnreviewedMaterials:
    """Tests for ReviewRepository.get_unreviewed_materials."""

    @pytest.mark.asyncio
    async def test_get_unreviewed_materials_returns_list(
        self, repository, mock_session
    ):
        """Mock query results — should return list of dicts with correct keys."""
        completed_1 = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        completed_2 = datetime(2024, 1, 2, 14, 0, 0, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("mat-001", "cv_and_cover_letter", "standard_material_review", completed_1),
            ("mat-002", "cold_email_composition", "email_review", completed_2),
        ]
        mock_session.execute.return_value = mock_result

        results = await repository.get_unreviewed_materials(limit=50)

        assert len(results) == 2
        assert results[0] == {
            "material_id": "mat-001",
            "prepare_technique_id": "cv_and_cover_letter",
            "review_technique_id": "standard_material_review",
            "completed_at": completed_1,
        }
        assert results[1] == {
            "material_id": "mat-002",
            "prepare_technique_id": "cold_email_composition",
            "review_technique_id": "email_review",
            "completed_at": completed_2,
        }

    @pytest.mark.asyncio
    async def test_get_unreviewed_materials_returns_empty_list(
        self, repository, mock_session
    ):
        """No unreviewed materials — should return empty list."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        results = await repository.get_unreviewed_materials()

        assert results == []

    @pytest.mark.asyncio
    async def test_get_unreviewed_materials_passes_correct_params(
        self, repository, mock_session
    ):
        """Verify the query uses UNREVIEWED status and the correct limit."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        await repository.get_unreviewed_materials(limit=25)

        call_params = mock_session.execute.call_args_list[0][0][1]
        assert call_params["status"] == "unreviewed"
        assert call_params["limit"] == 25
