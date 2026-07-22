# Feature: sender-voice-assets, Property 5: Avoid list items appear as explicit prohibitions
"""Property-based test for PersonalizationEngine._build_avoid_prohibitions().

Generates random non-empty vocabulary_avoid lists (1-10 items, varied string
content) and verifies that every item in the avoid list appears as an explicit
prohibition directive prefixed with "NEVER" in the generation prompt output.

**Validates: Requirements 2.3**
"""

from __future__ import annotations

from unittest.mock import MagicMock, AsyncMock

from hypothesis import given, settings
from hypothesis import strategies as st

from app.core.personalization_engine import PersonalizationEngine


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for avoid list item text — varied printable content
_avoid_item_strategy = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z"),
        min_codepoint=32,
        max_codepoint=126,
    ),
    min_size=1,
    max_size=60,
).filter(lambda s: s.strip() != "")

# Strategy for non-empty avoid lists (1-10 items)
avoid_list_strategy = st.lists(
    _avoid_item_strategy,
    min_size=1,
    max_size=10,
)


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestVoiceAvoidProhibitions:
    """Property 5: Avoid list items appear as explicit prohibitions."""

    def _create_engine(self) -> PersonalizationEngine:
        """Create a PersonalizationEngine with mocked dependencies."""
        mock_llm = MagicMock()
        mock_llm.generate_content = AsyncMock(return_value="generated content")
        return PersonalizationEngine(llm_router=mock_llm)

    @given(avoid_list=avoid_list_strategy)
    @settings(max_examples=200)
    def test_every_avoid_item_appears_with_never_prefix(
        self, avoid_list: list[str]
    ) -> None:
        """FOR ANY non-empty vocabulary_avoid list, every item in the list
        appears as "NEVER: {item}" in the prohibition output from
        _build_avoid_prohibitions().

        **Validates: Requirements 2.3**
        """
        engine = self._create_engine()
        result = engine._build_avoid_prohibitions(avoid_list)

        for item in avoid_list:
            expected = f"NEVER: {item}"
            assert expected in result, (
                f"Avoid item {item!r} not found with 'NEVER:' prefix in "
                f"prohibition output. Got:\n{result}"
            )

    @given(avoid_list=avoid_list_strategy)
    @settings(max_examples=200)
    def test_prohibition_count_matches_avoid_list_length(
        self, avoid_list: list[str]
    ) -> None:
        """FOR ANY non-empty vocabulary_avoid list, the prohibition output
        contains exactly as many "NEVER:" lines as there are items in the
        avoid list.

        **Validates: Requirements 2.3**
        """
        engine = self._create_engine()
        result = engine._build_avoid_prohibitions(avoid_list)

        never_lines = [
            line for line in result.splitlines() if "NEVER:" in line
        ]
        assert len(never_lines) == len(avoid_list), (
            f"Expected {len(avoid_list)} NEVER lines, got {len(never_lines)}. "
            f"Avoid list: {avoid_list!r}\nOutput:\n{result}"
        )

    @given(avoid_list=avoid_list_strategy)
    @settings(max_examples=200)
    def test_prohibition_block_has_header(
        self, avoid_list: list[str]
    ) -> None:
        """FOR ANY non-empty vocabulary_avoid list, the prohibition output
        starts with a descriptive header line identifying the section as
        prohibitions.

        **Validates: Requirements 2.3**
        """
        engine = self._create_engine()
        result = engine._build_avoid_prohibitions(avoid_list)

        assert "PROHIBITIONS" in result, (
            f"Prohibition output missing 'PROHIBITIONS' header. Got:\n{result}"
        )
