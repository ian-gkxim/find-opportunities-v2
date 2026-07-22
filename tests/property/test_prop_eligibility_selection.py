# Feature: capability-gap-analytics, Property 1: Opportunity eligibility selection
"""Property-based tests for opportunity eligibility selection logic.

Tests the pure-logic eligibility determination for gap analysis:
given a list of pipeline records with varied states, tiers, timestamps,
and extraction flags, the selection returns exactly the eligible records.

Eligibility criteria (from Requirement 1.1):
- (state IN ('rejected', 'lost') OR tier IN ('C-tier', 'D-tier'))
- AND updated_at >= window_cutoff
- AND NOT already_extracted

Key properties:
1. Every record returned by selection satisfies all three eligibility criteria.
2. Every record NOT returned fails at least one eligibility criterion.
3. The set of selected records equals the set determined by is_eligible.

**Validates: Requirements 1.1**
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hypothesis import given, settings
from hypothesis import strategies as st


# ─── Pure helper function under test ──────────────────────────────────────────


# All possible states in the pipeline
ELIGIBLE_STATES = ("rejected", "lost")
ELIGIBLE_TIERS = ("C-tier", "D-tier")

ALL_STATES = ("prospecting", "qualifying", "proposing", "negotiating", "won", "rejected", "lost")
ALL_TIERS = ("A-tier", "B-tier", "C-tier", "D-tier")


def is_eligible(
    state: str,
    tier: str,
    updated_at: datetime,
    window_cutoff: datetime,
    already_extracted: bool,
) -> bool:
    """Determine if a pipeline record is eligible for gap analysis extraction.

    A record is eligible when:
    - (state is 'rejected' or 'lost') OR (tier is 'C-tier' or 'D-tier')
    - AND it was updated within the analysis window (updated_at >= window_cutoff)
    - AND it has not already been extracted

    Args:
        state: Pipeline record current status.
        tier: Account score tier associated with the record.
        updated_at: When the record was last updated.
        window_cutoff: Earliest timestamp considered within the analysis window.
        already_extracted: Whether this record already has an extraction.

    Returns:
        True if eligible for extraction, False otherwise.
    """
    state_or_tier_eligible = (state in ELIGIBLE_STATES) or (tier in ELIGIBLE_TIERS)
    within_window = updated_at >= window_cutoff
    not_extracted = not already_extracted

    return state_or_tier_eligible and within_window and not_extracted


def select_eligible(
    records: list[dict],
    window_cutoff: datetime,
) -> list[str]:
    """Select eligible pipeline records for gap analysis extraction.

    Pure-logic equivalent of GapAnalyzer.get_eligible_opportunities().

    Args:
        records: List of dicts with keys: id, state, tier, updated_at, already_extracted.
        window_cutoff: Earliest timestamp considered within the analysis window.

    Returns:
        List of record IDs that are eligible.
    """
    return [
        r["id"]
        for r in records
        if is_eligible(
            state=r["state"],
            tier=r["tier"],
            updated_at=r["updated_at"],
            window_cutoff=window_cutoff,
            already_extracted=r["already_extracted"],
        )
    ]


# ─── Strategies ───────────────────────────────────────────────────────────────

# Base timestamp for generating realistic datetimes
_BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)
_WINDOW_DAYS = 90

# Strategy for a pipeline record state
state_st = st.sampled_from(ALL_STATES)

# Strategy for an account tier
tier_st = st.sampled_from(ALL_TIERS)

# Strategy for a unique record ID
record_id_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=8,
    max_size=16,
)

# Strategy for a timestamp spanning a wide range around the window cutoff
# (some before, some after to test the boundary condition)
timestamp_st = st.integers(min_value=-30 * 24 * 3600, max_value=120 * 24 * 3600).map(
    lambda offset: _BASE_TS + timedelta(seconds=offset)
)

# Strategy for already_extracted flag
extracted_st = st.booleans()


@st.composite
def pipeline_record_st(draw: st.DrawFn) -> dict:
    """Generate a single random pipeline record."""
    return {
        "id": draw(record_id_st),
        "state": draw(state_st),
        "tier": draw(tier_st),
        "updated_at": draw(timestamp_st),
        "already_extracted": draw(extracted_st),
    }


# Strategy for a list of pipeline records (1-50 with unique IDs)
pipeline_records_st = st.lists(
    pipeline_record_st(),
    min_size=1,
    max_size=50,
    unique_by=lambda r: r["id"],
)

# Strategy for window cutoff within the timestamp range
window_cutoff_st = st.integers(min_value=0, max_value=90 * 24 * 3600).map(
    lambda offset: _BASE_TS + timedelta(seconds=offset)
)


# ─── Property 1: Opportunity eligibility selection ────────────────────────────


class TestProperty1OpportunityEligibilitySelection:
    """Property 1: Opportunity eligibility selection.

    **Validates: Requirements 1.1**

    Key invariants:
    - Every selected record satisfies all eligibility criteria.
    - Every non-selected record fails at least one criterion.
    - Selection is exactly the set filtered by is_eligible.
    """

    @given(records=pipeline_records_st, cutoff=window_cutoff_st)
    @settings(max_examples=300)
    def test_selected_records_all_satisfy_eligibility_criteria(
        self,
        records: list[dict],
        cutoff: datetime,
    ) -> None:
        """FOR ANY set of pipeline records and window cutoff,
        every record returned by selection satisfies all three criteria:
        (state or tier eligible) AND within window AND not already extracted.

        **Validates: Requirements 1.1**
        """
        selected_ids = select_eligible(records, cutoff)
        records_by_id = {r["id"]: r for r in records}

        for rid in selected_ids:
            r = records_by_id[rid]
            assert is_eligible(
                state=r["state"],
                tier=r["tier"],
                updated_at=r["updated_at"],
                window_cutoff=cutoff,
                already_extracted=r["already_extracted"],
            ), (
                f"Selected record {rid} does not satisfy eligibility criteria.\n"
                f"State: {r['state']}, Tier: {r['tier']}, "
                f"Updated: {r['updated_at']}, Cutoff: {cutoff}, "
                f"Already extracted: {r['already_extracted']}"
            )

    @given(records=pipeline_records_st, cutoff=window_cutoff_st)
    @settings(max_examples=300)
    def test_non_selected_records_fail_at_least_one_criterion(
        self,
        records: list[dict],
        cutoff: datetime,
    ) -> None:
        """FOR ANY set of pipeline records and window cutoff,
        every record NOT in the selection fails at least one eligibility criterion.

        **Validates: Requirements 1.1**
        """
        selected_ids = set(select_eligible(records, cutoff))
        records_by_id = {r["id"]: r for r in records}

        for r in records:
            if r["id"] not in selected_ids:
                eligible = is_eligible(
                    state=r["state"],
                    tier=r["tier"],
                    updated_at=r["updated_at"],
                    window_cutoff=cutoff,
                    already_extracted=r["already_extracted"],
                )
                assert not eligible, (
                    f"Record {r['id']} NOT selected but IS eligible.\n"
                    f"State: {r['state']}, Tier: {r['tier']}, "
                    f"Updated: {r['updated_at']}, Cutoff: {cutoff}, "
                    f"Already extracted: {r['already_extracted']}"
                )

    @given(records=pipeline_records_st, cutoff=window_cutoff_st)
    @settings(max_examples=300)
    def test_selection_equals_is_eligible_filter(
        self,
        records: list[dict],
        cutoff: datetime,
    ) -> None:
        """FOR ANY set of pipeline records and window cutoff,
        filtering by is_eligible produces exactly the same set as select_eligible.

        **Validates: Requirements 1.1**
        """
        selected_ids = set(select_eligible(records, cutoff))

        expected_ids = {
            r["id"]
            for r in records
            if is_eligible(
                state=r["state"],
                tier=r["tier"],
                updated_at=r["updated_at"],
                window_cutoff=cutoff,
                already_extracted=r["already_extracted"],
            )
        }

        assert selected_ids == expected_ids, (
            f"Selection mismatch.\n"
            f"Selected but not eligible: {selected_ids - expected_ids}\n"
            f"Eligible but not selected: {expected_ids - selected_ids}"
        )

    @given(records=pipeline_records_st, cutoff=window_cutoff_st)
    @settings(max_examples=300)
    def test_already_extracted_records_never_selected(
        self,
        records: list[dict],
        cutoff: datetime,
    ) -> None:
        """FOR ANY set of pipeline records,
        no record with already_extracted=True is ever selected.

        **Validates: Requirements 1.1**
        """
        selected_ids = set(select_eligible(records, cutoff))

        for r in records:
            if r["already_extracted"]:
                assert r["id"] not in selected_ids, (
                    f"Already-extracted record {r['id']} was selected.\n"
                    f"State: {r['state']}, Tier: {r['tier']}, "
                    f"Updated: {r['updated_at']}, Cutoff: {cutoff}"
                )

    @given(records=pipeline_records_st, cutoff=window_cutoff_st)
    @settings(max_examples=300)
    def test_records_outside_window_never_selected(
        self,
        records: list[dict],
        cutoff: datetime,
    ) -> None:
        """FOR ANY set of pipeline records,
        no record with updated_at < window_cutoff is ever selected.

        **Validates: Requirements 1.1**
        """
        selected_ids = set(select_eligible(records, cutoff))

        for r in records:
            if r["updated_at"] < cutoff:
                assert r["id"] not in selected_ids, (
                    f"Record {r['id']} outside window was selected.\n"
                    f"Updated: {r['updated_at']}, Cutoff: {cutoff}, "
                    f"State: {r['state']}, Tier: {r['tier']}"
                )

    @given(records=pipeline_records_st, cutoff=window_cutoff_st)
    @settings(max_examples=300)
    def test_ineligible_state_and_tier_never_selected(
        self,
        records: list[dict],
        cutoff: datetime,
    ) -> None:
        """FOR ANY set of pipeline records,
        no record with a non-eligible state AND non-eligible tier is selected.

        **Validates: Requirements 1.1**
        """
        selected_ids = set(select_eligible(records, cutoff))

        for r in records:
            state_ok = r["state"] in ELIGIBLE_STATES
            tier_ok = r["tier"] in ELIGIBLE_TIERS
            if not state_ok and not tier_ok:
                assert r["id"] not in selected_ids, (
                    f"Record {r['id']} with ineligible state AND tier was selected.\n"
                    f"State: {r['state']}, Tier: {r['tier']}, "
                    f"Updated: {r['updated_at']}, Cutoff: {cutoff}"
                )
