# Feature: capability-gap-analytics, Property 5: Gap computation as set difference
"""Property-based tests for GapAnalyzer.compute_gaps() set-difference semantics.

Tests that the set of gap canonical_names returned by compute_gaps() equals the
set difference: {demanded canonical names} - {profile capabilities}, when no
profile levels are involved (simplest case: profile has no levels, so gaps are
purely absent capabilities).

**Validates: Requirements 2.1**
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.gap_analyzer import (
    CapabilityLevel,
    ExtractedCapability,
    GapAnalysisConfig,
    GapAnalyzer,
)


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for canonical capability names (lowercase ASCII identifiers)
_CAPABILITY_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-_"

canonical_name_st = st.text(
    alphabet=_CAPABILITY_ALPHABET,
    min_size=2,
    max_size=15,
).filter(lambda s: s.strip() != "")

# Strategy for opportunity IDs (simple uuid-like strings)
opportunity_id_st = st.uuids().map(str)

# Strategy for opportunity values (positive floats)
opportunity_value_st = st.floats(min_value=1000.0, max_value=500000.0, allow_nan=False, allow_infinity=False)


@st.composite
def demanded_capabilities_st(draw) -> list[ExtractedCapability]:
    """Generate a random list of demanded capabilities (all REQUIRED level).

    Generates 1-10 unique canonical names, each appearing in 1-3 opportunities.
    """
    num_capabilities = draw(st.integers(min_value=1, max_value=10))
    canonical_names = draw(
        st.lists(
            canonical_name_st,
            min_size=num_capabilities,
            max_size=num_capabilities,
            unique=True,
        )
    )

    capabilities: list[ExtractedCapability] = []
    for canonical_name in canonical_names:
        num_opps = draw(st.integers(min_value=1, max_value=3))
        for _ in range(num_opps):
            opp_id = draw(opportunity_id_st)
            capabilities.append(
                ExtractedCapability(
                    raw_name=canonical_name,  # raw_name = canonical for simplicity
                    canonical_name=canonical_name,
                    level=CapabilityLevel.REQUIRED,
                    opportunity_id=opp_id,
                )
            )

    assume(len(capabilities) >= 1)
    return capabilities


@st.composite
def gap_computation_inputs_st(draw) -> tuple[list[ExtractedCapability], set[str], dict[str, float]]:
    """Generate full inputs for compute_gaps():
    - demanded capabilities (REQUIRED level)
    - profile capabilities (subset or superset or disjoint from demanded)
    - opportunity values map

    The profile set is drawn as a random subset of all possible names
    (demanded names + some extra), ensuring realistic scenarios.
    """
    demanded = draw(demanded_capabilities_st())

    # Collect all demanded canonical names
    demanded_names = {cap.canonical_name for cap in demanded}

    # Generate profile capabilities: random subset of demanded + some extras
    extra_names = draw(
        st.lists(canonical_name_st, min_size=0, max_size=5, unique=True)
    )
    all_possible_profile_names = list(demanded_names | set(extra_names))

    # Profile is a random subset of all possible names
    profile_capabilities = set(
        draw(
            st.lists(
                st.sampled_from(all_possible_profile_names),
                min_size=0,
                max_size=len(all_possible_profile_names),
                unique=True,
            )
        )
    )

    # Build opportunity_values map for all opportunity IDs
    opp_ids = {cap.opportunity_id for cap in demanded}
    opportunity_values: dict[str, float] = {}
    for opp_id in opp_ids:
        opportunity_values[opp_id] = draw(opportunity_value_st)

    return demanded, profile_capabilities, opportunity_values


# ─── Property 5: Gap computation as set difference ────────────────────────────


class TestProperty5GapComputationAsSetDifference:
    """Property 5: Gap computation as set difference.

    **Validates: Requirements 2.1**

    Key invariant: The set of gap canonical_names returned by compute_gaps()
    equals {demanded canonical names} - {profile capabilities} when no
    profile levels are involved.
    """

    @given(inputs=gap_computation_inputs_st())
    @settings(max_examples=200)
    def test_gaps_equal_set_difference_no_levels(
        self,
        inputs: tuple[list[ExtractedCapability], set[str], dict[str, float]],
    ) -> None:
        """FOR ANY demanded capability set and profile set (no levels),
        the gap canonical_names == demanded_names - profile_names.

        **Validates: Requirements 2.1**
        """
        demanded, profile_capabilities, opportunity_values = inputs

        config = GapAnalysisConfig()
        analyzer = GapAnalyzer(
            config=config,
            db_session=None,
            redis_client=None,
            ws_manager=None,
            llm_router=None,
            schema_registry=None,
        )

        gaps = analyzer.compute_gaps(
            demanded_capabilities=demanded,
            profile_capabilities=profile_capabilities,
            opportunity_values=opportunity_values,
        )

        # Compute expected set difference
        demanded_names = {cap.canonical_name for cap in demanded}
        expected_gap_names = demanded_names - profile_capabilities

        # Actual gap names from the result
        actual_gap_names = {gap.canonical_name for gap in gaps}

        assert actual_gap_names == expected_gap_names, (
            f"Gap names do not match set difference.\n"
            f"Demanded names: {demanded_names}\n"
            f"Profile capabilities: {profile_capabilities}\n"
            f"Expected gaps (demanded - profile): {expected_gap_names}\n"
            f"Actual gaps: {actual_gap_names}"
        )

    @given(inputs=gap_computation_inputs_st())
    @settings(max_examples=200)
    def test_no_gap_appears_for_profile_capability(
        self,
        inputs: tuple[list[ExtractedCapability], set[str], dict[str, float]],
    ) -> None:
        """FOR ANY inputs, no gap entry should have a canonical_name that
        exists in the profile capabilities (when no profile levels).

        **Validates: Requirements 2.1**
        """
        demanded, profile_capabilities, opportunity_values = inputs

        config = GapAnalysisConfig()
        analyzer = GapAnalyzer(
            config=config,
            db_session=None,
            redis_client=None,
            ws_manager=None,
            llm_router=None,
            schema_registry=None,
        )

        gaps = analyzer.compute_gaps(
            demanded_capabilities=demanded,
            profile_capabilities=profile_capabilities,
            opportunity_values=opportunity_values,
        )

        for gap in gaps:
            assert gap.canonical_name not in profile_capabilities, (
                f"Gap '{gap.canonical_name}' should not appear because it "
                f"exists in profile_capabilities: {profile_capabilities}"
            )

    @given(inputs=gap_computation_inputs_st())
    @settings(max_examples=200)
    def test_every_demanded_name_not_in_profile_is_a_gap(
        self,
        inputs: tuple[list[ExtractedCapability], set[str], dict[str, float]],
    ) -> None:
        """FOR ANY inputs, every demanded capability not in the profile
        must appear in the gap results.

        **Validates: Requirements 2.1**
        """
        demanded, profile_capabilities, opportunity_values = inputs

        config = GapAnalysisConfig()
        analyzer = GapAnalyzer(
            config=config,
            db_session=None,
            redis_client=None,
            ws_manager=None,
            llm_router=None,
            schema_registry=None,
        )

        gaps = analyzer.compute_gaps(
            demanded_capabilities=demanded,
            profile_capabilities=profile_capabilities,
            opportunity_values=opportunity_values,
        )

        demanded_names = {cap.canonical_name for cap in demanded}
        actual_gap_names = {gap.canonical_name for gap in gaps}

        for name in demanded_names:
            if name not in profile_capabilities:
                assert name in actual_gap_names, (
                    f"Demanded capability '{name}' is NOT in profile but "
                    f"does NOT appear in gaps.\n"
                    f"Profile: {profile_capabilities}\n"
                    f"Gaps: {actual_gap_names}"
                )
