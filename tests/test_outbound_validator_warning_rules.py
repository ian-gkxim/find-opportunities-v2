"""Unit tests for Outbound Validator warning rules.

Tests requirements 2.2 and 2.3: Warning-severity rules that flag potential issues
in outbound materials without blocking delivery.
"""

import pytest
import httpx

from unittest.mock import AsyncMock, patch, MagicMock

from app.core.outbound_validator import (
    DuplicateContentRule,
    LengthBoundsRule,
    LinkLivenessRule,
    MalformedUrlRule,
    Material,
    RuleSeverity,
    TextSpan,
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


# ─── LengthBoundsRule ─────────────────────────────────────────────────────────


class TestLengthBoundsRule:
    """Tests for LengthBoundsRule checking body length within configured bounds."""

    def setup_method(self):
        self.rule = LengthBoundsRule()

    def test_49_chars_below_min_fails(self, email_context: ValidationContext):
        """Body of 49 chars fails when min is 50 (default)."""
        material = Material(subject="Subject", body="a" * 49)
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert result.severity == RuleSeverity.WARNING
        assert "too short" in result.message.lower()

    def test_50_chars_at_min_passes(self, email_context: ValidationContext):
        """Body of exactly 50 chars passes (min boundary inclusive)."""
        material = Material(subject="Subject", body="a" * 50)
        result = self.rule.check(material, email_context, {})

        assert result.passed is True
        assert result.message == ""

    def test_5001_chars_above_max_fails(self, email_context: ValidationContext):
        """Body of 5001 chars fails when max is 5000 (default)."""
        material = Material(subject="Subject", body="a" * 5001)
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert result.severity == RuleSeverity.WARNING
        assert "too long" in result.message.lower()

    def test_5000_chars_at_max_passes(self, email_context: ValidationContext):
        """Body of exactly 5000 chars passes (max boundary inclusive)."""
        material = Material(subject="Subject", body="a" * 5000)
        result = self.rule.check(material, email_context, {})

        assert result.passed is True
        assert result.message == ""

    def test_custom_params_override_defaults(self, email_context: ValidationContext):
        """Custom min_length and max_length params override defaults."""
        material = Material(subject="Subject", body="a" * 10)
        result = self.rule.check(
            material, email_context, {"min_length": 5, "max_length": 20}
        )

        assert result.passed is True

        # Same body against tighter bounds
        result = self.rule.check(
            material, email_context, {"min_length": 15, "max_length": 20}
        )

        assert result.passed is False
        assert "too short" in result.message.lower()


# ─── MalformedUrlRule ─────────────────────────────────────────────────────────


class TestMalformedUrlRule:
    """Tests for MalformedUrlRule detecting syntactically malformed URLs."""

    def setup_method(self):
        self.rule = MalformedUrlRule()

    def test_valid_http_url_passes(self, email_context: ValidationContext):
        """'http://valid.com' is a well-formed URL and passes."""
        material = Material(subject="Subject", body="Visit http://valid.com for details")
        result = self.rule.check(material, email_context, {})

        assert result.passed is True
        assert result.offending_spans == []

    def test_no_dot_in_netloc_fails(self, email_context: ValidationContext):
        """'http://nohost' has no dot in netloc and should fail."""
        material = Material(subject="Subject", body="Check http://nohost for info")
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert result.severity == RuleSeverity.WARNING
        assert len(result.offending_spans) >= 1
        assert "http://nohost" in result.offending_spans[0].text

    def test_www_url_passes(self, email_context: ValidationContext):
        """'www.example.com' is valid and passes."""
        material = Material(subject="Subject", body="Visit www.example.com today")
        result = self.rule.check(material, email_context, {})

        assert result.passed is True

    def test_body_with_no_urls_passes(self, email_context: ValidationContext):
        """Body text with no URLs at all passes."""
        material = Material(
            subject="Subject", body="This is a plain text email with no links."
        )
        result = self.rule.check(material, email_context, {})

        assert result.passed is True
        assert result.offending_spans == []

    def test_malformed_url_in_subject_detected(self, email_context: ValidationContext):
        """Malformed URL in subject line is also detected."""
        material = Material(subject="Visit http://badhost now", body="Clean body.")
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert any(span.field_name == "subject" for span in result.offending_spans)


# ─── DuplicateContentRule ─────────────────────────────────────────────────────


class TestDuplicateContentRule:
    """Tests for DuplicateContentRule detecting duplicate words and sentences."""

    def setup_method(self):
        self.rule = DuplicateContentRule()

    def test_consecutive_duplicate_word_fails(self, email_context: ValidationContext):
        """'the the' has a consecutive duplicate word and should fail with span."""
        material = Material(subject="Subject", body="I saw the the result today.")
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert result.severity == RuleSeverity.WARNING
        assert len(result.offending_spans) >= 1
        # The span should capture the duplicate
        assert any("the the" in span.text.lower() for span in result.offending_spans)

    def test_normal_text_passes(self, email_context: ValidationContext):
        """'This is normal text' has no duplicates and should pass."""
        material = Material(subject="Subject", body="This is normal text.")
        result = self.rule.check(material, email_context, {})

        assert result.passed is True
        assert result.offending_spans == []

    def test_repeated_sentences_fail(self, email_context: ValidationContext):
        """Repeated sentences should be detected as duplicate content."""
        material = Material(
            subject="Subject",
            body="This is great. I love it. This is great. Something else.",
        )
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert len(result.offending_spans) >= 1

    def test_different_case_duplicate_word_detected(
        self, email_context: ValidationContext
    ):
        """Consecutive duplicate words with different case are detected (case-insensitive)."""
        material = Material(subject="Subject", body="I saw The the result.")
        result = self.rule.check(material, email_context, {})

        assert result.passed is False
        assert len(result.offending_spans) >= 1


# ─── LinkLivenessRule ─────────────────────────────────────────────────────────


class TestLinkLivenessRule:
    """Tests for LinkLivenessRule verifying URL responses (async, mocked httpx)."""

    def setup_method(self):
        self.rule = LinkLivenessRule()

    @pytest.mark.asyncio
    async def test_disabled_passes(self, email_context: ValidationContext):
        """When enabled=False in params, rule immediately passes."""
        material = Material(
            subject="Subject",
            body="Check http://example.com for info",
        )
        result = await self.rule.check(material, email_context, {"enabled": False})

        assert result.passed is True
        assert result.severity == RuleSeverity.WARNING

    @pytest.mark.asyncio
    async def test_enabled_200_response_passes(self, email_context: ValidationContext):
        """URL returning HTTP 200 should pass."""
        material = Material(
            subject="Subject",
            body="Visit http://example.com/page for details",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.rule.check(
                material, email_context, {"enabled": True}
            )

        assert result.passed is True
        assert result.offending_spans == []

    @pytest.mark.asyncio
    async def test_enabled_404_response_fails_with_warning(
        self, email_context: ValidationContext
    ):
        """URL returning HTTP 404 should fail with warning severity."""
        material = Material(
            subject="Subject",
            body="Visit http://example.com/broken for details",
        )

        mock_response = MagicMock()
        mock_response.status_code = 404

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.rule.check(
                material, email_context, {"enabled": True}
            )

        assert result.passed is False
        assert result.severity == RuleSeverity.WARNING
        assert len(result.offending_spans) >= 1
        assert "404" in result.offending_spans[0].text

    @pytest.mark.asyncio
    async def test_enabled_timeout_fails_with_warning(
        self, email_context: ValidationContext
    ):
        """URL that times out should fail with warning severity."""
        material = Material(
            subject="Subject",
            body="Visit http://slow-server.com/page for details",
        )

        mock_client = AsyncMock()
        mock_client.head = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await self.rule.check(
                material, email_context, {"enabled": True}
            )

        assert result.passed is False
        assert result.severity == RuleSeverity.WARNING
        assert len(result.offending_spans) >= 1
        assert "timeout" in result.offending_spans[0].text.lower()

    @pytest.mark.asyncio
    async def test_no_urls_passes(self, email_context: ValidationContext):
        """Body with no URLs passes even when enabled."""
        material = Material(
            subject="Subject",
            body="This email has no links at all.",
        )
        result = await self.rule.check(material, email_context, {"enabled": True})

        assert result.passed is True
        assert result.offending_spans == []
