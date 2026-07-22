# Feature: capability-gap-analytics, Property 7: Heatmap ranking sorted and capped
"""Property-based tests for GapAnalyzer.rank_gaps() ranking behavior.

Tests that:
1. Output list is sorted descending by weighted_rank_score.
2. Output length ≤ max_entries.
3. Output length = min(len(input), max_entries).
4. All entries in output were in the original input.
5. No entry with a higher score was left out in favor of a lower-scored entry.

**Validates: Requirements 3.1**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.gap_analyzer import (
    GapAnalyzer,
    GapAnalysisConfig,
    GapEntry,
    GapClassification,
)


# ─── Strategies ───────────────────────────────────────────────────────────────

gap_classification_st = st.sampled_from([GapClassification.HARD, GapClassification.SOFT])

# Strategy for generating a single GapEntry with a random weighted_rank_score
gap_entry_st = st.builds(
    GapEntry,
    canonical_name=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_",
        min_size=1,
        max_size=20,
    ),
    classification=gap_classification_st,
    opportunity_count=st.integers(min_value=1, max_value=50),
    blocked_pipeline_value=st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    is_single_blocker=st.booleans(),
    weighted_rank_score=st.floats(min_value=0.0, max_value=1_000_000.0, allow_nan=False, allow_infinity=False),
    trend=st.none(),
)

# Strategy for a list of GapEntry objects (0–100 entries)
gap_entry_list_st = st.lists(gap_entry_st, min_size=0, max_size=100)

# Strategy for max_entries parameter (1–50)
max_entries_st = st.integers(min_value=1, max_value=50)


# ─── Property 7: Heatmap ranking sorted and capped ───────────────────────────


class TestProperty7HeatmapRankingSortedAndCapped:
    """Property 7: Heatmap ranking sorted and capped.

    **Validates: Requirements 3.1**

    Key invariants:
    - Output is sorted descending by weighted_rank_score.
    - Output length never exceeds max_entries.
    - Output length = min(len(input), max_entries).
    - All output entries exist in the original input.
    - No higher-scored entry was excluded in favor of a lower-scored entry.
    """

    def _make_analyzer(self) -> GapAnalyzer:
        """Create a GapAnalyzer instance with default config for testing."""
        config = GapAnalysisConfig()
        return GapAnalyzer(
            config=config,
            llm_router=None,
            schema_registry=None,
            db_session=None,
            redis_client=None,
            ws_manager=None,
        )

    @given(gaps=gap_entry_list_st, max_entries=max_entries_st)
    @settings(max_examples=200)
    def test_output_sorted_descending_by_weighted_rank_score(
        self,
        gaps: list[GapEntry],
        max_entries: int,
    ) -> None:
        """FOR ANY list of GapEntry objects and max_entries value,
        rank_gaps() output is sorted descending by weighted_rank_score.

        **Validates: Requirements 3.1**
        """
        analyzer = self._make_analyzer()
        result = analyzer.rank_gaps(gaps, max_entries=max_entries)

        for i in range(len(result) - 1):
            assert result[i].weighted_rank_score >= result[i + 1].weighted_rank_score, (
                f"Output not sorted descending at index {i}.\n"
                f"result[{i}].weighted_rank_score = {result[i].weighted_rank_score}\n"
                f"result[{i+1}].weighted_rank_score = {result[i+1].weighted_rank_score}"
            )

    @given(gaps=gap_entry_list_st, max_entries=max_entries_st)
    @settings(max_examples=200)
    def test_output_length_at_most_max_entries(
        self,
        gaps: list[GapEntry],
        max_entries: int,
    ) -> None:
        """FOR ANY list of GapEntry objects and max_entries value,
        rank_gaps() output length ≤ max_entries.

        **Validates: Requirements 3.1**
        """
        analyzer = self._make_analyzer()
        result = analyzer.rank_gaps(gaps, max_entries=max_entries)

        assert len(result) <= max_entries, (
            f"Output length {len(result)} exceeds max_entries {max_entries}.\n"
            f"Input length: {len(gaps)}"
        )

    @given(gaps=gap_entry_list_st, max_entries=max_entries_st)
    @settings(max_examples=200)
    def test_output_length_equals_min_of_input_and_max_entries(
        self,
        gaps: list[GapEntry],
        max_entries: int,
    ) -> None:
        """FOR ANY list of GapEntry objects and max_entries value,
        rank_gaps() output length = min(len(input), max_entries).

        **Validates: Requirements 3.1**
        """
        analyzer = self._make_analyzer()
        result = analyzer.rank_gaps(gaps, max_entries=max_entries)

        expected_length = min(len(gaps), max_entries)
        assert len(result) == expected_length, (
            f"Output length {len(result)} != min({len(gaps)}, {max_entries}) = {expected_length}"
        )

    @given(gaps=gap_entry_list_st, max_entries=max_entries_st)
    @settings(max_examples=200)
    def test_all_output_entries_were_in_input(
        self,
        gaps: list[GapEntry],
        max_entries: int,
    ) -> None:
        """FOR ANY list of GapEntry objects and max_entries value,
        every entry in rank_gaps() output exists in the original input.

        **Validates: Requirements 3.1**
        """
        analyzer = self._make_analyzer()
        result = analyzer.rank_gaps(gaps, max_entries=max_entries)

        for entry in result:
            assert entry in gaps, (
                f"Output entry not found in input.\n"
                f"Entry: {entry}\n"
                f"Input canonical names: {[g.canonical_name for g in gaps]}"
            )

    @given(gaps=gap_entry_list_st, max_entries=max_entries_st)
    @settings(max_examples=200)
    def test_no_higher_scored_entry_excluded_for_lower_scored(
        self,
        gaps: list[GapEntry],
        max_entries: int,
    ) -> None:
        """FOR ANY list of GapEntry objects and max_entries value,
        no entry with a higher weighted_rank_score was left out of the output
        in favor of an entry with a lower score.

        **Validates: Requirements 3.1**
        """
        analyzer = self._make_analyzer()
        result = analyzer.rank_gaps(gaps, max_entries=max_entries)

        if not result:
            return  # Nothing to check for empty output

        # The minimum score in the result
        min_result_score = min(entry.weighted_rank_score for entry in result)

        # Every input entry NOT in the result must have score ≤ min_result_score
        result_set = set(id(entry) for entry in result)
        for entry in gaps:
            if id(entry) not in result_set:
                # This entry was excluded — its score must be ≤ the lowest included score
                # (allowing equality since ties may be broken arbitrarily)
                assert entry.weighted_rank_score <= min_result_score, (
                    f"Higher-scored entry was excluded in favor of lower-scored entry.\n"
                    f"Excluded entry score: {entry.weighted_rank_score}\n"
                    f"Min included score: {min_result_score}\n"
                    f"Excluded entry: {entry.canonical_name}"
                )
