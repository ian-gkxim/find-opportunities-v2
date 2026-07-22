"""Unit tests for CompetencyExtractor.

Tests prompt template selection, content truncation, JSON parsing with
malformed responses, candidate capping, and confidence normalization.

Validates: Requirements 2.1, 2.3
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.competency_extractor import CompetencyCandidate, CompetencyExtractor


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_llm_router():
    """Mock LLM Router with configurable generate_content response."""
    router = AsyncMock()
    router.generate_content = AsyncMock(return_value="[]")
    return router


@pytest.fixture
def extractor(mock_llm_router):
    """CompetencyExtractor with mocked LLM Router."""
    return CompetencyExtractor(llm_router=mock_llm_router)


def _make_candidate_json(count: int = 1, **overrides) -> str:
    """Helper to generate valid candidate JSON arrays."""
    items = []
    for i in range(count):
        item = {
            "category": "technology",
            "name": f"Skill {i}",
            "evidence_summary": f"Evidence for skill {i}",
            "confidence": "strong",
        }
        item.update(overrides)
        items.append(item)
    return json.dumps(items)


# ─── TEST: Prompt template selection per source type ──────────────────────────


class TestPromptTemplateSelection:
    """extract() selects the correct prompt template for each source type."""

    @pytest.mark.parametrize(
        "source_type,expected_keyword",
        [
            ("github", "GitHub profile/repository"),
            ("google_scholar", "Google Scholar"),
            ("certification_badge", "certification/badge"),
            ("portfolio", "portfolio/personal website"),
        ],
    )
    async def test_selects_correct_prompt_for_known_source_types(
        self, extractor, mock_llm_router, source_type, expected_keyword
    ):
        mock_llm_router.generate_content.return_value = "[]"

        await extractor.extract(
            content="some content",
            source_type=source_type,
            source_url="https://example.com",
        )

        call_kwargs = mock_llm_router.generate_content.call_args
        prompt_sent = call_kwargs.kwargs.get("prompt") or call_kwargs[1].get(
            "prompt", call_kwargs[0][0] if call_kwargs[0] else ""
        )
        assert expected_keyword in prompt_sent

    async def test_selects_default_prompt_for_unknown_source_type(
        self, extractor, mock_llm_router
    ):
        mock_llm_router.generate_content.return_value = "[]"

        await extractor.extract(
            content="some content",
            source_type="unknown_type",
            source_url="https://example.com",
        )

        call_kwargs = mock_llm_router.generate_content.call_args
        prompt_sent = call_kwargs.kwargs.get("prompt") or call_kwargs[1].get(
            "prompt", call_kwargs[0][0] if call_kwargs[0] else ""
        )
        assert "professional web page" in prompt_sent

    async def test_selects_default_prompt_for_other_source_type(
        self, extractor, mock_llm_router
    ):
        mock_llm_router.generate_content.return_value = "[]"

        await extractor.extract(
            content="some content",
            source_type="other",
            source_url="https://example.com",
        )

        call_kwargs = mock_llm_router.generate_content.call_args
        prompt_sent = call_kwargs.kwargs.get("prompt") or call_kwargs[1].get(
            "prompt", call_kwargs[0][0] if call_kwargs[0] else ""
        )
        # "other" is not in PROMPTS dict, so should use default
        assert "professional web page" in prompt_sent


# ─── TEST: Content truncation at MAX_CONTENT_LENGTH ───────────────────────────


class TestContentTruncation:
    """extract() truncates content at 15000 chars before sending to LLM."""

    async def test_content_shorter_than_max_sent_in_full(
        self, extractor, mock_llm_router
    ):
        short_content = "Hello world" * 10  # 110 chars
        mock_llm_router.generate_content.return_value = "[]"

        await extractor.extract(
            content=short_content,
            source_type="github",
            source_url="https://github.com/user",
        )

        call_kwargs = mock_llm_router.generate_content.call_args
        prompt_sent = call_kwargs.kwargs.get("prompt") or call_kwargs[0][0]
        assert short_content in prompt_sent

    async def test_content_longer_than_max_is_truncated(
        self, extractor, mock_llm_router
    ):
        # Create content well beyond MAX_CONTENT_LENGTH (15000)
        long_content = "x" * 20_000
        mock_llm_router.generate_content.return_value = "[]"

        await extractor.extract(
            content=long_content,
            source_type="github",
            source_url="https://github.com/user",
        )

        call_kwargs = mock_llm_router.generate_content.call_args
        prompt_sent = call_kwargs.kwargs.get("prompt") or call_kwargs[0][0]
        # The prompt should contain exactly MAX_CONTENT_LENGTH chars of content
        # (not the full 20000)
        assert "x" * 20_000 not in prompt_sent
        assert "x" * 15_000 in prompt_sent

    async def test_content_exactly_at_max_sent_in_full(
        self, extractor, mock_llm_router
    ):
        exact_content = "a" * 15_000
        mock_llm_router.generate_content.return_value = "[]"

        await extractor.extract(
            content=exact_content,
            source_type="portfolio",
            source_url="https://example.com",
        )

        call_kwargs = mock_llm_router.generate_content.call_args
        prompt_sent = call_kwargs.kwargs.get("prompt") or call_kwargs[0][0]
        assert exact_content in prompt_sent


# ─── TEST: _parse_candidates with malformed JSON ─────────────────────────────


class TestParseCandidatesMalformedJson:
    """_parse_candidates() returns empty list for malformed JSON."""

    def test_plain_text_returns_empty_list(self, extractor):
        result = extractor._parse_candidates("not json at all", "https://example.com")
        assert result == []

    def test_broken_json_returns_empty_list(self, extractor):
        result = extractor._parse_candidates("{broken", "https://example.com")
        assert result == []

    def test_incomplete_array_returns_empty_list(self, extractor):
        result = extractor._parse_candidates('[{"name": "incomplete"', "https://example.com")
        assert result == []

    def test_empty_string_returns_empty_list(self, extractor):
        result = extractor._parse_candidates("", "https://example.com")
        assert result == []

    def test_none_like_returns_empty_list(self, extractor):
        result = extractor._parse_candidates("null", "https://example.com")
        assert result == []

    def test_number_returns_empty_list(self, extractor):
        result = extractor._parse_candidates("42", "https://example.com")
        assert result == []


# ─── TEST: _parse_candidates with markdown code fences ────────────────────────


class TestParseCandidatesCodeFences:
    """_parse_candidates() handles markdown code fences in LLM response."""

    def test_strips_json_code_fence(self, extractor):
        response = '```json\n[{"category": "technology", "name": "Python", "evidence_summary": "Used extensively", "confidence": "strong"}]\n```'
        result = extractor._parse_candidates(response, "https://example.com")
        assert len(result) == 1
        assert result[0].name == "Python"

    def test_strips_bare_code_fence(self, extractor):
        response = '```\n[{"category": "project", "name": "MyApp", "evidence_summary": "Owner", "confidence": "strong"}]\n```'
        result = extractor._parse_candidates(response, "https://example.com")
        assert len(result) == 1
        assert result[0].name == "MyApp"

    def test_handles_code_fence_with_extra_whitespace(self, extractor):
        response = '  ```json\n[{"category": "technology", "name": "Rust", "evidence_summary": "Contributor", "confidence": "inferred"}]\n```  '
        result = extractor._parse_candidates(response, "https://example.com")
        assert len(result) == 1
        assert result[0].name == "Rust"


# ─── TEST: MAX_CANDIDATES_PER_SOURCE cap ──────────────────────────────────────


class TestCandidateCap:
    """extract() returns at most 20 candidates even if LLM returns more."""

    async def test_caps_at_max_candidates(self, extractor, mock_llm_router):
        # LLM returns 25 candidates
        mock_llm_router.generate_content.return_value = _make_candidate_json(25)

        result = await extractor.extract(
            content="lots of content",
            source_type="github",
            source_url="https://github.com/user",
        )

        assert len(result) == 20

    async def test_does_not_cap_when_under_limit(self, extractor, mock_llm_router):
        # LLM returns 5 candidates
        mock_llm_router.generate_content.return_value = _make_candidate_json(5)

        result = await extractor.extract(
            content="some content",
            source_type="github",
            source_url="https://github.com/user",
        )

        assert len(result) == 5

    async def test_returns_exactly_max_when_at_limit(self, extractor, mock_llm_router):
        # LLM returns exactly 20 candidates
        mock_llm_router.generate_content.return_value = _make_candidate_json(20)

        result = await extractor.extract(
            content="some content",
            source_type="github",
            source_url="https://github.com/user",
        )

        assert len(result) == 20


# ─── TEST: Skipping items with empty/missing name ─────────────────────────────


class TestSkipEmptyName:
    """_parse_candidates() skips items with empty or missing name."""

    def test_skips_item_with_empty_name(self, extractor):
        items = json.dumps([
            {"category": "technology", "name": "", "evidence_summary": "ev", "confidence": "strong"},
            {"category": "technology", "name": "Valid", "evidence_summary": "ev", "confidence": "strong"},
        ])
        result = extractor._parse_candidates(items, "https://example.com")
        assert len(result) == 1
        assert result[0].name == "Valid"

    def test_skips_item_with_missing_name_key(self, extractor):
        items = json.dumps([
            {"category": "technology", "evidence_summary": "ev", "confidence": "strong"},
            {"category": "technology", "name": "Present", "evidence_summary": "ev", "confidence": "strong"},
        ])
        result = extractor._parse_candidates(items, "https://example.com")
        assert len(result) == 1
        assert result[0].name == "Present"

    def test_all_items_without_name_returns_empty(self, extractor):
        items = json.dumps([
            {"category": "technology", "name": "", "evidence_summary": "ev", "confidence": "strong"},
            {"category": "project", "evidence_summary": "ev", "confidence": "inferred"},
        ])
        result = extractor._parse_candidates(items, "https://example.com")
        assert result == []


# ─── TEST: Confidence normalization ──────────────────────────────────────────


class TestConfidenceNormalization:
    """_parse_candidates() normalizes invalid confidence values to 'inferred'."""

    def test_strong_confidence_kept(self, extractor):
        items = json.dumps([
            {"category": "technology", "name": "Python", "evidence_summary": "ev", "confidence": "strong"},
        ])
        result = extractor._parse_candidates(items, "https://example.com")
        assert result[0].confidence == "strong"

    def test_inferred_confidence_kept(self, extractor):
        items = json.dumps([
            {"category": "technology", "name": "Python", "evidence_summary": "ev", "confidence": "inferred"},
        ])
        result = extractor._parse_candidates(items, "https://example.com")
        assert result[0].confidence == "inferred"

    def test_invalid_confidence_normalized_to_inferred(self, extractor):
        items = json.dumps([
            {"category": "technology", "name": "Python", "evidence_summary": "ev", "confidence": "high"},
        ])
        result = extractor._parse_candidates(items, "https://example.com")
        assert result[0].confidence == "inferred"

    def test_missing_confidence_defaults_to_inferred(self, extractor):
        items = json.dumps([
            {"category": "technology", "name": "Python", "evidence_summary": "ev"},
        ])
        result = extractor._parse_candidates(items, "https://example.com")
        assert result[0].confidence == "inferred"

    def test_empty_confidence_normalized_to_inferred(self, extractor):
        items = json.dumps([
            {"category": "technology", "name": "Python", "evidence_summary": "ev", "confidence": ""},
        ])
        result = extractor._parse_candidates(items, "https://example.com")
        assert result[0].confidence == "inferred"
