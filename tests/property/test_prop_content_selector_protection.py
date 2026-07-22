# Feature: relevance-weighted-selection, Property 5: Protection Threshold Invariant
"""Property-based tests for the Content_Selector protection threshold invariant.

Tests that protected units (narrative_dependency_score > protection_threshold) are never
cut when the constraint can be satisfied without them, and that ProtectionWarnings are
emitted for each force-cut protected unit when cutting them is unavoidable.

**Validates: Requirements 2.2**
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
def content_unit_st(draw, unit_id: str, document_order: int) -> ContentUnit:
    """Generate a ContentUnit with a given id and document_order."""
    # Generate text with 1-5 words so we can reason about word counts
    word_count = draw(st.integers(min_value=1, max_value=5))
    words = [draw(st.from_regex(r"[a-z]{3,8}", fullmatch=True)) for _ in range(word_count)]
    text = " ".join(words)
    unit_type = draw(st.sampled_from(list(ContentUnitType)))
    section = draw(st.sampled_from(["experience", "skills", "profile", "education"]))
    return ContentUnit(
        id=unit_id,
        unit_type=unit_type,
        text=text,
        section=section,
        document_order=document_order,
    )


@st.composite
def satisfiable_without_protected_scenario_st(draw):
    """Generate a scenario where the constraint CAN be satisfied by cutting only unprotected units.

    Strategy:
    - Generate a mix of protected and unprotected units
    - Set the constraint so that cutting only the unprotected units is sufficient
    - Use MAX_UNITS constraint for simplicity (each unit counts as 1)
    """
    protection_threshold = draw(st.integers(min_value=50, max_value=90))

    # Generate 3-8 unprotected units (dependency score <= threshold)
    num_unprotected = draw(st.integers(min_value=3, max_value=8))
    # Generate 1-4 protected units (dependency score > threshold)
    num_protected = draw(st.integers(min_value=1, max_value=4))

    total_units = num_unprotected + num_protected

    units: list[ContentUnit] = []
    companion_refs: list[CompanionReference] = []

    # Create unprotected units (no companion references or low-strength ones)
    for i in range(num_unprotected):
        unit = draw(content_unit_st(unit_id=f"unprotected_{i}", document_order=i))
        units.append(unit)
        # Some unprotected units may have low-strength references (at or below threshold)
        if draw(st.booleans()):
            strength = draw(st.integers(min_value=0, max_value=protection_threshold))
            companion_refs.append(CompanionReference(
                source_material="cover_letter",
                source_passage=f"References unit {unit.id}",
                target_unit_id=unit.id,
                strength=strength,
            ))

    # Create protected units (high-strength companion references)
    for i in range(num_protected):
        unit = draw(content_unit_st(
            unit_id=f"protected_{i}",
            document_order=num_unprotected + i,
        ))
        units.append(unit)
        # Protected units have strength > threshold
        strength = draw(st.integers(min_value=protection_threshold + 1, max_value=100))
        companion_refs.append(CompanionReference(
            source_material="cover_letter",
            source_passage=f"This passage depends on unit {unit.id}",
            target_unit_id=unit.id,
            strength=strength,
        ))

    # Set constraint so that we need to cut some units but NOT all unprotected ones
    # We want: max_value >= num_protected (so protected can all fit)
    # and max_value < total_units (so some cutting is needed)
    # and (total_units - num_unprotected) <= max_value (protected all fit within constraint)
    min_constraint = num_protected  # At minimum, all protected must fit
    max_constraint = total_units - 1  # Must require at least 1 cut
    assume(min_constraint <= max_constraint)

    max_value = draw(st.integers(min_value=min_constraint, max_value=max_constraint))

    # Ensure we can satisfy constraint by cutting only unprotected units
    # Number of cuts needed = total_units - max_value
    cuts_needed = total_units - max_value
    assume(cuts_needed <= num_unprotected)  # Can satisfy without touching protected

    constraint = LengthConstraint(
        constraint_type=ConstraintType.MAX_UNITS,
        max_value=max_value,
    )

    config = SelectionConfig(
        weights=SelectionWeights(relevance=50, uniqueness=25, narrative_dependency=25),
        protection_threshold=protection_threshold,
        length_constraint=constraint,
    )

    keywords = draw(st.lists(
        st.from_regex(r"[a-z]{3,6}", fullmatch=True),
        min_size=1,
        max_size=3,
    ))

    return units, keywords, companion_refs, config, protection_threshold


@st.composite
def must_force_cut_protected_scenario_st(draw):
    """Generate a scenario where the constraint CANNOT be satisfied without cutting protected units.

    Strategy:
    - Make ALL or most units protected (high narrative_dependency_score)
    - Set a very tight constraint so we must cut some protected units
    """
    protection_threshold = draw(st.integers(min_value=50, max_value=90))

    # Generate 3-6 units, ALL protected
    num_units = draw(st.integers(min_value=3, max_value=6))

    units: list[ContentUnit] = []
    companion_refs: list[CompanionReference] = []

    for i in range(num_units):
        unit = draw(content_unit_st(unit_id=f"unit_{i}", document_order=i))
        units.append(unit)
        # All units are protected (strength > threshold)
        strength = draw(st.integers(min_value=protection_threshold + 1, max_value=100))
        companion_refs.append(CompanionReference(
            source_material=draw(st.sampled_from(["cover_letter", "proposal", "email"])),
            source_passage=f"Depends on unit {unit.id} for narrative coherence",
            target_unit_id=unit.id,
            strength=strength,
        ))

    # Set constraint very tight: must retain fewer units than we have
    # This forces cutting some protected units
    max_value = draw(st.integers(min_value=1, max_value=num_units - 1))

    constraint = LengthConstraint(
        constraint_type=ConstraintType.MAX_UNITS,
        max_value=max_value,
    )

    config = SelectionConfig(
        weights=SelectionWeights(relevance=50, uniqueness=25, narrative_dependency=25),
        protection_threshold=protection_threshold,
        length_constraint=constraint,
    )

    keywords = draw(st.lists(
        st.from_regex(r"[a-z]{3,6}", fullmatch=True),
        min_size=1,
        max_size=3,
    ))

    return units, keywords, companion_refs, config, protection_threshold


# ─── Property 5: Protection Threshold Invariant ──────────────────────────────


class TestProperty5ProtectionThresholdInvariant:
    """Property 5: Protection Threshold Invariant.

    Feature: relevance-weighted-selection, Property 5: Protection Threshold Invariant

    **Validates: Requirements 2.2**

    Key invariants:
    - When constraint is satisfiable without cutting protected units,
      no protected unit appears in the cut_list.
    - When constraint requires cutting protected units,
      each force-cut protected unit has a ProtectionWarning.
    """

    @given(scenario=satisfiable_without_protected_scenario_st())
    @settings(max_examples=200)
    def test_protected_units_never_cut_when_unnecessary(self, scenario) -> None:
        """FOR ANY selection run where the LengthConstraint can be satisfied by
        cutting only units with narrative_dependency_score <= protection_threshold,
        no unit with narrative_dependency_score > protection_threshold SHALL appear
        in the cut_list.

        Feature: relevance-weighted-selection, Property 5: Protection Threshold Invariant

        **Validates: Requirements 2.2**
        """
        units, keywords, companion_refs, config, protection_threshold = scenario

        selector = ContentSelector()
        result = selector.select_content(
            units=units,
            opportunity_keywords=keywords,
            companion_references=companion_refs,
            config=config,
        )

        # Identify which units are protected based on their scored dependency
        protected_unit_ids = set()
        for scored_unit in result.scored_units:
            if scored_unit.narrative_dependency_score > protection_threshold:
                protected_unit_ids.add(scored_unit.unit.id)

        # No protected unit should appear in the cut list
        cut_unit_ids = {entry.unit.id for entry in result.cut_list}
        wrongly_cut_protected = cut_unit_ids & protected_unit_ids

        assert wrongly_cut_protected == set(), (
            f"Protected units were cut when it was unnecessary!\n"
            f"Protection threshold: {protection_threshold}\n"
            f"Protected unit IDs: {protected_unit_ids}\n"
            f"Cut unit IDs: {cut_unit_ids}\n"
            f"Wrongly cut protected units: {wrongly_cut_protected}\n"
            f"Total units: {len(units)}, Constraint max: {config.length_constraint.max_value}"
        )

        # Also verify no warnings were emitted (no force-cuts happened)
        assert result.warnings == [], (
            f"Warnings were emitted when no force-cuts should have occurred.\n"
            f"Warnings: {result.warnings}"
        )

    @given(scenario=must_force_cut_protected_scenario_st())
    @settings(max_examples=200)
    def test_force_cut_protected_units_emit_warnings(self, scenario) -> None:
        """FOR ANY selection run where the constraint CANNOT be satisfied without
        cutting protected units, the warnings list SHALL contain a ProtectionWarning
        for each force-cut protected unit, identifying the dependent companion passage.

        Feature: relevance-weighted-selection, Property 5: Protection Threshold Invariant

        **Validates: Requirements 2.2**
        """
        units, keywords, companion_refs, config, protection_threshold = scenario

        selector = ContentSelector()
        result = selector.select_content(
            units=units,
            opportunity_keywords=keywords,
            companion_references=companion_refs,
            config=config,
        )

        # Identify force-cut entries (entries with forced=True)
        force_cut_entries = [entry for entry in result.cut_list if entry.forced]

        # Each force-cut entry must correspond to a protected unit
        for entry in force_cut_entries:
            # Find the scored unit to verify its dependency score
            scored = next(
                su for su in result.scored_units if su.unit.id == entry.unit.id
            )
            assert scored.narrative_dependency_score > protection_threshold, (
                f"Unit {entry.unit.id} was marked as forced but has "
                f"narrative_dependency_score={scored.narrative_dependency_score} "
                f"which is not above threshold={protection_threshold}"
            )

        # Each force-cut protected unit must have a corresponding ProtectionWarning
        force_cut_ids = {entry.unit.id for entry in force_cut_entries}
        warning_unit_ids = {w.unit_id for w in result.warnings}

        assert force_cut_ids == warning_unit_ids, (
            f"Mismatch between force-cut units and warnings!\n"
            f"Force-cut unit IDs: {force_cut_ids}\n"
            f"Warning unit IDs: {warning_unit_ids}\n"
            f"Missing warnings for: {force_cut_ids - warning_unit_ids}\n"
            f"Extra warnings for: {warning_unit_ids - force_cut_ids}"
        )

        # Each warning must identify the dependent companion passage
        for warning in result.warnings:
            assert warning.dependent_passage != "", (
                f"ProtectionWarning for unit {warning.unit_id} has empty dependent_passage.\n"
                f"Expected identification of the dependent companion passage."
            )
            assert warning.source_material != "", (
                f"ProtectionWarning for unit {warning.unit_id} has empty source_material.\n"
                f"Expected identification of which companion material is affected."
            )
            assert warning.narrative_dependency_score > protection_threshold, (
                f"ProtectionWarning for unit {warning.unit_id} has "
                f"narrative_dependency_score={warning.narrative_dependency_score} "
                f"which is not above threshold={protection_threshold}"
            )

        # If there are force-cut entries, there MUST be warnings
        if force_cut_entries:
            assert len(result.warnings) > 0, (
                f"Force-cut protected units exist but no warnings were emitted.\n"
                f"Force-cut entries: {[e.unit.id for e in force_cut_entries]}"
            )

        # Verify the constraint is still satisfied
        assert result.final_length <= config.length_constraint.max_value, (
            f"Constraint not satisfied after cuts.\n"
            f"Final length: {result.final_length}, "
            f"Max allowed: {config.length_constraint.max_value}"
        )
