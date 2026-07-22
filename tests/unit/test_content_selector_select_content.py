"""Unit tests for ContentSelector.select_content public method.

Tests validation, edge cases, orchestration of scoring and cut list generation,
and correct computation of retained units and lengths.

Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2
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


def _make_unit(id: str, text: str, document_order: int) -> ContentUnit:
    """Helper to create a ContentUnit."""
    return ContentUnit(
        id=id,
        unit_type=ContentUnitType.BULLET,
        text=text,
        section="experience",
        document_order=document_order,
    )


class TestSelectContentValidation:
    """Tests that select_content raises ValueError for invalid configurations."""

    def test_raises_on_invalid_weights_sum(self, selector: ContentSelector):
        """Weights not summing to 100 raise ValueError."""
        config = SelectionConfig(
            weights=SelectionWeights(relevance=40, uniqueness=30, narrative_dependency=20),
        )
        units = [_make_unit("u1", "Python developer", 0)]
        with pytest.raises(ValueError, match="Invalid weight configuration"):
            selector.select_content(
                units=units,
                opportunity_keywords=["python"],
                companion_references=[],
                config=config,
            )

    def test_raises_on_negative_weight(self, selector: ContentSelector):
        """Negative weight raises ValueError."""
        config = SelectionConfig(
            weights=SelectionWeights(relevance=-10, uniqueness=60, narrative_dependency=50),
        )
        units = [_make_unit("u1", "Python developer", 0)]
        with pytest.raises(ValueError, match="Invalid weight configuration"):
            selector.select_content(
                units=units,
                opportunity_keywords=["python"],
                companion_references=[],
                config=config,
            )

    def test_raises_on_protection_threshold_above_100(self, selector: ContentSelector):
        """Protection threshold > 100 raises ValueError."""
        config = SelectionConfig(protection_threshold=101)
        units = [_make_unit("u1", "Python developer", 0)]
        with pytest.raises(ValueError, match="Protection threshold must be between 0 and 100"):
            selector.select_content(
                units=units,
                opportunity_keywords=["python"],
                companion_references=[],
                config=config,
            )

    def test_raises_on_protection_threshold_below_0(self, selector: ContentSelector):
        """Protection threshold < 0 raises ValueError."""
        config = SelectionConfig(protection_threshold=-1)
        units = [_make_unit("u1", "Python developer", 0)]
        with pytest.raises(ValueError, match="Protection threshold must be between 0 and 100"):
            selector.select_content(
                units=units,
                opportunity_keywords=["python"],
                companion_references=[],
                config=config,
            )

    def test_raises_on_zero_max_value(self, selector: ContentSelector):
        """max_value of 0 raises ValueError."""
        config = SelectionConfig(
            length_constraint=LengthConstraint(ConstraintType.MAX_WORDS, 0),
        )
        units = [_make_unit("u1", "Python developer", 0)]
        with pytest.raises(ValueError, match="Length constraint max_value must be positive"):
            selector.select_content(
                units=units,
                opportunity_keywords=["python"],
                companion_references=[],
                config=config,
            )

    def test_raises_on_negative_max_value(self, selector: ContentSelector):
        """Negative max_value raises ValueError."""
        config = SelectionConfig(
            length_constraint=LengthConstraint(ConstraintType.MAX_WORDS, -5),
        )
        units = [_make_unit("u1", "Python developer", 0)]
        with pytest.raises(ValueError, match="Length constraint max_value must be positive"):
            selector.select_content(
                units=units,
                opportunity_keywords=["python"],
                companion_references=[],
                config=config,
            )


class TestSelectContentEdgeCases:
    """Tests for edge cases: empty units, constraint already satisfied."""

    def test_empty_units_returns_empty_result(self, selector: ContentSelector):
        """Empty units list → empty SelectionResult."""
        config = SelectionConfig()
        result = selector.select_content(
            units=[],
            opportunity_keywords=["python"],
            companion_references=[],
            config=config,
        )
        assert result.scored_units == []
        assert result.cut_list == []
        assert result.retained_units == []
        assert result.warnings == []
        assert result.original_length == 0
        assert result.final_length == 0

    def test_constraint_already_satisfied(self, selector: ContentSelector):
        """Material within limit → no cuts."""
        units = [
            _make_unit("u1", "Python developer", 0),
            _make_unit("u2", "Django expert", 1),
        ]
        # 4 words total, constraint is 10 words
        config = SelectionConfig(
            length_constraint=LengthConstraint(ConstraintType.MAX_WORDS, 10),
        )
        result = selector.select_content(
            units=units,
            opportunity_keywords=["python"],
            companion_references=[],
            config=config,
        )
        assert result.cut_list == []
        assert len(result.retained_units) == 2
        assert result.original_length == 4
        assert result.final_length == 4


class TestSelectContentOrchestration:
    """Tests that select_content correctly orchestrates scoring and cutting."""

    def test_cuts_lowest_scoring_units(self, selector: ContentSelector):
        """Units with no keyword match should be cut first."""
        units = [
            _make_unit("u1", "Python developer with expertise", 0),  # matches "python"
            _make_unit("u2", "Managed team meetings weekly", 1),  # no match
            _make_unit("u3", "Django REST framework experience", 2),  # matches "django"
        ]
        # Total words: 5 + 4 + 4 = 13, constraint is 9
        config = SelectionConfig(
            length_constraint=LengthConstraint(ConstraintType.MAX_WORDS, 9),
        )
        result = selector.select_content(
            units=units,
            opportunity_keywords=["python", "django"],
            companion_references=[],
            config=config,
        )
        # u2 should be cut (0 relevance, lowest composite)
        cut_ids = [entry.unit.id for entry in result.cut_list]
        assert "u2" in cut_ids
        assert result.final_length <= 9

    def test_retained_units_in_document_order(self, selector: ContentSelector):
        """Retained units are sorted by document_order."""
        units = [
            _make_unit("u1", "Python developer with expertise", 0),
            _make_unit("u2", "Managed team meetings weekly", 1),
            _make_unit("u3", "Django REST framework experience", 2),
        ]
        config = SelectionConfig(
            length_constraint=LengthConstraint(ConstraintType.MAX_WORDS, 9),
        )
        result = selector.select_content(
            units=units,
            opportunity_keywords=["python", "django"],
            companion_references=[],
            config=config,
        )
        # Retained units should be in document order
        orders = [u.document_order for u in result.retained_units]
        assert orders == sorted(orders)

    def test_scored_units_ordered_by_composite_descending(self, selector: ContentSelector):
        """scored_units are sorted by composite_score descending."""
        units = [
            _make_unit("u1", "Python developer", 0),
            _make_unit("u2", "Team management", 1),
            _make_unit("u3", "Django and Python expert", 2),
        ]
        config = SelectionConfig(
            length_constraint=LengthConstraint(ConstraintType.MAX_WORDS, 100),
        )
        result = selector.select_content(
            units=units,
            opportunity_keywords=["python", "django"],
            companion_references=[],
            config=config,
        )
        scores = [su.composite_score for su in result.scored_units]
        assert scores == sorted(scores, reverse=True)

    def test_original_and_final_length_computed_correctly(self, selector: ContentSelector):
        """original_length and final_length reflect word counts."""
        units = [
            _make_unit("u1", "one two three", 0),  # 3 words
            _make_unit("u2", "four five six seven", 1),  # 4 words
            _make_unit("u3", "eight nine", 2),  # 2 words
        ]
        # Total = 9 words, constraint = 5
        config = SelectionConfig(
            length_constraint=LengthConstraint(ConstraintType.MAX_WORDS, 5),
        )
        result = selector.select_content(
            units=units,
            opportunity_keywords=[],
            companion_references=[],
            config=config,
        )
        assert result.original_length == 9
        assert result.final_length <= 5

    def test_protection_threshold_respected(self, selector: ContentSelector):
        """Protected units (narrative_dependency > threshold) are not cut if possible."""
        units = [
            _make_unit("u1", "Python developer expert", 0),
            _make_unit("u2", "Django framework specialist", 1),
            _make_unit("u3", "Team management skills", 2),
        ]
        # u1 is referenced by a companion with strength 90 → protected (threshold 80)
        companion_refs = [
            CompanionReference(
                source_material="cover_letter",
                source_passage="As a Python developer...",
                target_unit_id="u1",
                strength=90,
            ),
        ]
        # Total = 3 + 3 + 3 = 9 words, constraint = 6
        config = SelectionConfig(
            protection_threshold=80,
            length_constraint=LengthConstraint(ConstraintType.MAX_WORDS, 6),
        )
        result = selector.select_content(
            units=units,
            opportunity_keywords=["python"],
            companion_references=companion_refs,
            config=config,
        )
        # u1 should be retained (protected), u3 should be cut (lowest relevance)
        retained_ids = [u.id for u in result.retained_units]
        assert "u1" in retained_ids
        assert result.final_length <= 6

    def test_valid_boundary_protection_threshold_0(self, selector: ContentSelector):
        """Protection threshold 0 is valid (no protection at all)."""
        config = SelectionConfig(protection_threshold=0)
        result = selector.select_content(
            units=[_make_unit("u1", "hello", 0)],
            opportunity_keywords=[],
            companion_references=[],
            config=config,
        )
        assert result.final_length == 1

    def test_valid_boundary_protection_threshold_100(self, selector: ContentSelector):
        """Protection threshold 100 is valid (only units scoring > 100 protected, i.e. none)."""
        config = SelectionConfig(protection_threshold=100)
        result = selector.select_content(
            units=[_make_unit("u1", "hello", 0)],
            opportunity_keywords=[],
            companion_references=[],
            config=config,
        )
        assert result.final_length == 1
