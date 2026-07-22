# Feature: internal-profile-enrichment, Property 5: Competency Candidate Parsing Completeness
"""Property-based tests for CompetencyExtractor._parse_candidates completeness.

Tests that:
1. For any valid JSON array of candidate objects, the parser produces
   CompetencyCandidate objects each with non-empty category, non-empty name,
   confidence in {"strong", "inferred"}, and source_url matching the input.
2. The parser never crashes — returns [] on invalid/malformed input.

**Validates: Requirements 2.1, 2.3**
"""

from __future__ import annotations

import json

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.competency_extractor import CompetencyExtractor, CompetencyCandidate


# ─── Strategies ───────────────────────────────────────────────────────────────

# Valid categories as specified in the LLM prompts
VALID_CATEGORIES = [
    "technology",
    "publication",
    "certification",
    "course",
    "project",
    "community_role",
]

# Valid confidence levels
VALID_CONFIDENCES = ["strong", "inferred"]

# Strategy for non-empty text fields (names, summaries)
non_empty_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "S", "Z"),
        blacklist_characters="\x00",
    ),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip() != "")


# Strategy for a single valid candidate dict
@st.composite
def valid_candidate_dict_st(draw) -> dict:
    """Generate a valid candidate dictionary with all required fields."""
    category = draw(st.sampled_from(VALID_CATEGORIES))
    name = draw(non_empty_text_st)
    evidence_summary = draw(non_empty_text_st)
    confidence = draw(st.sampled_from(VALID_CONFIDENCES))
    return {
        "category": category,
        "name": name,
        "evidence_summary": evidence_summary,
        "confidence": confidence,
    }


# Strategy for a list of valid candidate dicts
valid_candidate_list_st = st.lists(
    valid_candidate_dict_st(),
    min_size=1,
    max_size=10,
)


# Strategy for source URLs
source_url_st = st.from_regex(
    r"https://[a-z]{3,12}\.[a-z]{2,4}/[a-z0-9\-]{1,20}",
    fullmatch=True,
)


# Strategy for arbitrary/malformed strings (to test robustness)
malformed_input_st = st.one_of(
    st.text(min_size=0, max_size=500),
    st.just(""),
    st.just("null"),
    st.just("undefined"),
    st.just("{not json}"),
    st.just("[{]"),
    st.just("```json\n[broken```"),
    st.binary().map(lambda b: b.decode("utf-8", errors="replace")),
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_extractor() -> CompetencyExtractor:
    """Create a CompetencyExtractor instance with a dummy LLM router.

    We're testing _parse_candidates directly, so the LLM router is unused.
    """
    # _parse_candidates is a sync method that doesn't use the LLM router,
    # so we can pass None safely.
    return CompetencyExtractor(llm_router=None)  # type: ignore[arg-type]


# ─── Property 5: Competency Candidate Parsing Completeness ────────────────────


class TestProperty5CandidateParsingCompleteness:
    """Property 5: Competency Candidate Parsing Completeness.

    **Validates: Requirements 2.1, 2.3**

    Key invariants:
    - For any valid JSON array of candidate objects, the parser produces
      CompetencyCandidate objects each with non-empty category, non-empty
      name, confidence in {"strong", "inferred"}, and source_url matching
      the input source_url.
    - The parser never crashes on any input (returns [] for invalid input).
    """

    @given(candidates=valid_candidate_list_st, source_url=source_url_st)
    @settings(max_examples=200)
    def test_valid_candidates_parsed_with_correct_fields(
        self, candidates: list[dict], source_url: str
    ) -> None:
        """FOR ANY valid JSON array of candidate objects, the parser produces
        CompetencyCandidate objects each with non-empty category, non-empty
        name, confidence in {"strong", "inferred"}, and source_url matching
        the input.

        **Validates: Requirements 2.1, 2.3**
        """
        extractor = _make_extractor()
        json_input = json.dumps(candidates)

        result = extractor._parse_candidates(json_input, source_url)

        # Each valid candidate with a non-empty name should produce a result
        assert len(result) == len(candidates), (
            f"Parser produced {len(result)} candidates from {len(candidates)} inputs.\n"
            f"Input: {json_input[:200]}"
        )

        for i, candidate in enumerate(result):
            assert isinstance(candidate, CompetencyCandidate), (
                f"Result[{i}] is not a CompetencyCandidate: {type(candidate)}"
            )

            # Non-empty category
            assert candidate.category != "", (
                f"Result[{i}] has empty category.\n"
                f"Input item: {candidates[i]}"
            )

            # Non-empty name
            assert candidate.name != "", (
                f"Result[{i}] has empty name.\n"
                f"Input item: {candidates[i]}"
            )

            # Confidence must be one of the valid values
            assert candidate.confidence in ("strong", "inferred"), (
                f"Result[{i}] has invalid confidence: {candidate.confidence!r}.\n"
                f"Input item: {candidates[i]}"
            )

            # source_url must match the input source_url
            assert candidate.source_url == source_url, (
                f"Result[{i}] source_url mismatch.\n"
                f"Expected: {source_url!r}\n"
                f"Got: {candidate.source_url!r}"
            )

    @given(candidates=valid_candidate_list_st, source_url=source_url_st)
    @settings(max_examples=200)
    def test_valid_candidates_preserve_evidence_summary(
        self, candidates: list[dict], source_url: str
    ) -> None:
        """FOR ANY valid JSON array of candidate objects with evidence_summary,
        the parser preserves the evidence_summary value in the output.

        **Validates: Requirements 2.1, 2.3**
        """
        extractor = _make_extractor()
        json_input = json.dumps(candidates)

        result = extractor._parse_candidates(json_input, source_url)

        for i, candidate in enumerate(result):
            expected_summary = candidates[i].get("evidence_summary", "")
            assert candidate.evidence_summary == expected_summary, (
                f"Result[{i}] evidence_summary mismatch.\n"
                f"Expected: {expected_summary!r}\n"
                f"Got: {candidate.evidence_summary!r}"
            )

    @given(candidates=valid_candidate_list_st, source_url=source_url_st)
    @settings(max_examples=200)
    def test_markdown_fenced_json_parsed_correctly(
        self, candidates: list[dict], source_url: str
    ) -> None:
        """FOR ANY valid JSON array wrapped in markdown code fences,
        the parser still extracts candidates correctly.

        **Validates: Requirements 2.1, 2.3**
        """
        extractor = _make_extractor()
        json_content = json.dumps(candidates)
        # Wrap in markdown code fences (common LLM response format)
        fenced_input = f"```json\n{json_content}\n```"

        result = extractor._parse_candidates(fenced_input, source_url)

        assert len(result) == len(candidates), (
            f"Parser produced {len(result)} candidates from fenced input "
            f"with {len(candidates)} items."
        )

        for candidate in result:
            assert candidate.confidence in ("strong", "inferred")
            assert candidate.source_url == source_url
            assert candidate.name != ""

    @given(malformed=malformed_input_st, source_url=source_url_st)
    @settings(max_examples=200)
    def test_parser_never_crashes_on_invalid_input(
        self, malformed: str, source_url: str
    ) -> None:
        """FOR ANY arbitrary string input (including malformed JSON),
        the parser never raises an exception — it returns an empty list.

        **Validates: Requirements 2.1, 2.3**
        """
        extractor = _make_extractor()

        # This must never raise
        result = extractor._parse_candidates(malformed, source_url)

        assert isinstance(result, list), (
            f"Parser did not return a list for malformed input.\n"
            f"Input: {malformed[:100]!r}\n"
            f"Got: {type(result)}"
        )
        # All items in the result (if any) must be CompetencyCandidate
        for item in result:
            assert isinstance(item, CompetencyCandidate)

    @given(source_url=source_url_st)
    @settings(max_examples=50)
    def test_empty_array_returns_empty_list(self, source_url: str) -> None:
        """FOR ANY source_url, parsing an empty JSON array returns
        an empty list (no candidates).

        **Validates: Requirements 2.1, 2.3**
        """
        extractor = _make_extractor()

        result = extractor._parse_candidates("[]", source_url)

        assert result == [], (
            f"Parser should return [] for empty array input, got: {result}"
        )

    @given(candidates=valid_candidate_list_st, source_url=source_url_st)
    @settings(max_examples=100)
    def test_confidence_normalization(
        self, candidates: list[dict], source_url: str
    ) -> None:
        """FOR ANY valid candidates with invalid confidence values,
        the parser normalizes confidence to 'inferred'.

        **Validates: Requirements 2.1, 2.3**
        """
        extractor = _make_extractor()

        # Mutate candidates to have invalid confidence values
        mutated = []
        for c in candidates:
            mutated_item = dict(c)
            mutated_item["confidence"] = "INVALID_VALUE"
            mutated.append(mutated_item)

        json_input = json.dumps(mutated)
        result = extractor._parse_candidates(json_input, source_url)

        for candidate in result:
            assert candidate.confidence == "inferred", (
                f"Invalid confidence was not normalized to 'inferred'.\n"
                f"Got: {candidate.confidence!r}"
            )
