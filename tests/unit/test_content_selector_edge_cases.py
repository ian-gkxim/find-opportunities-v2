"""Unit tests for Content_Selector edge cases.

Tests default weight scoring, zero-relevance, single-unit materials,
exact-boundary behavior, force-cut with warnings, and document-order stability.

Requirements: 1.2, 1.4, 2.1, 2.2
"""

import pytest

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


@pytest.fixture
def selector() -> ContentSelector:
    return ContentSelector()


def _make_unit(
    id: str,
    text: str,
    document_order: int = 0,
    section: str = "experience",
    unit_type: ContentUnitType = ContentUnitType.BULLET,
) -> ContentUnit:
    """Helper to create a ContentUnit with customizable fields."""
    return ContentUnit(
        id=id,
        unit_type=unit_type,
        text=text,
        section=section,
        document_order=document_order,
    )


class TestDefaultWeightsKnownScores:
    """Verify default 50/25/25 weights produce expected composite scores for known inputs.

    Requirements: 1.2
    """

    def test_default_weights_known_scores(self, selector: ContentSelector):
        """Create 3 units with known keyword overlap, verify composite scores
        match expected formula with default 50/25/25 weights.
        """
        # Unit 1: matches all keywords, unique text
        # Unit 2: matches some keywords, somewhat unique
        # Unit 3: matches no keywords, duplicate of unit 2
        units = [
            _make_unit("u1", "Python Django REST API development", document_order=0),
            _make_unit("u2", "Managed team of engineers effectively", document_order=1),
            _make_unit("u3", "Managed team of engineers effectively", document_order=2),
        ]
        keywords = ["python", "django"]
        config = SelectionConfig(
            weights=SelectionWeights(),  # default 50/25/25
            length_constraint=LengthConstraint(ConstraintType.MAX_UNITS, 10),
        )

        result = selector.select_content(
            units=units,
            opportunity_keywords=keywords,
            companion_references=[],
            config=config,
        )

        # Find scored units by id
        scores_by_id = {su.unit.id: su for su in result.scored_units}

        # Unit 1: relevance = 2/2 = 100, unique text → high uniqueness, no deps → 0
        u1 = scores_by_id["u1"]
        assert u1.relevance_score == 100
        assert u1.narrative_dependency_score == 0
        # Composite = round((100*50 + uniqueness*25 + 0*25) / 100)
        expected_composite_u1 = round((100 * 50 + u1.uniqueness_score * 25 + 0 * 25) / 100)
        assert u1.composite_score == expected_composite_u1

        # Unit 2: relevance = 0/2 = 0, duplicate of u3 → low uniqueness, no deps → 0
        u2 = scores_by_id["u2"]
        assert u2.relevance_score == 0
        assert u2.narrative_dependency_score == 0
        expected_composite_u2 = round((0 * 50 + u2.uniqueness_score * 25 + 0 * 25) / 100)
        assert u2.composite_score == expected_composite_u2

        # Unit 3: same text as u2 → same relevance and uniqueness
        u3 = scores_by_id["u3"]
        assert u3.relevance_score == 0
        assert u3.narrative_dependency_score == 0
        expected_composite_u3 = round((0 * 50 + u3.uniqueness_score * 25 + 0 * 25) / 100)
        assert u3.composite_score == expected_composite_u3

        # u1 should have the highest composite score
        assert u1.composite_score > u2.composite_score


class TestAllZeroRelevance:
    """Units with no keyword matches should get relevance_score=0.

    Requirements: 1.2
    """

    def test_all_zero_relevance(self, selector: ContentSelector):
        """Units whose text contains none of the opportunity keywords score 0 relevance."""
        units = [
            _make_unit("u1", "Managed a cross-functional team", document_order=0),
            _make_unit("u2", "Led strategic planning initiatives", document_order=1),
            _make_unit("u3", "Coordinated stakeholder meetings", document_order=2),
        ]
        keywords = ["python", "django", "kubernetes"]
        config = SelectionConfig(
            weights=SelectionWeights(),
            length_constraint=LengthConstraint(ConstraintType.MAX_UNITS, 10),
        )

        result = selector.select_content(
            units=units,
            opportunity_keywords=keywords,
            companion_references=[],
            config=config,
        )

        for su in result.scored_units:
            assert su.relevance_score == 0


class TestSingleUnitNotCut:
    """A single-unit material should never be cut when constraint max_value >= 1.

    Requirements: 2.1
    """

    def test_single_unit_not_cut(self, selector: ContentSelector):
        """Single unit with MAX_UNITS constraint of 1 → no cuts."""
        units = [_make_unit("u1", "Python developer with experience", document_order=0)]
        config = SelectionConfig(
            weights=SelectionWeights(),
            length_constraint=LengthConstraint(ConstraintType.MAX_UNITS, 1),
        )

        result = selector.select_content(
            units=units,
            opportunity_keywords=["python"],
            companion_references=[],
            config=config,
        )

        assert result.cut_list == []
        assert len(result.retained_units) == 1
        assert result.final_length <= config.length_constraint.max_value

    def test_single_unit_not_cut_words(self, selector: ContentSelector):
        """Single unit with MAX_WORDS constraint equal to its word count → no cuts."""
        text = "Built scalable APIs"  # 3 words
        units = [_make_unit("u1", text, document_order=0)]
        config = SelectionConfig(
            weights=SelectionWeights(),
            length_constraint=LengthConstraint(ConstraintType.MAX_WORDS, 3),
        )

        result = selector.select_content(
            units=units,
            opportunity_keywords=[],
            companion_references=[],
            config=config,
        )

        assert result.cut_list == []
        assert len(result.retained_units) == 1


class TestExactBoundaryNoCuts:
    """Material exactly at the limit → empty cut_list.

    Requirements: 2.1
    """

    def test_exact_boundary_no_cuts(self, selector: ContentSelector):
        """3 units with MAX_UNITS constraint of 3 → no cuts needed."""
        units = [
            _make_unit("u1", "Python development", document_order=0),
            _make_unit("u2", "Django framework", document_order=1),
            _make_unit("u3", "REST API design", document_order=2),
        ]
        config = SelectionConfig(
            weights=SelectionWeights(),
            length_constraint=LengthConstraint(ConstraintType.MAX_UNITS, 3),
        )

        result = selector.select_content(
            units=units,
            opportunity_keywords=["python"],
            companion_references=[],
            config=config,
        )

        assert result.cut_list == []
        assert len(result.retained_units) == 3
        assert result.original_length == 3
        assert result.final_length == 3

    def test_exact_boundary_words(self, selector: ContentSelector):
        """Total words exactly match MAX_WORDS → no cuts."""
        units = [
            _make_unit("u1", "one two", document_order=0),       # 2 words
            _make_unit("u2", "three four five", document_order=1),  # 3 words
        ]
        config = SelectionConfig(
            weights=SelectionWeights(),
            length_constraint=LengthConstraint(ConstraintType.MAX_WORDS, 5),
        )

        result = selector.select_content(
            units=units,
            opportunity_keywords=[],
            companion_references=[],
            config=config,
        )

        assert result.cut_list == []
        assert result.original_length == 5
        assert result.final_length == 5


class TestForceCutAllProtected:
    """All units protected (narrative_dependency > threshold), material over limit
    → force-cuts with warnings and forced=True.

    Requirements: 2.2
    """

    def test_force_cut_all_protected(self, selector: ContentSelector):
        """All units have high narrative_dependency, material exceeds constraint.
        Must force-cut lowest-scoring protected units and emit warnings.
        """
        units = [
            _make_unit("u1", "Python development experience", document_order=0),
            _make_unit("u2", "Django REST API work", document_order=1),
            _make_unit("u3", "Kubernetes deployment skills", document_order=2),
        ]
        # All units are referenced by cover letter with strength > protection threshold (80)
        companion_refs = [
            CompanionReference(
                source_material="cover_letter",
                source_passage="As shown by my Python experience",
                target_unit_id="u1",
                strength=90,
            ),
            CompanionReference(
                source_material="cover_letter",
                source_passage="My Django API expertise",
                target_unit_id="u2",
                strength=85,
            ),
            CompanionReference(
                source_material="cover_letter",
                source_passage="My Kubernetes deployment background",
                target_unit_id="u3",
                strength=95,
            ),
        ]
        config = SelectionConfig(
            weights=SelectionWeights(),
            protection_threshold=80,
            length_constraint=LengthConstraint(ConstraintType.MAX_UNITS, 2),
        )

        result = selector.select_content(
            units=units,
            opportunity_keywords=["python", "django", "kubernetes"],
            companion_references=companion_refs,
            config=config,
        )

        # At least one unit must be cut to satisfy MAX_UNITS=2
        assert len(result.cut_list) >= 1
        assert result.final_length <= 2

        # All cuts should be forced since all units are protected
        for entry in result.cut_list:
            assert entry.forced is True

        # Warnings should be emitted for each force-cut
        assert len(result.warnings) == len(result.cut_list)
        for warning in result.warnings:
            assert warning.narrative_dependency_score > 80
            assert warning.source_material == "cover_letter"
            assert warning.dependent_passage != ""


class TestDocumentOrderStability:
    """Units with identical scores → highest document_order is cut first.

    Requirements: 1.4
    """

    def test_document_order_stability(self, selector: ContentSelector):
        """Units with identical text (same composite, same relevance) →
        highest document_order is cut first.
        """
        # All units have identical text → same relevance, same uniqueness
        identical_text = "Generic project management experience"
        units = [
            _make_unit("u1", identical_text, document_order=0),
            _make_unit("u2", identical_text, document_order=1),
            _make_unit("u3", identical_text, document_order=2),
            _make_unit("u4", identical_text, document_order=3),
        ]
        config = SelectionConfig(
            weights=SelectionWeights(),
            length_constraint=LengthConstraint(ConstraintType.MAX_UNITS, 2),
        )

        result = selector.select_content(
            units=units,
            opportunity_keywords=["python"],  # None match → all get relevance 0
            companion_references=[],
            config=config,
        )

        # Need to cut 2 out of 4 units
        assert len(result.cut_list) == 2

        # With identical scores, highest document_order should be cut first
        # Cut order should be: u4 (order 3), then u3 (order 2)
        cut_orders = [entry.unit.document_order for entry in result.cut_list]
        assert cut_orders == [3, 2]

        # Retained units should be u1 and u2 (lowest document_order preserved)
        retained_ids = [u.id for u in result.retained_units]
        assert "u1" in retained_ids
        assert "u2" in retained_ids
