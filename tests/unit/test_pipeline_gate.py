"""Unit tests for PipelineGateService.

Validates can_transition() and get_warning_badge() logic including
gated state detection, blocking on ungrounded claims, and warning badge display.

Requirements: 3.1, 3.4
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.grounding_verifier import (
    Claim,
    ClaimCategory,
    GroundingReport,
    GroundingStatus,
    MaterialGroundingStatus,
)
from app.core.pipeline_gate import PipelineGateService


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


def _make_report(
    *,
    material_grounding_status: MaterialGroundingStatus = MaterialGroundingStatus.GROUNDING_VERIFIED,
    grounded_count: int = 3,
    partially_grounded_count: int = 0,
    ungrounded_count: int = 0,
    claims: list[Claim] | None = None,
) -> GroundingReport:
    """Helper to build a GroundingReport with sensible defaults."""
    now = datetime.now(timezone.utc)
    total = grounded_count + partially_grounded_count + ungrounded_count
    return GroundingReport(
        id="rpt-001",
        material_id="mat-001",
        pipeline_record_id="pr-001",
        claims=claims or [],
        total_claims=total,
        grounded_count=grounded_count,
        partially_grounded_count=partially_grounded_count,
        ungrounded_count=ungrounded_count,
        material_grounding_status=material_grounding_status,
        extraction_duration_ms=100,
        verification_duration_ms=50,
        created_at=now,
        updated_at=now,
    )


def _make_claim(
    *,
    claim_id: str = "claim-1",
    grounding_status: GroundingStatus = GroundingStatus.UNGROUNDED,
) -> Claim:
    """Helper to build a Claim."""
    return Claim(
        id=claim_id,
        material_id="mat-001",
        category=ClaimCategory.SKILL_TECHNOLOGY,
        claim_text="Expert in Kubernetes",
        source_span="Expert in Kubernetes",
        source_span_start=0,
        source_span_end=20,
        grounding_status=grounding_status,
    )


@pytest.fixture
def mock_db_repo():
    repo = MagicMock()
    repo.get_latest_grounding_report = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def gate_service(mock_db_repo):
    return PipelineGateService(db_repo=mock_db_repo)


# ─── GATED_STATES DEFINITION TESTS ──────────────────────────────────────────


class TestGatedStates:
    """Verify the GATED_STATES class attribute."""

    def test_gated_states_contains_expected_states(self):
        """GATED_STATES includes Approve, Applied, Sent, Proposal Submitted."""
        assert PipelineGateService.GATED_STATES == {
            "Approve", "Applied", "Sent", "Proposal Submitted"
        }

    def test_gated_states_is_a_set(self):
        """GATED_STATES is a set for O(1) membership checks."""
        assert isinstance(PipelineGateService.GATED_STATES, set)


# ─── can_transition TESTS ────────────────────────────────────────────────────


class TestCanTransition:
    """Tests for can_transition() method."""

    @pytest.mark.asyncio
    async def test_non_gated_state_always_allows(self, gate_service, mock_db_repo):
        """Transition to a non-gated state returns (True, None) without DB call."""
        result = await gate_service.can_transition("pr-001", "Drafted")

        assert result == (True, None)
        mock_db_repo.get_latest_grounding_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_gated_state_personalise(self, gate_service, mock_db_repo):
        """Transition to 'Personalise' is non-gated."""
        result = await gate_service.can_transition("pr-001", "Personalise")

        assert result == (True, None)
        mock_db_repo.get_latest_grounding_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_gated_state_researched(self, gate_service, mock_db_repo):
        """Transition to 'Researched' is non-gated."""
        result = await gate_service.can_transition("pr-001", "Researched")

        assert result == (True, None)

    @pytest.mark.asyncio
    async def test_gated_state_no_report_blocks(self, gate_service, mock_db_repo):
        """Transition to gated state with no report returns (False, [])."""
        mock_db_repo.get_latest_grounding_report.return_value = None

        result = await gate_service.can_transition("pr-001", "Approve")

        assert result == (False, [])
        mock_db_repo.get_latest_grounding_report.assert_called_once_with("pr-001")

    @pytest.mark.asyncio
    async def test_gated_state_blocked_returns_ungrounded_claims(self, gate_service, mock_db_repo):
        """Transition to gated state with GROUNDING_BLOCKED returns ungrounded claims."""
        ungrounded_claim = _make_claim(claim_id="c-1", grounding_status=GroundingStatus.UNGROUNDED)
        grounded_claim = _make_claim(claim_id="c-2", grounding_status=GroundingStatus.GROUNDED)
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            grounded_count=1,
            partially_grounded_count=0,
            ungrounded_count=1,
            claims=[ungrounded_claim, grounded_claim],
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        result = await gate_service.can_transition("pr-001", "Applied")

        allowed, claims = result
        assert allowed is False
        assert claims is not None
        assert len(claims) == 1
        assert claims[0].id == "c-1"
        assert claims[0].grounding_status == GroundingStatus.UNGROUNDED

    @pytest.mark.asyncio
    async def test_gated_state_verified_allows(self, gate_service, mock_db_repo):
        """Transition to gated state with GROUNDING_VERIFIED returns (True, None)."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            grounded_count=3,
            ungrounded_count=0,
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        result = await gate_service.can_transition("pr-001", "Sent")

        assert result == (True, None)

    @pytest.mark.asyncio
    async def test_gated_state_unverified_allows(self, gate_service, mock_db_repo):
        """Transition to gated state with GROUNDING_UNVERIFIED returns (True, None).

        Note: unverified means extraction failed — not actively blocked.
        """
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_UNVERIFIED,
            grounded_count=0,
            ungrounded_count=0,
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        result = await gate_service.can_transition("pr-001", "Approve")

        assert result == (True, None)

    @pytest.mark.asyncio
    async def test_all_gated_states_are_checked(self, gate_service, mock_db_repo):
        """All four gated states trigger the grounding check."""
        mock_db_repo.get_latest_grounding_report.return_value = None

        for state in ["Approve", "Applied", "Sent", "Proposal Submitted"]:
            result = await gate_service.can_transition("pr-001", state)
            assert result == (False, []), f"State '{state}' should be gated"

    @pytest.mark.asyncio
    async def test_blocked_with_multiple_ungrounded(self, gate_service, mock_db_repo):
        """Returns all ungrounded claims when multiple exist."""
        claims = [
            _make_claim(claim_id="c-1", grounding_status=GroundingStatus.UNGROUNDED),
            _make_claim(claim_id="c-2", grounding_status=GroundingStatus.UNGROUNDED),
            _make_claim(claim_id="c-3", grounding_status=GroundingStatus.GROUNDED),
            _make_claim(claim_id="c-4", grounding_status=GroundingStatus.PARTIALLY_GROUNDED),
        ]
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            grounded_count=1,
            partially_grounded_count=1,
            ungrounded_count=2,
            claims=claims,
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        allowed, ungrounded = await gate_service.can_transition("pr-001", "Proposal Submitted")

        assert allowed is False
        assert ungrounded is not None
        assert len(ungrounded) == 2
        assert all(c.grounding_status == GroundingStatus.UNGROUNDED for c in ungrounded)


# ─── get_warning_badge TESTS ─────────────────────────────────────────────────


class TestGetWarningBadge:
    """Tests for get_warning_badge() method."""

    @pytest.mark.asyncio
    async def test_no_report_returns_false(self, gate_service, mock_db_repo):
        """Returns False when no grounding report exists."""
        mock_db_repo.get_latest_grounding_report.return_value = None

        result = await gate_service.get_warning_badge("pr-001")

        assert result is False

    @pytest.mark.asyncio
    async def test_partially_grounded_with_no_ungrounded_returns_true(self, gate_service, mock_db_repo):
        """Returns True when partially_grounded > 0 and ungrounded == 0."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            grounded_count=2,
            partially_grounded_count=1,
            ungrounded_count=0,
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        result = await gate_service.get_warning_badge("pr-001")

        assert result is True

    @pytest.mark.asyncio
    async def test_all_grounded_returns_false(self, gate_service, mock_db_repo):
        """Returns False when all claims are fully grounded."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            grounded_count=5,
            partially_grounded_count=0,
            ungrounded_count=0,
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        result = await gate_service.get_warning_badge("pr-001")

        assert result is False

    @pytest.mark.asyncio
    async def test_has_ungrounded_returns_false(self, gate_service, mock_db_repo):
        """Returns False when ungrounded claims exist (even with partially_grounded)."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            grounded_count=1,
            partially_grounded_count=1,
            ungrounded_count=1,
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        result = await gate_service.get_warning_badge("pr-001")

        assert result is False

    @pytest.mark.asyncio
    async def test_zero_claims_returns_false(self, gate_service, mock_db_repo):
        """Returns False when there are zero claims total."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            grounded_count=0,
            partially_grounded_count=0,
            ungrounded_count=0,
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        result = await gate_service.get_warning_badge("pr-001")

        assert result is False

    @pytest.mark.asyncio
    async def test_multiple_partially_grounded_returns_true(self, gate_service, mock_db_repo):
        """Returns True when multiple partially_grounded claims exist with no ungrounded."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            grounded_count=2,
            partially_grounded_count=3,
            ungrounded_count=0,
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        result = await gate_service.get_warning_badge("pr-001")

        assert result is True
