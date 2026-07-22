# Feature: capability-gap-analytics, Property 8: Trend diff classification
"""Property-based tests for GapAnalyzer.compute_trend() trend annotations.

Tests that:
1. If previous_gaps is None → all current gaps have trend=NEW
2. Gaps in current but NOT in previous → trend=NEW
3. Gaps in current AND previous with higher blocked_pipeline_value → trend=GROWING
4. Gaps in current AND previous with lower blocked_pipeline_value → trend=SHRINKING
5. Gaps in current AND previous with same blocked_pipeline_value → trend=None
6. Gaps in previous but NOT in current → appear in result with trend=RESOLVED
7. RESOLVED entries have opportunity_count=0, blocked_pipeline_value=0.0, weighted_rank_score=0.0

**Validates: Requirements 3.2**
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.gap_analyzer import (
    GapAnalyzer,
    GapAnalysisConfig,
    GapEntry,
    GapClassification,
    GapTrend,
)


# ─── Strategies ───────────────────────────────────────────────────────────────

_CAPABILITY_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-_"

canonical_name_st = st.text(
    alphabet=_CAPABILITY_ALPHABET,
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")


@st.composite
def gap_entry_st(draw, name: str | None = None) -> GapEntry:
    """Generate a random GapEntry with optional fixed canonical_name."""
    canonical = name if name is not None else draw(canonical_name_st)
    classification = draw(st.sampled_from(list(GapClassification)))
    opportunity_count = draw(st.integers(min_value=1, max_value=50))
    blocked_pipeline_value = draw(st.floats(min_value=1.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False))
    is_single_blocker = draw(st.booleans())
    weighted_rank_score = draw(st.floats(min_value=1.0, max_value=2_000_000.0, allow_nan=False, allow_infinity=False))
    trend = draw(st.sampled_from([None, GapTrend.NEW, GapTrend.GROWING, GapTrend.SHRINKING]))

    return GapEntry(
        canonical_name=canonical,
        classification=classification,
        opportunity_count=opportunity_count,
        blocked_pipeline_value=blocked_pipeline_value,
        is_single_blocker=is_single_blocker,
        weighted_rank_score=weighted_rank_score,
        trend=trend,
    )


@st.composite
def gap_entry_list_st(draw, min_size: int = 0, max_size: int = 15) -> list[GapEntry]:
    """Generate a list of GapEntry objects with unique canonical_names."""
    num_entries = draw(st.integers(min_value=min_size, max_value=max_size))
    names = draw(
        st.lists(
            canonical_name_st,
            min_size=num_entries,
            max_size=num_entries,
            unique=True,
        )
    )
    entries = []
    for name in names:
        entry = draw(gap_entry_st(name=name))
        entries.append(entry)
    return entries


def _make_analyzer() -> GapAnalyzer:
    """Create a GapAnalyzer instance with default config and no external deps."""
    config = GapAnalysisConfig()
    return GapAnalyzer(
        config=config,
        llm_router=None,
        schema_registry=None,
        db_session=None,
        redis_client=None,
        ws_manager=None,
    )


# ─── Property 8: Trend diff classification ───────────────────────────────────


class TestProperty8TrendDiffClassification:
    """Property 8: Trend diff classification.

    **Validates: Requirements 3.2**

    Key invariants:
    - First report (previous_gaps=None): all gaps annotated NEW
    - Gaps only in current: NEW
    - Gaps in both with higher blocked_pipeline_value: GROWING
    - Gaps in both with lower blocked_pipeline_value: SHRINKING
    - Gaps in both with same blocked_pipeline_value: None (stable)
    - Gaps only in previous: RESOLVED with zeroed metrics
    """

    @given(current_gaps=gap_entry_list_st(min_size=1, max_size=15))
    @settings(max_examples=200)
    def test_no_previous_all_gaps_are_new(
        self,
        current_gaps: list[GapEntry],
    ) -> None:
        """FOR ANY list of current gaps with no previous report,
        all gaps in the result have trend=NEW.

        **Validates: Requirements 3.2**
        """
        analyzer = _make_analyzer()
        result = analyzer.compute_trend(current_gaps, previous_gaps=None)

        assert len(result) == len(current_gaps)
        for entry in result:
            assert entry.trend == GapTrend.NEW, (
                f"Expected trend=NEW for first report, got trend={entry.trend} "
                f"for gap '{entry.canonical_name}'"
            )

    @given(
        current_gaps=gap_entry_list_st(min_size=1, max_size=10),
        previous_gaps=gap_entry_list_st(min_size=1, max_size=10),
    )
    @settings(max_examples=200)
    def test_gaps_only_in_current_are_new(
        self,
        current_gaps: list[GapEntry],
        previous_gaps: list[GapEntry],
    ) -> None:
        """FOR ANY gap that appears in current but NOT in previous,
        its trend is NEW.

        **Validates: Requirements 3.2**
        """
        analyzer = _make_analyzer()
        previous_names = {g.canonical_name for g in previous_gaps}

        result = analyzer.compute_trend(current_gaps, previous_gaps)
        result_lookup = {g.canonical_name: g for g in result}

        for gap in current_gaps:
            if gap.canonical_name not in previous_names:
                assert gap.canonical_name in result_lookup, (
                    f"Gap '{gap.canonical_name}' missing from result"
                )
                assert result_lookup[gap.canonical_name].trend == GapTrend.NEW, (
                    f"Expected trend=NEW for gap '{gap.canonical_name}' "
                    f"(only in current), got {result_lookup[gap.canonical_name].trend}"
                )

    @given(data=st.data())
    @settings(max_examples=200)
    def test_higher_blocked_value_is_growing(self, data: st.DataObject) -> None:
        """FOR ANY gap present in both current and previous where
        current.blocked_pipeline_value > previous.blocked_pipeline_value,
        the trend is GROWING.

        **Validates: Requirements 3.2**
        """
        analyzer = _make_analyzer()

        # Generate a shared name
        shared_name = data.draw(canonical_name_st)

        # Generate previous entry with some value
        prev_value = data.draw(st.floats(min_value=1.0, max_value=500_000.0, allow_nan=False, allow_infinity=False))
        # Current value must be strictly greater
        curr_value = data.draw(st.floats(min_value=prev_value + 0.01, max_value=1_000_000.0, allow_nan=False, allow_infinity=False))
        assume(curr_value > prev_value)

        prev_entry = GapEntry(
            canonical_name=shared_name,
            classification=GapClassification.HARD,
            opportunity_count=3,
            blocked_pipeline_value=prev_value,
            is_single_blocker=False,
            weighted_rank_score=prev_value,
            trend=None,
        )
        curr_entry = GapEntry(
            canonical_name=shared_name,
            classification=GapClassification.HARD,
            opportunity_count=5,
            blocked_pipeline_value=curr_value,
            is_single_blocker=False,
            weighted_rank_score=curr_value,
            trend=None,
        )

        result = analyzer.compute_trend([curr_entry], [prev_entry])
        result_lookup = {g.canonical_name: g for g in result}

        assert shared_name in result_lookup
        assert result_lookup[shared_name].trend == GapTrend.GROWING, (
            f"Expected GROWING for '{shared_name}' "
            f"(prev={prev_value}, curr={curr_value}), "
            f"got {result_lookup[shared_name].trend}"
        )

    @given(data=st.data())
    @settings(max_examples=200)
    def test_lower_blocked_value_is_shrinking(self, data: st.DataObject) -> None:
        """FOR ANY gap present in both current and previous where
        current.blocked_pipeline_value < previous.blocked_pipeline_value,
        the trend is SHRINKING.

        **Validates: Requirements 3.2**
        """
        analyzer = _make_analyzer()

        shared_name = data.draw(canonical_name_st)

        # Generate previous entry with a higher value
        prev_value = data.draw(st.floats(min_value=100.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False))
        # Current value must be strictly less
        curr_value = data.draw(st.floats(min_value=1.0, max_value=prev_value - 0.01, allow_nan=False, allow_infinity=False))
        assume(curr_value < prev_value)

        prev_entry = GapEntry(
            canonical_name=shared_name,
            classification=GapClassification.HARD,
            opportunity_count=5,
            blocked_pipeline_value=prev_value,
            is_single_blocker=True,
            weighted_rank_score=prev_value * 2,
            trend=None,
        )
        curr_entry = GapEntry(
            canonical_name=shared_name,
            classification=GapClassification.HARD,
            opportunity_count=3,
            blocked_pipeline_value=curr_value,
            is_single_blocker=False,
            weighted_rank_score=curr_value,
            trend=None,
        )

        result = analyzer.compute_trend([curr_entry], [prev_entry])
        result_lookup = {g.canonical_name: g for g in result}

        assert shared_name in result_lookup
        assert result_lookup[shared_name].trend == GapTrend.SHRINKING, (
            f"Expected SHRINKING for '{shared_name}' "
            f"(prev={prev_value}, curr={curr_value}), "
            f"got {result_lookup[shared_name].trend}"
        )

    @given(data=st.data())
    @settings(max_examples=200)
    def test_same_blocked_value_is_stable(self, data: st.DataObject) -> None:
        """FOR ANY gap present in both current and previous where
        current.blocked_pipeline_value == previous.blocked_pipeline_value,
        the trend is None (stable, no annotation).

        **Validates: Requirements 3.2**
        """
        analyzer = _make_analyzer()

        shared_name = data.draw(canonical_name_st)
        shared_value = data.draw(st.floats(min_value=1.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False))

        prev_entry = GapEntry(
            canonical_name=shared_name,
            classification=GapClassification.SOFT,
            opportunity_count=4,
            blocked_pipeline_value=shared_value,
            is_single_blocker=False,
            weighted_rank_score=shared_value,
            trend=None,
        )
        curr_entry = GapEntry(
            canonical_name=shared_name,
            classification=GapClassification.HARD,
            opportunity_count=6,
            blocked_pipeline_value=shared_value,
            is_single_blocker=True,
            weighted_rank_score=shared_value * 2,
            trend=None,
        )

        result = analyzer.compute_trend([curr_entry], [prev_entry])
        result_lookup = {g.canonical_name: g for g in result}

        assert shared_name in result_lookup
        assert result_lookup[shared_name].trend is None, (
            f"Expected trend=None (stable) for '{shared_name}' "
            f"(same value={shared_value}), "
            f"got {result_lookup[shared_name].trend}"
        )

    @given(
        current_gaps=gap_entry_list_st(min_size=0, max_size=10),
        previous_gaps=gap_entry_list_st(min_size=1, max_size=10),
    )
    @settings(max_examples=200)
    def test_gaps_only_in_previous_are_resolved(
        self,
        current_gaps: list[GapEntry],
        previous_gaps: list[GapEntry],
    ) -> None:
        """FOR ANY gap that was in previous but NOT in current,
        it appears in the result with trend=RESOLVED.

        **Validates: Requirements 3.2**
        """
        analyzer = _make_analyzer()
        current_names = {g.canonical_name for g in current_gaps}

        result = analyzer.compute_trend(current_gaps, previous_gaps)
        result_lookup = {g.canonical_name: g for g in result}

        for prev_gap in previous_gaps:
            if prev_gap.canonical_name not in current_names:
                assert prev_gap.canonical_name in result_lookup, (
                    f"Previous gap '{prev_gap.canonical_name}' missing from result "
                    f"(should appear as RESOLVED)"
                )
                resolved_entry = result_lookup[prev_gap.canonical_name]
                assert resolved_entry.trend == GapTrend.RESOLVED, (
                    f"Expected trend=RESOLVED for '{prev_gap.canonical_name}' "
                    f"(only in previous), got {resolved_entry.trend}"
                )

    @given(
        current_gaps=gap_entry_list_st(min_size=0, max_size=10),
        previous_gaps=gap_entry_list_st(min_size=1, max_size=10),
    )
    @settings(max_examples=200)
    def test_resolved_entries_have_zeroed_metrics(
        self,
        current_gaps: list[GapEntry],
        previous_gaps: list[GapEntry],
    ) -> None:
        """FOR ANY RESOLVED entry, it must have
        opportunity_count=0, blocked_pipeline_value=0.0, weighted_rank_score=0.0.

        **Validates: Requirements 3.2**
        """
        analyzer = _make_analyzer()
        current_names = {g.canonical_name for g in current_gaps}

        result = analyzer.compute_trend(current_gaps, previous_gaps)

        for entry in result:
            if entry.trend == GapTrend.RESOLVED:
                assert entry.opportunity_count == 0, (
                    f"RESOLVED entry '{entry.canonical_name}' has "
                    f"opportunity_count={entry.opportunity_count}, expected 0"
                )
                assert entry.blocked_pipeline_value == 0.0, (
                    f"RESOLVED entry '{entry.canonical_name}' has "
                    f"blocked_pipeline_value={entry.blocked_pipeline_value}, expected 0.0"
                )
                assert entry.weighted_rank_score == 0.0, (
                    f"RESOLVED entry '{entry.canonical_name}' has "
                    f"weighted_rank_score={entry.weighted_rank_score}, expected 0.0"
                )
