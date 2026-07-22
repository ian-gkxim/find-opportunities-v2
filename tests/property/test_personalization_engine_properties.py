# Feature: claim-grounding-verification, Property 9: Grounding constraint injection
"""Property-based tests for PersonalizationEngine grounding constraint injection.

Tests that the generation prompt built by `_build_prompt()` always includes
the GROUNDING_CONSTRAINT_INJECTION text for every material type, regardless
of enrichment data availability.

**Validates: Requirement 4, AC 1**
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.personalization_engine import (
    EnrichmentData,
    MaterialType,
    PersonalizationEngine,
)
from app.core.grounding_prompts import GROUNDING_CONSTRAINT_INJECTION


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for material types — all four valid types
material_type_st = st.sampled_from([mt.value for mt in MaterialType])

# Strategy for tone descriptions
tone_st = st.sampled_from([
    "company-vision and ROI-focused",
    "implementation-focused and team-impact",
    "hands-on and collaboration-focused",
])

# Strategy for enrichment fields that may or may not be present
available_fields_st = st.lists(
    st.sampled_from([
        "industry", "tech_stack", "company_size",
        "recent_funding", "intent_signals", "hooks",
    ]),
    min_size=0,
    max_size=6,
    unique=True,
)

# Strategy for hooks (may be empty or populated)
hook_st = st.fixed_dictionaries({
    "type": st.sampled_from(["news", "job_posting", "tech_adoption"]),
    "topic": st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z"),
                               blacklist_characters="\x00"),
        min_size=3,
        max_size=40,
    ).filter(lambda s: s.strip() != ""),
})

hooks_st = st.lists(hook_st, min_size=0, max_size=3)

# Strategy for beneficiary context — various shapes including empty
beneficiary_asset_text_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z", "S"),
                           blacklist_characters="\x00"),
    min_size=0,
    max_size=200,
)

baseline_assets_st = st.dictionaries(
    keys=st.sampled_from(["resume", "cover_letter", "consultant_profiles"]),
    values=beneficiary_asset_text_st,
    min_size=0,
    max_size=3,
)

offerings_assets_st = st.dictionaries(
    keys=st.sampled_from(["company_profile", "capability_statement", "company_documents"]),
    values=beneficiary_asset_text_st,
    min_size=0,
    max_size=3,
)


@st.composite
def beneficiary_context_st(draw):
    """Generate a beneficiary_context dict with optional nested assets."""
    context: dict = {}
    # Optionally include baseline_assets
    if draw(st.booleans()):
        context["baseline_assets"] = draw(baseline_assets_st)
    # Optionally include offerings_assets
    if draw(st.booleans()):
        context["offerings_assets"] = draw(offerings_assets_st)
    # Optionally include flat top-level string values
    if draw(st.booleans()):
        context["extra_info"] = draw(beneficiary_asset_text_st)
    return context


# ─── Property 9: Generation prompt always includes grounding constraint injection ─


class TestProperty9GroundingConstraintInjection:
    """Property 9: Generation prompt always includes grounding constraint injection.

    **Validates: Requirement 4, AC 1**

    Key invariant: For every material type (cv, cover_letter, proposal, email),
    the generation prompt built by `_build_prompt()` always contains the
    GROUNDING_CONSTRAINT_INJECTION text, including:
    - "CRITICAL GROUNDING CONSTRAINT" marker
    - "BENEFICIARY PROFILE ASSETS" section
    """

    def _create_engine(self) -> PersonalizationEngine:
        """Create a PersonalizationEngine with mocked dependencies."""
        mock_llm = MagicMock()
        mock_llm.generate_content = AsyncMock(return_value="generated content")
        return PersonalizationEngine(llm_router=mock_llm)

    @given(
        material_type=material_type_st,
        tone=tone_st,
        available_fields=available_fields_st,
        hooks=hooks_st,
        beneficiary_context=beneficiary_context_st(),
    )
    @settings(max_examples=100)
    def test_prompt_always_contains_critical_grounding_constraint_marker(
        self,
        material_type: str,
        tone: str,
        available_fields: list[str],
        hooks: list[dict],
        beneficiary_context: dict,
    ) -> None:
        """FOR ANY material type and enrichment configuration, the prompt built
        by _build_prompt() always contains "CRITICAL GROUNDING CONSTRAINT".

        **Validates: Requirement 4, AC 1**
        """
        engine = self._create_engine()
        is_sparse = len(available_fields) < 3

        prompt = engine._build_prompt(
            material_type=material_type,
            tone=tone,
            available_fields=available_fields,
            hooks=hooks,
            is_sparse=is_sparse,
            beneficiary_context=beneficiary_context,
        )

        assert "CRITICAL GROUNDING CONSTRAINT" in prompt, (
            f"Prompt for material_type={material_type!r} is missing "
            f"'CRITICAL GROUNDING CONSTRAINT' marker. Prompt: {prompt[:200]}..."
        )

    @given(
        material_type=material_type_st,
        tone=tone_st,
        available_fields=available_fields_st,
        hooks=hooks_st,
        beneficiary_context=beneficiary_context_st(),
    )
    @settings(max_examples=100)
    def test_prompt_always_contains_beneficiary_profile_assets_section(
        self,
        material_type: str,
        tone: str,
        available_fields: list[str],
        hooks: list[dict],
        beneficiary_context: dict,
    ) -> None:
        """FOR ANY material type and enrichment configuration, the prompt built
        by _build_prompt() always contains "BENEFICIARY PROFILE ASSETS" section.

        **Validates: Requirement 4, AC 1**
        """
        engine = self._create_engine()
        is_sparse = len(available_fields) < 3

        prompt = engine._build_prompt(
            material_type=material_type,
            tone=tone,
            available_fields=available_fields,
            hooks=hooks,
            is_sparse=is_sparse,
            beneficiary_context=beneficiary_context,
        )

        assert "BENEFICIARY PROFILE ASSETS" in prompt, (
            f"Prompt for material_type={material_type!r} is missing "
            f"'BENEFICIARY PROFILE ASSETS' section. Prompt: {prompt[:200]}..."
        )

    @given(
        material_type=material_type_st,
        tone=tone_st,
        available_fields=available_fields_st,
        hooks=hooks_st,
        beneficiary_context=beneficiary_context_st(),
    )
    @settings(max_examples=100)
    def test_prompt_contains_full_grounding_constraint_structure(
        self,
        material_type: str,
        tone: str,
        available_fields: list[str],
        hooks: list[dict],
        beneficiary_context: dict,
    ) -> None:
        """FOR ANY material type, the prompt contains all key parts of the
        grounding constraint: the critical constraint marker, the no-fabrication
        instruction, and the beneficiary profile assets section.

        **Validates: Requirement 4, AC 1**
        """
        engine = self._create_engine()
        is_sparse = len(available_fields) < 3

        prompt = engine._build_prompt(
            material_type=material_type,
            tone=tone,
            available_fields=available_fields,
            hooks=hooks,
            is_sparse=is_sparse,
            beneficiary_context=beneficiary_context,
        )

        # Must contain the critical constraint marker
        assert "CRITICAL GROUNDING CONSTRAINT" in prompt

        # Must contain the no-fabrication instruction
        assert "Do NOT invent, embellish, or fabricate" in prompt, (
            f"Prompt missing no-fabrication instruction for material_type={material_type!r}"
        )

        # Must contain the beneficiary profile assets section
        assert "BENEFICIARY PROFILE ASSETS" in prompt

        # Must contain gap acknowledgment instruction
        assert "Acknowledge the gap honestly" in prompt, (
            f"Prompt missing gap acknowledgment instruction for material_type={material_type!r}"
        )

    @given(
        material_type=material_type_st,
        tone=tone_st,
    )
    @settings(max_examples=100)
    def test_constraint_present_with_no_enrichment_data(
        self,
        material_type: str,
        tone: str,
    ) -> None:
        """WHEN no enrichment data is available (empty fields, no hooks, no
        beneficiary context), the grounding constraint injection is STILL
        present in the prompt.

        **Validates: Requirement 4, AC 1**
        """
        engine = self._create_engine()

        prompt = engine._build_prompt(
            material_type=material_type,
            tone=tone,
            available_fields=[],
            hooks=[],
            is_sparse=True,
            beneficiary_context=None,
        )

        assert "CRITICAL GROUNDING CONSTRAINT" in prompt, (
            f"Grounding constraint missing when no enrichment data is available "
            f"(material_type={material_type!r})"
        )
        assert "BENEFICIARY PROFILE ASSETS" in prompt, (
            f"Beneficiary profile assets section missing when no enrichment data "
            f"is available (material_type={material_type!r})"
        )

    @given(
        material_type=material_type_st,
        tone=tone_st,
        available_fields=available_fields_st,
        hooks=hooks_st,
        beneficiary_context=beneficiary_context_st(),
    )
    @settings(max_examples=100)
    def test_constraint_present_regardless_of_sparsity(
        self,
        material_type: str,
        tone: str,
        available_fields: list[str],
        hooks: list[dict],
        beneficiary_context: dict,
    ) -> None:
        """FOR BOTH sparse (< 3 fields) and non-sparse enrichment scenarios,
        the grounding constraint injection is always present.

        **Validates: Requirement 4, AC 1**
        """
        engine = self._create_engine()

        # Test with is_sparse=True
        prompt_sparse = engine._build_prompt(
            material_type=material_type,
            tone=tone,
            available_fields=available_fields,
            hooks=hooks,
            is_sparse=True,
            beneficiary_context=beneficiary_context,
        )

        # Test with is_sparse=False
        prompt_rich = engine._build_prompt(
            material_type=material_type,
            tone=tone,
            available_fields=available_fields,
            hooks=hooks,
            is_sparse=False,
            beneficiary_context=beneficiary_context,
        )

        assert "CRITICAL GROUNDING CONSTRAINT" in prompt_sparse, (
            "Grounding constraint missing in sparse enrichment prompt"
        )
        assert "CRITICAL GROUNDING CONSTRAINT" in prompt_rich, (
            "Grounding constraint missing in rich enrichment prompt"
        )
        assert "BENEFICIARY PROFILE ASSETS" in prompt_sparse
        assert "BENEFICIARY PROFILE ASSETS" in prompt_rich
