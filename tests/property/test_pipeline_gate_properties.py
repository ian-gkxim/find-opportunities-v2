# Feature: claim-grounding-verification, Property 1: Pipeline gate blocking logic
"""Property-based tests for PipelineGateService pipeline gate blocking.

Tests that the pipeline gate blocks if and only if ungrounded claims exist:
- When a grounding report has ungrounded_count > 0, can_transition blocks for all gated states
- When a grounding report has ungrounded_count == 0, can_transition allows for all gated states
- The "if and only if" relationship: blocked ⟺ ungrounded claims exist

**Validates: Requirement 3, AC 1 and AC 4**
"""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.grounding_verifier import (
    Claim,
    ClaimCategory,
    GroundingReport,
    GroundingStatus,
    MaterialGroundingStatus,
)
from app.core.pipeline_gate import PipelineGateService


# ─── Constants ────────────────────────────────────────────────────────────────

GATED_STATES = {"Approve", "Applied", "Sent", "Proposal Submitted"}

NON_GATED_STATES = [
    "New",
    "Enriched",
    "Scored",
    "Personalise",
    "Drafted",
    "Rejected",
    "Lost",
    "Won",
]


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for gated target states
gated_state_st = st.sampled_from(sorted(GATED_STATES))

# Strategy for non-gated target states
non_gated_state_st = st.sampled_from(NON_GATED_STATES)

# Strategy for a pipeline record ID
pipeline_record_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters="\x00"),
    min_size=5,
    max_size=36,
).map(lambda _: str(uuid.uuid4()))

# Strategy for positive ungrounded count
positive_ungrounded_count_st = st.integers(min_value=1, max_value=50)

# Strategy for zero ungrounded count
zero_ungrounded_count_st = st.just(0)

# Strategy for grounded/partially_grounded counts
grounded_count_st = st.integers(min_value=0, max_value=50)
partially_grounded_count_st = st.integers(min_value=0, max_value=50)


@st.composite
def ungrounded_claim_st(draw, material_id: str = "mat-001"):
    """Generate a Claim with grounding_status = UNGROUNDED."""
    return Claim(
        id=str(uuid.uuid4()),
        material_id=material_id,
        category=draw(st.sampled_from(list(ClaimCategory))),
        claim_text=draw(st.text(min_size=5, max_size=50, alphabet=st.characters(
            whitelist_categories=("L", "N", "Z"), blacklist_characters="\x00"
        ))),
        source_span=draw(st.text(min_size=3, max_size=30, alphabet=st.characters(
            whitelist_categories=("L", "N", "Z"), blacklist_characters="\x00"
        ))),
        source_span_start=draw(st.integers(min_value=0, max_value=100)),
        source_span_end=draw(st.integers(min_value=101, max_value=200)),
        grounding_status=GroundingStatus.UNGROUNDED,
        is_prospect_side=False,
    )


@st.composite
def grounded_claim_st(draw, material_id: str = "mat-001"):
    """Generate a Claim with grounding_status = GROUNDED."""
    return Claim(
        id=str(uuid.uuid4()),
        material_id=material_id,
        category=draw(st.sampled_from(list(ClaimCategory))),
        claim_text=draw(st.text(min_size=5, max_size=50, alphabet=st.characters(
            whitelist_categories=("L", "N", "Z"), blacklist_characters="\x00"
        ))),
        source_span=draw(st.text(min_size=3, max_size=30, alphabet=st.characters(
            whitelist_categories=("L", "N", "Z"), blacklist_characters="\x00"
        ))),
        source_span_start=draw(st.integers(min_value=0, max_value=100)),
        source_span_end=draw(st.integers(min_value=101, max_value=200)),
        grounding_status=GroundingStatus.GROUNDED,
        is_prospect_side=False,
    )


@st.composite
def partially_grounded_claim_st(draw, material_id: str = "mat-001"):
    """Generate a Claim with grounding_status = PARTIALLY_GROUNDED."""
    return Claim(
        id=str(uuid.uuid4()),
        material_id=material_id,
        category=draw(st.sampled_from(list(ClaimCategory))),
        claim_text=draw(st.text(min_size=5, max_size=50, alphabet=st.characters(
            whitelist_categories=("L", "N", "Z"), blacklist_characters="\x00"
        ))),
        source_span=draw(st.text(min_size=3, max_size=30, alphabet=st.characters(
            whitelist_categories=("L", "N", "Z"), blacklist_characters="\x00"
        ))),
        source_span_start=draw(st.integers(min_value=0, max_value=100)),
        source_span_end=draw(st.integers(min_value=101, max_value=200)),
        grounding_status=GroundingStatus.PARTIALLY_GROUNDED,
        is_prospect_side=False,
        discrepancy="Number differs from source",
    )


@st.composite
def blocked_grounding_report_st(draw):
    """Generate a GroundingReport with ungrounded_count > 0 (GROUNDING_BLOCKED).

    This represents a report where at least one claim is ungrounded,
    meaning the pipeline should be blocked.
    """
    material_id = "mat-" + str(uuid.uuid4())[:8]
    pipeline_record_id = str(uuid.uuid4())

    # Generate at least 1 ungrounded claim
    ungrounded_claims = draw(st.lists(
        ungrounded_claim_st(material_id=material_id),
        min_size=1, max_size=5,
    ))
    # Optionally add some grounded/partially_grounded claims
    grounded_claims = draw(st.lists(
        grounded_claim_st(material_id=material_id),
        min_size=0, max_size=5,
    ))
    partial_claims = draw(st.lists(
        partially_grounded_claim_st(material_id=material_id),
        min_size=0, max_size=3,
    ))

    all_claims = ungrounded_claims + grounded_claims + partial_claims

    return GroundingReport(
        id=str(uuid.uuid4()),
        material_id=material_id,
        pipeline_record_id=pipeline_record_id,
        claims=all_claims,
        total_claims=len(all_claims),
        grounded_count=len(grounded_claims),
        partially_grounded_count=len(partial_claims),
        ungrounded_count=len(ungrounded_claims),
        material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
        extraction_duration_ms=draw(st.integers(min_value=100, max_value=5000)),
        verification_duration_ms=draw(st.integers(min_value=50, max_value=3000)),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@st.composite
def verified_grounding_report_st(draw):
    """Generate a GroundingReport with ungrounded_count == 0 (GROUNDING_VERIFIED).

    This represents a report where no claims are ungrounded,
    meaning the pipeline should be allowed to advance.
    """
    material_id = "mat-" + str(uuid.uuid4())[:8]
    pipeline_record_id = str(uuid.uuid4())

    # Generate only grounded and/or partially_grounded claims (no ungrounded)
    grounded_claims = draw(st.lists(
        grounded_claim_st(material_id=material_id),
        min_size=1, max_size=8,
    ))
    partial_claims = draw(st.lists(
        partially_grounded_claim_st(material_id=material_id),
        min_size=0, max_size=3,
    ))

    all_claims = grounded_claims + partial_claims

    return GroundingReport(
        id=str(uuid.uuid4()),
        material_id=material_id,
        pipeline_record_id=pipeline_record_id,
        claims=all_claims,
        total_claims=len(all_claims),
        grounded_count=len(grounded_claims),
        partially_grounded_count=len(partial_claims),
        ungrounded_count=0,
        material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
        extraction_duration_ms=draw(st.integers(min_value=100, max_value=5000)),
        verification_duration_ms=draw(st.integers(min_value=50, max_value=3000)),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


# ─── Property 1: Pipeline gate blocks if and only if ungrounded claims exist ──


class TestProperty1PipelineGateBlocking:
    """Property 1: Pipeline gate blocks if and only if ungrounded claims exist.

    **Validates: Requirement 3, AC 1 and AC 4**

    Key invariants:
    - blocked ⟺ ungrounded claims exist (for gated states)
    - Non-gated states are always allowed regardless of grounding status
    """

    @given(
        report=blocked_grounding_report_st(),
        target_state=gated_state_st,
    )
    @settings(max_examples=100)
    def test_blocks_when_ungrounded_claims_exist(
        self, report: GroundingReport, target_state: str
    ) -> None:
        """WHEN a grounding report has ungrounded_count > 0, THEN can_transition
        blocks the transition for ALL gated states (Approve, Applied, Sent,
        Proposal Submitted).

        **Validates: Requirement 3, AC 1**
        """
        # Set up mock repository returning the blocked report
        mock_repo = MagicMock()
        mock_repo.get_latest_grounding_report = AsyncMock(return_value=report)

        gate = PipelineGateService(db_repo=mock_repo)

        allowed, blocking_claims = asyncio.run(
            gate.can_transition(report.pipeline_record_id, target_state)
        )

        # PROPERTY: Gate blocks when ungrounded claims exist
        assert allowed is False, (
            f"Expected gate to BLOCK transition to '{target_state}' when "
            f"ungrounded_count={report.ungrounded_count}, but got allowed=True"
        )
        assert blocking_claims is not None, (
            f"Expected blocking_claims to be non-None when blocked"
        )
        # All returned claims should be ungrounded
        for claim in blocking_claims:
            assert claim.grounding_status == GroundingStatus.UNGROUNDED, (
                f"Expected only ungrounded claims in blocking list, "
                f"got {claim.grounding_status}"
            )

    @given(
        report=verified_grounding_report_st(),
        target_state=gated_state_st,
    )
    @settings(max_examples=100)
    def test_allows_when_no_ungrounded_claims(
        self, report: GroundingReport, target_state: str
    ) -> None:
        """WHEN a grounding report has ungrounded_count == 0, THEN can_transition
        allows the transition for ALL gated states.

        **Validates: Requirement 3, AC 4**
        """
        # Set up mock repository returning the verified report
        mock_repo = MagicMock()
        mock_repo.get_latest_grounding_report = AsyncMock(return_value=report)

        gate = PipelineGateService(db_repo=mock_repo)

        allowed, blocking_claims = asyncio.run(
            gate.can_transition(report.pipeline_record_id, target_state)
        )

        # PROPERTY: Gate allows when no ungrounded claims exist
        assert allowed is True, (
            f"Expected gate to ALLOW transition to '{target_state}' when "
            f"ungrounded_count=0, but got allowed=False. "
            f"Report status: {report.material_grounding_status}"
        )
        assert blocking_claims is None, (
            f"Expected blocking_claims=None when allowed, got {blocking_claims}"
        )

    @given(
        report=st.one_of(blocked_grounding_report_st(), verified_grounding_report_st()),
        target_state=gated_state_st,
    )
    @settings(max_examples=100)
    def test_biconditional_blocked_iff_ungrounded_exists(
        self, report: GroundingReport, target_state: str
    ) -> None:
        """The "if and only if" relationship: for gated states, a transition is
        blocked ⟺ the report contains ungrounded claims (ungrounded_count > 0).

        **Validates: Requirement 3, AC 1 and AC 4**
        """
        mock_repo = MagicMock()
        mock_repo.get_latest_grounding_report = AsyncMock(return_value=report)

        gate = PipelineGateService(db_repo=mock_repo)

        allowed, blocking_claims = asyncio.run(
            gate.can_transition(report.pipeline_record_id, target_state)
        )

        has_ungrounded = report.ungrounded_count > 0

        # PROPERTY: blocked ⟺ ungrounded claims exist
        if has_ungrounded:
            assert allowed is False, (
                f"Biconditional violated: ungrounded_count={report.ungrounded_count} "
                f"but gate allowed transition to '{target_state}'"
            )
        else:
            assert allowed is True, (
                f"Biconditional violated: ungrounded_count=0 "
                f"but gate blocked transition to '{target_state}'"
            )

    @given(
        report=st.one_of(blocked_grounding_report_st(), verified_grounding_report_st()),
        target_state=non_gated_state_st,
    )
    @settings(max_examples=100)
    def test_non_gated_states_always_allowed(
        self, report: GroundingReport, target_state: str
    ) -> None:
        """FOR non-gated states, can_transition always returns (True, None)
        regardless of grounding status.

        **Validates: Requirement 3, AC 1 and AC 4**
        """
        mock_repo = MagicMock()
        # The repo should NOT even be called for non-gated states
        mock_repo.get_latest_grounding_report = AsyncMock(return_value=report)

        gate = PipelineGateService(db_repo=mock_repo)

        allowed, blocking_claims = asyncio.run(
            gate.can_transition(report.pipeline_record_id, target_state)
        )

        # PROPERTY: Non-gated states are never blocked
        assert allowed is True, (
            f"Expected non-gated state '{target_state}' to always be allowed, "
            f"but got blocked"
        )
        assert blocking_claims is None, (
            f"Expected None claims for non-gated state, got {blocking_claims}"
        )

    @given(target_state=gated_state_st)
    @settings(max_examples=50)
    def test_blocks_when_no_report_exists(
        self, target_state: str
    ) -> None:
        """WHEN no grounding report exists for a pipeline record, THEN
        can_transition blocks the transition to gated states with an empty
        claims list (material hasn't been verified yet).

        **Validates: Requirement 3, AC 1**
        """
        mock_repo = MagicMock()
        mock_repo.get_latest_grounding_report = AsyncMock(return_value=None)

        gate = PipelineGateService(db_repo=mock_repo)

        pipeline_record_id = str(uuid.uuid4())
        allowed, blocking_claims = asyncio.run(
            gate.can_transition(pipeline_record_id, target_state)
        )

        # PROPERTY: No report means blocked (material hasn't been verified)
        assert allowed is False, (
            f"Expected gate to block when no report exists for gated state "
            f"'{target_state}', but got allowed=True"
        )
        assert blocking_claims == [], (
            f"Expected empty claims list when no report exists, "
            f"got {blocking_claims}"
        )



# ─── Property 13: Warning badge displayed if only partially_grounded claims ───


class TestProperty13WarningBadgeLogic:
    """Property 13: Warning badge displayed if only partially_grounded claims exist.

    **Validates: Requirement 3, AC 4**

    Key invariant: get_warning_badge(pipeline_record_id) returns True
    if and only if partially_grounded_count > 0 AND ungrounded_count == 0.
    """

    # ─── Strategies ───────────────────────────────────────────────────────

    # Non-negative integer for claim counts
    count_st = st.integers(min_value=0, max_value=100)

    # Positive integer (at least 1)
    positive_count_st = st.integers(min_value=1, max_value=100)

    def _make_warning_badge_report(
        self,
        *,
        grounded_count: int = 0,
        partially_grounded_count: int = 0,
        ungrounded_count: int = 0,
    ) -> GroundingReport:
        """Build a GroundingReport with the given claim counts for warning badge tests."""
        now = datetime.now(timezone.utc)
        total = grounded_count + partially_grounded_count + ungrounded_count

        if ungrounded_count > 0:
            status = MaterialGroundingStatus.GROUNDING_BLOCKED
        else:
            status = MaterialGroundingStatus.GROUNDING_VERIFIED

        return GroundingReport(
            id="rpt-prop13",
            material_id="mat-prop13",
            pipeline_record_id="pr-prop13",
            claims=[],
            total_claims=total,
            grounded_count=grounded_count,
            partially_grounded_count=partially_grounded_count,
            ungrounded_count=ungrounded_count,
            material_grounding_status=status,
            extraction_duration_ms=50,
            verification_duration_ms=30,
            created_at=now,
            updated_at=now,
        )

    def _make_gate_service(self, report: GroundingReport | None) -> PipelineGateService:
        """Build a PipelineGateService with a mocked repository returning the given report."""
        mock_repo = MagicMock()
        mock_repo.get_latest_grounding_report = AsyncMock(return_value=report)
        return PipelineGateService(db_repo=mock_repo)

    @given(
        partially_grounded_count=st.integers(min_value=1, max_value=100),
        grounded_count=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=100)
    def test_warning_badge_true_when_partially_grounded_and_no_ungrounded(
        self,
        partially_grounded_count: int,
        grounded_count: int,
    ) -> None:
        """WHEN partially_grounded_count > 0 AND ungrounded_count == 0,
        THEN get_warning_badge returns True.

        **Validates: Requirement 3, AC 4**
        """
        report = self._make_warning_badge_report(
            grounded_count=grounded_count,
            partially_grounded_count=partially_grounded_count,
            ungrounded_count=0,
        )
        service = self._make_gate_service(report)

        result = asyncio.run(service.get_warning_badge("pr-prop13"))

        assert result is True, (
            f"Expected True for partially_grounded={partially_grounded_count}, "
            f"ungrounded=0, grounded={grounded_count}"
        )

    @given(
        partially_grounded_count=st.integers(min_value=0, max_value=100),
        ungrounded_count=st.integers(min_value=1, max_value=100),
        grounded_count=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=100)
    def test_warning_badge_false_when_ungrounded_exists(
        self,
        partially_grounded_count: int,
        ungrounded_count: int,
        grounded_count: int,
    ) -> None:
        """WHEN ungrounded_count > 0, THEN get_warning_badge returns False
        regardless of partially_grounded_count.

        **Validates: Requirement 3, AC 4**
        """
        report = self._make_warning_badge_report(
            grounded_count=grounded_count,
            partially_grounded_count=partially_grounded_count,
            ungrounded_count=ungrounded_count,
        )
        service = self._make_gate_service(report)

        result = asyncio.run(service.get_warning_badge("pr-prop13"))

        assert result is False, (
            f"Expected False when ungrounded={ungrounded_count} > 0, "
            f"partially_grounded={partially_grounded_count}, grounded={grounded_count}"
        )

    @given(grounded_count=st.integers(min_value=0, max_value=100))
    @settings(max_examples=100)
    def test_warning_badge_false_when_no_partially_grounded(
        self,
        grounded_count: int,
    ) -> None:
        """WHEN partially_grounded_count == 0 AND ungrounded_count == 0,
        THEN get_warning_badge returns False (no warning needed).

        **Validates: Requirement 3, AC 4**
        """
        report = self._make_warning_badge_report(
            grounded_count=grounded_count,
            partially_grounded_count=0,
            ungrounded_count=0,
        )
        service = self._make_gate_service(report)

        result = asyncio.run(service.get_warning_badge("pr-prop13"))

        assert result is False, (
            f"Expected False for partially_grounded=0, ungrounded=0, "
            f"grounded={grounded_count}"
        )

    @given(
        grounded_count=st.integers(min_value=0, max_value=100),
        partially_grounded_count=st.integers(min_value=0, max_value=100),
        ungrounded_count=st.integers(min_value=0, max_value=100),
    )
    @settings(max_examples=200)
    def test_warning_badge_iff_partially_grounded_only(
        self,
        grounded_count: int,
        partially_grounded_count: int,
        ungrounded_count: int,
    ) -> None:
        """FOR ANY combination of claim counts, get_warning_badge returns True
        if and only if partially_grounded_count > 0 AND ungrounded_count == 0.

        This is the universal property covering the complete truth table.

        **Validates: Requirement 3, AC 4**
        """
        report = self._make_warning_badge_report(
            grounded_count=grounded_count,
            partially_grounded_count=partially_grounded_count,
            ungrounded_count=ungrounded_count,
        )
        service = self._make_gate_service(report)

        result = asyncio.run(service.get_warning_badge("pr-prop13"))

        expected = partially_grounded_count > 0 and ungrounded_count == 0
        assert result is expected, (
            f"Expected {expected} for partially_grounded={partially_grounded_count}, "
            f"ungrounded={ungrounded_count}, grounded={grounded_count}, got {result}"
        )

    def test_warning_badge_false_when_no_report(self) -> None:
        """WHEN no grounding report exists (report is None),
        THEN get_warning_badge returns False.

        **Validates: Requirement 3, AC 4**
        """
        service = self._make_gate_service(report=None)

        result = asyncio.run(service.get_warning_badge("pr-prop13"))

        assert result is False


# ─── Property 7 (Testing Strategy): Gate state completeness ──────────────────


class TestProperty7GateStateCompleteness:
    """Property 7 (Testing Strategy): Gate state completeness.

    All MaterialGroundingStatus values produce the correct gate decision
    from can_transition().

    **Validates: Requirement 3, AC 1 and AC 4**

    Key invariants:
    - GROUNDING_VERIFIED → allows transition (True, None)
    - GROUNDING_BLOCKED → blocks transition (False, ungrounded_claims)
    - GROUNDING_UNVERIFIED → allows transition (True, None)
    """

    # ─── Helpers ──────────────────────────────────────────────────────────

    def _make_report(
        self,
        *,
        material_grounding_status: MaterialGroundingStatus,
        claims: list[Claim] | None = None,
        grounded_count: int = 0,
        partially_grounded_count: int = 0,
        ungrounded_count: int = 0,
    ) -> GroundingReport:
        """Build a GroundingReport with the given status and counts."""
        now = datetime.now(timezone.utc)
        total = grounded_count + partially_grounded_count + ungrounded_count
        return GroundingReport(
            id=str(uuid.uuid4()),
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
        self,
        *,
        grounding_status: GroundingStatus = GroundingStatus.GROUNDED,
        category: ClaimCategory = ClaimCategory.SKILL_TECHNOLOGY,
    ) -> Claim:
        """Build a Claim with the given grounding status."""
        return Claim(
            id=str(uuid.uuid4()),
            material_id="mat-001",
            category=category,
            claim_text="Expert in Python",
            source_span="Expert in Python",
            source_span_start=0,
            source_span_end=16,
            grounding_status=grounding_status,
        )

    # ─── Test: GROUNDING_VERIFIED always allows ───────────────────────────

    @given(
        target_state=gated_state_st,
        grounded_count=st.integers(min_value=1, max_value=50),
        partially_grounded_count=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=100)
    def test_grounding_verified_allows_transition(
        self,
        target_state: str,
        grounded_count: int,
        partially_grounded_count: int,
    ) -> None:
        """WHEN the grounding status is GROUNDING_VERIFIED and the target state
        is gated, THEN can_transition returns (True, None) — transition is allowed.

        **Validates: Requirement 3, AC 1 and AC 4**
        """
        report = self._make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            grounded_count=grounded_count,
            partially_grounded_count=partially_grounded_count,
            ungrounded_count=0,
        )

        mock_db = MagicMock()
        mock_db.get_latest_grounding_report = AsyncMock(return_value=report)
        gate = PipelineGateService(db_repo=mock_db)

        allowed, claims = asyncio.run(
            gate.can_transition("pr-001", target_state)
        )

        assert allowed is True, (
            f"GROUNDING_VERIFIED should allow transition to '{target_state}', "
            f"but got allowed=False"
        )
        assert claims is None, (
            f"GROUNDING_VERIFIED should return claims=None, got {claims}"
        )

    # ─── Test: GROUNDING_BLOCKED always blocks ────────────────────────────

    @given(
        target_state=gated_state_st,
        ungrounded_count=st.integers(min_value=1, max_value=20),
        grounded_count=st.integers(min_value=0, max_value=20),
        category=st.sampled_from(list(ClaimCategory)),
    )
    @settings(max_examples=100)
    def test_grounding_blocked_blocks_transition(
        self,
        target_state: str,
        ungrounded_count: int,
        grounded_count: int,
        category: ClaimCategory,
    ) -> None:
        """WHEN the grounding status is GROUNDING_BLOCKED and the target state
        is gated, THEN can_transition returns (False, ungrounded_claims) —
        transition is blocked and the ungrounded claims are returned.

        **Validates: Requirement 3, AC 1 and AC 4**
        """
        ungrounded = [
            self._make_claim(grounding_status=GroundingStatus.UNGROUNDED, category=category)
            for _ in range(ungrounded_count)
        ]
        grounded = [
            self._make_claim(grounding_status=GroundingStatus.GROUNDED, category=category)
            for _ in range(grounded_count)
        ]
        all_claims = ungrounded + grounded

        report = self._make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            claims=all_claims,
            grounded_count=grounded_count,
            ungrounded_count=ungrounded_count,
        )

        mock_db = MagicMock()
        mock_db.get_latest_grounding_report = AsyncMock(return_value=report)
        gate = PipelineGateService(db_repo=mock_db)

        allowed, returned_claims = asyncio.run(
            gate.can_transition("pr-001", target_state)
        )

        assert allowed is False, (
            f"GROUNDING_BLOCKED should block transition to '{target_state}', "
            f"but got allowed=True"
        )
        assert returned_claims is not None, (
            "GROUNDING_BLOCKED should return ungrounded claims list, got None"
        )
        assert len(returned_claims) == ungrounded_count, (
            f"Expected {ungrounded_count} ungrounded claims, "
            f"got {len(returned_claims)}"
        )
        # Every returned claim must be UNGROUNDED
        for claim in returned_claims:
            assert claim.grounding_status == GroundingStatus.UNGROUNDED, (
                f"Returned claim has status {claim.grounding_status}, "
                f"expected UNGROUNDED"
            )

    # ─── Test: GROUNDING_UNVERIFIED always allows ─────────────────────────

    @given(target_state=gated_state_st)
    @settings(max_examples=100)
    def test_grounding_unverified_allows_transition(
        self,
        target_state: str,
    ) -> None:
        """WHEN the grounding status is GROUNDING_UNVERIFIED (extraction failed)
        and the target state is gated, THEN can_transition returns (True, None) —
        transition is allowed because extraction failure is not blocking.

        **Validates: Requirement 3, AC 1 and AC 4**
        """
        report = self._make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_UNVERIFIED,
            grounded_count=0,
            partially_grounded_count=0,
            ungrounded_count=0,
        )

        mock_db = MagicMock()
        mock_db.get_latest_grounding_report = AsyncMock(return_value=report)
        gate = PipelineGateService(db_repo=mock_db)

        allowed, claims = asyncio.run(
            gate.can_transition("pr-001", target_state)
        )

        assert allowed is True, (
            f"GROUNDING_UNVERIFIED should allow transition to '{target_state}', "
            f"but got allowed=False"
        )
        assert claims is None, (
            f"GROUNDING_UNVERIFIED should return claims=None, got {claims}"
        )

    # ─── Test: All statuses produce deterministic decision ────────────────

    @given(
        status=st.sampled_from(list(MaterialGroundingStatus)),
        target_state=gated_state_st,
        ungrounded_count=st.integers(min_value=1, max_value=20),
        grounded_count=st.integers(min_value=0, max_value=20),
    )
    @settings(max_examples=200)
    def test_all_statuses_produce_deterministic_decision(
        self,
        status: MaterialGroundingStatus,
        target_state: str,
        ungrounded_count: int,
        grounded_count: int,
    ) -> None:
        """FOR ANY MaterialGroundingStatus value and any gated target state,
        can_transition produces a deterministic, correct decision:
        - GROUNDING_VERIFIED → (True, None)
        - GROUNDING_BLOCKED → (False, list of ungrounded claims)
        - GROUNDING_UNVERIFIED → (True, None)

        **Validates: Requirement 3, AC 1 and AC 4**
        """
        # Build claims matching the status
        if status == MaterialGroundingStatus.GROUNDING_BLOCKED:
            ungrounded = [
                self._make_claim(grounding_status=GroundingStatus.UNGROUNDED)
                for _ in range(ungrounded_count)
            ]
            grounded = [
                self._make_claim(grounding_status=GroundingStatus.GROUNDED)
                for _ in range(grounded_count)
            ]
            all_claims = ungrounded + grounded
            report = self._make_report(
                material_grounding_status=status,
                claims=all_claims,
                grounded_count=grounded_count,
                ungrounded_count=ungrounded_count,
            )
        elif status == MaterialGroundingStatus.GROUNDING_VERIFIED:
            report = self._make_report(
                material_grounding_status=status,
                grounded_count=grounded_count + ungrounded_count,
                ungrounded_count=0,
            )
        else:
            # GROUNDING_UNVERIFIED
            report = self._make_report(
                material_grounding_status=status,
                grounded_count=0,
                ungrounded_count=0,
            )

        mock_db = MagicMock()
        mock_db.get_latest_grounding_report = AsyncMock(return_value=report)
        gate = PipelineGateService(db_repo=mock_db)

        allowed, returned_claims = asyncio.run(
            gate.can_transition("pr-001", target_state)
        )

        if status == MaterialGroundingStatus.GROUNDING_BLOCKED:
            assert allowed is False, (
                f"Status {status.value} should block, got allowed=True"
            )
            assert returned_claims is not None
            assert len(returned_claims) == ungrounded_count
        elif status == MaterialGroundingStatus.GROUNDING_VERIFIED:
            assert allowed is True, (
                f"Status {status.value} should allow, got allowed=False"
            )
            assert returned_claims is None
        elif status == MaterialGroundingStatus.GROUNDING_UNVERIFIED:
            assert allowed is True, (
                f"Status {status.value} should allow, got allowed=False"
            )
            assert returned_claims is None

    # ─── Test: Non-gated states always pass regardless of status ──────────

    @given(
        status=st.sampled_from(list(MaterialGroundingStatus)),
        target_state=non_gated_state_st,
    )
    @settings(max_examples=100)
    def test_non_gated_states_always_allowed_regardless_of_status(
        self,
        status: MaterialGroundingStatus,
        target_state: str,
    ) -> None:
        """FOR ANY MaterialGroundingStatus value and any non-gated target state,
        can_transition always returns (True, None) without consulting the DB.

        **Validates: Requirement 3, AC 1 and AC 4**
        """
        mock_db = MagicMock()
        mock_db.get_latest_grounding_report = AsyncMock(return_value=None)
        gate = PipelineGateService(db_repo=mock_db)

        allowed, claims = asyncio.run(
            gate.can_transition("pr-001", target_state)
        )

        assert allowed is True, (
            f"Non-gated state '{target_state}' should always allow transition "
            f"regardless of grounding status {status.value}"
        )
        assert claims is None
        # DB should NOT be consulted for non-gated states
        mock_db.get_latest_grounding_report.assert_not_called()
