"""Unit tests for Outbound Validator blocking rules.

Tests requirement 2.1: Built-in validation rules that block outbound materials
when delivery-layer defects are detected.
"""

import pytest

from app.core.outbound_validator import (
    EmptyPersonalizationFieldRule,
    EmptySubjectRule,
    Material,
    MissingSignatureRule,
    RecipientNameMismatchRule,
    RuleSeverity,
    TextSpan,
    UnreplacedTokenRule,
    ValidationContext,
)


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


@pytest.fixture
def email_context() -> ValidationContext:
    """Standard email context for testing."""
    return ValidationContext(
        pipeline_record_id="rec-001",
        contact_first_name="John",
        contact_last_name="Doe",
        outreach_technique="cold_email_consultant",
        material_type="email",
        required_fields=["first_name", "company_name"],
    )


@pytest.fixture
def linkedin_context() -> ValidationContext:
    """Non-email context for testing channel-specific rules."""
    return ValidationContext(
        pipeline_record_id="rec-002",
        contact_first_name="Jane",
        contact_last_name="Smith",
        outreach_technique="linkedin_outreach",
        material_type="linkedin_message",
        required_fields=[],
    )


# ─── UnreplacedTokenRule ──────────────────────────────────────────────────────


class TestUnreplacedTokenRule:
    """Tests for UnreplacedTokenRule detecting template tokens."""

    def setup_method(self):
        self.rule = UnreplacedTokenRule()

    @pytest.mark.parametrize(
        "text,pattern_desc",
        [
            ("Hi {{name}}, welcome!", "double curly braces"),
            ("Hello {company}, we noticed", "single curly braces"),
            ("Please see [PLACEHOLDER] for details", "PLACEHOLDER bracket"),
            ("Dear <INSERT_NAME>, I wanted", "INSERT angle bracket"),
        ],
    )
    def test_detects_unreplaced_token_patterns(
        self, text: str, pattern_desc: str, email_context: ValidationContext
    ):
        """Each token pattern ({{...}}, {word}, [PLACEHOLDER], <INSERT...>) should fail."""
        material = Material(subject="Test Subject", body=text)
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert result.severity == RuleSeverity.BLOCKING
        assert len(result.offending_spans) >= 1

    def test_clean_text_passes(self, email_context: ValidationContext):
        """Text with no template tokens passes validation."""
        material = Material(
            subject="Meeting follow-up",
            body="Hi John, great chatting with you about the project.",
        )
        result = self.rule.check(material, email_context, {})

        assert result.passed is True
        assert result.offending_spans == []
        assert result.message == ""

    def test_detects_tokens_in_subject(self, email_context: ValidationContext):
        """Tokens in the subject line are also detected."""
        material = Material(
            subject="Hi {{name}}, quick question",
            body="Clean body text here.",
        )
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert any(span.field_name == "subject" for span in result.offending_spans)

    def test_multiple_tokens_all_reported(self, email_context: ValidationContext):
        """Multiple distinct tokens produce multiple offending spans."""
        material = Material(
            subject="Test",
            body="Hi [PLACEHOLDER], I work at <INSERT_COMPANY>.",
        )
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert len(result.offending_spans) == 2


# ─── EmptySubjectRule ─────────────────────────────────────────────────────────


class TestEmptySubjectRule:
    """Tests for EmptySubjectRule blocking empty subjects on emails."""

    def setup_method(self):
        self.rule = EmptySubjectRule()

    def test_empty_string_subject_fails_for_email(self, email_context: ValidationContext):
        """Empty string subject on email material should fail."""
        material = Material(subject="", body="Some body text")
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert result.severity == RuleSeverity.BLOCKING
        assert "empty" in result.message.lower() or "missing" in result.message.lower()

    def test_none_subject_fails_for_email(self, email_context: ValidationContext):
        """None subject on email material should fail."""
        material = Material(subject=None, body="Some body text")
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert result.severity == RuleSeverity.BLOCKING

    def test_whitespace_only_subject_fails(self, email_context: ValidationContext):
        """Whitespace-only subject on email material should fail."""
        material = Material(subject="   \t  ", body="Some body text")
        result = self.rule.check(material, email_context, {})

        assert result.passed is False

    def test_non_email_passes_even_with_empty_subject(
        self, linkedin_context: ValidationContext
    ):
        """Non-email material type passes regardless of subject."""
        material = Material(subject="", body="LinkedIn message body")
        result = self.rule.check(material, linkedin_context, {})

        assert result.passed is True

    def test_non_empty_subject_passes(self, email_context: ValidationContext):
        """Email with a valid subject passes."""
        material = Material(subject="Re: Our conversation", body="Body text")
        result = self.rule.check(material, email_context, {})

        assert result.passed is True
        assert result.message == ""


# ─── MissingSignatureRule ─────────────────────────────────────────────────────


class TestMissingSignatureRule:
    """Tests for MissingSignatureRule blocking when signature is required but absent."""

    def setup_method(self):
        self.rule = MissingSignatureRule()

    def test_required_and_missing_fails(self, email_context: ValidationContext):
        """required=True with no signature should fail."""
        material = Material(subject="Hello", body="Message body", signature=None)
        result = self.rule.check(material, email_context, {"required": True})

        assert result.passed is False
        assert result.severity == RuleSeverity.BLOCKING
        assert "signature" in result.message.lower()

    def test_required_and_present_passes(self, email_context: ValidationContext):
        """required=True with a signature present should pass."""
        material = Material(
            subject="Hello",
            body="Message body",
            signature="Best regards,\nJohn Doe\nConsultant",
        )
        result = self.rule.check(material, email_context, {"required": True})

        assert result.passed is True

    def test_not_required_and_missing_passes(self, email_context: ValidationContext):
        """required=False with no signature should pass."""
        material = Material(subject="Hello", body="Message body", signature=None)
        result = self.rule.check(material, email_context, {"required": False})

        assert result.passed is True

    def test_required_and_whitespace_only_signature_fails(
        self, email_context: ValidationContext
    ):
        """A whitespace-only signature is treated as missing."""
        material = Material(subject="Hello", body="Body", signature="   \n  ")
        result = self.rule.check(material, email_context, {"required": True})

        assert result.passed is False


# ─── RecipientNameMismatchRule ────────────────────────────────────────────────


class TestRecipientNameMismatchRule:
    """Tests for RecipientNameMismatchRule detecting wrong names in greetings."""

    def setup_method(self):
        self.rule = RecipientNameMismatchRule()

    def test_wrong_name_in_greeting_fails(self, email_context: ValidationContext):
        """'Hi Sarah' when contact is 'John' should fail with span on 'Sarah'."""
        material = Material(subject="Hello", body="Hi Sarah, I wanted to reach out.")
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert result.severity == RuleSeverity.BLOCKING
        assert len(result.offending_spans) == 1
        assert result.offending_spans[0].text == "Sarah"
        assert result.offending_spans[0].field_name == "body"

    def test_correct_first_name_passes(self, email_context: ValidationContext):
        """'Hi John' when contact is 'John' should pass."""
        material = Material(subject="Hello", body="Hi John, I wanted to reach out.")
        result = self.rule.check(material, email_context, {})

        assert result.passed is True
        assert result.offending_spans == []

    def test_no_greeting_passes(self, email_context: ValidationContext):
        """Body without a greeting pattern passes (no name to check)."""
        material = Material(
            subject="Hello",
            body="I wanted to reach out about the consulting opportunity.",
        )
        result = self.rule.check(material, email_context, {})

        assert result.passed is True

    def test_correct_last_name_passes(self, email_context: ValidationContext):
        """'Dear Doe' when contact last name is 'Doe' should pass."""
        material = Material(subject="Hello", body="Dear Doe, I wanted to connect.")
        result = self.rule.check(material, email_context, {})

        assert result.passed is True

    def test_empty_contact_name_passes(self):
        """When contact_first_name is empty, rule passes (nothing to validate)."""
        context = ValidationContext(
            pipeline_record_id="rec-003",
            contact_first_name="",
            contact_last_name="",
            outreach_technique="cold_email_consultant",
            material_type="email",
        )
        material = Material(subject="Hello", body="Hi Sarah, great to meet you.")
        result = self.rule.check(material, context, {})

        assert result.passed is True


# ─── EmptyPersonalizationFieldRule ────────────────────────────────────────────


class TestEmptyPersonalizationFieldRule:
    """Tests for EmptyPersonalizationFieldRule blocking on empty required fields."""

    def setup_method(self):
        self.rule = EmptyPersonalizationFieldRule()

    def test_required_field_empty_fails(self, email_context: ValidationContext):
        """A required field with empty value should fail."""
        material = Material(
            subject="Hello",
            body="Body text",
            personalization_fields={"first_name": "", "company_name": "Acme"},
        )
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert result.severity == RuleSeverity.BLOCKING
        assert "first_name" in result.message

    def test_all_required_fields_populated_passes(self, email_context: ValidationContext):
        """All required fields with non-empty values should pass."""
        material = Material(
            subject="Hello",
            body="Body text",
            personalization_fields={
                "first_name": "John",
                "company_name": "Acme Corp",
            },
        )
        result = self.rule.check(material, email_context, {})

        assert result.passed is True
        assert result.message == ""

    def test_whitespace_only_field_fails(self, email_context: ValidationContext):
        """A required field with whitespace-only value should fail."""
        material = Material(
            subject="Hello",
            body="Body text",
            personalization_fields={"first_name": "   ", "company_name": "Acme"},
        )
        result = self.rule.check(material, email_context, {})

        assert result.passed is False

    def test_missing_field_key_fails(self, email_context: ValidationContext):
        """A required field that is completely absent from dict should fail."""
        material = Material(
            subject="Hello",
            body="Body text",
            personalization_fields={"company_name": "Acme"},
        )
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert "first_name" in result.message

    def test_params_override_required_fields(self, email_context: ValidationContext):
        """params.required_fields overrides context.required_fields."""
        material = Material(
            subject="Hello",
            body="Body text",
            personalization_fields={"hook": ""},
        )
        result = self.rule.check(
            material, email_context, {"required_fields": ["hook"]}
        )

        assert result.passed is False
        assert "hook" in result.message
