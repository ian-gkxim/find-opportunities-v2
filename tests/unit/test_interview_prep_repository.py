"""Unit tests for app.core.interview_prep_repository.InterviewPrepRepository.

Verifies persistence logic with mocked async sessions since we cannot
connect to a real PostgreSQL database in unit tests.

Requirements: 2.1, 3.2
"""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.interview_prep_models import (
    Interview_Prep_Pack,
    PackStatus,
    STAR_Talking_Point,
)
from app.core.interview_prep_repository import InterviewPrepRepository


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
    """Create an InterviewPrepRepository instance with the mocked session factory."""
    return InterviewPrepRepository(session_factory=mock_session_factory)


@pytest.fixture
def sample_star_talking_point():
    """A sample STAR talking point."""
    return STAR_Talking_Point(
        competency="Python development",
        question="Tell me about a time you led a Python project",
        situation="At Company X, the legacy system needed migration",
        task="I was tasked with leading the Python migration effort",
        action="I designed the architecture and led 3 developers",
        result="Completed migration 2 weeks early with 40% performance gain",
        source_asset_refs=["asset-001", "asset-002"],
        is_gap_handled=False,
        gap_note=None,
    )


@pytest.fixture
def sample_pack(sample_star_talking_point):
    """A complete Interview_Prep_Pack for testing."""
    now = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
    return Interview_Prep_Pack(
        id="pack-001",
        pipeline_record_id="pipeline-001",
        beneficiary_id="beneficiary-001",
        opportunity_type_id="job_site",
        likely_questions=[
            "Tell me about your Python experience",
            "Describe a challenging project",
            "How do you handle deadlines?",
            "What is your approach to testing?",
            "Describe your leadership style",
            "How do you handle conflict?",
            "What motivates you?",
            "Where do you see yourself in 5 years?",
        ],
        star_talking_points=[sample_star_talking_point] * 5,
        company_briefing="Company X is a tech startup focused on AI solutions.",
        questions_to_ask=[
            "What does the team structure look like?",
            "How is success measured?",
            "What are the growth opportunities?",
        ],
        status=PackStatus.READY,
        omission_notes=[],
        grounding_flags=[],
        generation_duration_ms=4500,
        created_at=now,
        updated_at=now,
    )


# ─── SAVE PACK TESTS ─────────────────────────────────────────────────────────


class TestSavePack:
    """Tests for InterviewPrepRepository.save_pack."""

    @pytest.mark.asyncio
    async def test_save_pack_executes_insert_with_correct_params(
        self, repository, mock_session, sample_pack
    ):
        """Verify session.execute called with pack fields serialized."""
        await repository.save_pack(sample_pack)

        mock_session.execute.assert_called_once()
        call_params = mock_session.execute.call_args[0][1]

        assert call_params["id"] == "pack-001"
        assert call_params["pipeline_record_id"] == "pipeline-001"
        assert call_params["beneficiary_id"] == "beneficiary-001"
        assert call_params["opportunity_type_id"] == "job_site"
        assert call_params["status"] == "ready"
        assert call_params["generation_duration_ms"] == 4500
        assert call_params["company_briefing"] == "Company X is a tech startup focused on AI solutions."

        # Verify JSONB serialized fields
        likely_questions = json.loads(call_params["likely_questions"])
        assert len(likely_questions) == 8
        assert likely_questions[0] == "Tell me about your Python experience"

        star_points = json.loads(call_params["star_talking_points"])
        assert len(star_points) == 5
        assert star_points[0]["competency"] == "Python development"

        questions_to_ask = json.loads(call_params["questions_to_ask"])
        assert len(questions_to_ask) == 3

        mock_session.commit.assert_called_once()


# ─── GET PACK TESTS ──────────────────────────────────────────────────────────


class TestGetPack:
    """Tests for InterviewPrepRepository.get_pack."""

    @pytest.mark.asyncio
    async def test_get_pack_returns_pack_when_found(
        self, repository, mock_session
    ):
        """Mock fetchone to return a row, verify deserialization."""
        created = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        updated = datetime(2024, 3, 15, 10, 0, 5, tzinfo=timezone.utc)

        star_points_json = json.dumps([
            {
                "competency": "Python",
                "question": "Tell me about Python",
                "situation": "At Company X",
                "task": "Lead migration",
                "action": "Designed architecture",
                "result": "Completed early",
                "source_asset_refs": ["asset-001"],
                "is_gap_handled": False,
                "gap_note": None,
            }
        ] * 5)

        row = (
            "pack-001",             # id
            "pipeline-001",         # pipeline_record_id
            "beneficiary-001",      # beneficiary_id
            "job_site",             # opportunity_type_id
            "ready",                # status
            json.dumps(["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"]),  # likely_questions
            star_points_json,       # star_talking_points
            "Company briefing text",  # company_briefing
            json.dumps(["Ask Q1", "Ask Q2", "Ask Q3"]),  # questions_to_ask
            json.dumps([]),         # omission_notes
            json.dumps([]),         # grounding_flags
            4500,                   # generation_duration_ms
            created,                # created_at
            updated,                # updated_at
        )

        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        mock_session.execute.return_value = mock_result

        result = await repository.get_pack("pipeline-001")

        assert result is not None
        assert isinstance(result, Interview_Prep_Pack)
        assert result.id == "pack-001"
        assert result.pipeline_record_id == "pipeline-001"
        assert result.beneficiary_id == "beneficiary-001"
        assert result.opportunity_type_id == "job_site"
        assert result.status == PackStatus.READY
        assert len(result.likely_questions) == 8
        assert len(result.star_talking_points) == 5
        assert result.star_talking_points[0].competency == "Python"
        assert result.company_briefing == "Company briefing text"
        assert len(result.questions_to_ask) == 3
        assert result.generation_duration_ms == 4500

    @pytest.mark.asyncio
    async def test_get_pack_returns_none_when_not_found(
        self, repository, mock_session
    ):
        """Mock fetchone to return None."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repository.get_pack("nonexistent-pipeline")

        assert result is None


# ─── GET PACK BY ID TESTS ────────────────────────────────────────────────────


class TestGetPackById:
    """Tests for InterviewPrepRepository.get_pack_by_id."""

    @pytest.mark.asyncio
    async def test_get_pack_by_id_returns_pack(
        self, repository, mock_session
    ):
        """Mock fetchone to return a row, verify deserialization by pack_id."""
        created = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        updated = datetime(2024, 3, 15, 10, 0, 5, tzinfo=timezone.utc)

        star_points_json = json.dumps([
            {
                "competency": "Leadership",
                "question": "Describe your leadership style",
                "situation": "At startup Y",
                "task": "Build a team",
                "action": "Recruited and mentored",
                "result": "Team grew from 2 to 8",
                "source_asset_refs": ["asset-003"],
                "is_gap_handled": False,
                "gap_note": None,
            }
        ] * 5)

        row = (
            "pack-002",             # id
            "pipeline-002",         # pipeline_record_id
            "beneficiary-002",      # beneficiary_id
            "company",              # opportunity_type_id
            "grounding",            # status
            json.dumps(["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9"]),
            star_points_json,
            "Another company briefing",
            json.dumps(["Ask1", "Ask2", "Ask3", "Ask4"]),
            json.dumps(["CV was unavailable"]),
            json.dumps(["claim X ungrounded"]),
            3200,
            created,
            updated,
        )

        mock_result = MagicMock()
        mock_result.fetchone.return_value = row
        mock_session.execute.return_value = mock_result

        result = await repository.get_pack_by_id("pack-002")

        assert result is not None
        assert isinstance(result, Interview_Prep_Pack)
        assert result.id == "pack-002"
        assert result.pipeline_record_id == "pipeline-002"
        assert result.status == PackStatus.GROUNDING
        assert len(result.likely_questions) == 9
        assert result.omission_notes == ["CV was unavailable"]
        assert result.grounding_flags == ["claim X ungrounded"]


# ─── UPDATE PACK STATUS TESTS ────────────────────────────────────────────────


class TestUpdatePackStatus:
    """Tests for InterviewPrepRepository.update_pack_status."""

    @pytest.mark.asyncio
    async def test_update_pack_status_sets_status(
        self, repository, mock_session
    ):
        """Verify session.execute called with correct status."""
        await repository.update_pack_status("pack-001", PackStatus.READY)

        mock_session.execute.assert_called_once()
        call_params = mock_session.execute.call_args[0][1]

        assert call_params["pack_id"] == "pack-001"
        assert call_params["status"] == "ready"
        assert "updated_at" in call_params
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_pack_status_with_kwargs(
        self, repository, mock_session
    ):
        """Verify additional fields passed through in kwargs."""
        await repository.update_pack_status(
            "pack-001",
            PackStatus.READY_WITH_FLAGS,
            grounding_flags=["ungrounded claim about AWS"],
            generation_duration_ms=5000,
            omission_notes=["Cover letter unavailable"],
        )

        mock_session.execute.assert_called_once()
        call_params = mock_session.execute.call_args[0][1]

        assert call_params["pack_id"] == "pack-001"
        assert call_params["status"] == "ready_with_flags"
        assert json.loads(call_params["grounding_flags"]) == ["ungrounded claim about AWS"]
        assert call_params["generation_duration_ms"] == 5000
        assert json.loads(call_params["omission_notes"]) == ["Cover letter unavailable"]
        mock_session.commit.assert_called_once()


# ─── SUPERSEDE PACK TESTS ────────────────────────────────────────────────────


class TestSupersedePack:
    """Tests for InterviewPrepRepository.supersede_pack."""

    @pytest.mark.asyncio
    async def test_supersede_pack_updates_old_pack(
        self, repository, mock_session
    ):
        """Verify session.execute sets superseded_by on old pack."""
        await repository.supersede_pack("old-pack-001", "new-pack-002")

        mock_session.execute.assert_called_once()
        call_params = mock_session.execute.call_args[0][1]

        assert call_params["old_pack_id"] == "old-pack-001"
        assert call_params["new_pack_id"] == "new-pack-002"
        assert "updated_at" in call_params
        mock_session.commit.assert_called_once()


# ─── SAVE HISTORY TESTS ──────────────────────────────────────────────────────


class TestSaveHistory:
    """Tests for InterviewPrepRepository.save_history."""

    @pytest.mark.asyncio
    async def test_save_history_creates_record(
        self, repository, mock_session
    ):
        """Verify session.execute called with history fields."""
        await repository.save_history(
            pack_id="pack-001",
            trigger_reason="state_entry",
            context_hash="abc123def456",
        )

        mock_session.execute.assert_called_once()
        call_params = mock_session.execute.call_args[0][1]

        assert call_params["pack_id"] == "pack-001"
        assert call_params["trigger_reason"] == "state_entry"
        assert call_params["generation_context_hash"] == "abc123def456"
        assert "id" in call_params  # UUID generated
        assert "created_at" in call_params
        mock_session.commit.assert_called_once()


# ─── GET FAILED PACKS TESTS ──────────────────────────────────────────────────


class TestGetFailedPacks:
    """Tests for InterviewPrepRepository.get_failed_packs."""

    @pytest.mark.asyncio
    async def test_get_failed_packs_returns_failed_only(
        self, repository, mock_session
    ):
        """Mock fetchall with failed packs, verify filtering."""
        created = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
        updated = datetime(2024, 3, 15, 10, 0, 5, tzinfo=timezone.utc)

        star_points_json = json.dumps([
            {
                "competency": "Testing",
                "question": "How do you approach testing?",
                "situation": "At company Z",
                "task": "Improve coverage",
                "action": "Implemented PBT",
                "result": "Coverage went from 60% to 95%",
                "source_asset_refs": ["asset-010"],
                "is_gap_handled": False,
                "gap_note": None,
            }
        ] * 5)

        failed_row = (
            "pack-failed-001",
            "pipeline-003",
            "beneficiary-003",
            "job_site",
            "failed",
            json.dumps(["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8"]),
            star_points_json,
            "Failed company briefing",
            json.dumps(["Ask1", "Ask2", "Ask3"]),
            json.dumps([]),
            json.dumps([]),
            0,
            created,
            updated,
        )

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [failed_row]
        mock_session.execute.return_value = mock_result

        results = await repository.get_failed_packs(limit=20)

        assert len(results) == 1
        pack = results[0]
        assert isinstance(pack, Interview_Prep_Pack)
        assert pack.id == "pack-failed-001"
        assert pack.status == PackStatus.FAILED
        assert pack.pipeline_record_id == "pipeline-003"

        # Verify query params include failed status
        call_params = mock_session.execute.call_args[0][1]
        assert call_params["status"] == "failed"
        assert call_params["limit"] == 20

    @pytest.mark.asyncio
    async def test_get_failed_packs_returns_empty_when_none(
        self, repository, mock_session
    ):
        """Mock empty fetchall — should return empty list."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        results = await repository.get_failed_packs()

        assert results == []
