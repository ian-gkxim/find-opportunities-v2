# Feature: sender-voice-assets, Property 1: Voice_Asset schema validation rejects invalid placement
"""Property-based test for voice asset placement validation in SchemaRegistry.

Generates random beneficiary configurations with voice asset type combinations
(valid and invalid placements), verifying that SchemaRegistry:
- Accepts writing_style and behavioral_profile ONLY on consultant beneficiaries
- Accepts brand_voice ONLY on team beneficiaries
- Rejects behavioral_profile when writing_style is not also declared

**Validates: Requirements 1.1**
"""

from pathlib import Path

import yaml
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.schema_registry import SchemaRegistry
from app.core.errors import SchemaValidationError


# ─── Strategies ───────────────────────────────────────────────────────────────

# Non-voice baseline assets that can be freely assigned
NON_VOICE_ASSETS = ["resume", "cover_letter", "instructions", "company_profile",
                    "capability_statement", "consultant_profiles", "company_documents"]

VOICE_ASSETS = ["writing_style", "behavioral_profile", "brand_voice"]

# Beneficiary id strategy: either "consultant" or "team"
beneficiary_id_strategy = st.sampled_from(["consultant", "team"])

# Strategy for non-voice baseline assets (at least one required)
non_voice_assets_strategy = st.lists(
    st.sampled_from(NON_VOICE_ASSETS), min_size=1, max_size=4, unique=True
)

# Strategy for a subset of voice assets (0 to all 3)
voice_assets_subset_strategy = st.lists(
    st.sampled_from(VOICE_ASSETS), min_size=0, max_size=3, unique=True
)


def _minimal_schema_with_beneficiary(ben_id: str, baseline_assets: list[str]) -> dict:
    """Return a minimal valid schema dict with a single beneficiary for testing."""
    return {
        "stages": [
            {"id": "find", "label": "Find", "description": "Find stage"},
        ],
        "beneficiaries": [
            {
                "id": ben_id,
                "label": ben_id.capitalize(),
                "description": f"Test {ben_id}",
                "baseline_assets": baseline_assets,
                "offerings_asset": "profiles",
                "offerings_label": "Offerings",
                "search_criteria_asset": "search_criteria",
            },
        ],
        "opportunity_types": [
            {
                "id": "test_opp",
                "label": "Test Opportunity",
                "beneficiaries": [ben_id],
                "source_asset": "test_source",
                "source_label": "Test Source",
                "find_technique": "test_find",
                "find_label": "Test Find",
                "prepare_technique": "test_prepare",
                "outreach_technique": "test_outreach",
                "pipeline_states": ["Stage1", "Stage2"],
            },
        ],
        "find_techniques": [
            {
                "id": "test_find",
                "service_class": "TestFindService",
                "description": "Test find technique",
            },
        ],
        "prepare_techniques": [
            {
                "id": "test_prepare",
                "service_class": "TestPrepareService",
                "description": "Test prepare technique",
            },
        ],
        "outreach_techniques": [
            {
                "id": "test_outreach",
                "service_class": "TestOutreachService",
                "description": "Test outreach technique",
            },
        ],
    }


def _is_valid_placement(ben_id: str, voice_assets: list[str]) -> bool:
    """Determine if a given voice asset placement is valid per the rules.

    Rules:
    - writing_style: only on consultant
    - behavioral_profile: only on consultant, AND requires writing_style
    - brand_voice: only on team
    """
    voice_set = set(voice_assets)

    # brand_voice only on team
    if "brand_voice" in voice_set and ben_id != "team":
        return False

    # writing_style and behavioral_profile only on consultant
    if ("writing_style" in voice_set or "behavioral_profile" in voice_set) and ben_id == "team":
        return False

    # behavioral_profile requires writing_style
    if "behavioral_profile" in voice_set and "writing_style" not in voice_set:
        return False

    return True


# ─── Property Tests ──────────────────────────────────────────────────────────


class TestVoiceAssetPlacementValidation:
    """Property 1: Voice_Asset schema validation rejects invalid placement."""

    @given(
        ben_id=beneficiary_id_strategy,
        non_voice=non_voice_assets_strategy,
        voice_assets=voice_assets_subset_strategy,
    )
    @settings(max_examples=200)
    def test_valid_placements_always_accepted(
        self, ben_id: str, non_voice: list[str], voice_assets: list[str], tmp_path_factory
    ) -> None:
        """WHEN voice assets are placed on the correct beneficiary type with
        correct dependencies, THEN SchemaRegistry loads without raising
        SchemaValidationError for voice asset placement.

        Valid placements:
        - writing_style on consultant
        - brand_voice on team
        - behavioral_profile + writing_style on consultant

        **Validates: Requirements 1.1**
        """
        # Only test valid combinations
        assume(_is_valid_placement(ben_id, voice_assets))

        baseline_assets = non_voice + voice_assets
        schema = _minimal_schema_with_beneficiary(ben_id, baseline_assets)

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        # Should load without SchemaValidationError related to voice placement
        registry = SchemaRegistry(schema_file)
        assert registry is not None

    @given(
        ben_id=beneficiary_id_strategy,
        non_voice=non_voice_assets_strategy,
        voice_assets=voice_assets_subset_strategy,
    )
    @settings(max_examples=200)
    def test_invalid_placements_always_rejected(
        self, ben_id: str, non_voice: list[str], voice_assets: list[str], tmp_path_factory
    ) -> None:
        """WHEN voice assets are placed on the wrong beneficiary type or
        behavioral_profile is declared without writing_style, THEN SchemaRegistry
        ALWAYS raises SchemaValidationError.

        Invalid placements:
        - brand_voice on consultant
        - writing_style on team
        - behavioral_profile on team
        - behavioral_profile without writing_style (on any beneficiary)

        **Validates: Requirements 1.1**
        """
        # Only test invalid combinations (at least one voice asset must be present)
        assume(len(voice_assets) > 0)
        assume(not _is_valid_placement(ben_id, voice_assets))

        baseline_assets = non_voice + voice_assets
        schema = _minimal_schema_with_beneficiary(ben_id, baseline_assets)

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        # SchemaRegistry MUST raise SchemaValidationError
        try:
            SchemaRegistry(schema_file)
            raise AssertionError(
                f"SchemaRegistry accepted invalid voice asset placement: "
                f"beneficiary='{ben_id}', voice_assets={voice_assets}"
            )
        except SchemaValidationError as exc:
            # Verify the error is about voice asset placement
            assert exc.entity_id == ben_id, (
                f"Expected entity_id='{ben_id}', got entity_id='{exc.entity_id}'"
            )

    @given(
        non_voice=non_voice_assets_strategy,
    )
    @settings(max_examples=50)
    def test_brand_voice_on_consultant_always_rejected(
        self, non_voice: list[str], tmp_path_factory
    ) -> None:
        """WHEN brand_voice is placed on a consultant beneficiary, THEN
        SchemaRegistry ALWAYS raises SchemaValidationError mentioning brand_voice.

        **Validates: Requirements 1.1**
        """
        baseline_assets = non_voice + ["brand_voice"]
        schema = _minimal_schema_with_beneficiary("consultant", baseline_assets)

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        try:
            SchemaRegistry(schema_file)
            raise AssertionError(
                "SchemaRegistry accepted brand_voice on consultant"
            )
        except SchemaValidationError as exc:
            assert exc.entity_id == "consultant"
            assert "brand_voice" in str(exc)

    @given(
        non_voice=non_voice_assets_strategy,
        consultant_voice=st.sampled_from(["writing_style", "behavioral_profile"]),
    )
    @settings(max_examples=50)
    def test_writing_style_or_behavioral_profile_on_team_always_rejected(
        self, non_voice: list[str], consultant_voice: str, tmp_path_factory
    ) -> None:
        """WHEN writing_style or behavioral_profile is placed on a team beneficiary,
        THEN SchemaRegistry ALWAYS raises SchemaValidationError.

        **Validates: Requirements 1.1**
        """
        baseline_assets = non_voice + [consultant_voice]
        schema = _minimal_schema_with_beneficiary("team", baseline_assets)

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        try:
            SchemaRegistry(schema_file)
            raise AssertionError(
                f"SchemaRegistry accepted {consultant_voice} on team"
            )
        except SchemaValidationError as exc:
            assert exc.entity_id == "team"
            assert "writing_style" in str(exc) or "behavioral_profile" in str(exc)

    @given(
        non_voice=non_voice_assets_strategy,
    )
    @settings(max_examples=50)
    def test_behavioral_profile_without_writing_style_always_rejected(
        self, non_voice: list[str], tmp_path_factory
    ) -> None:
        """WHEN behavioral_profile is declared on consultant WITHOUT writing_style,
        THEN SchemaRegistry ALWAYS raises SchemaValidationError mentioning
        the dependency requirement.

        **Validates: Requirements 1.1**
        """
        baseline_assets = non_voice + ["behavioral_profile"]
        schema = _minimal_schema_with_beneficiary("consultant", baseline_assets)

        tmp_path = tmp_path_factory.mktemp("schema")
        schema_file = tmp_path / "schema.yaml"
        schema_file.write_text(yaml.dump(schema), encoding="utf-8")

        try:
            SchemaRegistry(schema_file)
            raise AssertionError(
                "SchemaRegistry accepted behavioral_profile without writing_style"
            )
        except SchemaValidationError as exc:
            assert exc.entity_id == "consultant"
            assert "behavioral_profile" in str(exc)
            assert "writing_style" in str(exc)
