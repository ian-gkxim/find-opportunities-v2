# Feature: outbound-validation-gate, Property 3: Unreplaced token detection
"""Property-based tests for UnreplacedTokenRule token detection.

Tests that the unreplaced token rule correctly identifies template tokens:
- When a material body/subject contains token patterns, passed is False
- When no token patterns are present, passed is True
- All detected tokens are reported as TextSpans with correct positions

**Validates: Requirements 2.1**
"""

import re

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.outbound_validator import (
    Material,
    RuleResult,
    TextSpan,
    UnreplacedTokenRule,
    ValidationContext,
)


# ─── Constants ────────────────────────────────────────────────────────────────

# The token patterns recognized by UnreplacedTokenRule
TOKEN_PATTERNS = [
    re.compile(r"\{\{[^}]+\}\}"),       # {{first_name}}
    re.compile(r"\{[a-z_]+\}"),         # {company_name}
    re.compile(r"\[PLACEHOLDER\]", re.I),  # [PLACEHOLDER]
    re.compile(r"<INSERT[^>]*>", re.I),    # <INSERT_NAME>
]


def text_contains_token(text: str) -> bool:
    """Check if text contains any token pattern."""
    for pattern in TOKEN_PATTERNS:
        if pattern.search(text):
            return True
    return False


def find_all_tokens(text: str) -> list[re.Match]:
    """Find all token matches in text."""
    matches = []
    for pattern in TOKEN_PATTERNS:
        matches.extend(pattern.finditer(text))
    return matches


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for generating double-brace tokens: {{...}}
double_brace_token_st = st.from_regex(r"\{\{[a-z_]{1,20}\}\}", fullmatch=True)

# Strategy for generating single-brace tokens: {word}
single_brace_token_st = st.from_regex(r"\{[a-z_]{1,20}\}", fullmatch=True)

# Strategy for generating PLACEHOLDER tokens
placeholder_token_st = st.sampled_from(["[PLACEHOLDER]", "[placeholder]", "[Placeholder]"])

# Strategy for generating INSERT tokens: <INSERT...>
insert_token_st = st.from_regex(r"<INSERT[A-Z_]{0,15}>", fullmatch=True)

# Any token pattern
any_token_st = st.one_of(
    double_brace_token_st,
    single_brace_token_st,
    placeholder_token_st,
    insert_token_st,
)

# Strategy for safe text that does NOT contain any token patterns.
# We use printable characters but exclude { } [ ] < > to avoid accidental matches.
safe_alphabet = st.characters(
    whitelist_categories=("L", "N", "Z", "P"),
    blacklist_characters="{}<>[]",
)
safe_text_st = st.text(alphabet=safe_alphabet, min_size=0, max_size=200)

# Strategy for text that definitely contains at least one token
@st.composite
def text_with_tokens_st(draw):
    """Generate text that definitely contains at least one token pattern."""
    prefix = draw(safe_text_st)
    token = draw(any_token_st)
    suffix = draw(safe_text_st)
    return prefix + token + suffix


# Strategy for context (minimal, not relevant to this rule)
context_st = st.builds(
    ValidationContext,
    pipeline_record_id=st.just("test-record-001"),
    contact_first_name=st.just("John"),
    contact_last_name=st.just("Doe"),
    outreach_technique=st.just("cold_email_consultant"),
    material_type=st.just("email"),
)


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestProperty3UnreplacedTokenDetection:
    """Property 3: Unreplaced token detection.

    **Validates: Requirements 2.1**

    Key invariants:
    - passed == True ⟺ no token patterns present in material
    - passed == False ⟺ at least one token pattern present
    - Each TextSpan in offending_spans corresponds to an actual token in the text
    """

    @given(
        body=text_with_tokens_st(),
        context=context_st,
    )
    @settings(max_examples=200)
    def test_fails_when_body_contains_tokens(
        self,
        body: str,
        context: ValidationContext,
    ) -> None:
        """WHEN a material body contains any token pattern, THEN the rule
        returns passed=False.

        **Validates: Requirements 2.1**
        """
        material = Material(subject="Clean subject", body=body)
        rule = UnreplacedTokenRule()

        result = rule.check(material, context, {})

        assert result.passed is False, (
            f"Expected passed=False when body contains tokens, "
            f"but got passed=True. Body: {body!r}"
        )
        assert len(result.offending_spans) > 0, (
            f"Expected at least one offending span, got none. Body: {body!r}"
        )

    @given(
        subject=text_with_tokens_st(),
        context=context_st,
    )
    @settings(max_examples=200)
    def test_fails_when_subject_contains_tokens(
        self,
        subject: str,
        context: ValidationContext,
    ) -> None:
        """WHEN a material subject contains any token pattern, THEN the rule
        returns passed=False.

        **Validates: Requirements 2.1**
        """
        material = Material(subject=subject, body="Clean body text here.")
        rule = UnreplacedTokenRule()

        result = rule.check(material, context, {})

        assert result.passed is False, (
            f"Expected passed=False when subject contains tokens, "
            f"but got passed=True. Subject: {subject!r}"
        )
        assert len(result.offending_spans) > 0, (
            f"Expected at least one offending span, got none. Subject: {subject!r}"
        )

    @given(
        body=safe_text_st,
        subject=safe_text_st,
        context=context_st,
    )
    @settings(max_examples=200)
    def test_passes_when_no_tokens_present(
        self,
        body: str,
        subject: str,
        context: ValidationContext,
    ) -> None:
        """WHEN neither body nor subject contain any token pattern, THEN the
        rule returns passed=True with no offending spans.

        **Validates: Requirements 2.1**
        """
        # Double-check our generator didn't accidentally produce a token
        assume(not text_contains_token(body))
        assume(not text_contains_token(subject))

        material = Material(subject=subject, body=body)
        rule = UnreplacedTokenRule()

        result = rule.check(material, context, {})

        assert result.passed is True, (
            f"Expected passed=True when no tokens present, "
            f"but got passed=False. Body: {body!r}, Subject: {subject!r}"
        )
        assert len(result.offending_spans) == 0, (
            f"Expected no offending spans, got {len(result.offending_spans)}. "
            f"Spans: {result.offending_spans}"
        )

    @given(
        body=text_with_tokens_st(),
        context=context_st,
    )
    @settings(max_examples=200)
    def test_spans_identify_actual_tokens(
        self,
        body: str,
        context: ValidationContext,
    ) -> None:
        """FOR EACH TextSpan in the result, the span text should correspond to
        an actual token pattern match at the correct position in the material.

        **Validates: Requirements 2.1**
        """
        material = Material(subject=None, body=body)
        rule = UnreplacedTokenRule()

        result = rule.check(material, context, {})

        for span in result.offending_spans:
            # Verify span text matches the substring at the given position
            if span.field_name == "body":
                actual_text = body[span.start:span.end]
            else:
                continue  # subject is None in this test

            assert actual_text == span.text, (
                f"Span text mismatch: span.text={span.text!r} but "
                f"text at [{span.start}:{span.end}]={actual_text!r}"
            )

            # Verify the span text matches at least one token pattern
            is_token = any(
                pattern.fullmatch(span.text) for pattern in TOKEN_PATTERNS
            )
            assert is_token, (
                f"Span text {span.text!r} does not match any token pattern"
            )

    @given(
        body=st.text(min_size=0, max_size=300),
        subject=st.one_of(st.none(), st.text(min_size=0, max_size=100)),
        context=context_st,
    )
    @settings(max_examples=200)
    def test_passed_iff_no_tokens_biconditional(
        self,
        body: str,
        subject: str | None,
        context: ValidationContext,
    ) -> None:
        """FOR ANY material text, passed == True if and only if no token
        patterns are present in the combined body + subject.

        This is the core biconditional property.

        **Validates: Requirements 2.1**
        """
        material = Material(subject=subject, body=body)
        rule = UnreplacedTokenRule()

        result = rule.check(material, context, {})

        # Determine expected result by checking both fields
        combined_has_tokens = text_contains_token(body) or text_contains_token(
            subject or ""
        )

        if combined_has_tokens:
            assert result.passed is False, (
                f"Expected passed=False when tokens present. "
                f"Body: {body!r}, Subject: {subject!r}"
            )
        else:
            assert result.passed is True, (
                f"Expected passed=True when no tokens present. "
                f"Body: {body!r}, Subject: {subject!r}"
            )
