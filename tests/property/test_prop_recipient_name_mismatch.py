# Feature: outbound-validation-gate, Property 4: Recipient name mismatch detection
"""Property-based tests for RecipientNameMismatchRule.

Tests that the recipient name mismatch rule correctly detects when a greeting
name in the material body doesn't match the pipeline contact's name:
- When the greeting name matches contact_first_name or contact_last_name → passed=True
- When the greeting name differs from both → passed=False with offending spans
- When no greeting pattern exists in the body → passed=True regardless of contact name

**Validates: Requirements 2.1**
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.outbound_validator import (
    Material,
    RecipientNameMismatchRule,
    RuleSeverity,
    ValidationContext,
)


# ─── Constants ────────────────────────────────────────────────────────────────

GREETING_PREFIXES = ["Hi", "Hello", "Dear", "Hey"]


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for capitalized names: first letter uppercase ASCII, rest lowercase ASCII, 2+ chars
# Must match the rule's regex pattern: [A-Z][a-z]+
capitalized_name_st = st.builds(
    lambda first, rest: first + rest,
    first=st.sampled_from("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    rest=st.text(
        alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz"),
        min_size=1,
        max_size=9,
    ),
)

# Strategy for greeting prefix
greeting_prefix_st = st.sampled_from(GREETING_PREFIXES)

# Strategy for body text without any greeting patterns
non_greeting_body_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Z", "P"),
        blacklist_characters="\x00",
    ),
    min_size=10,
    max_size=200,
).filter(
    lambda s: not any(
        prefix in s for prefix in GREETING_PREFIXES
    )
)


@st.composite
def matching_greeting_material_st(draw):
    """Generate a Material where the greeting name matches the contact name."""
    name = draw(capitalized_name_st)
    prefix = draw(greeting_prefix_st)
    # Build body with greeting that uses the contact's name
    extra_text = draw(st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "N", "Zs"), blacklist_characters="\x00"),
        min_size=5,
        max_size=100,
    ))
    body = f"{prefix} {name},\n\n{extra_text}"
    return body, name


@st.composite
def mismatched_greeting_material_st(draw):
    """Generate a Material where the greeting name differs from the contact name."""
    greeting_name = draw(capitalized_name_st)
    contact_first = draw(capitalized_name_st)
    contact_last = draw(capitalized_name_st)

    # Ensure actual mismatch: greeting_name != contact_first AND != contact_last
    assume(greeting_name.lower() != contact_first.lower())
    assume(greeting_name.lower() != contact_last.lower())

    prefix = draw(greeting_prefix_st)
    extra_text = draw(st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "N", "Zs"), blacklist_characters="\x00"),
        min_size=5,
        max_size=100,
    ))
    body = f"{prefix} {greeting_name},\n\n{extra_text}"
    return body, greeting_name, contact_first, contact_last


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_context(
    contact_first_name: str = "John",
    contact_last_name: str = "Doe",
) -> ValidationContext:
    """Build a minimal ValidationContext for testing."""
    return ValidationContext(
        pipeline_record_id="pr-001",
        contact_first_name=contact_first_name,
        contact_last_name=contact_last_name,
        outreach_technique="cold_email_consultant",
        material_type="email",
    )


# ─── Property 4: Recipient name mismatch detection ───────────────────────────


class TestProperty4RecipientNameMismatch:
    """Property 4: Recipient name mismatch detection.

    **Validates: Requirements 2.1**

    Key invariants:
    - passed=True when greeting name matches contact first or last name
    - passed=False when greeting name differs from both contact names
    - passed=True when no greeting pattern exists in the body
    """

    rule = RecipientNameMismatchRule()

    @given(data=matching_greeting_material_st())
    @settings(max_examples=100)
    def test_passes_when_greeting_matches_contact_first_name(
        self, data: tuple[str, str]
    ) -> None:
        """WHEN the greeting name matches contact_first_name,
        THEN the rule passes (passed=True).

        **Validates: Requirements 2.1**
        """
        body, name = data
        material = Material(body=body, subject="Test Subject")
        context = make_context(contact_first_name=name, contact_last_name="Zzzzunused")

        result = self.rule.check(material, context, {})

        assert result.passed is True, (
            f"Expected passed=True when greeting name '{name}' matches "
            f"contact_first_name '{context.contact_first_name}', "
            f"body='{body[:60]}...'"
        )
        assert result.offending_spans == [], (
            f"Expected no offending spans on match, got {result.offending_spans}"
        )

    @given(data=matching_greeting_material_st())
    @settings(max_examples=100)
    def test_passes_when_greeting_matches_contact_last_name(
        self, data: tuple[str, str]
    ) -> None:
        """WHEN the greeting name matches contact_last_name,
        THEN the rule passes (passed=True).

        **Validates: Requirements 2.1**
        """
        body, name = data
        material = Material(body=body, subject="Test Subject")
        context = make_context(contact_first_name="Zzzzunused", contact_last_name=name)

        result = self.rule.check(material, context, {})

        assert result.passed is True, (
            f"Expected passed=True when greeting name '{name}' matches "
            f"contact_last_name '{context.contact_last_name}', "
            f"body='{body[:60]}...'"
        )
        assert result.offending_spans == [], (
            f"Expected no offending spans on match, got {result.offending_spans}"
        )

    @given(data=mismatched_greeting_material_st())
    @settings(max_examples=100)
    def test_fails_when_greeting_differs_from_contact(
        self, data: tuple[str, str, str, str]
    ) -> None:
        """WHEN the greeting name differs from both contact_first_name
        AND contact_last_name, THEN the rule fails (passed=False)
        and offending spans identify the wrong name.

        **Validates: Requirements 2.1**
        """
        body, greeting_name, contact_first, contact_last = data
        material = Material(body=body, subject="Test Subject")
        context = make_context(
            contact_first_name=contact_first,
            contact_last_name=contact_last,
        )

        result = self.rule.check(material, context, {})

        assert result.passed is False, (
            f"Expected passed=False when greeting '{greeting_name}' differs from "
            f"contact first='{contact_first}', last='{contact_last}', "
            f"body='{body[:60]}...'"
        )
        assert len(result.offending_spans) > 0, (
            f"Expected offending spans to identify the wrong name, got empty list"
        )
        # Verify the span text is the mismatched greeting name
        for span in result.offending_spans:
            assert span.field_name == "body", (
                f"Expected span in 'body' field, got '{span.field_name}'"
            )
            assert span.text == greeting_name, (
                f"Expected span text to be '{greeting_name}', got '{span.text}'"
            )

    @given(
        body=non_greeting_body_st,
        contact_first=capitalized_name_st,
        contact_last=capitalized_name_st,
    )
    @settings(max_examples=100)
    def test_passes_when_no_greeting_pattern_in_body(
        self, body: str, contact_first: str, contact_last: str
    ) -> None:
        """WHEN the body contains no greeting patterns (Hi/Hello/Dear/Hey + Name),
        THEN the rule passes (passed=True) regardless of contact name.

        **Validates: Requirements 2.1**
        """
        material = Material(body=body, subject="Test Subject")
        context = make_context(
            contact_first_name=contact_first,
            contact_last_name=contact_last,
        )

        result = self.rule.check(material, context, {})

        assert result.passed is True, (
            f"Expected passed=True when body has no greeting pattern, "
            f"body='{body[:60]}...'"
        )
        assert result.offending_spans == [], (
            f"Expected no offending spans when no greeting, got {result.offending_spans}"
        )
