# Feature: capability-gap-analytics, Property 4: Batch cap enforcement with recency ordering
"""Property-based tests for batch cap enforcement logic.

Tests the pure-logic extraction of the batch cap enforcement:
given a list of eligible opportunities with timestamps and a cap C,
the function returns (batch, remainder) where batch contains the C
most-recent opportunities ordered most-recent first, and remainder
contains the rest.

Key properties:
1. When N <= C: all N opportunities are returned, nothing carried forward.
2. When N > C: exactly C opportunities are returned.
3. The C returned opportunities are the most recent (by timestamp).
4. The N-C remainder would be carried forward.
5. The returned batch is ordered most-recent first.

**Validates: Requirements 1.3**
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from hypothesis import given, settings
from hypothesis import strategies as st


# ─── Pure function under test ─────────────────────────────────────────────────


def enforce_batch_cap_pure(
    eligible_with_timestamps: list[tuple[str, datetime]],
    cap: int,
) -> tuple[list[str], list[str]]:
    """Pure-logic version of batch cap enforcement with recency ordering.

    Takes a list of (opportunity_id, timestamp) tuples and a cap.
    Returns (batch, remainder) where:
    - batch: up to `cap` opportunity IDs, ordered most-recent first
    - remainder: the rest, also ordered most-recent first

    This mirrors the logic of GapAnalyzer.enforce_batch_cap() without
    DB dependencies.

    Args:
        eligible_with_timestamps: List of (id, timestamp) tuples.
        cap: Maximum number of opportunities to process this cycle.

    Returns:
        Tuple of (batch_ids, remainder_ids).
    """
    if not eligible_with_timestamps:
        return ([], [])

    # Sort by timestamp descending (most recent first)
    sorted_by_recency = sorted(
        eligible_with_timestamps,
        key=lambda x: x[1],
        reverse=True,
    )

    if len(sorted_by_recency) <= cap:
        return ([item[0] for item in sorted_by_recency], [])

    batch = [item[0] for item in sorted_by_recency[:cap]]
    remainder = [item[0] for item in sorted_by_recency[cap:]]

    return (batch, remainder)


# ─── Strategies ───────────────────────────────────────────────────────────────

# Base timestamp for generating realistic datetimes
_BASE_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)

# Strategy for a unique opportunity ID
opportunity_id_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=8,
    max_size=16,
)

# Strategy for a timestamp within a 90-day window
timestamp_st = st.integers(min_value=0, max_value=90 * 24 * 3600).map(
    lambda offset: _BASE_TS + timedelta(seconds=offset)
)

# Strategy for a single eligible opportunity (id, timestamp)
eligible_opportunity_st = st.tuples(opportunity_id_st, timestamp_st)

# Strategy for N eligible opportunities (1-50) with unique IDs
eligible_list_st = st.lists(
    eligible_opportunity_st,
    min_size=1,
    max_size=50,
    unique_by=lambda x: x[0],  # Ensure unique IDs
)

# Strategy for cap values
cap_st = st.integers(min_value=1, max_value=50)


@st.composite
def eligible_over_cap_st(draw: st.DrawFn) -> tuple[list[tuple[str, datetime]], int]:
    """Generate (eligible_list, cap) where len(eligible_list) > cap.

    Ensures N > C without filtering, by first choosing N and C such that C < N.
    """
    n = draw(st.integers(min_value=2, max_value=50))
    cap = draw(st.integers(min_value=1, max_value=n - 1))
    eligible = draw(
        st.lists(
            eligible_opportunity_st,
            min_size=n,
            max_size=n,
            unique_by=lambda x: x[0],
        )
    )
    return (eligible, cap)


@st.composite
def eligible_within_cap_st(draw: st.DrawFn) -> tuple[list[tuple[str, datetime]], int]:
    """Generate (eligible_list, cap) where len(eligible_list) <= cap.

    Ensures N <= C without filtering.
    """
    n = draw(st.integers(min_value=1, max_value=50))
    cap = draw(st.integers(min_value=n, max_value=max(n, 50)))
    eligible = draw(
        st.lists(
            eligible_opportunity_st,
            min_size=n,
            max_size=n,
            unique_by=lambda x: x[0],
        )
    )
    return (eligible, cap)


# ─── Property 4: Batch cap enforcement with recency ordering ─────────────────


class TestProperty4BatchCapEnforcementWithRecencyOrdering:
    """Property 4: Batch cap enforcement with recency ordering.

    **Validates: Requirements 1.3**

    Key invariants:
    - When N <= C: all N opportunities returned, remainder is empty.
    - When N > C: exactly C opportunities returned.
    - Batch contains the C most-recent opportunities.
    - Remainder contains the N-C oldest opportunities.
    - Batch is ordered most-recent first.
    """

    @given(data=eligible_within_cap_st())
    @settings(max_examples=200)
    def test_within_cap_returns_all_empty_remainder(
        self,
        data: tuple[list[tuple[str, datetime]], int],
    ) -> None:
        """FOR ANY eligible list with N <= C,
        all N opportunities are returned and remainder is empty.

        **Validates: Requirements 1.3**
        """
        eligible, cap = data

        batch, remainder = enforce_batch_cap_pure(eligible, cap)

        # All IDs should be in the batch
        assert len(batch) == len(eligible), (
            f"Expected {len(eligible)} items in batch, got {len(batch)}"
        )
        # Remainder should be empty
        assert remainder == [], (
            f"Expected empty remainder when N <= C, got {len(remainder)} items"
        )
        # All original IDs should be present in batch
        original_ids = {item[0] for item in eligible}
        assert set(batch) == original_ids, (
            "Not all original IDs present in batch when N <= C"
        )

    @given(data=eligible_over_cap_st())
    @settings(max_examples=200)
    def test_over_cap_returns_exactly_cap_items(
        self,
        data: tuple[list[tuple[str, datetime]], int],
    ) -> None:
        """FOR ANY eligible list with N > C,
        exactly C opportunities are returned in the batch.

        **Validates: Requirements 1.3**
        """
        eligible, cap = data

        batch, remainder = enforce_batch_cap_pure(eligible, cap)

        assert len(batch) == cap, (
            f"Expected exactly {cap} items in batch, got {len(batch)}.\n"
            f"N = {len(eligible)}, C = {cap}"
        )

    @given(data=eligible_over_cap_st())
    @settings(max_examples=200)
    def test_batch_contains_most_recent_by_timestamp(
        self,
        data: tuple[list[tuple[str, datetime]], int],
    ) -> None:
        """FOR ANY eligible list with N > C,
        the batch contains the C most-recent opportunities (by timestamp).

        **Validates: Requirements 1.3**
        """
        eligible, cap = data

        batch, remainder = enforce_batch_cap_pure(eligible, cap)

        # Sort eligible by timestamp descending to determine expected most-recent
        sorted_eligible = sorted(eligible, key=lambda x: x[1], reverse=True)
        expected_most_recent_ids = {item[0] for item in sorted_eligible[:cap]}

        assert set(batch) == expected_most_recent_ids, (
            f"Batch does not contain the {cap} most-recent opportunities.\n"
            f"Expected IDs: {expected_most_recent_ids}\n"
            f"Got IDs: {set(batch)}"
        )

    @given(data=eligible_over_cap_st())
    @settings(max_examples=200)
    def test_remainder_contains_oldest_opportunities(
        self,
        data: tuple[list[tuple[str, datetime]], int],
    ) -> None:
        """FOR ANY eligible list with N > C,
        the remainder contains the N-C oldest opportunities.

        **Validates: Requirements 1.3**
        """
        eligible, cap = data

        batch, remainder = enforce_batch_cap_pure(eligible, cap)

        # Sort eligible by timestamp descending
        sorted_eligible = sorted(eligible, key=lambda x: x[1], reverse=True)
        expected_remainder_ids = {item[0] for item in sorted_eligible[cap:]}

        assert len(remainder) == len(eligible) - cap, (
            f"Expected {len(eligible) - cap} items in remainder, got {len(remainder)}"
        )
        assert set(remainder) == expected_remainder_ids, (
            f"Remainder does not contain the N-C oldest opportunities.\n"
            f"Expected IDs: {expected_remainder_ids}\n"
            f"Got IDs: {set(remainder)}"
        )

    @given(data=eligible_over_cap_st())
    @settings(max_examples=200)
    def test_batch_ordered_most_recent_first(
        self,
        data: tuple[list[tuple[str, datetime]], int],
    ) -> None:
        """FOR ANY eligible list,
        the batch is ordered most-recent first (by timestamp).

        **Validates: Requirements 1.3**
        """
        eligible, cap = data
        batch, _remainder = enforce_batch_cap_pure(eligible, cap)

        if len(batch) <= 1:
            return  # Nothing to check for 0 or 1 items

        # Build ID -> timestamp lookup
        id_to_ts = {item[0]: item[1] for item in eligible}

        # Verify ordering: each item's timestamp >= next item's timestamp
        for i in range(len(batch) - 1):
            ts_current = id_to_ts[batch[i]]
            ts_next = id_to_ts[batch[i + 1]]
            assert ts_current >= ts_next, (
                f"Batch not ordered most-recent first at index {i}.\n"
                f"batch[{i}] timestamp = {ts_current}\n"
                f"batch[{i+1}] timestamp = {ts_next}"
            )

    @given(data=eligible_over_cap_st())
    @settings(max_examples=200)
    def test_batch_and_remainder_are_complete_partition(
        self,
        data: tuple[list[tuple[str, datetime]], int],
    ) -> None:
        """FOR ANY eligible list and cap,
        batch + remainder forms a complete partition of the input IDs
        (no duplicates, no missing).

        **Validates: Requirements 1.3**
        """
        eligible, cap = data
        batch, remainder = enforce_batch_cap_pure(eligible, cap)

        original_ids = {item[0] for item in eligible}
        result_ids = set(batch) | set(remainder)

        # No overlap between batch and remainder
        overlap = set(batch) & set(remainder)
        assert overlap == set(), (
            f"Batch and remainder overlap: {overlap}"
        )

        # Union equals original
        assert result_ids == original_ids, (
            f"Batch + remainder does not equal input.\n"
            f"Missing: {original_ids - result_ids}\n"
            f"Extra: {result_ids - original_ids}"
        )

        # Total count matches
        assert len(batch) + len(remainder) == len(eligible), (
            f"Count mismatch: {len(batch)} + {len(remainder)} != {len(eligible)}"
        )
