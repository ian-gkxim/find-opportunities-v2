"""Unit tests for ReviewService._build_fresh_context_prompt().

Validates that the critique prompt:
- Contains only allowed context (material, opportunity, enrichment, beneficiary)
- Excludes drafting conversation, prompt, and reasoning references
- Includes all four critique categories in instructions
- Requires reporting on all four categories even when clean
- Contains structured JSON output format

Requirements: 1.2, 1.3, 1.4
"""

import pytest

from app.core.review_models import CritiqueCategory
from app.core.review_service import ReviewService


@pytest.fixture
def review_service():
    """Create a ReviewService with mock dependencies (not needed for prompt building)."""
    return ReviewService(
        llm_router=None,
        schema_registry=None,
        review_repository=None,
        personalization_engine=None,
    )


@pytest.fixture
def all_categories():
    return list(CritiqueCategory)


@pytest.fixture
def sample_enrichment_dict():
    return {
        "firmographics": {
            "industry": "FinTech",
            "size": "500-1000",
            "revenue": "$50M",
        },
        "technographics": {
            "stack": ["Python", "AWS", "Kubernetes"],
            "tools": ["Terraform", "Datadog"],
        },
        "intent_signals": [
            {"signal": "Hiring senior engineers", "strength": "high"},
            {"signal": "Cloud migration initiative", "strength": "medium"},
        ],
        "contact_seniority": "VP Engineering",
    }


@pytest.fixture
def sample_beneficiary_dict():
    return {
        "profile_assets": {
            "skills": ["Python", "AWS", "System Design", "Team Leadership"],
            "achievements": ["Led cloud migration for 200-person org"],
            "credentials": ["AWS Solutions Architect"],
        }
    }


class TestBuildFreshContextPrompt:
    """Tests for _build_fresh_context_prompt() method."""

    def test_contains_draft_material_in_xml_tags(
        self, review_service, all_categories, sample_enrichment_dict, sample_beneficiary_dict
    ):
        material_text = "Dear Hiring Manager, I bring experience in cloud systems."
        prompt = review_service._build_fresh_context_prompt(
            material_text=material_text,
            opportunity_description="Senior Cloud Engineer at FinTech Corp",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert "<draft_material>" in prompt
        assert material_text in prompt
        assert "</draft_material>" in prompt

    def test_contains_opportunity_in_xml_tags(
        self, review_service, all_categories, sample_enrichment_dict, sample_beneficiary_dict
    ):
        opportunity = "Senior Cloud Engineer at FinTech Corp"
        prompt = review_service._build_fresh_context_prompt(
            material_text="Some draft content",
            opportunity_description=opportunity,
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert "<opportunity>" in prompt
        assert opportunity in prompt
        assert "</opportunity>" in prompt

    def test_contains_enrichment_record_in_xml_tags(
        self, review_service, all_categories, sample_enrichment_dict, sample_beneficiary_dict
    ):
        prompt = review_service._build_fresh_context_prompt(
            material_text="Some draft content",
            opportunity_description="Role description",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert "<enrichment_record>" in prompt
        assert "</enrichment_record>" in prompt
        # Should contain enrichment data
        assert "FinTech" in prompt
        assert "firmographics" in prompt
        assert "technographics" in prompt
        assert "intent_signals" in prompt
        assert "contact_seniority" in prompt

    def test_contains_beneficiary_assets_in_xml_tags(
        self, review_service, all_categories, sample_enrichment_dict, sample_beneficiary_dict
    ):
        prompt = review_service._build_fresh_context_prompt(
            material_text="Some draft content",
            opportunity_description="Role description",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert "<beneficiary_assets>" in prompt
        assert "</beneficiary_assets>" in prompt
        assert "Python" in prompt
        assert "AWS Solutions Architect" in prompt

    def test_contains_all_four_category_instructions(
        self, review_service, all_categories, sample_enrichment_dict, sample_beneficiary_dict
    ):
        prompt = review_service._build_fresh_context_prompt(
            material_text="Some draft content",
            opportunity_description="Role description",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert "missed_keywords" in prompt
        assert "company_angles" in prompt
        assert "reframing" in prompt
        assert "tone_style" in prompt

    def test_instructs_report_all_categories_even_when_clean(
        self, review_service, all_categories, sample_enrichment_dict, sample_beneficiary_dict
    ):
        prompt = review_service._build_fresh_context_prompt(
            material_text="Some draft content",
            opportunity_description="Role description",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert "ALL four categories" in prompt
        assert "empty arrays" in prompt

    def test_excludes_drafting_conversation_references(
        self, review_service, all_categories, sample_enrichment_dict, sample_beneficiary_dict
    ):
        prompt = review_service._build_fresh_context_prompt(
            material_text="Some draft content",
            opportunity_description="Role description",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        # Explicit exclusion instruction present
        assert "Do NOT reference any drafting conversation" in prompt
        assert "prompt instructions" in prompt
        assert "reasoning chain" in prompt

    def test_contains_json_schema_output_format(
        self, review_service, all_categories, sample_enrichment_dict, sample_beneficiary_dict
    ):
        prompt = review_service._build_fresh_context_prompt(
            material_text="Some draft content",
            opportunity_description="Role description",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert "structured_edits" in prompt
        assert "narrative_findings" in prompt
        assert "old_string" in prompt
        assert "new_string" in prompt
        assert "target_material_id" in prompt
        assert "flagged_passage" in prompt

    def test_contains_role_instruction(
        self, review_service, all_categories, sample_enrichment_dict, sample_beneficiary_dict
    ):
        prompt = review_service._build_fresh_context_prompt(
            material_text="Some draft content",
            opportunity_description="Role description",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert "independent reviewer" in prompt
        assert "evaluating" in prompt

    def test_works_with_object_enrichment(self, review_service, all_categories):
        """Enrichment as object with attributes works via getattr."""

        class MockEnrichment:
            firmographics = {"industry": "Healthcare"}
            technographics = {"stack": ["Java", "Spring"]}
            intent_signals = [{"signal": "Digital transformation"}]
            contact_seniority = "CTO"

        beneficiary = {"profile_assets": {"skills": ["Java", "Architecture"]}}

        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft text",
            opportunity_description="Opportunity",
            enrichment=MockEnrichment(),
            beneficiary=beneficiary,
            categories=all_categories,
        )
        assert "Healthcare" in prompt
        assert "CTO" in prompt
        assert "Java" in prompt

    def test_works_with_object_beneficiary(self, review_service, all_categories):
        """Beneficiary as object with profile_assets attribute."""

        class MockBeneficiary:
            profile_assets = {
                "skills": ["Rust", "Go"],
                "achievements": ["Built distributed system"],
            }

        enrichment = {
            "firmographics": {},
            "technographics": {},
            "intent_signals": [],
            "contact_seniority": "",
        }

        prompt = review_service._build_fresh_context_prompt(
            material_text="Draft text",
            opportunity_description="Opportunity",
            enrichment=enrichment,
            beneficiary=MockBeneficiary(),
            categories=all_categories,
        )
        assert "Rust" in prompt
        assert "Built distributed system" in prompt

    def test_returns_string(
        self, review_service, all_categories, sample_enrichment_dict, sample_beneficiary_dict
    ):
        prompt = review_service._build_fresh_context_prompt(
            material_text="Content",
            opportunity_description="Opp",
            enrichment=sample_enrichment_dict,
            beneficiary=sample_beneficiary_dict,
            categories=all_categories,
        )
        assert isinstance(prompt, str)
        assert len(prompt) > 0
