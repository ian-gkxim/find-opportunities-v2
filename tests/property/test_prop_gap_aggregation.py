# Feature: capability-gap-analytics, Property 6: Gap aggregation, classification, and single-blocker weighting
"""Property-based tests for gap aggregation, classification, and single-blocker weighting.

Tests that for any collection of extracted capabilities from multiple opportunities:
1. opportunity_count equals the number of distinct opportunity_ids requiring that capability
2. blocked_pipeline_value equals the sum of opportunity values for those distinct opportunity_ids
3. Classification is HARD when capability absent from profile, SOFT when present but junior
4. is_single_blocker is True only for capabilities that were sole unmet required in some opportunity
5. weighted_rank_score = blocked_pipeline_value * 2.0 for single-blockers, else blocked_pipeline_value

**Validates: Requirements 2.2, 2.3**
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.gap_analyzer import (
    CapabilityLevel,
    ExtractedCapability,
    GapAnalysisConfig,
    GapAnalyzer,
    GapClassification,
)

# ─── Strategies ───────────────────────────────────────────────────────────────

_CAP_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

capability_name_st = st.text(
    alphabet=_CAP_ALPHABET,
    min_size=2,
    max_size=15,
)

opportunity_id_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=4,
    max_size=10,
).map(lambda s: f"opp-{s}")

opportunity_value_st = st.floats(
    min_value=1000.0, max_value=500_000.0, allow_nan=False, allow_infinity=False
)


@st.composite
def extracted_capabilities_st(draw) -> list[ExtractedCapability]:
    """Generate a random list of ExtractedCapability objects across multiple opportunities.

    Generates 2-6 distinct capability names and 2-5 distinct opportunity IDs,
    then creates random assignments of capabilities to opportunities.
    All capabilities are REQUIRED level (only required are considered for gap computation).
    """
    num_caps = draw(st.integers(min_value=2, max_value=6))
    num_opps = draw(st.integers(min_value=2, max_value=5))

    cap_names = draw(
        st.lists(capability_name_st, min_size=num_caps, max_size=num_caps, unique=True)
    )
    opp_ids = draw(
        st.lists(opportunity_id_st, min_size=num_opps, max_size=num_opps, unique=True)
    )

    # Generate random assignments: for each opportunity, pick a subset of capabilities
    extracted: list[ExtractedCapability] = []
    for opp_id in opp_ids:
        # Each opportunity requires at least 1 capability
        num_required = draw(st.integers(min_value=1, max_value=len(cap_names)))
        chosen_caps = draw(
            st.lists(
                st.sampled_from(cap_names),
                min_size=num_required,
                max_size=num_required,
                unique=True,
            )
        )
        for cap_name in chosen_caps:
            extracted.append(
                ExtractedCapability(
                    raw_name=cap_name,
                    canonical_name=cap_name,
                    level=CapabilityLevel.REQUIRED,
                    opportunity_id=opp_id,
                )
            )

    assume(len(extracted) >= 2)
    return extracted


@st.composite
def gap_aggregation_scenario_st(draw) -> tuple[
    list[ExtractedCapability],
    set[str],
    dict[str, float],
    dict[str, str],
]:
    """Generate a full scenario for gap aggregation testing.

    Returns:
        Tuple of (extracted_capabilities, profile_capabilities, opportunity_values, profile_levels)

    Ensures there are gaps (some demanded caps not in profile or at junior level).
    """
    extracted = draw(extracted_capabilities_st())

    # Gather all unique canonical names and opportunity IDs
    all_cap_names = list({cap.canonical_name for cap in extracted})
    all_opp_ids = list({cap.opportunity_id for cap in extracted})

    # Create profile: include some capabilities but not all (to ensure gaps exist)
    # At least one capability should be absent (hard gap) and optionally one junior (soft gap)
    num_in_profile = draw(st.integers(min_value=0, max_value=max(0, len(all_cap_names) - 1)))
    profile_caps_list = draw(
        st.lists(
            st.sampled_from(all_cap_names),
            min_size=num_in_profile,
            max_size=num_in_profile,
            unique=True,
        )
    ) if num_in_profile > 0 and len(all_cap_names) > 0 else []

    profile_capabilities = set(profile_caps_list)

    # Assign proficiency levels: some profile caps are junior (soft gap), rest are senior
    profile_levels: dict[str, str] = {}
    for cap in profile_caps_list:
        level = draw(st.sampled_from(["senior", "mid", "junior"]))
        profile_levels[cap] = level

    # Generate opportunity values for all opportunity IDs
    opportunity_values: dict[str, float] = {}
    for opp_id in all_opp_ids:
        opportunity_values[opp_id] = draw(opportunity_value_st)

    # Ensure at least one gap exists
    demanded_names = {cap.canonical_name for cap in extracted}
    has_hard_gap = any(
        name not in profile_capabilities for name in demanded_names
    )
    has_soft_gap = any(
        name in profile_capabilities and profile_levels.get(name) == "junior"
        for name in demanded_names
    )
    assume(has_hard_gap or has_soft_gap)

    return extracted, profile_capabilities, opportunity_values, profile_levels


# ─── Property 6: Gap aggregation, classification, and single-blocker weighting ─


class TestProperty6GapAggregationClassificationAndWeighting:
    """Property 6: Gap aggregation, classification, and single-blocker weighting.

    **Validates: Requirements 2.2, 2.3**

    Key invariants:
    - opportunity_count for each gap equals distinct opportunity_ids requiring that capability
    - blocked_pipeline_value equals sum of opportunity values for those distinct opportunity_ids
    - Classification is HARD when absent from profile, SOFT when present but junior
    - is_single_blocker is True only when capability was sole unmet in some opportunity
    - weighted_rank_score = blocked_pipeline_value * 2.0 for single-blockers, else * 1.0
    """

    def _make_analyzer(self) -> GapAnalyzer:
        """Create a GapAnalyzer instance with default config and no external deps."""
        return GapAnalyzer(
            config=GapAnalysisConfig(),
            llm_router=None,
            schema_registry=None,
            db_session=None,
            redis_client=None,
            ws_manager=None,
        )

    @given(data=gap_aggregation_scenario_st())
    @settings(max_examples=200)
    def test_opportunity_count_equals_distinct_opp_ids(
        self,
        data: tuple[list[ExtractedCapability], set[str], dict[str, float], dict[str, str]],
    ) -> None:
        """FOR ANY set of extracted capabilities, each gap's opportunity_count
        equals the number of distinct opportunity_ids that require that capability.

        **Validates: Requirements 2.2**
        """
        extracted, profile_capabilities, opportunity_values, profile_levels = data
        analyzer = self._make_analyzer()

        gaps = analyzer.compute_gaps(
            extracted, profile_capabilities, opportunity_values, profile_levels
        )

        # Compute expected opportunity_count independently
        from collections import defaultdict

        caps_by_name: dict[str, set[str]] = defaultdict(set)
        for cap in extracted:
            if cap.level == CapabilityLevel.REQUIRED:
                caps_by_name[cap.canonical_name].add(cap.opportunity_id)

        for gap in gaps:
            expected_count = len(caps_by_name[gap.canonical_name])
            assert gap.opportunity_count == expected_count, (
                f"Gap '{gap.canonical_name}' opportunity_count mismatch.\n"
                f"Expected: {expected_count}\n"
                f"Got: {gap.opportunity_count}"
            )

    @given(data=gap_aggregation_scenario_st())
    @settings(max_examples=200)
    def test_blocked_pipeline_value_equals_sum_of_opp_values(
        self,
        data: tuple[list[ExtractedCapability], set[str], dict[str, float], dict[str, str]],
    ) -> None:
        """FOR ANY set of extracted capabilities, each gap's blocked_pipeline_value
        equals the sum of opportunity values for the distinct opportunity_ids
        that require that capability.

        **Validates: Requirements 2.2**
        """
        extracted, profile_capabilities, opportunity_values, profile_levels = data
        analyzer = self._make_analyzer()
        config = GapAnalysisConfig()

        gaps = analyzer.compute_gaps(
            extracted, profile_capabilities, opportunity_values, profile_levels
        )

        # Compute expected blocked_pipeline_value independently
        from collections import defaultdict

        caps_by_name: dict[str, set[str]] = defaultdict(set)
        for cap in extracted:
            if cap.level == CapabilityLevel.REQUIRED:
                caps_by_name[cap.canonical_name].add(cap.opportunity_id)

        for gap in gaps:
            opp_ids = caps_by_name[gap.canonical_name]
            expected_value = sum(
                opportunity_values.get(oid, config.default_opportunity_value)
                for oid in opp_ids
            )
            assert abs(gap.blocked_pipeline_value - expected_value) < 0.01, (
                f"Gap '{gap.canonical_name}' blocked_pipeline_value mismatch.\n"
                f"Expected: {expected_value}\n"
                f"Got: {gap.blocked_pipeline_value}\n"
                f"Opportunity IDs: {opp_ids}"
            )

    @given(data=gap_aggregation_scenario_st())
    @settings(max_examples=200)
    def test_classification_hard_when_absent_soft_when_junior(
        self,
        data: tuple[list[ExtractedCapability], set[str], dict[str, float], dict[str, str]],
    ) -> None:
        """FOR ANY gap, classification is HARD if the capability is absent from the
        profile, and SOFT if the capability is present at junior level.

        **Validates: Requirements 2.2**
        """
        extracted, profile_capabilities, opportunity_values, profile_levels = data
        analyzer = self._make_analyzer()

        gaps = analyzer.compute_gaps(
            extracted, profile_capabilities, opportunity_values, profile_levels
        )

        for gap in gaps:
            if gap.canonical_name not in profile_capabilities:
                assert gap.classification == GapClassification.HARD, (
                    f"Gap '{gap.canonical_name}' should be HARD (absent from profile) "
                    f"but got {gap.classification}"
                )
            elif profile_levels.get(gap.canonical_name) == "junior":
                assert gap.classification == GapClassification.SOFT, (
                    f"Gap '{gap.canonical_name}' should be SOFT (junior level) "
                    f"but got {gap.classification}"
                )

    @given(data=gap_aggregation_scenario_st())
    @settings(max_examples=200)
    def test_single_blocker_detection_and_weighting(
        self,
        data: tuple[list[ExtractedCapability], set[str], dict[str, float], dict[str, str]],
    ) -> None:
        """FOR ANY set of extracted capabilities, after detect_single_blockers
        and apply_single_blocker_weighting:
        - is_single_blocker is True only for capabilities that were sole unmet
          required in at least one opportunity
        - weighted_rank_score = blocked_pipeline_value * 2.0 for single-blockers
        - weighted_rank_score = blocked_pipeline_value for non-single-blockers

        **Validates: Requirements 2.3**
        """
        extracted, profile_capabilities, opportunity_values, profile_levels = data
        analyzer = self._make_analyzer()

        # Step 1: compute gaps
        gaps = analyzer.compute_gaps(
            extracted, profile_capabilities, opportunity_values, profile_levels
        )

        # Step 2: detect single blockers
        single_blockers = analyzer.detect_single_blockers(extracted, profile_capabilities)

        # Step 3: apply weighting
        weighted_gaps = analyzer.apply_single_blocker_weighting(gaps, single_blockers)

        # Independently compute expected single blockers
        from collections import defaultdict

        caps_by_opp: dict[str, set[str]] = defaultdict(set)
        for cap in extracted:
            if cap.level == CapabilityLevel.REQUIRED:
                caps_by_opp[cap.opportunity_id].add(cap.canonical_name)

        expected_single_blockers: set[str] = set()
        for _opp_id, required_names in caps_by_opp.items():
            unmet = required_names - profile_capabilities
            if len(unmet) == 1:
                expected_single_blockers.update(unmet)

        # Verify single_blockers matches expectation
        assert single_blockers == expected_single_blockers, (
            f"Single blockers mismatch.\n"
            f"Expected: {expected_single_blockers}\n"
            f"Got: {single_blockers}"
        )

        # Verify weighting on each gap entry
        for gap in weighted_gaps:
            if gap.canonical_name in expected_single_blockers:
                assert gap.is_single_blocker is True, (
                    f"Gap '{gap.canonical_name}' should be flagged as single-blocker"
                )
                expected_score = gap.blocked_pipeline_value * 2.0
                assert abs(gap.weighted_rank_score - expected_score) < 0.01, (
                    f"Gap '{gap.canonical_name}' weighted_rank_score mismatch.\n"
                    f"Expected: {expected_score} (blocked * 2.0)\n"
                    f"Got: {gap.weighted_rank_score}"
                )
            else:
                assert gap.is_single_blocker is False, (
                    f"Gap '{gap.canonical_name}' should NOT be flagged as single-blocker"
                )
                expected_score = gap.blocked_pipeline_value
                assert abs(gap.weighted_rank_score - expected_score) < 0.01, (
                    f"Gap '{gap.canonical_name}' weighted_rank_score mismatch.\n"
                    f"Expected: {expected_score} (blocked * 1.0)\n"
                    f"Got: {gap.weighted_rank_score}"
                )
