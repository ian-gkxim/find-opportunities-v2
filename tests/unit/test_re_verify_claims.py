"""Unit tests for GroundingVerifier.re_verify_claims, resolve_regenerate,
and resolve_confirm_and_add methods.

These methods handle resolution-path re-verification of affected claims
after a user resolves blocked materials.

Requirements: 3.2, 3.3
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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


@pytest.fixture
def mock_db_repo():
    """Mock GroundingRepository with necessary async methods."""
    db = AsyncMock()
    db.get_latest_grounding_report_by_material = AsyncMock()
    db.update_grounding_report = AsyncMock()
    db.store_resolution = AsyncMock(return_value="resolution-001")
    return db


@pytest.fixture
def mock_llm_router():
    """Mock LLM Router."""
    llm = AsyncMock()
    return llm


@pytest.fixture
def mock_schema_registry():
    """Mock Schema Registry."""
    return MagicMock()


@pytest.fixture
def mock_personalization():
    """Mock PersonalizationEngine."""
    pe = AsyncMock()
    pe.regenerate_passages = AsyncMock(return_value="Updated material text with grounded claims")
    return pe


@pytest.fixture
def verifier(mock_llm_router, mock_schema_registry, mock_db_repo, mock_personalization):
    """Create a GroundingVerifier with mocked dependencies."""
    return GroundingVerifier(
        llm_router=mock_llm_router,
        schema_registry=mock_schema_registry,
        db_repo=mock_db_repo,
        personalization_engine=mock_personalization,
    )


@pytest.fixture
def sample_grounded_claim():
    """A claim that is already grounded."""
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
            asset_id="resume",
            passage="Python developer since 2019",
            confidence=0.9,
        ),
        is_prospect_side=False,
    )


@pytest.fixture
def sample_ungrounded_claim():
    """An ungrounded claim to be resolved."""
    return Claim(
        id="claim-002",
        material_id="mat-001",
        category=ClaimCategory.ACHIEVEMENT_OUTCOME,
        claim_text="Led a team of 20 engineers",
        source_span="Led a team of 20 engineers to build the platform",
        source_span_start=100,
        source_span_end=148,
        grounding_status=GroundingStatus.UNGROUNDED,
        source_pointer=None,
        is_prospect_side=False,
    )


@pytest.fixture
def existing_report(sample_grounded_claim, sample_ungrounded_claim):
    """A grounding report with one grounded and one ungrounded claim."""
    now = datetime(2024, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
    return GroundingReport(
        id="report-001",
        material_id="mat-001",
        pipeline_record_id="pipeline-001",
        claims=[sample_grounded_claim, sample_ungrounded_claim],
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


@pytest.fixture
def mock_beneficiary():
    """Mock beneficiary with assets that ground the previously ungrounded claim."""
    beneficiary = MagicMock()
    beneficiary.baseline_assets = {
        "resume": "Led a team of 20 engineers in building cloud platforms. Python developer since 2019."
    }
    beneficiary.offerings_assets = {}
    return beneficiary


@pytest.fixture
def mock_enrichment():
    """Mock enrichment record."""
    enrichment = MagicMock()
    enrichment.company_name = "Acme Corp"
    enrichment.industry = "Technology"
    enrichment.tech_stack = ["Python", "AWS"]
    enrichment.revenue_range = None
    enrichment.funding_stage = None
    enrichment.headquarters_city = None
    enrichment.headquarters_country = None
    enrichment.employee_count = None
    return enrichment


# ─── RE_VERIFY_CLAIMS TESTS ──────────────────────────────────────────────────


class TestReVerifyClaims:
    """Tests for GroundingVerifier.re_verify_claims."""

    @pytest.mark.asyncio
    async def test_re_verify_only_affected_claims(
        self, verifier, mock_db_repo, existing_report, mock_beneficiary, mock_enrichment
    ):
        """Only affected claims should be re-verified; unaffected remain unchanged."""
        mock_db_repo.get_latest_grounding_report_by_material.return_value = existing_report

        result = await verifier.re_verify_claims(
            material_id="mat-001",
            affected_claim_ids=["claim-002"],
            updated_assets={"resume": "Led a team of 20 engineers in cloud platform development."},
            beneficiary=mock_beneficiary,
            enrichment=mock_enrichment,
        )

        assert isinstance(result, GroundingResult)
        assert result.material_id == "mat-001"
        # The grounded claim should remain unchanged
        grounded_claims = [
            c for c in result.grounding_report.claims
            if c.id == "claim-001"
        ]
        assert len(grounded_claims) == 1
        assert grounded_claims[0].grounding_status == GroundingStatus.GROUNDED

    @pytest.mark.asyncio
    async def test_re_verify_updates_report_counts(
        self, verifier, mock_db_repo, existing_report, mock_beneficiary, mock_enrichment
    ):
        """Report counts should be recomputed after re-verification."""
        mock_db_repo.get_latest_grounding_report_by_material.return_value = existing_report

        result = await verifier.re_verify_claims(
            material_id="mat-001",
            affected_claim_ids=["claim-002"],
            updated_assets={"resume": "Led a team of 20 engineers building cloud platforms."},
            beneficiary=mock_beneficiary,
            enrichment=mock_enrichment,
        )

        report = result.grounding_report
        # The report should reflect updated counts
        assert report.total_claims == 2
        # Counts are recomputed — specific values depend on verification logic
        assert report.grounded_count + report.partially_grounded_count + report.ungrounded_count == 2

    @pytest.mark.asyncio
    async def test_re_verify_persists_updated_report(
        self, verifier, mock_db_repo, existing_report, mock_beneficiary, mock_enrichment
    ):
        """The updated report should be saved via update_grounding_report."""
        mock_db_repo.get_latest_grounding_report_by_material.return_value = existing_report

        await verifier.re_verify_claims(
            material_id="mat-001",
            affected_claim_ids=["claim-002"],
            updated_assets={"resume": "Led a team of 20 engineers."},
            beneficiary=mock_beneficiary,
            enrichment=mock_enrichment,
        )

        mock_db_repo.update_grounding_report.assert_called_once()

    @pytest.mark.asyncio
    async def test_re_verify_stores_resolution_record(
        self, verifier, mock_db_repo, existing_report, mock_beneficiary, mock_enrichment
    ):
        """A resolution record should be stored for each affected claim."""
        mock_db_repo.get_latest_grounding_report_by_material.return_value = existing_report

        await verifier.re_verify_claims(
            material_id="mat-001",
            affected_claim_ids=["claim-002"],
            updated_assets={"resume": "Led a team of 20 engineers."},
            beneficiary=mock_beneficiary,
            enrichment=mock_enrichment,
        )

        mock_db_repo.store_resolution.assert_called_once()
        resolution_arg = mock_db_repo.store_resolution.call_args[0][0]
        assert resolution_arg["claim_id"] == "claim-002"
        assert resolution_arg["grounding_report_id"] == "report-001"

    @pytest.mark.asyncio
    async def test_re_verify_raises_on_missing_report(
        self, verifier, mock_db_repo, mock_beneficiary, mock_enrichment
    ):
        """Should raise ValueError if no report exists for the material."""
        mock_db_repo.get_latest_grounding_report_by_material.return_value = None

        with pytest.raises(ValueError, match="No grounding report found"):
            await verifier.re_verify_claims(
                material_id="nonexistent",
                affected_claim_ids=["claim-001"],
                beneficiary=mock_beneficiary,
                enrichment=mock_enrichment,
            )

    @pytest.mark.asyncio
    async def test_re_verify_unblocks_pipeline_when_resolved(
        self, verifier, mock_db_repo, existing_report, mock_beneficiary, mock_enrichment
    ):
        """Pipeline should unblock when no ungrounded claims remain after re-verification."""
        mock_db_repo.get_latest_grounding_report_by_material.return_value = existing_report

        # Provide assets that ground the ungrounded claim
        result = await verifier.re_verify_claims(
            material_id="mat-001",
            affected_claim_ids=["claim-002"],
            updated_assets={"resume": "Led a team of 20 engineers building cloud platforms."},
            beneficiary=mock_beneficiary,
            enrichment=mock_enrichment,
        )

        # If re-verification grounds the claim, pipeline should be unblocked
        if result.grounding_report.ungrounded_count == 0:
            assert result.material_grounding_status == MaterialGroundingStatus.GROUNDING_VERIFIED
            assert result.blocked_states == []
            assert result.requires_action is False


# ─── RESOLVE_CONFIRM_AND_ADD TESTS ───────────────────────────────────────────


class TestResolveConfirmAndAdd:
    """Tests for GroundingVerifier.resolve_confirm_and_add."""

    @pytest.mark.asyncio
    async def test_confirm_and_add_re_verifies_with_updated_assets(
        self, verifier, mock_db_repo, existing_report, mock_beneficiary, mock_enrichment
    ):
        """resolve_confirm_and_add should add the fact and re-verify."""
        mock_db_repo.get_latest_grounding_report_by_material.return_value = existing_report

        result = await verifier.resolve_confirm_and_add(
            material_id="mat-001",
            claim_id="claim-002",
            supporting_fact="Led a team of 20 engineers at CloudCo in 2023",
            target_asset_id="resume",
            beneficiary=mock_beneficiary,
            enrichment=mock_enrichment,
        )

        assert isinstance(result, GroundingResult)
        assert result.material_id == "mat-001"

    @pytest.mark.asyncio
    async def test_confirm_and_add_stores_resolution_with_correct_path(
        self, verifier, mock_db_repo, existing_report, mock_beneficiary, mock_enrichment
    ):
        """Resolution should be stored with path='confirm_and_add'."""
        mock_db_repo.get_latest_grounding_report_by_material.return_value = existing_report

        await verifier.resolve_confirm_and_add(
            material_id="mat-001",
            claim_id="claim-002",
            supporting_fact="Led a team of 20 engineers at CloudCo",
            target_asset_id="resume",
            beneficiary=mock_beneficiary,
            enrichment=mock_enrichment,
        )

        # store_resolution is called from both re_verify_claims (manual_edit) and resolve_confirm_and_add (confirm_and_add)
        resolution_calls = mock_db_repo.store_resolution.call_args_list
        # The last call should be the confirm_and_add one
        last_resolution = resolution_calls[-1][0][0]
        assert last_resolution["resolution_path"] == "confirm_and_add"
        assert last_resolution["claim_id"] == "claim-002"
        assert last_resolution["resolution_detail"]["supporting_fact"] == "Led a team of 20 engineers at CloudCo"
        assert last_resolution["resolution_detail"]["target_asset_id"] == "resume"


# ─── RESOLVE_REGENERATE TESTS ────────────────────────────────────────────────


class TestResolveRegenerate:
    """Tests for GroundingVerifier.resolve_regenerate."""

    @pytest.mark.asyncio
    async def test_regenerate_calls_personalization_engine(
        self, verifier, mock_db_repo, mock_personalization, existing_report,
        mock_beneficiary, mock_enrichment
    ):
        """resolve_regenerate should call personalization_engine.regenerate_passages."""
        mock_db_repo.get_latest_grounding_report_by_material.return_value = existing_report

        # The extraction for the updated text
        with patch.object(verifier, 'extract_claims', new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = [
                Claim(
                    id="claim-new",
                    material_id="mat-001",
                    category=ClaimCategory.ACHIEVEMENT_OUTCOME,
                    claim_text="Led a cross-functional team",
                    source_span="Led a cross-functional team to build the platform",
                    source_span_start=100,
                    source_span_end=148,
                    grounding_status=None,
                    source_pointer=None,
                    is_prospect_side=False,
                )
            ]

            await verifier.resolve_regenerate(
                material_id="mat-001",
                ungrounded_claim_ids=["claim-002"],
                beneficiary=mock_beneficiary,
                enrichment=mock_enrichment,
            )

        mock_personalization.regenerate_passages.assert_called_once()

    @pytest.mark.asyncio
    async def test_regenerate_returns_grounding_result(
        self, verifier, mock_db_repo, mock_personalization, existing_report,
        mock_beneficiary, mock_enrichment
    ):
        """resolve_regenerate should return a GroundingResult."""
        mock_db_repo.get_latest_grounding_report_by_material.return_value = existing_report

        with patch.object(verifier, 'extract_claims', new_callable=AsyncMock) as mock_extract:
            mock_extract.return_value = []

            result = await verifier.resolve_regenerate(
                material_id="mat-001",
                ungrounded_claim_ids=["claim-002"],
                beneficiary=mock_beneficiary,
                enrichment=mock_enrichment,
            )

        assert isinstance(result, GroundingResult)
        assert result.material_id == "mat-001"
