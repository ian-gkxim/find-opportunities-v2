# Feature: relevance-weighted-selection, Property 2: Weight Validation Acceptance and Rejection
"""Property-based tests for SelectionWeights.validate() acceptance and rejection.

Tests that valid weight triples (all in [0,100] and summing to 100) are accepted,
and invalid weight triples (sum != 100 or any value outside [0,100]) are rejected
with a descriptive error message.

**Validates: Requirements 1.3**
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.content_selector import SelectionWeights


# ─── Strategies ───────────────────────────────────────────────────────────────


@st.composite
def valid_weight_triples_st(draw) -> tuple[int, int, int]:
    """Generate valid weight triples: all in [0, 100] and summing to exactly 100."""
    a = draw(st.integers(min_value=0, max_value=100))
    b = draw(st.integers(min_value=0, max_value=100 - a))
    c = 100 - a - b
    # All must be in [0, 100] — c is guaranteed by construction
    assume(0 <= c <= 100)
    return a, b, c


@st.composite
def invalid_sum_weight_triples_st(draw) -> tuple[int, int, int]:
    """Generate weight triples where all are in [0, 100] but sum != 100."""
    a = draw(st.integers(min_value=0, max_value=100))
    b = draw(st.integers(min_value=0, max_value=100))
    c = draw(st.integers(min_value=0, max_value=100))
    assume(a + b + c != 100)
    return a, b, c


@st.composite
def out_of_range_weight_triples_st(draw) -> tuple[int, int, int]:
    """Generate weight triples where at least one value is outside [0, 100]."""
    # Generate at least one value outside [0, 100]
    out_of_range = draw(st.one_of(
        st.integers(max_value=-1),
        st.integers(min_value=101),
    ))
    # Place the out-of-range value in a random position
    position = draw(st.integers(min_value=0, max_value=2))
    others = [draw(st.integers(min_value=-200, max_value=300)) for _ in range(2)]

    triple = list(others)
    triple.insert(position, out_of_range)
    return triple[0], triple[1], triple[2]


# ─── Property 2: Weight Validation Acceptance and Rejection ───────────────────


class TestProperty2WeightValidation:
    """Property 2: Weight Validation Acceptance and Rejection.

    Feature: relevance-weighted-selection, Property 2: Weight Validation Acceptance and Rejection

    **Validates: Requirements 1.3**

    Key invariants:
    - If a + b + c = 100 and all are in [0, 100], validate() returns (True, "")
    - If a + b + c != 100 OR any value is outside [0, 100], validate() returns (False, descriptive_message)
    """

    @given(triple=valid_weight_triples_st())
    @settings(max_examples=200)
    def test_valid_weights_are_accepted(
        self,
        triple: tuple[int, int, int],
    ) -> None:
        """FOR ANY triple (a, b, c) where all are in [0, 100] and a + b + c = 100,
        SelectionWeights(a, b, c).validate() SHALL return (True, "").

        **Validates: Requirements 1.3**
        """
        a, b, c = triple
        weights = SelectionWeights(relevance=a, uniqueness=b, narrative_dependency=c)
        is_valid, error_msg = weights.validate()

        assert is_valid is True, (
            f"Valid weights ({a}, {b}, {c}) were rejected.\n"
            f"Sum: {a + b + c}\n"
            f"Error: {error_msg}"
        )
        assert error_msg == "", (
            f"Valid weights ({a}, {b}, {c}) returned non-empty error: {error_msg}"
        )

    @given(triple=invalid_sum_weight_triples_st())
    @settings(max_examples=200)
    def test_invalid_sum_weights_are_rejected(
        self,
        triple: tuple[int, int, int],
    ) -> None:
        """FOR ANY triple (a, b, c) where all are in [0, 100] but a + b + c != 100,
        SelectionWeights(a, b, c).validate() SHALL return (False, descriptive_message).

        **Validates: Requirements 1.3**
        """
        a, b, c = triple
        weights = SelectionWeights(relevance=a, uniqueness=b, narrative_dependency=c)
        is_valid, error_msg = weights.validate()

        assert is_valid is False, (
            f"Invalid weights ({a}, {b}, {c}) with sum={a + b + c} were accepted.\n"
            f"Expected rejection because sum != 100."
        )
        assert error_msg != "", (
            f"Invalid weights ({a}, {b}, {c}) returned empty error message.\n"
            f"Expected a descriptive error message."
        )

    @given(triple=out_of_range_weight_triples_st())
    @settings(max_examples=200)
    def test_out_of_range_weights_are_rejected(
        self,
        triple: tuple[int, int, int],
    ) -> None:
        """FOR ANY triple (a, b, c) where at least one value is outside [0, 100],
        SelectionWeights(a, b, c).validate() SHALL return (False, descriptive_message).

        **Validates: Requirements 1.3**
        """
        a, b, c = triple
        weights = SelectionWeights(relevance=a, uniqueness=b, narrative_dependency=c)
        is_valid, error_msg = weights.validate()

        assert is_valid is False, (
            f"Out-of-range weights ({a}, {b}, {c}) were accepted.\n"
            f"At least one value is outside [0, 100]."
        )
        assert error_msg != "", (
            f"Out-of-range weights ({a}, {b}, {c}) returned empty error message.\n"
            f"Expected a descriptive error message."
        )
