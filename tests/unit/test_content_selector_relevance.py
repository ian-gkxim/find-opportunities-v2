"""Unit tests for ContentSelector._compute_relevance_score method.

Tests substring matching of opportunity keywords against unit text (case-insensitive)
and edge cases: empty keywords → 100, empty text → 0.

Requirements: 1.2
"""

import pytest

from app.core.content_selector import ContentSelector, ContentUnit, ContentUnitType


@pytest.fixture
def selector() -> ContentSelector:
    return ContentSelector()


def _make_unit(text: str) -> ContentUnit:
    """Helper to create a ContentUnit with the given text."""
    return ContentUnit(
        id="test-unit",
        unit_type=ContentUnitType.BULLET,
        text=text,
        section="experience",
        document_order=0,
    )


class TestComputeRelevanceScoreEdgeCases:
    """Edge case handling for _compute_relevance_score."""

    def test_empty_keywords_returns_100(self, selector: ContentSelector):
        """Empty keywords list → score 100 (everything is relevant by default)."""
        unit = _make_unit("Python developer with 5 years experience")
        assert selector._compute_relevance_score(unit, []) == 100

    def test_empty_text_returns_0(self, selector: ContentSelector):
        """Empty unit text → score 0."""
        unit = _make_unit("")
        assert selector._compute_relevance_score(unit, ["python"]) == 0

    def test_whitespace_only_text_returns_0(self, selector: ContentSelector):
        """Whitespace-only unit text → score 0."""
        unit = _make_unit("   \t\n  ")
        assert selector._compute_relevance_score(unit, ["python"]) == 0

    def test_empty_keywords_with_empty_text_returns_100(self, selector: ContentSelector):
        """Empty keywords takes priority over empty text."""
        unit = _make_unit("")
        assert selector._compute_relevance_score(unit, []) == 100


class TestComputeRelevanceScoreMatching:
    """Substring matching behavior for _compute_relevance_score."""

    def test_all_keywords_match(self, selector: ContentSelector):
        """All keywords found → score 100."""
        unit = _make_unit("Experienced Python developer using Django framework")
        keywords = ["python", "django"]
        assert selector._compute_relevance_score(unit, keywords) == 100

    def test_no_keywords_match(self, selector: ContentSelector):
        """No keywords found → score 0."""
        unit = _make_unit("Managed team of 5 engineers")
        keywords = ["python", "django", "flask"]
        assert selector._compute_relevance_score(unit, keywords) == 0

    def test_partial_keywords_match(self, selector: ContentSelector):
        """Some keywords match → proportional score."""
        unit = _make_unit("Built REST APIs with Python and FastAPI")
        keywords = ["python", "django", "fastapi", "rust"]
        # 2 out of 4 match (python, fastapi)
        assert selector._compute_relevance_score(unit, keywords) == 50

    def test_case_insensitive_matching(self, selector: ContentSelector):
        """Keywords and text are matched case-insensitively."""
        unit = _make_unit("PYTHON Developer with DJANGO experience")
        keywords = ["Python", "django"]
        assert selector._compute_relevance_score(unit, keywords) == 100

    def test_substring_matching(self, selector: ContentSelector):
        """Keywords are matched as substrings, not whole words."""
        unit = _make_unit("Experienced in microservices architecture")
        keywords = ["micro"]
        assert selector._compute_relevance_score(unit, keywords) == 100

    def test_single_keyword_match(self, selector: ContentSelector):
        """Single keyword match → 100."""
        unit = _make_unit("Python scripting for automation")
        keywords = ["python"]
        assert selector._compute_relevance_score(unit, keywords) == 100

    def test_single_keyword_no_match(self, selector: ContentSelector):
        """Single keyword no match → 0."""
        unit = _make_unit("Project management and planning")
        keywords = ["python"]
        assert selector._compute_relevance_score(unit, keywords) == 0

    def test_rounding_behavior(self, selector: ContentSelector):
        """Score rounds to nearest integer (1/3 → 33, 2/3 → 67)."""
        unit = _make_unit("Python is great")
        keywords = ["python", "django", "flask"]
        # 1 out of 3 = 33.33... → 33
        assert selector._compute_relevance_score(unit, keywords) == 33

    def test_two_thirds_rounding(self, selector: ContentSelector):
        """2/3 keywords → 67 (rounds to nearest)."""
        unit = _make_unit("Built APIs with Python and Django")
        keywords = ["python", "django", "rust"]
        # 2 out of 3 = 66.66... → 67
        assert selector._compute_relevance_score(unit, keywords) == 67
