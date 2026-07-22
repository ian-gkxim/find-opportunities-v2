# Feature: relevance-weighted-selection, Property 6: Schema Length Constraints Parsing Round-Trip
"""Property-based tests for LengthConstraintConfig → LengthConstraint round-trip.

Tests that constructing a LengthConstraintConfig with exactly one constraint type
(max_words, max_characters, or max_units) and calling to_length_constraint() produces
a LengthConstraint with the matching constraint_type and max_value.

**Validates: Requirements 3.1**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.content_selector import ConstraintType, LengthConstraint
from app.core.schema_registry import LengthConstraintConfig


# ─── Strategies ───────────────────────────────────────────────────────────────


@st.composite
def length_constraint_config_st(draw) -> tuple[LengthConstraintConfig, str, int]:
    """Generate a valid LengthConstraintConfig with exactly one constraint set.

    Returns:
        A tuple of (config, expected_constraint_type_value, expected_max_value)
        where expected_constraint_type_value is the ConstraintType enum value string.
    """
    constraint_type = draw(st.sampled_from(["max_words", "max_characters", "max_units"]))
    value = draw(st.integers(min_value=1, max_value=10_000))

    if constraint_type == "max_words":
        config = LengthConstraintConfig(max_words=value)
        expected_type = ConstraintType.MAX_WORDS
    elif constraint_type == "max_characters":
        config = LengthConstraintConfig(max_characters=value)
        expected_type = ConstraintType.MAX_CHARACTERS
    else:
        config = LengthConstraintConfig(max_units=value)
        expected_type = ConstraintType.MAX_UNITS

    return config, expected_type, value


# ─── Property 6: Schema Length Constraints Parsing Round-Trip ─────────────────


class TestProperty6SchemaLengthConstraintsRoundTrip:
    """Property 6: Schema Length Constraints Parsing Round-Trip.

    Feature: relevance-weighted-selection, Property 6: Schema Length Constraints Parsing Round-Trip

    **Validates: Requirements 3.1**

    Key invariant:
    - For any valid LengthConstraintConfig with exactly one constraint type set to
      a positive integer, calling to_length_constraint() produces a LengthConstraint
      with the matching constraint_type and max_value.
    """

    @given(data=length_constraint_config_st())
    @settings(max_examples=200)
    def test_length_constraint_config_round_trip(
        self,
        data: tuple[LengthConstraintConfig, ConstraintType, int],
    ) -> None:
        """FOR ANY valid LengthConstraintConfig specifying one of max_words,
        max_characters, or max_units with a positive integer value,
        to_length_constraint() SHALL produce a LengthConstraint with matching
        constraint_type and max_value.

        **Validates: Requirements 3.1**
        """
        config, expected_type, expected_value = data

        result = config.to_length_constraint()

        assert isinstance(result, LengthConstraint), (
            f"Expected LengthConstraint instance, got {type(result).__name__}"
        )
        assert result.constraint_type == expected_type, (
            f"Expected constraint_type={expected_type}, got {result.constraint_type}.\n"
            f"Config: max_words={config.max_words}, max_characters={config.max_characters}, "
            f"max_units={config.max_units}"
        )
        assert result.max_value == expected_value, (
            f"Expected max_value={expected_value}, got {result.max_value}.\n"
            f"Config: max_words={config.max_words}, max_characters={config.max_characters}, "
            f"max_units={config.max_units}"
        )
