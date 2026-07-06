"""Tests for app.core.utils module."""

import pytest

from app.core.utils import compute_content_hash, normalize_company_name, truncate_string


class TestNormalizeCompanyName:
    """Tests for company name normalization used in deduplication."""

    def test_empty_string(self):
        assert normalize_company_name("") == ""

    def test_basic_lowercasing(self):
        assert normalize_company_name("ACME") == "acme"

    def test_strips_inc_suffix(self):
        assert normalize_company_name("Acme Inc.") == "acme"

    def test_strips_llc_suffix(self):
        assert normalize_company_name("TechCo LLC") == "techco"

    def test_strips_ltd_suffix(self):
        assert normalize_company_name("Widget Ltd") == "widget"

    def test_strips_corporation(self):
        assert normalize_company_name("Big Corp Corporation") == "big"

    def test_strips_gmbh(self):
        assert normalize_company_name("Deutsche Software GmbH") == "deutsche software"

    def test_strips_multiple_suffixes(self):
        result = normalize_company_name("Global Tech Solutions Inc")
        assert result == "global"

    def test_removes_punctuation(self):
        # Apostrophe becomes space, then collapse; "Associates" is not a suffix
        assert normalize_company_name("O'Reilly & Associates") == "o reilly associates"

    def test_collapses_whitespace(self):
        assert normalize_company_name("  Foo   Bar   ") == "foo bar"

    def test_matching_variants(self):
        """Core use case: different representations of same company should match."""
        variants = [
            "Acme Inc.",
            "ACME",
            "Acme, Inc",
            "acme",
            "Acme Inc",
        ]
        normalized = {normalize_company_name(v) for v in variants}
        assert len(normalized) == 1
        assert "acme" in normalized

    def test_unicode_normalization(self):
        # NFKD decomposes ü into u + combining diaeresis; the combining mark
        # is a \w character in Python's Unicode regex, so it stays as part of the word.
        # The key behavior is that the same company with different unicode forms matches.
        result1 = normalize_company_name("München Tech")
        result2 = normalize_company_name("Mu\u0308nchen Tech")
        assert result1 == result2

    def test_preserves_meaningful_words(self):
        result = normalize_company_name("Stripe Payments")
        assert "stripe" in result
        assert "payments" in result

    def test_strips_technologies_suffix(self):
        result = normalize_company_name("Palantir Technologies")
        assert result == "palantir"

    def test_strips_consulting_suffix(self):
        result = normalize_company_name("McKinsey Consulting")
        assert result == "mckinsey"


class TestComputeContentHash:
    """Tests for SHA-256 content hashing used in LLM cache keys."""

    def test_deterministic(self):
        h1 = compute_content_hash("hello", "world")
        h2 = compute_content_hash("hello", "world")
        assert h1 == h2

    def test_returns_64_char_hex(self):
        result = compute_content_hash("test")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_different_inputs_different_hashes(self):
        h1 = compute_content_hash("prospect A", "profile 1")
        h2 = compute_content_hash("prospect B", "profile 1")
        assert h1 != h2

    def test_order_matters(self):
        h1 = compute_content_hash("a", "b")
        h2 = compute_content_hash("b", "a")
        assert h1 != h2

    def test_empty_parts(self):
        # Should not crash on empty strings
        result = compute_content_hash("", "")
        assert len(result) == 64

    def test_single_part(self):
        result = compute_content_hash("only-one-part")
        assert len(result) == 64

    def test_many_parts(self):
        result = compute_content_hash("a", "b", "c", "d", "e")
        assert len(result) == 64


class TestTruncateString:
    """Tests for string truncation utility."""

    def test_short_string_unchanged(self):
        assert truncate_string("hello", 10) == "hello"

    def test_exact_length_unchanged(self):
        assert truncate_string("hello", 5) == "hello"

    def test_truncated_with_suffix(self):
        result = truncate_string("hello world", 8)
        assert result == "hello..."
        assert len(result) == 8

    def test_custom_suffix(self):
        result = truncate_string("hello world", 9, suffix="…")
        assert result == "hello wo…"

    def test_empty_string(self):
        assert truncate_string("", 5) == ""

    def test_none_like_empty(self):
        # Empty string should be returned as-is
        assert truncate_string("", 0) == ""
