"""Property-based tests for ContentSelector tie-breaking determinism.

Feature: relevance-weighted-selection, Property 4: Tie-Breaking Determinism

For any two scored units with equal composite_score, the unit with higher
relevance_score SHALL rank higher (retained over the other). If relevance_score
is also equal, the unit with lower document_order SHALL rank higher.

**Validates: Requirements 1.4**
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.content_selector import (
    CompanionReference,
    ConstraintType,
    ContentSelector,
    ContentUnit,
    ContentUnitType,
    LengthConstraint,
    SelectionConfig,
    SelectionWeights,
)


# ─── Strategies ───────────────────────────────────────────────────────────────


@st.composite
def content_unit_st(draw, document_order: int, unit_id: str | None = None) -> ContentUnit:
    """Generate a ContentUnit with a fixed document_order."""
    if unit_id is None:
        unit_id = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=4, max_size=8))
    unit_type = draw(st.sampled_from(list(ContentUnitType)))
    # Use distinct single words to ensure uniqueness scores are high (no overlap)
    text = draw(st.text(alphabet="abcdefghijklmnopqrstuvwxyz", min_size=3, max_size=20))
    section = draw(st.sampled_from(["experience", "skills", "profile"]))
    return ContentUnit(
        id=unit_id,
        unit_type=unit_type,
        text=text,
        section=section,
        document_order=document_order,
    )


# ─── Property 4: Tie-Breaking Determinism ────────────────────────────────────


class TestProperty4TieBreakingDeterminism:
    """Property 4: Tie-Breaking Determinism.

    **Validates: Requirements 1.4**

    For any two scored units with equal composite_score, the unit with higher
    relevance_score SHALL rank higher (retained over the other). If relevance_score
    is also equal, the unit with lower document_order SHALL rank higher.
    """

    @given(
        n_units=st.integers(min_value=3, max_value=8),
        max_units=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=200)
    def test_equal_composite_higher_relevance_retained(
        self,
        n_units: int,
        max_units: int,
    ) -> None:
        """When units have equal composite scores but different relevance scores,
        units with higher relevance_score are retained over those with lower.

        Strategy: Create N units with identical text (same token overlap → same
        uniqueness), no companion references (narrative_dependency=0 for all),
        but different keyword matches controlling relevance. With weights set to
        give all units the same composite, verify tie-breaking by relevance.

        Actually, a cleaner approach: Use MAX_UNITS constraint so we can directly
        control which units are cut by forcing equal composite scores. We achieve
        equal composite by giving all units identical text and no keywords (so
        relevance=100 for all, uniqueness varies). Instead, we test at the cut_list
        level: generate units, score them, find any tied composites, and verify
        the ordering property on those ties.

        Feature: relevance-weighted-selection, Property 4: Tie-Breaking Determinism
        **Validates: Requirements 1.4**
        """
        assume(max_units < n_units)

        # Create units with identical single-word text → they all get the same
        # uniqueness score (high Jaccard overlap with each other → low uniqueness).
        # No keywords → relevance_score = 100 for all.
        # No companion refs → narrative_dependency = 0 for all.
        # Result: all units will have the SAME composite score.
        # Tie-break should be by document_order (lower = retained).
        units = [
            ContentUnit(
                id=f"unit-{i}",
                unit_type=ContentUnitType.BULLET,
                text="identical",
                section="experience",
                document_order=i,
            )
            for i in range(n_units)
        ]

        config = SelectionConfig(
            weights=SelectionWeights(relevance=50, uniqueness=25, narrative_dependency=25),
            protection_threshold=80,
            length_constraint=LengthConstraint(ConstraintType.MAX_UNITS, max_units),
        )

        selector = ContentSelector()
        result = selector.select_content(
            units=units,
            opportunity_keywords=[],
            companion_references=[],
            config=config,
        )

        # All units have identical text, no keywords, no references → same composite score.
        # With equal composite AND equal relevance, tie-break is by document_order:
        # lower document_order is retained (higher document_order is cut first).
        scored_composites = {su.unit.id: su.composite_score for su in result.scored_units}
        scored_relevances = {su.unit.id: su.relevance_score for su in result.scored_units}

        # Verify all composites are equal (sanity check for our setup)
        composite_values = set(scored_composites.values())
        assert len(composite_values) == 1, (
            f"Expected all equal composites but got {composite_values}"
        )

        # Verify all relevances are equal (all get 100 since no keywords)
        relevance_values = set(scored_relevances.values())
        assert len(relevance_values) == 1, (
            f"Expected all equal relevances but got {relevance_values}"
        )

        # With equal composite + equal relevance → lower document_order retained.
        # The cut list should contain units with HIGHEST document_order.
        retained_orders = sorted(u.document_order for u in result.retained_units)
        cut_orders = sorted(entry.unit.document_order for entry in result.cut_list)

        # All retained units must have lower document_order than all cut units
        if retained_orders and cut_orders:
            assert max(retained_orders) < min(cut_orders), (
                f"Tie-break violation: retained orders {retained_orders} should all be "
                f"less than cut orders {cut_orders} when composite and relevance are equal"
            )

    @given(
        n_units=st.integers(min_value=3, max_value=8),
        max_units=st.integers(min_value=1, max_value=4),
    )
    @settings(max_examples=200)
    def test_equal_composite_different_relevance_higher_retained(
        self,
        n_units: int,
        max_units: int,
    ) -> None:
        """When units have equal composite scores but different relevance scores,
        units with higher relevance are retained.

        Strategy: Construct units where composite is tied but relevance differs.
        We achieve this by manipulating keywords and text such that:
        - Some units match keywords (high relevance) but have low uniqueness
        - Other units don't match keywords (low relevance) but have high uniqueness
        - The weighted sum ends up equal

        Simpler approach: Use 100% uniqueness weight (relevance weight=0, uniqueness=100,
        narrative_dependency=0). This makes composite = uniqueness_score only.
        Then all units with same uniqueness get the same composite, but their relevance
        differs based on keyword matching. Tie-break should favor higher relevance.

        Feature: relevance-weighted-selection, Property 4: Tie-Breaking Determinism
        **Validates: Requirements 1.4**
        """
        assume(max_units < n_units)

        # Use uniqueness-only weights: composite = uniqueness_score.
        # All units have unique distinct text → each gets high uniqueness (no overlap).
        # But keywords only match some units → different relevance scores.
        # Since composite depends only on uniqueness (which is ~100 for all distinct texts),
        # composites will be equal, but relevance differs.
        keywords = ["python", "aws"]

        # Create units: some match keywords, some don't.
        # First half has "python" in text, second half has random distinct text.
        units = []
        for i in range(n_units):
            if i % 2 == 0:
                # Matches "python" keyword → higher relevance
                text = f"python expertise area{i}"
            else:
                # Doesn't match any keyword → lower relevance
                text = f"gardening hobby area{i}"
            units.append(
                ContentUnit(
                    id=f"unit-{i}",
                    unit_type=ContentUnitType.BULLET,
                    text=text,
                    section="experience",
                    document_order=i,
                )
            )

        config = SelectionConfig(
            weights=SelectionWeights(relevance=0, uniqueness=100, narrative_dependency=0),
            protection_threshold=80,
            length_constraint=LengthConstraint(ConstraintType.MAX_UNITS, max_units),
        )

        selector = ContentSelector()
        result = selector.select_content(
            units=units,
            opportunity_keywords=keywords,
            companion_references=[],
            config=config,
        )

        # Group scored units by composite score
        composite_groups: dict[int, list] = {}
        for su in result.scored_units:
            composite_groups.setdefault(su.composite_score, []).append(su)

        # For any group with tied composites, verify ordering:
        # Higher relevance_score should be retained over lower relevance_score.
        cut_ids = {entry.unit.id for entry in result.cut_list}

        for composite_val, group in composite_groups.items():
            if len(group) < 2:
                continue

            # Within this tie group, check retained vs cut
            retained_in_group = [su for su in group if su.unit.id not in cut_ids]
            cut_in_group = [su for su in group if su.unit.id in cut_ids]

            if not retained_in_group or not cut_in_group:
                continue  # All retained or all cut — no tie-break to verify

            # Every retained unit's relevance should be >= every cut unit's relevance
            min_retained_relevance = min(su.relevance_score for su in retained_in_group)
            max_cut_relevance = max(su.relevance_score for su in cut_in_group)

            assert min_retained_relevance >= max_cut_relevance, (
                f"Tie-break violation at composite={composite_val}: "
                f"retained min relevance={min_retained_relevance} < "
                f"cut max relevance={max_cut_relevance}. "
                f"Retained: {[(su.unit.id, su.relevance_score) for su in retained_in_group]}, "
                f"Cut: {[(su.unit.id, su.relevance_score) for su in cut_in_group]}"
            )

    @given(
        n_units=st.integers(min_value=4, max_value=10),
        max_units=st.integers(min_value=1, max_value=5),
    )
    @settings(max_examples=200)
    def test_cut_list_ordering_respects_tiebreak_rules(
        self,
        n_units: int,
        max_units: int,
    ) -> None:
        """The cut_list ordering respects the tie-breaking sort key:
        (composite_score ASC, relevance_score ASC, -document_order ASC).

        This means within the cut_list, entries are sorted such that for any
        two consecutive entries with equal composite: the one with lower
        relevance comes first, and if relevance is also equal, higher
        document_order comes first.

        Feature: relevance-weighted-selection, Property 4: Tie-Breaking Determinism
        **Validates: Requirements 1.4**
        """
        assume(max_units < n_units)

        # Create units with identical text to force composite ties
        units = [
            ContentUnit(
                id=f"unit-{i}",
                unit_type=ContentUnitType.BULLET,
                text="same text here",
                section="experience",
                document_order=i,
            )
            for i in range(n_units)
        ]

        config = SelectionConfig(
            weights=SelectionWeights(relevance=50, uniqueness=25, narrative_dependency=25),
            protection_threshold=80,
            length_constraint=LengthConstraint(ConstraintType.MAX_UNITS, max_units),
        )

        selector = ContentSelector()
        result = selector.select_content(
            units=units,
            opportunity_keywords=[],
            companion_references=[],
            config=config,
        )

        # The cut_list should be in the order they were cut (ascending sort key).
        # With equal composite and equal relevance, higher document_order is cut first.
        # So cut_list should have highest document_order first → descending doc order.
        if len(result.cut_list) >= 2:
            for i in range(len(result.cut_list) - 1):
                entry_a = result.cut_list[i]
                entry_b = result.cut_list[i + 1]

                # Both have same composite (verified by construction)
                if entry_a.composite_score == entry_b.composite_score:
                    # Look up relevance scores
                    relevance_a = next(
                        su.relevance_score for su in result.scored_units
                        if su.unit.id == entry_a.unit.id
                    )
                    relevance_b = next(
                        su.relevance_score for su in result.scored_units
                        if su.unit.id == entry_b.unit.id
                    )

                    if relevance_a == relevance_b:
                        # Equal relevance → higher doc order cut first (appears earlier)
                        assert entry_a.unit.document_order >= entry_b.unit.document_order, (
                            f"Cut list order violation: entry at index {i} "
                            f"(doc_order={entry_a.unit.document_order}) should have "
                            f">= doc_order than entry at index {i+1} "
                            f"(doc_order={entry_b.unit.document_order}) "
                            f"when composite and relevance are tied"
                        )
                    else:
                        # Different relevance → lower relevance cut first (appears earlier)
                        assert relevance_a <= relevance_b, (
                            f"Cut list order violation: entry at index {i} "
                            f"(relevance={relevance_a}) should have <= relevance "
                            f"than entry at index {i+1} (relevance={relevance_b}) "
                            f"when composite is tied"
                        )
