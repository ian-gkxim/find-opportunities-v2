# Feature: internal-profile-enrichment, Property 2: Scan Scheduling Correctness
"""Property-based tests for scan scheduling correctness.

Tests the is_source_due function which determines whether a source needs
scanning based on its schedule. A source is due if:
- last_scanned_at is None (never scanned), OR
- current_time - last_scanned_at >= scan_interval_days

**Validates: Requirements 1.2**
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hypothesis import given, settings
from hypothesis import strategies as st

from app.workers.profile_enrichment_worker import is_source_due


# ─── Strategies ───────────────────────────────────────────────────────────────

# Scan interval in days: 1 to 365 as per the DB CHECK constraint
interval_days_st = st.integers(min_value=1, max_value=365)

# Datetime strategy: aware datetimes in a reasonable range
aware_datetimes_st = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.just(timezone.utc),
)


# ─── Property 2: Scan Scheduling Correctness ─────────────────────────────────


class TestProperty2ScanSchedulingCorrectness:
    """Property 2: Scan Scheduling Correctness.

    **Validates: Requirements 1.2**

    Key invariants:
    - If last_scanned_at is None, the source is always due (never scanned)
    - If now - last_scanned_at >= timedelta(days=scan_interval_days), source is due
    - If now - last_scanned_at < timedelta(days=scan_interval_days), source is NOT due
    """

    @given(
        scan_interval_days=interval_days_st,
        now=aware_datetimes_st,
    )
    @settings(max_examples=200)
    def test_never_scanned_source_is_always_due(
        self,
        scan_interval_days: int,
        now: datetime,
    ) -> None:
        """FOR ANY scan_interval_days and current time, a source with
        last_scanned_at=None is always due for scanning (never scanned).

        **Validates: Requirements 1.2**
        """
        result = is_source_due(
            last_scanned_at=None,
            scan_interval_days=scan_interval_days,
            now=now,
        )
        assert result is True, (
            f"Source with last_scanned_at=None should always be due, "
            f"but got False for interval={scan_interval_days}, now={now}"
        )

    @given(
        now=aware_datetimes_st,
        scan_interval_days=interval_days_st,
        extra_seconds=st.integers(min_value=0, max_value=365 * 24 * 3600),
    )
    @settings(max_examples=200)
    def test_source_due_when_elapsed_ge_interval(
        self,
        now: datetime,
        scan_interval_days: int,
        extra_seconds: int,
    ) -> None:
        """FOR ANY (now, last_scanned_at, scan_interval_days) where
        now - last_scanned_at >= timedelta(days=scan_interval_days),
        is_source_due returns True.

        **Validates: Requirements 1.2**
        """
        # Construct last_scanned_at such that elapsed >= interval
        interval = timedelta(days=scan_interval_days)
        elapsed = interval + timedelta(seconds=extra_seconds)
        last_scanned_at = now - elapsed

        result = is_source_due(
            last_scanned_at=last_scanned_at,
            scan_interval_days=scan_interval_days,
            now=now,
        )
        assert result is True, (
            f"Source should be due: elapsed={elapsed} >= interval={interval}, "
            f"but got False. now={now}, last_scanned_at={last_scanned_at}, "
            f"scan_interval_days={scan_interval_days}"
        )

    @given(
        now=aware_datetimes_st,
        scan_interval_days=interval_days_st,
        seconds_short=st.integers(min_value=1, max_value=365 * 24 * 3600),
    )
    @settings(max_examples=200)
    def test_source_not_due_when_elapsed_lt_interval(
        self,
        now: datetime,
        scan_interval_days: int,
        seconds_short: int,
    ) -> None:
        """FOR ANY (now, last_scanned_at, scan_interval_days) where
        now - last_scanned_at < timedelta(days=scan_interval_days),
        is_source_due returns False.

        **Validates: Requirements 1.2**
        """
        # Construct last_scanned_at such that elapsed < interval
        interval = timedelta(days=scan_interval_days)
        # Ensure we don't go below 0 elapsed time: pick seconds_short < interval total seconds
        interval_total_seconds = int(interval.total_seconds())
        # Clamp seconds_short to be at most interval_total_seconds - 1 so elapsed is positive but < interval
        actual_short = (seconds_short % interval_total_seconds) if interval_total_seconds > 1 else 0
        if actual_short == 0:
            actual_short = 1

        elapsed = interval - timedelta(seconds=actual_short)
        last_scanned_at = now - elapsed

        result = is_source_due(
            last_scanned_at=last_scanned_at,
            scan_interval_days=scan_interval_days,
            now=now,
        )
        assert result is False, (
            f"Source should NOT be due: elapsed={elapsed} < interval={interval}, "
            f"but got True. now={now}, last_scanned_at={last_scanned_at}, "
            f"scan_interval_days={scan_interval_days}"
        )

    @given(
        now=aware_datetimes_st,
        scan_interval_days=interval_days_st,
    )
    @settings(max_examples=200)
    def test_source_due_at_exact_boundary(
        self,
        now: datetime,
        scan_interval_days: int,
    ) -> None:
        """FOR ANY (now, scan_interval_days), when elapsed is exactly equal to
        the interval (now - last_scanned_at == timedelta(days=scan_interval_days)),
        is_source_due returns True.

        **Validates: Requirements 1.2**
        """
        # Construct last_scanned_at at exactly the boundary
        interval = timedelta(days=scan_interval_days)
        last_scanned_at = now - interval

        result = is_source_due(
            last_scanned_at=last_scanned_at,
            scan_interval_days=scan_interval_days,
            now=now,
        )
        assert result is True, (
            f"Source should be due at exact boundary: "
            f"elapsed={interval} == interval={interval}, but got False. "
            f"now={now}, last_scanned_at={last_scanned_at}"
        )
