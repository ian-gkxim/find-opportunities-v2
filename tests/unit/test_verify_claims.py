"""Unit tests for GroundingVerifier.verify_claims() and helper methods.

Validates deterministic verification logic: prospect-side exemption,
enrichment-based verification, quantified metric partial grounding,
and asset-based substring matching.

Requirements: 2.1, 2.2, 2.3
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from app.core.grounding_verifier import (
    Claim,
    ClaimCategory,
    GroundingStatus,
    GroundingVerifier,
    SourcePointer,
)


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


@dataclass
class FakeEnrichment:
    """Fake enrichment record for testing."""

    company_name: str | None = None
    employee_count: int | None = None
    revenue_range: str | None = None
    industry: str | None = None
    tech_stack: list[str] = field(default_factory=list)
    funding_stage: str | None = None
    headquarters_city: str | None = None
    headquarters_country: str | None = None


def _make_claim(
    claim_text: str,
    category: ClaimCategory = ClaimCategory.SKILL_TECHNOLOGY,
    is_prospect_side: bool = False,
) -> Claim:
    """Helper to build a Claim for testing."""
    return Claim(
        id="claim-001",
        material_id="mat-001",
        category=category,
        claim_text=claim_text,
        source_span=claim_text,
        source_span_start=0,
        source_span_end=len(claim_text),
        is_prospect_side=is_prospect_side,
    )


@pytest.fixture
def verifier():
    """Create a GroundingVerifier with mocked dependencies."""
    return GroundingVerifier(
        llm_router=MagicMock(),
        schema_registry=MagicMock(),
        db_repo=MagicMock(),
        personalization_engine=MagicMock(),
    )


@pytest.fixture
def enrichment():
    """Create a standard enrichment record for testing."""
    return FakeEnrichment(
        company_name="TechCorp",
        employee_count=250,
        revenue_range="$10M-$50M",
        industry="Software",
        tech_stack=["Python", "React", "PostgreSQL"],
        funding_stage="Series B",
        headquarters_city="San Francisco",
        headquarters_country="United States",
    )


# ─── _is_prospect_side_claim TESTS ───────────────────────────────────────────


class TestIsProspectSideClaim:
    """Tests for _is_prospect_side_claim helper method."""

    def test_returns_true_when_flag_set(self, verifier, enrichment):
        """Claim with is_prospect_side=True is detected as prospect-side."""
        claim = _make_claim("They use Python", is_prospect_side=True)
        assert verifier._is_prospect_side_claim(claim, enrichment) is True

    def test_returns_true_when_claim_mentions_company_name(self, verifier, enrichment):
        """Claim mentioning the enrichment company_name is prospect-side."""
        claim = _make_claim("TechCorp has been growing rapidly")
        assert verifier._is_prospect_side_claim(claim, enrichment) is True

    def test_returns_true_when_claim_mentions_industry(self, verifier, enrichment):
        """Claim mentioning the enrichment industry is prospect-side."""
        claim = _make_claim("The Software industry is booming")
        assert verifier._is_prospect_side_claim(claim, enrichment) is True

    def test_returns_true_when_claim_mentions_tech_stack(self, verifier, enrichment):
        """Claim mentioning a tech_stack entry is prospect-side."""
        claim = _make_claim("They use React for their frontend")
        assert verifier._is_prospect_side_claim(claim, enrichment) is True

    def test_returns_true_when_claim_mentions_employee_count(self, verifier, enrichment):
        """Claim mentioning the employee_count is prospect-side."""
        claim = _make_claim("The company has 250 employees")
        assert verifier._is_prospect_side_claim(claim, enrichment) is True

    def test_returns_true_when_claim_mentions_headquarters(self, verifier, enrichment):
        """Claim mentioning HQ city is prospect-side."""
        claim = _make_claim("Based in San Francisco")
        assert verifier._is_prospect_side_claim(claim, enrichment) is True

    def test_returns_false_for_beneficiary_claim(self, verifier, enrichment):
        """Claim about beneficiary skills is not prospect-side."""
        claim = _make_claim("10 years of Java experience")
        assert verifier._is_prospect_side_claim(claim, enrichment) is False

    def test_case_insensitive_match(self, verifier, enrichment):
        """Detection is case-insensitive."""
        claim = _make_claim("techcorp is a great company")
        assert verifier._is_prospect_side_claim(claim, enrichment) is True

    def test_returns_false_with_empty_enrichment(self, verifier):
        """Claim is not prospect-side when enrichment has no values."""
        empty_enrichment = FakeEnrichment()
        claim = _make_claim("Some generic claim about skills")
        assert verifier._is_prospect_side_claim(claim, empty_enrichment) is False


# ─── _verify_against_enrichment TESTS ────────────────────────────────────────


class TestVerifyAgainstEnrichment:
    """Tests for _verify_against_enrichment helper method."""

    def test_grounded_when_industry_matches(self, verifier, enrichment):
        """Claim about industry is grounded when it matches enrichment."""
        claim = _make_claim("TechCorp operates in the Software industry")
        result = verifier._verify_against_enrichment(claim, enrichment)

        assert result.grounding_status == GroundingStatus.GROUNDED
        assert result.source_pointer is not None
        assert result.source_pointer.asset_type == "enrichment_record"

    def test_grounded_when_tech_stack_matches(self, verifier, enrichment):
        """Claim mentioning tech stack entry is grounded."""
        claim = _make_claim("The company uses Python for backend")
        result = verifier._verify_against_enrichment(claim, enrichment)

        assert result.grounding_status == GroundingStatus.GROUNDED
        assert result.source_pointer.passage == "Python"

    def test_grounded_when_employee_count_matches(self, verifier, enrichment):
        """Claim about employee count is grounded."""
        claim = _make_claim("A team of 250 engineers")
        result = verifier._verify_against_enrichment(claim, enrichment)

        assert result.grounding_status == GroundingStatus.GROUNDED
        assert result.source_pointer.asset_id == "employee_count"

    def test_ungrounded_when_no_enrichment_match(self, verifier, enrichment):
        """Claim that doesn't match any enrichment field is ungrounded."""
        claim = _make_claim("They operate in healthcare")
        result = verifier._verify_against_enrichment(claim, enrichment)

        assert result.grounding_status == GroundingStatus.UNGROUNDED
        assert result.source_pointer is None


# ─── _verify_against_assets TESTS ────────────────────────────────────────────


class TestVerifyAgainstAssets:
    """Tests for _verify_against_assets helper method."""

    def test_grounded_when_exact_match_in_baseline(self, verifier):
        """Claim text found as substring in baseline asset is grounded."""
        claim = _make_claim("Python development")
        baseline = {"resume": "10 years of Python development experience"}
        offerings = {}

        result = verifier._verify_against_assets(claim, baseline, offerings)

        assert result.grounding_status == GroundingStatus.GROUNDED
        assert result.source_pointer is not None
        assert result.source_pointer.asset_type == "resume"

    def test_grounded_when_exact_match_in_offerings(self, verifier):
        """Claim text found in offerings asset is grounded."""
        claim = _make_claim("cloud migration")
        baseline = {}
        offerings = {"company_profile": "We specialize in cloud migration and DevOps"}

        result = verifier._verify_against_assets(claim, baseline, offerings)

        assert result.grounding_status == GroundingStatus.GROUNDED
        assert result.source_pointer.asset_type == "company_profile"

    def test_case_insensitive_matching(self, verifier):
        """Matching is case-insensitive."""
        claim = _make_claim("AWS Certified Solutions Architect")
        baseline = {"resume": "aws certified solutions architect professional"}
        offerings = {}

        result = verifier._verify_against_assets(claim, baseline, offerings)

        assert result.grounding_status == GroundingStatus.GROUNDED

    def test_ungrounded_when_no_match(self, verifier):
        """Claim with no matching text is ungrounded."""
        claim = _make_claim("PhD in Machine Learning")
        baseline = {"resume": "BSc in Computer Science, 5 years of Java experience"}
        offerings = {"company_profile": "We build web applications"}

        result = verifier._verify_against_assets(claim, baseline, offerings)

        assert result.grounding_status == GroundingStatus.UNGROUNDED
        assert result.source_pointer is None

    def test_keyword_matching_fallback(self, verifier):
        """When exact match fails, keyword matching (>70%) grounds the claim."""
        claim = _make_claim("Python Django developer")
        baseline = {"resume": "Senior Python and Django developer with extensive experience"}
        offerings = {}

        result = verifier._verify_against_assets(claim, baseline, offerings)

        assert result.grounding_status == GroundingStatus.GROUNDED
        assert result.source_pointer.confidence == 0.8

    def test_source_pointer_has_passage(self, verifier):
        """Grounded claims include the supporting passage."""
        claim = _make_claim("React development")
        baseline = {"resume": "Built frontend applications using React development for 3 years"}
        offerings = {}

        result = verifier._verify_against_assets(claim, baseline, offerings)

        assert result.grounding_status == GroundingStatus.GROUNDED
        assert "React development" in result.source_pointer.passage


# ─── _verify_quantified_metric TESTS ─────────────────────────────────────────


class TestVerifyQuantifiedMetric:
    """Tests for quantified metric verification (partially_grounded logic)."""

    def test_grounded_when_numbers_match(self, verifier):
        """Quantified metric is grounded when numbers match in asset."""
        claim = _make_claim(
            "Reduced costs by 40%",
            category=ClaimCategory.QUANTIFIED_METRIC,
        )
        baseline = {"resume": "Led initiative that reduced costs by 40% over 2 years"}
        offerings = {}

        result = verifier._verify_quantified_metric(claim, baseline, offerings)

        assert result.grounding_status == GroundingStatus.GROUNDED

    def test_partially_grounded_when_numbers_differ(self, verifier):
        """Quantified metric is partially_grounded when achievement exists but number differs."""
        claim = _make_claim(
            "Reduced costs by 50%",
            category=ClaimCategory.QUANTIFIED_METRIC,
        )
        baseline = {"resume": "Led initiative that reduced costs by 30% over 2 years"}
        offerings = {}

        result = verifier._verify_quantified_metric(claim, baseline, offerings)

        assert result.grounding_status == GroundingStatus.PARTIALLY_GROUNDED
        assert result.discrepancy is not None
        assert "50%" in result.discrepancy
        assert "30%" in result.discrepancy or "2" in result.discrepancy

    def test_partially_grounded_when_no_number_in_source(self, verifier):
        """Quantified metric is partially_grounded when achievement exists without a number."""
        claim = _make_claim(
            "Managed team of 15 developers",
            category=ClaimCategory.QUANTIFIED_METRIC,
        )
        baseline = {"resume": "Managed team of developers on multiple projects"}
        offerings = {}

        result = verifier._verify_quantified_metric(claim, baseline, offerings)

        assert result.grounding_status == GroundingStatus.PARTIALLY_GROUNDED
        assert result.discrepancy is not None
        assert result.source_pointer is not None

    def test_ungrounded_when_achievement_not_found(self, verifier):
        """Quantified metric is ungrounded when achievement text not in any asset."""
        claim = _make_claim(
            "Increased revenue by 200%",
            category=ClaimCategory.QUANTIFIED_METRIC,
        )
        baseline = {"resume": "Python developer with 5 years experience"}
        offerings = {}

        result = verifier._verify_quantified_metric(claim, baseline, offerings)

        assert result.grounding_status == GroundingStatus.UNGROUNDED

    def test_source_pointer_set_for_partially_grounded(self, verifier):
        """Partially grounded claims include source_pointer."""
        claim = _make_claim(
            "Improved performance by 60%",
            category=ClaimCategory.QUANTIFIED_METRIC,
        )
        baseline = {"resume": "Improved performance by 35% through optimization"}
        offerings = {}

        result = verifier._verify_quantified_metric(claim, baseline, offerings)

        assert result.grounding_status == GroundingStatus.PARTIALLY_GROUNDED
        assert result.source_pointer is not None
        assert result.source_pointer.asset_type == "resume"


# ─── verify_claims INTEGRATION TESTS ─────────────────────────────────────────


class TestVerifyClaims:
    """Integration tests for the full verify_claims dispatch logic."""

    def test_prospect_side_dispatches_to_enrichment(self, verifier, enrichment):
        """Prospect-side claims are verified against enrichment."""
        claim = _make_claim(
            "TechCorp uses Python and React",
            is_prospect_side=True,
        )

        results = verifier.verify_claims([claim], {}, {}, enrichment)

        assert len(results) == 1
        assert results[0].grounding_status == GroundingStatus.GROUNDED
        assert results[0].source_pointer.asset_type == "enrichment_record"

    def test_quantified_metric_uses_special_logic(self, verifier, enrichment):
        """QUANTIFIED_METRIC claims use the quantified metric verifier."""
        claim = _make_claim(
            "Increased revenue by 200%",
            category=ClaimCategory.QUANTIFIED_METRIC,
        )
        baseline = {"resume": "Increased revenue by 150% through strategic initiatives"}
        empty_enrichment = FakeEnrichment()

        results = verifier.verify_claims([claim], baseline, {}, empty_enrichment)

        assert len(results) == 1
        # Achievement text matches but numbers differ
        assert results[0].grounding_status == GroundingStatus.PARTIALLY_GROUNDED

    def test_regular_claim_dispatches_to_assets(self, verifier):
        """Non-prospect, non-metric claims are verified against assets."""
        claim = _make_claim(
            "AWS Certified Developer",
            category=ClaimCategory.CREDENTIAL_CERTIFICATION,
        )
        baseline = {"resume": "Holds AWS Certified Developer certification"}
        empty_enrichment = FakeEnrichment()

        results = verifier.verify_claims([claim], baseline, {}, empty_enrichment)

        assert len(results) == 1
        assert results[0].grounding_status == GroundingStatus.GROUNDED

    def test_multiple_claims_verified_independently(self, verifier, enrichment):
        """Each claim is verified independently and all get a status."""
        claims = [
            _make_claim("TechCorp is growing", is_prospect_side=True),
            _make_claim(
                "Delivered 3 projects on time",
                category=ClaimCategory.QUANTIFIED_METRIC,
            ),
            _make_claim(
                "Expert in Kubernetes",
                category=ClaimCategory.SKILL_TECHNOLOGY,
            ),
        ]
        baseline = {"resume": "Expert in Kubernetes and Docker orchestration"}

        results = verifier.verify_claims(claims, baseline, {}, enrichment)

        assert len(results) == 3
        # All claims should have a grounding_status assigned
        assert all(r.grounding_status is not None for r in results)

    def test_all_grounded_when_everything_matches(self, verifier):
        """When all claims match assets, all are grounded."""
        claims = [
            _make_claim("Java development", category=ClaimCategory.SKILL_TECHNOLOGY),
            _make_claim("Led API redesign", category=ClaimCategory.ACHIEVEMENT_OUTCOME),
        ]
        baseline = {
            "resume": "10 years of Java development. Led API redesign at previous company."
        }
        empty_enrichment = FakeEnrichment()

        results = verifier.verify_claims(claims, baseline, {}, empty_enrichment)

        assert all(r.grounding_status == GroundingStatus.GROUNDED for r in results)

    def test_ungrounded_when_nothing_matches(self, verifier):
        """When no assets support the claims, all are ungrounded."""
        claims = [
            _make_claim("PhD in Physics", category=ClaimCategory.CREDENTIAL_CERTIFICATION),
            _make_claim("Worked at NASA", category=ClaimCategory.NAMED_CLIENT_EMPLOYER),
        ]
        baseline = {"resume": "BSc Computer Science. 3 years at a startup."}
        empty_enrichment = FakeEnrichment()

        results = verifier.verify_claims(claims, baseline, {}, empty_enrichment)

        assert all(r.grounding_status == GroundingStatus.UNGROUNDED for r in results)
