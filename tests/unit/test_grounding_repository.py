"""Unit tests for app.repositories.grounding_repository.GroundingRepository.

Verifies persistence logic with mocked async sessions since we cannot
connect to a real PostgreSQL database in unit tests.

Requirements: 2.4, 3.3
"""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.grounding_verifier import (
    Claim,
    ClaimCategory,
    GroundingReport,
    GroundingStatus,
    MaterialGroundingStatus,
    SourcePointer,
)
from app.repositories.grounding_repository import GroundingRepository


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
    """Create a GroundingRepository instance with the mocked session factory."""
    return GroundingRepository(session_factory=mock_session_factory)


@pytest.fixture
def sample_claim_grounded():
    """A grounded claim with source pointer."""
    return Claim(
        id="claim-001",
        material_id="mat-001",
        category=ClaimCategory.SKILL_TECHNOLOGY,
        claim_text="5 years of Python experience",
        source_span="With 5 years of Python experience",
        source_span_start=10,
        source_span_end=44,
        grounding_status=GroundingStatus.GROUNDED,
        source_pointer=SourcePointer(
            asset_type="resume",
            asset_id="asset-001",
            passage="Python developer since 2019",
            confidence=0.9,
        ),
        is_prospect_side=False,
    )


@pytest.fixture
def sample_claim_ungrounded():
    """An ungrounded claim without source pointer."""
    return Claim(
        id="claim-002",
        material_id="mat-001",
        category=ClaimCategory.QUANTIFIED_METRIC,
        claim_text="Increased revenue by 40%",
        source_span="achieving a 40% revenue increase",
        source_span_start=100,
        source_span_end=132,
        grounding_status=GroundingStatus.UNGROUNDED,
        source_pointer=None,
        is_prospect_side=False,
    )


@pytest.fixture
def sample_grounding_report(sample_claim_grounded, sample_claim_ungrounded):
    """A sample GroundingReport with two claims."""
    now = datetime(2024, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
    return GroundingReport(
        id="report-001",
        material_id="mat-001",
        pipeline_record_id="pipeline-001",
        claims=[sample_claim_grounded, sample_claim_ungrounded],
        total_claims=2,
        grounded_count=1,
        partially_grounded_count=0,
        ungrounded_count=1,
        material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
        extraction_duration_ms=1500,
        verification_duration_ms=800,
        created_at=now,
        updated_at=now,
    )


# ─── STORE GROUNDING REPORT TESTS ────────────────────────────────────────────


class TestStoreGroundingReport:
    """Tests for GroundingRepository.store_grounding_report."""

    @pytest.mark.asyncio
    async def test_store_report_inserts_report_and_claims(
        self, repository, mock_session, sample_grounding_report
    ):
        """Verify session.execute is called once for report + once per claim, and commit is called."""
        await repository.store_grounding_report(sample_grounding_report)

        # 1 insert for the report + 2 inserts for claims
        assert mock_session.execute.call_count == 3
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_report_returns_report_id(
        self, repository, sample_grounding_report
    ):
        """Verify store_grounding_report returns the report id."""
        result = await repository.store_grounding_report(sample_grounding_report)

        assert result == "report-001"

    @pytest.mark.asyncio
    async def test_store_report_passes_correct_report_params(
        self, repository, mock_session, sample_grounding_report
    ):
        """Verify the report insert uses correct parameter values."""
        await repository.store_grounding_report(sample_grounding_report)

        first_call_params = mock_session.execute.call_args_list[0][0][1]
        assert first_call_params["id"] == "report-001"
        assert first_call_params["material_id"] == "mat-001"
        assert first_call_params["pipeline_record_id"] == "pipeline-001"
        assert first_call_params["total_claims"] == 2
        assert first_call_params["grounded_count"] == 1
        assert first_call_params["ungrounded_count"] == 1
        assert first_call_params["material_grounding_status"] == "grounding_blocked"
        assert first_call_params["extraction_duration_ms"] == 1500
        assert first_call_params["verification_duration_ms"] == 800

    @pytest.mark.asyncio
    async def test_store_report_passes_correct_claim_params(
        self, repository, mock_session, sample_grounding_report
    ):
        """Verify the claim inserts use correct parameter values."""
        await repository.store_grounding_report(sample_grounding_report)

        # Second call is first claim (grounded with source pointer)
        grounded_params = mock_session.execute.call_args_list[1][0][1]
        assert grounded_params["id"] == "claim-001"
        assert grounded_params["grounding_report_id"] == "report-001"
        assert grounded_params["category"] == "skill_technology"
        assert grounded_params["claim_text"] == "5 years of Python experience"
        assert grounded_params["grounding_status"] == "grounded"
        assert grounded_params["source_asset_type"] == "resume"
        assert grounded_params["source_asset_id"] == "asset-001"
        assert grounded_params["source_passage"] == "Python developer since 2019"
        assert grounded_params["is_prospect_side"] is False

        # Third call is second claim (ungrounded without source pointer)
        ungrounded_params = mock_session.execute.call_args_list[2][0][1]
        assert ungrounded_params["id"] == "claim-002"
        assert ungrounded_params["category"] == "quantified_metric"
        assert ungrounded_params["grounding_status"] == "ungrounded"
        assert ungrounded_params["source_asset_type"] is None
        assert ungrounded_params["source_asset_id"] is None
        assert ungrounded_params["source_passage"] is None


# ─── GET LATEST GROUNDING REPORT TESTS ───────────────────────────────────────


class TestGetLatestGroundingReport:
    """Tests for GroundingRepository.get_latest_grounding_report."""

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, repository, mock_session):
        """Mock session to return no rows — should return None."""
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        mock_session.execute.return_value = mock_result

        result = await repository.get_latest_grounding_report("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_report_with_claims(self, repository, mock_session):
        """Mock session with valid data — should return a GroundingReport with claims."""
        created = datetime(2024, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        updated = datetime(2024, 2, 1, 12, 0, 5, tzinfo=timezone.utc)

        report_row = (
            "report-001",       # id
            "mat-001",          # material_id
            "pipeline-001",     # pipeline_record_id
            "cv_and_cover_letter",  # prepare_technique_id
            "standard_grounding",    # grounding_technique_id
            2,                  # total_claims
            1,                  # grounded_count
            0,                  # partially_grounded_count
            1,                  # ungrounded_count
            "grounding_blocked",  # material_grounding_status
            1500,               # extraction_duration_ms
            800,                # verification_duration_ms
            created,            # created_at
            updated,            # updated_at
        )

        claim_row = (
            "claim-001",            # id
            "skill_technology",     # category
            "5 years of Python",    # claim_text
            "With 5 years of Python experience",  # source_span
            10,                     # source_span_start
            44,                     # source_span_end
            "grounded",             # grounding_status
            False,                  # is_prospect_side
            "resume",               # source_asset_type
            "asset-001",            # source_asset_id
            "Python developer since 2019",  # source_passage
            None,                   # discrepancy
        )

        mock_report_result = MagicMock()
        mock_report_result.fetchone.return_value = report_row

        mock_claims_result = MagicMock()
        mock_claims_result.fetchall.return_value = [claim_row]

        mock_session.execute.side_effect = [mock_report_result, mock_claims_result]

        result = await repository.get_latest_grounding_report("pipeline-001")

        assert result is not None
        assert isinstance(result, GroundingReport)
        assert result.id == "report-001"
        assert result.material_id == "mat-001"
        assert result.pipeline_record_id == "pipeline-001"
        assert result.total_claims == 2
        assert result.grounded_count == 1
        assert result.ungrounded_count == 1
        assert result.material_grounding_status == MaterialGroundingStatus.GROUNDING_BLOCKED
        assert result.extraction_duration_ms == 1500
        assert result.verification_duration_ms == 800
        assert len(result.claims) == 1

        claim = result.claims[0]
        assert claim.id == "claim-001"
        assert claim.material_id == "mat-001"
        assert claim.category == ClaimCategory.SKILL_TECHNOLOGY
        assert claim.claim_text == "5 years of Python"
        assert claim.grounding_status == GroundingStatus.GROUNDED
        assert claim.source_pointer is not None
        assert claim.source_pointer.asset_type == "resume"
        assert claim.source_pointer.passage == "Python developer since 2019"


# ─── UPDATE GROUNDING REPORT TESTS ───────────────────────────────────────────


class TestUpdateGroundingReport:
    """Tests for GroundingRepository.update_grounding_report."""

    @pytest.mark.asyncio
    async def test_update_report_calls_correct_count(
        self, repository, mock_session, sample_grounding_report
    ):
        """Verify session.execute is called once for report update + once per claim update."""
        await repository.update_grounding_report(sample_grounding_report)

        # 1 update for report + 2 updates for claims
        assert mock_session.execute.call_count == 3
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_report_passes_correct_params(
        self, repository, mock_session, sample_grounding_report
    ):
        """Verify the report update uses correct parameter values."""
        await repository.update_grounding_report(sample_grounding_report)

        report_params = mock_session.execute.call_args_list[0][0][1]
        assert report_params["id"] == "report-001"
        assert report_params["total_claims"] == 2
        assert report_params["grounded_count"] == 1
        assert report_params["ungrounded_count"] == 1
        assert report_params["material_grounding_status"] == "grounding_blocked"

    @pytest.mark.asyncio
    async def test_update_report_updates_claim_statuses(
        self, repository, mock_session, sample_grounding_report
    ):
        """Verify claim updates pass correct grounding_status values."""
        await repository.update_grounding_report(sample_grounding_report)

        # Second call is first claim update (grounded)
        grounded_params = mock_session.execute.call_args_list[1][0][1]
        assert grounded_params["id"] == "claim-001"
        assert grounded_params["grounding_status"] == "grounded"
        assert grounded_params["source_asset_type"] == "resume"

        # Third call is second claim update (ungrounded)
        ungrounded_params = mock_session.execute.call_args_list[2][0][1]
        assert ungrounded_params["id"] == "claim-002"
        assert ungrounded_params["grounding_status"] == "ungrounded"
        assert ungrounded_params["source_asset_type"] is None


# ─── STORE RESOLUTION TESTS ──────────────────────────────────────────────────


class TestStoreResolution:
    """Tests for GroundingRepository.store_resolution."""

    @pytest.mark.asyncio
    async def test_store_resolution_inserts_and_commits(
        self, repository, mock_session
    ):
        """Verify resolution insert and commit are called."""
        resolution = {
            "grounding_report_id": "report-001",
            "claim_id": "claim-002",
            "resolution_path": "regenerate",
            "resolved_by": "user@example.com",
            "resolution_detail": {"excluded_claims": ["claim-002"]},
            "re_verification_status": "grounded",
            "re_verification_duration_ms": 250,
            "resolved_at": datetime(2024, 2, 1, 13, 0, 0, tzinfo=timezone.utc),
        }

        await repository.store_resolution(resolution)

        assert mock_session.execute.call_count == 1
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_resolution_returns_uuid(self, repository, mock_session):
        """Verify store_resolution returns a UUID string."""
        resolution = {
            "grounding_report_id": "report-001",
            "claim_id": "claim-002",
            "resolution_path": "manual_edit",
            "resolved_by": "user@example.com",
            "resolution_detail": {},
            "resolved_at": datetime(2024, 2, 1, 13, 0, 0, tzinfo=timezone.utc),
        }

        result = await repository.store_resolution(resolution)

        assert isinstance(result, str)
        parts = result.split("-")
        assert len(parts) == 5

    @pytest.mark.asyncio
    async def test_store_resolution_passes_correct_params(
        self, repository, mock_session
    ):
        """Verify the resolution insert uses correct parameter values."""
        resolved_at = datetime(2024, 2, 1, 13, 0, 0, tzinfo=timezone.utc)
        resolution = {
            "grounding_report_id": "report-001",
            "claim_id": "claim-002",
            "resolution_path": "confirm_and_add",
            "resolved_by": "admin@example.com",
            "resolution_detail": {"supporting_fact": "Award in 2023"},
            "re_verification_status": "grounded",
            "re_verification_duration_ms": 150,
            "resolved_at": resolved_at,
        }

        await repository.store_resolution(resolution)

        call_params = mock_session.execute.call_args_list[0][0][1]
        assert call_params["grounding_report_id"] == "report-001"
        assert call_params["claim_id"] == "claim-002"
        assert call_params["resolution_path"] == "confirm_and_add"
        assert call_params["resolved_by"] == "admin@example.com"
        assert call_params["re_verification_status"] == "grounded"
        assert call_params["re_verification_duration_ms"] == 150
        assert call_params["resolved_at"] == resolved_at


# ─── GET PENDING VERIFICATIONS TESTS ─────────────────────────────────────────


class TestGetPendingVerifications:
    """Tests for GroundingRepository.get_pending_verifications."""

    @pytest.mark.asyncio
    async def test_returns_pending_materials(self, repository, mock_session):
        """Mock query results — should return list of dicts."""
        created = datetime(2024, 2, 1, 12, 0, 0, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("report-001", "mat-001", "pipeline-001", "cv_and_cover_letter", created),
            ("report-002", "mat-002", "pipeline-002", "cold_email_composition", created),
        ]
        mock_session.execute.return_value = mock_result

        results = await repository.get_pending_verifications(limit=10)

        assert len(results) == 2
        assert results[0]["report_id"] == "report-001"
        assert results[0]["material_id"] == "mat-001"
        assert results[0]["pipeline_record_id"] == "pipeline-001"
        assert results[0]["prepare_technique_id"] == "cv_and_cover_letter"
        assert results[1]["report_id"] == "report-002"

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_pending(self, repository, mock_session):
        """No pending verifications — should return empty list."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        results = await repository.get_pending_verifications()

        assert results == []

    @pytest.mark.asyncio
    async def test_passes_correct_params(self, repository, mock_session):
        """Verify the query uses grounding_unverified status and correct limit."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        await repository.get_pending_verifications(limit=5)

        call_params = mock_session.execute.call_args_list[0][0][1]
        assert call_params["status"] == "grounding_unverified"
        assert call_params["limit"] == 5


# ─── GET REPORTS FOR ANALYTICS TESTS ─────────────────────────────────────────


class TestGetReportsForAnalytics:
    """Tests for GroundingRepository.get_reports_for_analytics."""

    @pytest.mark.asyncio
    async def test_returns_reports_for_technique(self, repository, mock_session):
        """Mock query results — should return list of GroundingReport objects."""
        created = datetime(2024, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        updated = datetime(2024, 2, 1, 12, 0, 5, tzinfo=timezone.utc)

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            (
                "report-001", "mat-001", "pipeline-001",
                "cv_and_cover_letter", "standard_grounding",
                3, 2, 1, 0, "grounding_verified",
                1200, 600, created, updated,
            ),
        ]
        mock_session.execute.return_value = mock_result

        results = await repository.get_reports_for_analytics(
            technique_id="cv_and_cover_letter",
            week_start=date(2024, 1, 29),
            week_end=date(2024, 2, 5),
        )

        assert len(results) == 1
        report = results[0]
        assert isinstance(report, GroundingReport)
        assert report.id == "report-001"
        assert report.total_claims == 3
        assert report.grounded_count == 2
        assert report.partially_grounded_count == 1
        assert report.ungrounded_count == 0
        assert report.material_grounding_status == MaterialGroundingStatus.GROUNDING_VERIFIED
        assert report.claims == []  # Not loaded for analytics

    @pytest.mark.asyncio
    async def test_returns_empty_for_no_data(self, repository, mock_session):
        """No reports in date range — should return empty list."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        results = await repository.get_reports_for_analytics(
            technique_id="cv_and_cover_letter",
            week_start=date(2024, 3, 1),
            week_end=date(2024, 3, 8),
        )

        assert results == []

    @pytest.mark.asyncio
    async def test_passes_correct_params(self, repository, mock_session):
        """Verify the query uses correct technique_id and date range."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        await repository.get_reports_for_analytics(
            technique_id="cold_email_composition",
            week_start=date(2024, 2, 5),
            week_end=date(2024, 2, 12),
        )

        call_params = mock_session.execute.call_args_list[0][0][1]
        assert call_params["technique_id"] == "cold_email_composition"
