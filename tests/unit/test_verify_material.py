"""Unit tests for GroundingVerifier.verify_material() and apply_pipeline_gate().

Validates the full orchestration flow: extraction, verification, report building,
pipeline gating, persistence, and error handling.

Requirements: 1.1, 1.4, 2.1, 2.4, 3.1
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.grounding_errors import ExtractionError
from app.core.grounding_verifier import (
    Claim,
    ClaimCategory,
    GroundingReport,
    GroundingResult,
    GroundingStatus,
    GroundingVerifier,
    MaterialGroundingStatus,
    SourcePointer,
)


# ─── FIXTURES ─────────────────────────────────────────────────────────────────

SAMPLE_MATERIAL_TEXT = (
    "John has 10 years of experience in Python development. "
    "He led a cloud migration project at Acme Corp that reduced costs by 40%."
)


@dataclass
class FakeReviewedMaterial:
    id: str
    text: str
    pipeline_record_id: str


@dataclass
class FakeBeneficiary:
    baseline_assets: dict
    offerings_assets: dict


@dataclass
class FakeEnrichment:
    company_name: str = "Acme Corp"
    industry: str = "Technology"
    tech_stack: list = None
    employee_count: int = 500
    revenue_range: str | None = None
    funding_stage: str | None = None
    headquarters_city: str | None = None
    headquarters_country: str | None = None

    def __post_init__(self):
        if self.tech_stack is None:
            self.tech_stack = ["Python", "AWS"]


def _make_extracted_claims(material_id: str) -> list[Claim]:
    """Build claims that would come from extract_claims."""
    return [
        Claim(
            id="claim-1",
            material_id=material_id,
            category=ClaimCategory.EXPERIENCE_DURATION,
            claim_text="10 years of experience in Python development",
            source_span="10 years of experience in Python development",
            source_span_start=9,
            source_span_end=53,
        ),
        Claim(
            id="claim-2",
            material_id=material_id,
            category=ClaimCategory.ACHIEVEMENT_OUTCOME,
            claim_text="Led a cloud migration project at Acme Corp",
            source_span="led a cloud migration project at Acme Corp",
            source_span_start=55,
            source_span_end=98,
        ),
    ]


@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.dispatch_extraction = AsyncMock(return_value=[])
    return router


@pytest.fixture
def mock_db_repo():
    repo = MagicMock()
    repo.store_grounding_report = AsyncMock(return_value="report-id-123")
    return repo


@pytest.fixture
def verifier(mock_llm_router, mock_db_repo):
    return GroundingVerifier(
        llm_router=mock_llm_router,
        schema_registry=MagicMock(),
        db_repo=mock_db_repo,
        personalization_engine=MagicMock(),
    )


@pytest.fixture
def reviewed_material():
    return FakeReviewedMaterial(
        id="mat-001",
        text=SAMPLE_MATERIAL_TEXT,
        pipeline_record_id="pr-001",
    )


@pytest.fixture
def beneficiary():
    return FakeBeneficiary(
        baseline_assets={
            "resume": "10 years of experience in Python development. Cloud migration expertise."
        },
        offerings_assets={
            "consultant_profiles": "Senior developer specializing in cloud and Python."
        },
    )


@pytest.fixture
def enrichment():
    return FakeEnrichment()


# ─── apply_pipeline_gate TESTS ───────────────────────────────────────────────


class TestApplyPipelineGate:
    """Tests for apply_pipeline_gate method."""

    def test_blocks_when_ungrounded_claims_exist(self, verifier):
        """Pipeline is blocked when any claims are ungrounded."""
        report = GroundingReport(
            id="rpt-1",
            material_id="mat-001",
            pipeline_record_id="pr-001",
            claims=[],
            total_claims=3,
            grounded_count=1,
            partially_grounded_count=1,
            ungrounded_count=1,
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            extraction_duration_ms=100,
            verification_duration_ms=50,
            created_at=None,
            updated_at=None,
        )

        can_advance, blocked_states = verifier.apply_pipeline_gate(report)

        assert can_advance is False
        assert blocked_states == ["Approve", "Applied", "Sent", "Proposal Submitted"]

    def test_allows_when_no_ungrounded(self, verifier):
        """Pipeline advances when no ungrounded claims exist."""
        report = GroundingReport(
            id="rpt-1",
            material_id="mat-001",
            pipeline_record_id="pr-001",
            claims=[],
            total_claims=3,
            grounded_count=2,
            partially_grounded_count=1,
            ungrounded_count=0,
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            extraction_duration_ms=100,
            verification_duration_ms=50,
            created_at=None,
            updated_at=None,
        )

        can_advance, blocked_states = verifier.apply_pipeline_gate(report)

        assert can_advance is True
        assert blocked_states == []

    def test_allows_when_all_grounded(self, verifier):
        """Pipeline advances when all claims are fully grounded."""
        report = GroundingReport(
            id="rpt-1",
            material_id="mat-001",
            pipeline_record_id="pr-001",
            claims=[],
            total_claims=5,
            grounded_count=5,
            partially_grounded_count=0,
            ungrounded_count=0,
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            extraction_duration_ms=100,
            verification_duration_ms=50,
            created_at=None,
            updated_at=None,
        )

        can_advance, blocked_states = verifier.apply_pipeline_gate(report)

        assert can_advance is True
        assert blocked_states == []

    def test_allows_when_zero_claims(self, verifier):
        """Pipeline advances when no claims exist at all."""
        report = GroundingReport(
            id="rpt-1",
            material_id="mat-001",
            pipeline_record_id="pr-001",
            claims=[],
            total_claims=0,
            grounded_count=0,
            partially_grounded_count=0,
            ungrounded_count=0,
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            extraction_duration_ms=100,
            verification_duration_ms=50,
            created_at=None,
            updated_at=None,
        )

        can_advance, blocked_states = verifier.apply_pipeline_gate(report)

        assert can_advance is True
        assert blocked_states == []


# ─── verify_material TESTS ────────────────────────────────────────────────────


class TestVerifyMaterial:
    """Tests for verify_material orchestration method."""

    @pytest.mark.asyncio
    @patch("app.core.grounding_verifier.asyncio.sleep", new_callable=AsyncMock)
    async def test_extraction_failure_returns_unverified(
        self, mock_sleep, mock_llm_router, mock_db_repo, reviewed_material, beneficiary, enrichment
    ):
        """When extraction fails after retries, material is marked unverified."""
        mock_llm_router.dispatch_extraction = AsyncMock(
            side_effect=ExtractionError(material_id="mat-001", attempts=3)
        )
        verifier = GroundingVerifier(
            llm_router=mock_llm_router,
            schema_registry=MagicMock(),
            db_repo=mock_db_repo,
            personalization_engine=MagicMock(),
        )

        result = await verifier.verify_material(reviewed_material, beneficiary, enrichment)

        assert isinstance(result, GroundingResult)
        assert result.material_grounding_status == MaterialGroundingStatus.GROUNDING_UNVERIFIED
        assert result.material_id == "mat-001"
        assert result.requires_action is True
        assert result.blocked_states == []
        # Report should have zero claims
        assert result.grounding_report.total_claims == 0
        assert result.grounding_report.material_grounding_status == MaterialGroundingStatus.GROUNDING_UNVERIFIED
        # Report should be persisted
        mock_db_repo.store_grounding_report.assert_called_once()

    @pytest.mark.asyncio
    async def test_successful_extraction_all_grounded(
        self, verifier, mock_db_repo, reviewed_material, beneficiary, enrichment
    ):
        """When all claims are grounded, returns verified status."""
        claims = _make_extracted_claims("mat-001")

        with patch.object(verifier, "extract_claims", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = claims
            with patch.object(verifier, "verify_claims") as mock_verify:
                # All claims grounded
                for c in claims:
                    c.grounding_status = GroundingStatus.GROUNDED
                    c.source_pointer = SourcePointer(
                        asset_type="resume",
                        asset_id="resume",
                        passage="supporting text",
                        confidence=1.0,
                    )
                mock_verify.return_value = claims

                result = await verifier.verify_material(
                    reviewed_material, beneficiary, enrichment
                )

        assert result.material_grounding_status == MaterialGroundingStatus.GROUNDING_VERIFIED
        assert result.blocked_states == []
        assert result.requires_action is False
        assert result.grounding_report.total_claims == 2
        assert result.grounding_report.grounded_count == 2
        assert result.grounding_report.ungrounded_count == 0
        mock_db_repo.store_grounding_report.assert_called_once()

    @pytest.mark.asyncio
    async def test_ungrounded_claims_block_pipeline(
        self, verifier, mock_db_repo, reviewed_material, beneficiary, enrichment
    ):
        """When ungrounded claims exist, pipeline is blocked."""
        claims = _make_extracted_claims("mat-001")

        with patch.object(verifier, "extract_claims", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = claims
            with patch.object(verifier, "verify_claims") as mock_verify:
                # One grounded, one ungrounded
                claims[0].grounding_status = GroundingStatus.GROUNDED
                claims[0].source_pointer = SourcePointer(
                    asset_type="resume",
                    asset_id="resume",
                    passage="text",
                    confidence=1.0,
                )
                claims[1].grounding_status = GroundingStatus.UNGROUNDED
                mock_verify.return_value = claims

                result = await verifier.verify_material(
                    reviewed_material, beneficiary, enrichment
                )

        assert result.material_grounding_status == MaterialGroundingStatus.GROUNDING_BLOCKED
        assert result.blocked_states == ["Approve", "Applied", "Sent", "Proposal Submitted"]
        assert result.requires_action is True
        assert result.grounding_report.grounded_count == 1
        assert result.grounding_report.ungrounded_count == 1

    @pytest.mark.asyncio
    async def test_partially_grounded_allows_advancement(
        self, verifier, mock_db_repo, reviewed_material, beneficiary, enrichment
    ):
        """Partially grounded claims without ungrounded allow pipeline advancement."""
        claims = _make_extracted_claims("mat-001")

        with patch.object(verifier, "extract_claims", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = claims
            with patch.object(verifier, "verify_claims") as mock_verify:
                claims[0].grounding_status = GroundingStatus.GROUNDED
                claims[0].source_pointer = SourcePointer(
                    asset_type="resume",
                    asset_id="resume",
                    passage="text",
                    confidence=1.0,
                )
                claims[1].grounding_status = GroundingStatus.PARTIALLY_GROUNDED
                claims[1].source_pointer = SourcePointer(
                    asset_type="resume",
                    asset_id="resume",
                    passage="text",
                    confidence=0.7,
                )
                claims[1].discrepancy = "Number differs"
                mock_verify.return_value = claims

                result = await verifier.verify_material(
                    reviewed_material, beneficiary, enrichment
                )

        assert result.material_grounding_status == MaterialGroundingStatus.GROUNDING_VERIFIED
        assert result.blocked_states == []
        assert result.requires_action is False
        assert result.grounding_report.partially_grounded_count == 1

    @pytest.mark.asyncio
    async def test_report_has_correct_timing(
        self, verifier, mock_db_repo, reviewed_material, beneficiary, enrichment
    ):
        """Report captures extraction and verification durations."""
        claims = _make_extracted_claims("mat-001")

        with patch.object(verifier, "extract_claims", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = claims
            with patch.object(verifier, "verify_claims") as mock_verify:
                for c in claims:
                    c.grounding_status = GroundingStatus.GROUNDED
                    c.source_pointer = SourcePointer(
                        asset_type="resume",
                        asset_id="resume",
                        passage="text",
                        confidence=1.0,
                    )
                mock_verify.return_value = claims

                result = await verifier.verify_material(
                    reviewed_material, beneficiary, enrichment
                )

        report = result.grounding_report
        assert report.extraction_duration_ms >= 0
        assert report.verification_duration_ms >= 0
        assert report.created_at is not None
        assert report.updated_at is not None

    @pytest.mark.asyncio
    async def test_report_persisted_to_database(
        self, verifier, mock_db_repo, reviewed_material, beneficiary, enrichment
    ):
        """Grounding report is stored via db_repo."""
        claims = _make_extracted_claims("mat-001")

        with patch.object(verifier, "extract_claims", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = claims
            with patch.object(verifier, "verify_claims") as mock_verify:
                for c in claims:
                    c.grounding_status = GroundingStatus.GROUNDED
                    c.source_pointer = SourcePointer(
                        asset_type="resume",
                        asset_id="resume",
                        passage="text",
                        confidence=1.0,
                    )
                mock_verify.return_value = claims

                await verifier.verify_material(reviewed_material, beneficiary, enrichment)

        mock_db_repo.store_grounding_report.assert_called_once()
        stored_report = mock_db_repo.store_grounding_report.call_args[0][0]
        assert isinstance(stored_report, GroundingReport)
        assert stored_report.material_id == "mat-001"
        assert stored_report.pipeline_record_id == "pr-001"

    @pytest.mark.asyncio
    async def test_verify_material_calls_verify_claims_with_correct_args(
        self, verifier, mock_db_repo, reviewed_material, beneficiary, enrichment
    ):
        """verify_claims is called with extracted claims, beneficiary assets, and enrichment."""
        claims = _make_extracted_claims("mat-001")

        with patch.object(verifier, "extract_claims", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = claims
            with patch.object(verifier, "verify_claims") as mock_verify:
                for c in claims:
                    c.grounding_status = GroundingStatus.GROUNDED
                    c.source_pointer = SourcePointer(
                        asset_type="resume",
                        asset_id="resume",
                        passage="text",
                        confidence=1.0,
                    )
                mock_verify.return_value = claims

                await verifier.verify_material(reviewed_material, beneficiary, enrichment)

        mock_verify.assert_called_once_with(
            claims,
            beneficiary.baseline_assets,
            beneficiary.offerings_assets,
            enrichment,
        )

    @pytest.mark.asyncio
    async def test_empty_claims_list_results_in_verified(
        self, verifier, mock_db_repo, reviewed_material, beneficiary, enrichment
    ):
        """When extraction returns zero claims, material is verified."""
        with patch.object(verifier, "extract_claims", new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = []
            with patch.object(verifier, "verify_claims") as mock_verify:
                mock_verify.return_value = []

                result = await verifier.verify_material(
                    reviewed_material, beneficiary, enrichment
                )

        assert result.material_grounding_status == MaterialGroundingStatus.GROUNDING_VERIFIED
        assert result.grounding_report.total_claims == 0
        assert result.requires_action is False
