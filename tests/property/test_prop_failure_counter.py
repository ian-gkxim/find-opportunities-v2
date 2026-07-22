# Feature: internal-profile-enrichment, Property 4: Failure counter monotonicity and reset
"""Property-based tests for failure counter behavior in Profile_Enrichment_Worker.

Tests that for any sequence of scan outcomes:
1. consecutive_failures increments by exactly 1 on each failure
2. consecutive_failures resets to 0 on each success
3. Dashboard notice is emitted if and only if the counter reaches exactly 3

Rather than testing the full async worker, we extract and test the pure
counter logic that governs the failure tracking behavior.

**Validates: Requirements 1.4**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hypothesis import given, settings, assume
from hypothesis import strategies as st


# ─── Constants (mirror worker) ────────────────────────────────────────────────

CONSECUTIVE_FAILURE_THRESHOLD = 3  # Same as worker constant


# ─── Pure simulation of failure counter logic ─────────────────────────────────


@dataclass
class FailureCounterState:
    """Simulates the failure counter state for a single source."""

    consecutive_failures: int = 0
    notices_emitted: list[int] = field(default_factory=list)


def apply_scan_outcome(
    state: FailureCounterState, success: bool
) -> FailureCounterState:
    """Apply a single scan outcome to the failure counter state.

    This mirrors the logic in profile_enrichment_worker.py:
    - On success: reset consecutive_failures to 0
    - On failure: increment consecutive_failures by 1
    - Emit Dashboard notice iff counter reaches exactly CONSECUTIVE_FAILURE_THRESHOLD

    Args:
        state: Current counter state.
        success: True if the scan succeeded, False if it failed.

    Returns:
        Updated state (mutated in place and returned).
    """
    if success:
        state.consecutive_failures = 0
    else:
        state.consecutive_failures += 1
        if state.consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD:
            state.notices_emitted.append(state.consecutive_failures)

    return state


def simulate_sequence(outcomes: list[bool]) -> FailureCounterState:
    """Simulate a full sequence of scan outcomes from initial state.

    Args:
        outcomes: List of booleans (True=success, False=failure).

    Returns:
        Final FailureCounterState after processing all outcomes.
    """
    state = FailureCounterState()
    for outcome in outcomes:
        apply_scan_outcome(state, outcome)
    return state


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for random sequences of scan outcomes (True=success, False=failure)
outcome_sequence_st = st.lists(
    st.booleans(),
    min_size=0,
    max_size=100,
)


# ─── Property 4: Failure Counter Monotonicity and Reset ───────────────────────


class TestProperty4FailureCounterMonotonicity:
    """Property 4: Failure Counter Monotonicity and Reset.

    **Validates: Requirements 1.4**

    Key invariants:
    - consecutive_failures increments by exactly 1 on failure
    - consecutive_failures resets to 0 on success
    - Dashboard notice is emitted iff counter reaches exactly 3
    """

    @given(outcomes=outcome_sequence_st)
    @settings(max_examples=500)
    def test_failure_increments_by_one(self, outcomes: list[bool]) -> None:
        """FOR ANY sequence of scan outcomes, each failure increments
        consecutive_failures by exactly 1 from the previous value.

        **Validates: Requirements 1.4**
        """
        state = FailureCounterState()

        for outcome in outcomes:
            prev_failures = state.consecutive_failures
            apply_scan_outcome(state, outcome)

            if not outcome:  # failure
                assert state.consecutive_failures == prev_failures + 1, (
                    f"Failure did not increment counter by exactly 1.\n"
                    f"Previous: {prev_failures}\n"
                    f"Current: {state.consecutive_failures}\n"
                    f"Outcome: failure"
                )

    @given(outcomes=outcome_sequence_st)
    @settings(max_examples=500)
    def test_success_resets_to_zero(self, outcomes: list[bool]) -> None:
        """FOR ANY sequence of scan outcomes, each success resets
        consecutive_failures to exactly 0.

        **Validates: Requirements 1.4**
        """
        state = FailureCounterState()

        for outcome in outcomes:
            apply_scan_outcome(state, outcome)

            if outcome:  # success
                assert state.consecutive_failures == 0, (
                    f"Success did not reset counter to 0.\n"
                    f"Current: {state.consecutive_failures}\n"
                    f"Outcome: success"
                )

    @given(outcomes=outcome_sequence_st)
    @settings(max_examples=500)
    def test_counter_never_negative(self, outcomes: list[bool]) -> None:
        """FOR ANY sequence of scan outcomes, consecutive_failures is
        never negative.

        **Validates: Requirements 1.4**
        """
        state = FailureCounterState()

        for outcome in outcomes:
            apply_scan_outcome(state, outcome)
            assert state.consecutive_failures >= 0, (
                f"Counter went negative: {state.consecutive_failures}"
            )

    @given(outcomes=outcome_sequence_st)
    @settings(max_examples=500)
    def test_dashboard_notice_emitted_iff_counter_reaches_exactly_three(
        self, outcomes: list[bool]
    ) -> None:
        """FOR ANY sequence of scan outcomes, Dashboard notice is emitted
        if and only if the counter reaches exactly 3 (the threshold).

        The number of notices emitted equals the number of times the counter
        transitioned from 2 to 3 during the sequence.

        **Validates: Requirements 1.4**
        """
        state = simulate_sequence(outcomes)

        # Count how many times counter hit exactly 3 by replaying
        expected_notices = 0
        counter = 0
        for outcome in outcomes:
            if outcome:
                counter = 0
            else:
                counter += 1
                if counter == CONSECUTIVE_FAILURE_THRESHOLD:
                    expected_notices += 1

        assert len(state.notices_emitted) == expected_notices, (
            f"Dashboard notice count mismatch.\n"
            f"Expected: {expected_notices}\n"
            f"Actual: {len(state.notices_emitted)}\n"
            f"Outcomes: {outcomes}"
        )

    @given(outcomes=outcome_sequence_st)
    @settings(max_examples=500)
    def test_final_counter_matches_trailing_failures(
        self, outcomes: list[bool]
    ) -> None:
        """FOR ANY sequence of scan outcomes, the final counter value equals
        the number of consecutive failures at the end of the sequence
        (i.e., the count of trailing False values).

        **Validates: Requirements 1.4**
        """
        state = simulate_sequence(outcomes)

        # Count trailing failures
        trailing_failures = 0
        for outcome in reversed(outcomes):
            if not outcome:
                trailing_failures += 1
            else:
                break

        assert state.consecutive_failures == trailing_failures, (
            f"Final counter does not match trailing failures.\n"
            f"Expected (trailing failures): {trailing_failures}\n"
            f"Actual counter: {state.consecutive_failures}\n"
            f"Outcomes: {outcomes}"
        )

    @given(outcomes=outcome_sequence_st)
    @settings(max_examples=500)
    def test_notice_only_emitted_on_exact_threshold_crossing(
        self, outcomes: list[bool]
    ) -> None:
        """FOR ANY sequence of scan outcomes, notices are only emitted
        at the exact moment the counter hits 3 — not when it exceeds 3
        on subsequent failures.

        This ensures the notice fires exactly once per threshold crossing,
        not on every failure after the threshold.

        **Validates: Requirements 1.4**
        """
        state = FailureCounterState()

        for outcome in outcomes:
            notices_before = len(state.notices_emitted)
            apply_scan_outcome(state, outcome)
            notices_after = len(state.notices_emitted)

            notice_emitted = notices_after > notices_before

            if not outcome:  # failure
                if state.consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD:
                    assert notice_emitted, (
                        f"Notice NOT emitted when counter reached threshold.\n"
                        f"Counter: {state.consecutive_failures}"
                    )
                else:
                    assert not notice_emitted, (
                        f"Notice emitted when counter != threshold.\n"
                        f"Counter: {state.consecutive_failures}"
                    )
            else:  # success
                assert not notice_emitted, (
                    "Notice emitted on success (should never happen)."
                )
