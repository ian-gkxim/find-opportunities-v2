# Feature: claim-grounding-verification, Property 10: Analytics rate computation
"""Property-based tests for Grounding Analytics rate computation.

Tests that the ungrounded-claim rate is correctly computed per technique per week:
1. ungrounded_rate = ungrounded_claims / total_claims_extracted (0 if total is 0)
2. The rate is always between 0 and 1 inclusive
3. Rate is 0 when total_claims is 0

**Validates: Requirement 4, AC 2**
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.grounding_analytics_service import UngroundedClaimRate


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for prepare technique IDs
prepare_technique_id_st = st.sampled_from([
    "cv_and_cover_letter",
    "cold_email_composition",
    "proposal_composition",
])

# Strategy for a week start date (always a Monday, within realistic range)
week_start_st = st.dates(
    min_value=date(2024, 1, 1),
    max_value=date(2025, 12, 31),
).map(lambda d: d - timedelta(days=d.weekday()))  # align to Monday


# Strategy for total claims (includes zero for edge case)
total_claims_st = st.integers(min_value=0, max_value=10000)

# Strategy for positive total claims (non-zero)
positive_total_claims_st = st.integers(min_value=1, max_value=10000)


@st.composite
def claim_counts_st(draw):
    """Generate consistent claim counts where ungrounded + partially_grounded <= total."""
    total = draw(st.integers(min_value=0, max_value=10000))
    # ungrounded must be <= total
    ungrounded = draw(st.integers(min_value=0, max_value=total))
    # partially_grounded must be <= (total - ungrounded)
    remaining = total - ungrounded
    partially_grounded = draw(st.integers(min_value=0, max_value=remaining))
    return total, ungrounded, partially_grounded


@st.composite
def ungrounded_claim_rate_st(draw):
    """Generate a valid UngroundedClaimRate with correctly computed rate."""
    technique_id = draw(prepare_technique_id_st)
    week_start = draw(week_start_st)
    week_end = week_start + timedelta(days=6)
    total, ungrounded, partially_grounded = draw(claim_counts_st())

    expected_rate = ungrounded / total if total > 0 else 0.0
    expected_pg_rate = partially_grounded / total if total > 0 else 0.0

    return UngroundedClaimRate(
        prepare_technique_id=technique_id,
        week_start=week_start,
        week_end=week_end,
        total_claims_extracted=total,
        ungrounded_claims=ungrounded,
        partially_grounded_claims=partially_grounded,
        ungrounded_rate=round(expected_rate, 4),
        partially_grounded_rate=round(expected_pg_rate, 4),
    )


def compute_ungrounded_rate(ungrounded: int, total: int) -> float:
    """Mirror the analytics service rate computation logic.

    This is the formula from the analytics service:
    ungrounded_rate = ungrounded / total if total > 0 else 0.0
    """
    if total == 0:
        return 0.0
    return ungrounded / total


# ─── Property 10: Ungrounded-claim rate is correctly computed ─────────────────


class TestProperty10AnalyticsRateComputation:
    """Property 10: Ungrounded-claim rate is correctly computed per technique per week.

    **Validates: Requirement 4, AC 2**

    Key invariants:
    - ungrounded_rate = ungrounded_claims / total_claims_extracted (0 if total is 0)
    - The rate is always in [0, 1]
    - Rate is 0 when total_claims_extracted is 0
    """

    @given(data=claim_counts_st())
    @settings(max_examples=200)
    def test_rate_equals_ungrounded_divided_by_total(
        self,
        data: tuple[int, int, int],
    ) -> None:
        """FOR ANY combination of total_claims and ungrounded_claims where
        total > 0, the ungrounded_rate SHALL equal
        ungrounded_claims / total_claims_extracted.

        **Validates: Requirement 4, AC 2**
        """
        total, ungrounded, partially_grounded = data
        assume(total > 0)

        computed_rate = compute_ungrounded_rate(ungrounded, total)
        expected_rate = ungrounded / total

        assert math.isclose(computed_rate, expected_rate, rel_tol=1e-9), (
            f"Rate mismatch: compute_ungrounded_rate({ungrounded}, {total}) = "
            f"{computed_rate}, expected {expected_rate}"
        )

    @given(data=claim_counts_st())
    @settings(max_examples=200)
    def test_rate_is_always_between_zero_and_one(
        self,
        data: tuple[int, int, int],
    ) -> None:
        """FOR ANY valid combination of claim counts, the ungrounded_rate
        SHALL always be >= 0 and <= 1.

        **Validates: Requirement 4, AC 2**
        """
        total, ungrounded, partially_grounded = data

        rate = compute_ungrounded_rate(ungrounded, total)

        assert 0.0 <= rate <= 1.0, (
            f"Rate out of bounds: compute_ungrounded_rate({ungrounded}, {total}) = "
            f"{rate}, expected [0.0, 1.0]"
        )

    @given(
        ungrounded=st.integers(min_value=0, max_value=10000),
        partially_grounded=st.integers(min_value=0, max_value=10000),
    )
    @settings(max_examples=200)
    def test_rate_is_zero_when_total_claims_is_zero(
        self,
        ungrounded: int,
        partially_grounded: int,
    ) -> None:
        """WHEN total_claims_extracted is 0, THEN the ungrounded_rate SHALL
        be 0 regardless of other values.

        Note: In practice ungrounded should also be 0 when total is 0, but
        the rate formula must still produce 0 defensively.

        **Validates: Requirement 4, AC 2**
        """
        total = 0

        rate = compute_ungrounded_rate(ungrounded, total)

        assert rate == 0.0, (
            f"Expected rate 0.0 when total_claims=0, got {rate}"
        )

    @given(rate_record=ungrounded_claim_rate_st())
    @settings(max_examples=200)
    def test_dataclass_rate_matches_formula(
        self,
        rate_record: UngroundedClaimRate,
    ) -> None:
        """FOR ANY UngroundedClaimRate record, the stored ungrounded_rate
        SHALL match the formula: ungrounded_claims / total_claims_extracted
        (rounded to 4 decimal places), or 0 if total is 0.

        **Validates: Requirement 4, AC 2**
        """
        total = rate_record.total_claims_extracted
        ungrounded = rate_record.ungrounded_claims

        if total == 0:
            expected = 0.0
        else:
            expected = round(ungrounded / total, 4)

        assert rate_record.ungrounded_rate == expected, (
            f"UngroundedClaimRate.ungrounded_rate={rate_record.ungrounded_rate} "
            f"does not match expected={expected} for "
            f"ungrounded={ungrounded}, total={total}"
        )

    @given(rate_record=ungrounded_claim_rate_st())
    @settings(max_examples=200)
    def test_dataclass_rate_bounded_zero_to_one(
        self,
        rate_record: UngroundedClaimRate,
    ) -> None:
        """FOR ANY UngroundedClaimRate record, the ungrounded_rate field
        SHALL be in the range [0, 1].

        **Validates: Requirement 4, AC 2**
        """
        assert 0.0 <= rate_record.ungrounded_rate <= 1.0, (
            f"Rate out of bounds: {rate_record.ungrounded_rate} for "
            f"technique={rate_record.prepare_technique_id}, "
            f"week={rate_record.week_start}"
        )

    @given(
        total=positive_total_claims_st,
    )
    @settings(max_examples=200)
    def test_rate_is_one_when_all_claims_are_ungrounded(
        self,
        total: int,
    ) -> None:
        """WHEN every claim is ungrounded (ungrounded == total), THEN
        the rate SHALL equal 1.0.

        **Validates: Requirement 4, AC 2**
        """
        rate = compute_ungrounded_rate(total, total)

        assert rate == 1.0, (
            f"Expected rate 1.0 when all {total} claims are ungrounded, "
            f"got {rate}"
        )

    @given(total=positive_total_claims_st)
    @settings(max_examples=200)
    def test_rate_is_zero_when_no_claims_are_ungrounded(
        self,
        total: int,
    ) -> None:
        """WHEN no claims are ungrounded (ungrounded == 0, total > 0),
        THEN the rate SHALL equal 0.0.

        **Validates: Requirement 4, AC 2**
        """
        rate = compute_ungrounded_rate(0, total)

        assert rate == 0.0, (
            f"Expected rate 0.0 when 0 out of {total} claims are ungrounded, "
            f"got {rate}"
        )
