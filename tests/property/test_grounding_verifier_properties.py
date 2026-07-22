# Feature: claim-grounding-verification, Property 6: Extraction category validity
"""Property-based tests for Grounding_Verifier claim extraction.

Tests that extraction produces claims in all and only the six defined
categories: skill_technology, achievement_outcome, quantified_metric,
credential_certification, named_client_employer, experience_duration.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.grounding_verifier import (
    Claim,
    ClaimCategory,
    GroundingStatus,
    GroundingVerifier,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

VALID_CATEGORIES = {
    "skill_technology",
    "achievement_outcome",
    "quantified_metric",
    "credential_certification",
    "named_client_employer",
    "experience_duration",
}


def _parse_claims_from_llm_response(response: dict, material_id: str) -> list[Claim]:
    """Simulate the parsing logic from an LLM extraction response into Claim objects.

    This mirrors what GroundingVerifier.extract_claims does when parsing
    the raw LLM response into domain Claim objects. Claims with invalid
    categories are rejected.
    """
    claims = []
    raw_claims = response.get("claims", [])
    for raw in raw_claims:
        category_str = raw.get("category", "")
        # Only accept valid ClaimCategory values
        try:
            category = ClaimCategory(category_str)
        except ValueError:
            # Invalid category — skip this claim (verifier would log warning)
            continue

        claims.append(
            Claim(
                id=str(uuid.uuid4()),
                material_id=material_id,
                category=category,
                claim_text=raw.get("claim_text", ""),
                source_span=raw.get("source_span", ""),
                source_span_start=raw.get("source_span_start", 0),
                source_span_end=raw.get("source_span_end", 0),
                is_prospect_side=raw.get("is_prospect_side", False),
            )
        )
    return claims


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for generating a valid ClaimCategory value
valid_category_st = st.sampled_from(list(ClaimCategory))

# Strategy for generating an invalid category string that is NOT one of the six
invalid_category_st = st.text(min_size=1, max_size=30).filter(
    lambda s: s not in VALID_CATEGORIES
)

# Strategy for generating a claim text
claim_text_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z", "S"),
                           blacklist_characters="\x00"),
    min_size=5, max_size=100,
)

# Strategy for generating a single raw claim dict with a VALID category
valid_raw_claim_st = st.fixed_dictionaries({
    "claim_text": claim_text_st,
    "category": st.sampled_from([c.value for c in ClaimCategory]),
    "source_span": claim_text_st,
    "source_span_start": st.integers(min_value=0, max_value=1000),
    "source_span_end": st.integers(min_value=1, max_value=2000),
    "is_prospect_side": st.booleans(),
})

# Strategy for generating a single raw claim dict with an INVALID category
invalid_raw_claim_st = st.fixed_dictionaries({
    "claim_text": claim_text_st,
    "category": invalid_category_st,
    "source_span": claim_text_st,
    "source_span_start": st.integers(min_value=0, max_value=1000),
    "source_span_end": st.integers(min_value=1, max_value=2000),
    "is_prospect_side": st.booleans(),
})

# Strategy for generating a mixed list of raw claims (valid + invalid categories)
mixed_claims_st = st.lists(
    st.one_of(valid_raw_claim_st, invalid_raw_claim_st),
    min_size=1, max_size=15,
)


# ─── Property 6: Extraction produces claims in all and only the six categories ─


class TestProperty6ExtractionCategoryValidity:
    """Property 6: Extraction produces claims in all and only the six defined categories.

    **Validates: Requirement 1, AC 2**
    """

    @given(raw_claims=st.lists(valid_raw_claim_st, min_size=1, max_size=20))
    @settings(max_examples=100)
    def test_all_parsed_claims_have_valid_category(
        self, raw_claims: list[dict]
    ) -> None:
        """WHEN the LLM returns claims with valid category strings, THEN every
        parsed Claim has a category in the six defined ClaimCategory values.

        **Validates: Requirement 1, AC 2**
        """
        response = {"claims": raw_claims}
        claims = _parse_claims_from_llm_response(response, material_id="mat-001")

        # Every parsed claim must have a valid ClaimCategory
        for claim in claims:
            assert isinstance(claim.category, ClaimCategory)
            assert claim.category.value in VALID_CATEGORIES

        # All raw claims had valid categories, so all should be parsed
        assert len(claims) == len(raw_claims)

    @given(raw_claims=st.lists(invalid_raw_claim_st, min_size=1, max_size=10))
    @settings(max_examples=100)
    def test_invalid_categories_are_rejected(
        self, raw_claims: list[dict]
    ) -> None:
        """WHEN the LLM returns claims with invalid category strings, THEN
        those claims are rejected and not included in the parsed output.

        **Validates: Requirement 1, AC 2**
        """
        response = {"claims": raw_claims}
        claims = _parse_claims_from_llm_response(response, material_id="mat-001")

        # No claims should be parsed since all had invalid categories
        assert len(claims) == 0

    @given(raw_claims=mixed_claims_st)
    @settings(max_examples=100)
    def test_mixed_claims_only_valid_categories_survive(
        self, raw_claims: list[dict]
    ) -> None:
        """WHEN the LLM returns a mix of valid and invalid category claims,
        THEN only claims with valid categories are included in the result,
        and no claim has a category outside the defined six.

        **Validates: Requirement 1, AC 2**
        """
        response = {"claims": raw_claims}
        claims = _parse_claims_from_llm_response(response, material_id="mat-001")

        # Count how many raw claims had valid categories
        expected_count = sum(
            1 for rc in raw_claims if rc["category"] in VALID_CATEGORIES
        )

        assert len(claims) == expected_count

        # Every surviving claim must have a valid category
        for claim in claims:
            assert isinstance(claim.category, ClaimCategory)
            assert claim.category.value in VALID_CATEGORIES

    @given(
        categories=st.lists(
            st.sampled_from([c.value for c in ClaimCategory]),
            min_size=6, max_size=20,
        )
    )
    @settings(max_examples=100)
    def test_all_six_categories_are_accepted(
        self, categories: list[str]
    ) -> None:
        """WHEN claims span all six defined categories, THEN all six are
        represented in the parsed output — the parser accepts all and only
        these categories.

        **Validates: Requirement 1, AC 2**
        """
        # Ensure we cover all six categories
        assume(set(categories) == VALID_CATEGORIES)

        raw_claims = [
            {
                "claim_text": f"Claim for {cat}",
                "category": cat,
                "source_span": f"Span for {cat}",
                "source_span_start": i * 10,
                "source_span_end": i * 10 + 20,
                "is_prospect_side": False,
            }
            for i, cat in enumerate(categories)
        ]

        response = {"claims": raw_claims}
        claims = _parse_claims_from_llm_response(response, material_id="mat-001")

        # All claims should be parsed
        assert len(claims) == len(categories)

        # All six categories should be represented
        parsed_categories = {claim.category.value for claim in claims}
        assert parsed_categories == VALID_CATEGORIES

    @given(
        valid_claims=st.lists(valid_raw_claim_st, min_size=0, max_size=10),
        invalid_claims=st.lists(invalid_raw_claim_st, min_size=0, max_size=10),
    )
    @settings(max_examples=100)
    def test_category_set_is_subset_of_defined_categories(
        self, valid_claims: list[dict], invalid_claims: list[dict]
    ) -> None:
        """FOR ANY extraction result, the set of categories in parsed claims
        is always a subset of the six defined ClaimCategory values.

        **Validates: Requirement 1, AC 2**
        """
        assume(len(valid_claims) + len(invalid_claims) > 0)

        all_raw = valid_claims + invalid_claims
        response = {"claims": all_raw}
        claims = _parse_claims_from_llm_response(response, material_id="mat-001")

        # The set of parsed categories must be a subset of the defined six
        parsed_category_values = {claim.category.value for claim in claims}
        assert parsed_category_values <= VALID_CATEGORIES



# ─── Property 7: Every extracted claim has a valid source span ────────────────

import asyncio

import pytest


# ─── Strategies for Property 7 ───────────────────────────────────────────────

# Strategy for generating non-empty material text
material_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z", "S"),
        blacklist_characters="\x00",
    ),
    min_size=10,
    max_size=300,
)


def _build_claims_with_valid_spans(material_text: str, draw):
    """Build raw claim dicts where source_span IS a substring of material_text.

    Draws random slices from the material to produce valid spans.
    """
    claims = []
    text_len = len(material_text)
    # Draw how many claims to generate (1–5)
    num_claims = draw(st.integers(min_value=1, max_value=5))
    for _ in range(num_claims):
        # Pick a valid substring from the material
        start = draw(st.integers(min_value=0, max_value=max(0, text_len - 2)))
        end = draw(st.integers(min_value=start + 1, max_value=min(start + 80, text_len)))
        source_span = material_text[start:end]
        # Only use spans that are non-empty after stripping
        if not source_span.strip():
            continue
        claims.append({
            "claim_text": f"Claim about: {source_span[:30]}",
            "category": draw(st.sampled_from([c.value for c in ClaimCategory])),
            "source_span": source_span,
            "source_span_start": start,
            "source_span_end": end,
            "is_prospect_side": draw(st.booleans()),
        })
    return claims


def _build_claims_with_invalid_spans(material_text: str, draw):
    """Build raw claim dicts where source_span is NOT in material_text."""
    claims = []
    num_claims = draw(st.integers(min_value=1, max_value=5))
    for _ in range(num_claims):
        # Generate a span guaranteed to not be in the material
        invalid_span = draw(
            st.text(
                alphabet=st.characters(
                    whitelist_categories=("L", "N"),
                    blacklist_characters="\x00",
                ),
                min_size=5,
                max_size=50,
            ).filter(lambda s: s not in material_text)
        )
        claims.append({
            "claim_text": f"Invalid claim: {invalid_span[:20]}",
            "category": draw(st.sampled_from([c.value for c in ClaimCategory])),
            "source_span": invalid_span,
            "source_span_start": 0,
            "source_span_end": len(invalid_span),
            "is_prospect_side": draw(st.booleans()),
        })
    return claims


class TestProperty7SourceSpanValidity:
    """Property 7: Every extracted claim has a valid source span.

    **Validates: Requirement 1, AC 3**

    Key invariant: For every claim `c` returned by `extract_claims(material_text, material_id)`:
    - `c.source_span in material_text` is always True
    """

    @given(data=st.data())
    @settings(max_examples=100)
    def test_all_returned_claims_have_source_span_in_material(
        self, data,
    ) -> None:
        """WHEN the LLM returns claims with source_spans that ARE substrings
        of material_text, THEN every claim returned by extract_claims has
        source_span in material_text.

        **Validates: Requirement 1, AC 3**
        """
        material_text = data.draw(material_text_st)
        assume(len(material_text.strip()) >= 5)

        valid_claims = _build_claims_with_valid_spans(material_text, data.draw)
        assume(len(valid_claims) > 0)

        # Set up mock LLM router returning the generated claims
        mock_llm = MagicMock()
        mock_llm.dispatch_extraction = AsyncMock(return_value=valid_claims)

        verifier = GroundingVerifier(
            llm_router=mock_llm,
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        claims = asyncio.run(
            verifier.extract_claims(material_text, "mat-prop7")
        )

        # PROPERTY: Every returned claim's source_span is in material_text
        for claim in claims:
            assert claim.source_span in material_text, (
                f"Claim source_span {claim.source_span!r} is not a substring "
                f"of material_text {material_text!r}"
            )

    @given(data=st.data())
    @settings(max_examples=100)
    def test_claims_with_invalid_spans_are_excluded(
        self, data,
    ) -> None:
        """WHEN the LLM returns claims with source_spans that are NOT
        substrings of material_text, THEN those claims are excluded from
        the results.

        **Validates: Requirement 1, AC 3**
        """
        material_text = data.draw(material_text_st)
        assume(len(material_text.strip()) >= 5)

        invalid_claims = _build_claims_with_invalid_spans(material_text, data.draw)
        assume(len(invalid_claims) > 0)

        # Set up mock LLM router returning only invalid-span claims
        mock_llm = MagicMock()
        mock_llm.dispatch_extraction = AsyncMock(return_value=invalid_claims)

        verifier = GroundingVerifier(
            llm_router=mock_llm,
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        claims = asyncio.run(
            verifier.extract_claims(material_text, "mat-prop7")
        )

        # PROPERTY: No claims with invalid spans are returned
        assert len(claims) == 0, (
            f"Expected 0 claims (all had invalid spans), got {len(claims)}. "
            f"Material: {material_text!r}, invalid_claims: {invalid_claims}"
        )

    @given(data=st.data())
    @settings(max_examples=100)
    def test_mixed_valid_and_invalid_spans_only_valid_survive(
        self, data,
    ) -> None:
        """WHEN the LLM returns a mix of claims with valid and invalid
        source_spans, THEN only claims with valid spans are returned,
        and every returned claim satisfies source_span in material_text.

        **Validates: Requirement 1, AC 3**
        """
        material_text = data.draw(material_text_st)
        assume(len(material_text.strip()) >= 5)

        valid_claims = _build_claims_with_valid_spans(material_text, data.draw)
        invalid_claims = _build_claims_with_invalid_spans(material_text, data.draw)
        assume(len(valid_claims) > 0 and len(invalid_claims) > 0)

        # Combine valid + invalid claims and shuffle
        all_claims = valid_claims + invalid_claims

        # Set up mock LLM router
        mock_llm = MagicMock()
        mock_llm.dispatch_extraction = AsyncMock(return_value=all_claims)

        verifier = GroundingVerifier(
            llm_router=mock_llm,
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        claims = asyncio.run(
            verifier.extract_claims(material_text, "mat-prop7")
        )

        # PROPERTY 1: Every returned claim has a valid source_span
        for claim in claims:
            assert claim.source_span in material_text, (
                f"Claim source_span {claim.source_span!r} is not in material_text"
            )

        # PROPERTY 2: The count of returned claims equals the valid claims count
        # (valid claims all have spans that ARE in the material)
        assert len(claims) == len(valid_claims), (
            f"Expected {len(valid_claims)} claims (valid spans only), got {len(claims)}"
        )


# ─── Property 3: Quantified metrics with matching achievement but differing numbers ─


class TestProperty3QuantifiedMetricPartialGrounding:
    """Property 3: Quantified metrics with matching achievement but differing numbers are partially_grounded.

    **Validates: Requirement 2, AC 3**

    Key invariant: When a QUANTIFIED_METRIC claim references an achievement
    that exists in assets BUT with a different number, the claim is marked
    `partially_grounded` and the `discrepancy` field is populated.
    When numbers match exactly, the claim is `grounded`.
    """

    # ─── Strategies ───────────────────────────────────────────────────────

    # Achievement templates: "{verb} {noun} by {X}%"
    ACHIEVEMENT_TEMPLATES = [
        "Reduced costs by",
        "Increased revenue by",
        "Improved efficiency by",
        "Boosted sales by",
        "Decreased downtime by",
        "Grew customer base by",
        "Accelerated delivery by",
        "Expanded market share by",
        "Lowered error rate by",
        "Raised conversion rate by",
    ]

    @given(
        achievement_idx=st.integers(min_value=0, max_value=9),
        claim_number=st.integers(min_value=1, max_value=99),
        asset_number=st.integers(min_value=1, max_value=99),
    )
    @settings(max_examples=100)
    def test_differing_numbers_produce_partially_grounded(
        self,
        achievement_idx: int,
        claim_number: int,
        asset_number: int,
    ) -> None:
        """WHEN a QUANTIFIED_METRIC claim states a number that differs from
        the asset's number for the same achievement, THEN the claim is
        marked `partially_grounded` and discrepancy is populated.

        **Validates: Requirement 2, AC 3**
        """
        assume(claim_number != asset_number)

        achievement = self.ACHIEVEMENT_TEMPLATES[achievement_idx]
        claim_text = f"{achievement} {claim_number}%"
        asset_text = f"{achievement} {asset_number}%"

        claim = Claim(
            id="claim-001",
            material_id="mat-001",
            category=ClaimCategory.QUANTIFIED_METRIC,
            claim_text=claim_text,
            source_span=claim_text,
            source_span_start=0,
            source_span_end=len(claim_text),
            is_prospect_side=False,
        )

        # Mock enrichment with no matching fields (ensures not prospect-side)
        mock_enrichment = MagicMock()
        mock_enrichment.company_name = None
        mock_enrichment.industry = None
        mock_enrichment.revenue_range = None
        mock_enrichment.funding_stage = None
        mock_enrichment.headquarters_city = None
        mock_enrichment.headquarters_country = None
        mock_enrichment.employee_count = None
        mock_enrichment.tech_stack = []

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        baseline_assets = {"resume": asset_text}
        offerings_assets: dict[str, str] = {}

        results = verifier.verify_claims(
            [claim], baseline_assets, offerings_assets, mock_enrichment
        )

        assert len(results) == 1
        verified_claim = results[0]
        assert verified_claim.grounding_status == GroundingStatus.PARTIALLY_GROUNDED, (
            f"Expected partially_grounded for claim '{claim_text}' against "
            f"asset '{asset_text}', got {verified_claim.grounding_status}"
        )
        assert verified_claim.discrepancy is not None, (
            f"Expected discrepancy to be populated for partially_grounded claim, "
            f"but got None. Claim: '{claim_text}', Asset: '{asset_text}'"
        )

    @given(
        achievement_idx=st.integers(min_value=0, max_value=9),
        number=st.integers(min_value=1, max_value=999),
    )
    @settings(max_examples=100)
    def test_matching_numbers_produce_grounded(
        self,
        achievement_idx: int,
        number: int,
    ) -> None:
        """WHEN a QUANTIFIED_METRIC claim states a number that matches exactly
        what appears in the asset for the same achievement, THEN the claim is
        marked `grounded`.

        **Validates: Requirement 2, AC 3**
        """
        achievement = self.ACHIEVEMENT_TEMPLATES[achievement_idx]
        claim_text = f"{achievement} {number}%"
        asset_text = f"{achievement} {number}%"

        claim = Claim(
            id="claim-002",
            material_id="mat-002",
            category=ClaimCategory.QUANTIFIED_METRIC,
            claim_text=claim_text,
            source_span=claim_text,
            source_span_start=0,
            source_span_end=len(claim_text),
            is_prospect_side=False,
        )

        mock_enrichment = MagicMock()
        mock_enrichment.company_name = None
        mock_enrichment.industry = None
        mock_enrichment.revenue_range = None
        mock_enrichment.funding_stage = None
        mock_enrichment.headquarters_city = None
        mock_enrichment.headquarters_country = None
        mock_enrichment.employee_count = None
        mock_enrichment.tech_stack = []

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        baseline_assets = {"resume": asset_text}
        offerings_assets: dict[str, str] = {}

        results = verifier.verify_claims(
            [claim], baseline_assets, offerings_assets, mock_enrichment
        )

        assert len(results) == 1
        verified_claim = results[0]
        assert verified_claim.grounding_status == GroundingStatus.GROUNDED, (
            f"Expected grounded for claim '{claim_text}' against "
            f"asset '{asset_text}', got {verified_claim.grounding_status}"
        )

    @given(
        achievement_idx=st.integers(min_value=0, max_value=9),
        claim_number=st.integers(min_value=1, max_value=99),
        asset_number=st.integers(min_value=1, max_value=99),
    )
    @settings(max_examples=100)
    def test_discrepancy_contains_both_numbers(
        self,
        achievement_idx: int,
        claim_number: int,
        asset_number: int,
    ) -> None:
        """WHEN a QUANTIFIED_METRIC claim is partially_grounded due to number
        mismatch, THEN the discrepancy field references both the claimed
        number and the source number.

        **Validates: Requirement 2, AC 3**
        """
        assume(claim_number != asset_number)

        achievement = self.ACHIEVEMENT_TEMPLATES[achievement_idx]
        claim_text = f"{achievement} {claim_number}%"
        asset_text = f"{achievement} {asset_number}%"

        claim = Claim(
            id="claim-003",
            material_id="mat-003",
            category=ClaimCategory.QUANTIFIED_METRIC,
            claim_text=claim_text,
            source_span=claim_text,
            source_span_start=0,
            source_span_end=len(claim_text),
            is_prospect_side=False,
        )

        mock_enrichment = MagicMock()
        mock_enrichment.company_name = None
        mock_enrichment.industry = None
        mock_enrichment.revenue_range = None
        mock_enrichment.funding_stage = None
        mock_enrichment.headquarters_city = None
        mock_enrichment.headquarters_country = None
        mock_enrichment.employee_count = None
        mock_enrichment.tech_stack = []

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        baseline_assets = {"resume": asset_text}
        offerings_assets: dict[str, str] = {}

        results = verifier.verify_claims(
            [claim], baseline_assets, offerings_assets, mock_enrichment
        )

        assert len(results) == 1
        verified_claim = results[0]

        # Only check discrepancy content if partially_grounded
        if verified_claim.grounding_status == GroundingStatus.PARTIALLY_GROUNDED:
            assert verified_claim.discrepancy is not None
            # The discrepancy should reference the claim's number and the source's number
            assert str(claim_number) in verified_claim.discrepancy, (
                f"Discrepancy should mention claimed number {claim_number}, "
                f"but got: {verified_claim.discrepancy}"
            )
            assert str(asset_number) in verified_claim.discrepancy, (
                f"Discrepancy should mention source number {asset_number}, "
                f"but got: {verified_claim.discrepancy}"
            )


# ─── Property 2: Prospect-side claims verified against EnrichmentRecord ───────


# ─── Strategies for Property 2 ───────────────────────────────────────────────

# Enrichment field names we can populate
ENRICHMENT_FIELDS = [
    "company_name",
    "industry",
    "revenue_range",
    "funding_stage",
    "headquarters_city",
    "headquarters_country",
    "employee_count",
]

# Strategy for generating a non-empty enrichment field value (simple readable text)
enrichment_value_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Z"),
                           blacklist_characters="\x00"),
    min_size=3,
    max_size=30,
).filter(lambda s: s.strip() != "")

# Strategy for tech_stack list items
tech_stack_item_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"),
                           blacklist_characters="\x00"),
    min_size=2,
    max_size=20,
).filter(lambda s: s.strip() != "")


@st.composite
def enrichment_record_st(draw):
    """Generate a mock EnrichmentRecord with random field values."""
    record = MagicMock()
    # Always set company_name (required for meaningful tests)
    record.company_name = draw(enrichment_value_st)
    record.industry = draw(st.one_of(st.none(), enrichment_value_st))
    record.revenue_range = draw(st.one_of(st.none(), enrichment_value_st))
    record.funding_stage = draw(st.one_of(st.none(), enrichment_value_st))
    record.headquarters_city = draw(st.one_of(st.none(), enrichment_value_st))
    record.headquarters_country = draw(st.one_of(st.none(), enrichment_value_st))
    record.employee_count = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=100000)))
    record.tech_stack = draw(st.lists(tech_stack_item_st, min_size=0, max_size=5))
    return record


@st.composite
def prospect_side_claim_matching_enrichment_st(draw, enrichment):
    """Generate a prospect-side claim whose claim_text contains an enrichment field value.

    This ensures the claim WILL match during verification. The verifier checks
    `field_value.lower() in claim_text.lower()`, so we embed the exact value.
    """
    # Collect all non-None enrichment values (only those with length >= 2 to avoid
    # degenerate single-char matches)
    values = []
    if enrichment.company_name and len(str(enrichment.company_name)) >= 2:
        values.append(("company_name", str(enrichment.company_name)))
    if enrichment.industry and len(str(enrichment.industry)) >= 2:
        values.append(("industry", str(enrichment.industry)))
    if enrichment.revenue_range and len(str(enrichment.revenue_range)) >= 2:
        values.append(("revenue_range", str(enrichment.revenue_range)))
    if enrichment.funding_stage and len(str(enrichment.funding_stage)) >= 2:
        values.append(("funding_stage", str(enrichment.funding_stage)))
    if enrichment.headquarters_city and len(str(enrichment.headquarters_city)) >= 2:
        values.append(("headquarters_city", str(enrichment.headquarters_city)))
    if enrichment.headquarters_country and len(str(enrichment.headquarters_country)) >= 2:
        values.append(("headquarters_country", str(enrichment.headquarters_country)))
    if enrichment.employee_count is not None and enrichment.employee_count >= 10:
        values.append(("employee_count", str(enrichment.employee_count)))
    for tech in (enrichment.tech_stack or []):
        if len(str(tech)) >= 2:
            values.append(("tech_stack", str(tech)))

    assume(len(values) > 0)

    # Pick a random enrichment value to embed in the claim text
    field_name, field_value = draw(st.sampled_from(values))

    # Build claim text that embeds the enrichment value with context words
    # Use "uses" and "platform" as stable context words
    claim_text = f"The company uses {field_value} platform"

    claim = Claim(
        id=str(uuid.uuid4()),
        material_id="mat-prop2",
        category=draw(valid_category_st),
        claim_text=claim_text,
        source_span=claim_text,
        source_span_start=0,
        source_span_end=len(claim_text),
        is_prospect_side=True,
    )
    return claim


@st.composite
def prospect_side_claim_not_matching_enrichment_st(draw, enrichment):
    """Generate a prospect-side claim whose claim_text does NOT match any enrichment field."""
    # Collect all enrichment field values to avoid
    avoid_values = set()
    if enrichment.company_name:
        avoid_values.add(str(enrichment.company_name).lower())
    if enrichment.industry:
        avoid_values.add(str(enrichment.industry).lower())
    if enrichment.revenue_range:
        avoid_values.add(str(enrichment.revenue_range).lower())
    if enrichment.funding_stage:
        avoid_values.add(str(enrichment.funding_stage).lower())
    if enrichment.headquarters_city:
        avoid_values.add(str(enrichment.headquarters_city).lower())
    if enrichment.headquarters_country:
        avoid_values.add(str(enrichment.headquarters_country).lower())
    if enrichment.employee_count is not None:
        avoid_values.add(str(enrichment.employee_count).lower())
    for tech in (enrichment.tech_stack or []):
        avoid_values.add(str(tech).lower())

    # Generate claim text that doesn't contain any enrichment values
    claim_text = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L",),
                               blacklist_characters="\x00"),
        min_size=5,
        max_size=50,
    ).filter(lambda t: not any(v in t.lower() for v in avoid_values if v)))

    claim = Claim(
        id=str(uuid.uuid4()),
        material_id="mat-prop2",
        category=draw(valid_category_st),
        claim_text=claim_text,
        source_span=claim_text,
        source_span_start=0,
        source_span_end=len(claim_text),
        is_prospect_side=True,
    )
    return claim


class TestProperty2ProspectSideExemption:
    """Property 2: Prospect-side claims are verified against EnrichmentRecord, not Beneficiary assets.

    **Validates: Requirement 2, AC 2**

    Key invariants:
    - When claim.is_prospect_side=True, verification uses enrichment record
    - Grounded prospect-side claims have source_pointer.asset_type == "enrichment_record"
    - Prospect-side claims that would match beneficiary assets are still verified
      against enrichment only
    """

    @given(data=st.data())
    @settings(max_examples=100)
    def test_prospect_side_claim_matching_enrichment_is_grounded_via_enrichment(
        self, data,
    ) -> None:
        """WHEN a claim has is_prospect_side=True AND its claim_text matches
        an enrichment field value, THEN it is grounded with
        source_pointer.asset_type == "enrichment_record".

        **Validates: Requirement 2, AC 2**
        """
        enrichment = data.draw(enrichment_record_st())
        claim = data.draw(prospect_side_claim_matching_enrichment_st(enrichment))

        # Provide beneficiary assets that do NOT contain the enrichment values
        # to prove verification goes through enrichment, not assets
        baseline_assets = {"resume": "Unrelated resume content with no matching data."}
        offerings_assets = {"consultant_profiles": "Generic profile text here."}

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        results = verifier.verify_claims(
            claims=[claim],
            baseline_assets=baseline_assets,
            offerings_assets=offerings_assets,
            enrichment=enrichment,
        )

        assert len(results) == 1
        verified_claim = results[0]

        # PROPERTY: Prospect-side claim matching enrichment is grounded
        assert verified_claim.grounding_status == GroundingStatus.GROUNDED

        # PROPERTY: Source pointer asset_type is "enrichment_record"
        assert verified_claim.source_pointer is not None
        assert verified_claim.source_pointer.asset_type == "enrichment_record"

    @given(data=st.data())
    @settings(max_examples=100)
    def test_prospect_side_claim_not_matching_enrichment_is_ungrounded(
        self, data,
    ) -> None:
        """WHEN a claim has is_prospect_side=True AND its claim_text does NOT
        match any enrichment field value, THEN it is ungrounded (not verified
        against beneficiary assets).

        **Validates: Requirement 2, AC 2**
        """
        enrichment = data.draw(enrichment_record_st())
        claim = data.draw(prospect_side_claim_not_matching_enrichment_st(enrichment))

        # Even if assets contain the claim text, prospect-side claims
        # should NOT be checked against beneficiary assets
        baseline_assets = {"resume": f"Contains {claim.claim_text} in resume."}
        offerings_assets = {"consultant_profiles": f"Also has {claim.claim_text} here."}

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        results = verifier.verify_claims(
            claims=[claim],
            baseline_assets=baseline_assets,
            offerings_assets=offerings_assets,
            enrichment=enrichment,
        )

        assert len(results) == 1
        verified_claim = results[0]

        # PROPERTY: Prospect-side claim that doesn't match enrichment is ungrounded
        # even though beneficiary assets contain the claim text
        assert verified_claim.grounding_status == GroundingStatus.UNGROUNDED

    @given(data=st.data())
    @settings(max_examples=100)
    def test_prospect_side_claim_verified_against_enrichment_not_assets(
        self, data,
    ) -> None:
        """WHEN a claim has is_prospect_side=True AND it matches BOTH enrichment
        AND a beneficiary asset, THEN the source_pointer points to enrichment_record
        (not the beneficiary asset).

        This proves prospect-side claims bypass beneficiary asset verification.

        **Validates: Requirement 2, AC 2**
        """
        enrichment = data.draw(enrichment_record_st())
        claim = data.draw(prospect_side_claim_matching_enrichment_st(enrichment))

        # Deliberately put the same claim text in beneficiary assets
        # to prove that prospect-side claims don't use assets
        baseline_assets = {"resume": f"Profile contains {claim.claim_text} as a skill."}
        offerings_assets = {
            "consultant_profiles": f"Consultant has {claim.claim_text} expertise.",
        }

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        results = verifier.verify_claims(
            claims=[claim],
            baseline_assets=baseline_assets,
            offerings_assets=offerings_assets,
            enrichment=enrichment,
        )

        assert len(results) == 1
        verified_claim = results[0]

        # PROPERTY: Even though claim text appears in beneficiary assets,
        # prospect-side claims are verified via enrichment
        assert verified_claim.grounding_status == GroundingStatus.GROUNDED
        assert verified_claim.source_pointer is not None
        assert verified_claim.source_pointer.asset_type == "enrichment_record"
        # Source pointer should NOT reference resume or consultant_profiles
        assert verified_claim.source_pointer.asset_type != "resume"
        assert verified_claim.source_pointer.asset_type != "consultant_profiles"

    @given(data=st.data())
    @settings(max_examples=50)
    def test_non_prospect_side_claim_without_enrichment_refs_uses_assets(
        self, data,
    ) -> None:
        """WHEN a claim has is_prospect_side=False AND its claim_text does NOT
        reference any enrichment field value, THEN it is verified against
        beneficiary assets (not enrichment).

        This is the inverse property: claims that are not prospect-side and
        don't reference enrichment data go through asset verification only.

        **Validates: Requirement 2, AC 2**
        """
        enrichment = data.draw(enrichment_record_st())

        # Collect all enrichment values to avoid in claim text
        avoid_values = set()
        if enrichment.company_name:
            avoid_values.add(str(enrichment.company_name).lower())
        if enrichment.industry:
            avoid_values.add(str(enrichment.industry).lower())
        if enrichment.revenue_range:
            avoid_values.add(str(enrichment.revenue_range).lower())
        if enrichment.funding_stage:
            avoid_values.add(str(enrichment.funding_stage).lower())
        if enrichment.headquarters_city:
            avoid_values.add(str(enrichment.headquarters_city).lower())
        if enrichment.headquarters_country:
            avoid_values.add(str(enrichment.headquarters_country).lower())
        if enrichment.employee_count is not None:
            avoid_values.add(str(enrichment.employee_count).lower())
        for tech in (enrichment.tech_stack or []):
            avoid_values.add(str(tech).lower())

        # Generate a claim text that doesn't reference any enrichment values
        # Use a fixed unique phrase to guarantee no accidental match
        claim_text = "experienced in advanced quantum photonics research"
        # Verify our fixed claim text doesn't accidentally match enrichment
        assume(not any(v in claim_text.lower() for v in avoid_values if v))

        claim = Claim(
            id=str(uuid.uuid4()),
            material_id="mat-prop2-inverse",
            category=ClaimCategory.SKILL_TECHNOLOGY,
            claim_text=claim_text,
            source_span=claim_text,
            source_span_start=0,
            source_span_end=len(claim_text),
            is_prospect_side=False,  # NOT prospect-side
        )

        # Put the claim text in beneficiary assets so it WILL be grounded via assets
        baseline_assets = {
            "resume": f"Background: {claim_text} with 10 years experience.",
        }
        offerings_assets = {"consultant_profiles": "Other unrelated content."}

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        results = verifier.verify_claims(
            claims=[claim],
            baseline_assets=baseline_assets,
            offerings_assets=offerings_assets,
            enrichment=enrichment,
        )

        assert len(results) == 1
        verified_claim = results[0]

        # PROPERTY: Non-prospect-side claim verified through assets, NOT enrichment
        assert verified_claim.grounding_status == GroundingStatus.GROUNDED
        assert verified_claim.source_pointer is not None
        # The source pointer should reference the beneficiary asset, not enrichment
        assert verified_claim.source_pointer.asset_type == "resume"
        assert verified_claim.source_pointer.asset_type != "enrichment_record"



# ─── Property 12: Grounded and partially_grounded claims have source pointers ─

from dataclasses import dataclass
from typing import Optional

from app.core.grounding_verifier import (
    GroundingStatus,
    GroundingVerifier,
    SourcePointer,
)


# ─── Strategies for Property 12 ──────────────────────────────────────────────

# Generate a simple enrichment object with fields the verifier checks
@st.composite
def enrichment_st(draw):
    """Generate a mock enrichment object with common fields."""

    @dataclass
    class MockEnrichment:
        company_name: Optional[str] = None
        industry: Optional[str] = None
        revenue_range: Optional[str] = None
        funding_stage: Optional[str] = None
        headquarters_city: Optional[str] = None
        headquarters_country: Optional[str] = None
        employee_count: Optional[int] = None
        tech_stack: Optional[list] = None

    company_name = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L",)),
        min_size=4, max_size=20,
    ))
    industry = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L",)),
        min_size=4, max_size=20,
    ))
    tech_stack = draw(st.lists(
        st.text(alphabet=st.characters(whitelist_categories=("L",)), min_size=3, max_size=15),
        min_size=1, max_size=4,
    ))

    return MockEnrichment(
        company_name=company_name,
        industry=industry,
        revenue_range=draw(st.sampled_from(["$1M-$10M", "$10M-$50M", "$50M-$100M"])),
        funding_stage=draw(st.sampled_from(["Series A", "Series B", "Series C", "Seed"])),
        headquarters_city=draw(st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=4, max_size=15,
        )),
        headquarters_country=draw(st.text(
            alphabet=st.characters(whitelist_categories=("L",)),
            min_size=4, max_size=15,
        )),
        employee_count=draw(st.integers(min_value=10, max_value=10000)),
        tech_stack=tech_stack,
    )


@st.composite
def grounded_claim_and_assets_st(draw):
    """Generate a claim that WILL be grounded (claim_text appears in assets).

    Creates a claim with claim_text that is a substring of one of the
    baseline_assets, ensuring the verifier will match it.
    """
    # Generate asset content first, then derive a claim from it
    asset_text = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z"),
                               blacklist_characters="\x00"),
        min_size=30, max_size=200,
    ))
    assume(len(asset_text.strip()) >= 20)

    # Pick a substring from the asset text to use as claim_text
    text_len = len(asset_text)
    start = draw(st.integers(min_value=0, max_value=max(0, text_len - 10)))
    end = draw(st.integers(min_value=start + 5, max_value=min(start + 60, text_len)))
    claim_text = asset_text[start:end]
    assume(len(claim_text.strip()) >= 5)

    # Use a non-quantified-metric category so we go through _verify_against_assets
    category = draw(st.sampled_from([
        ClaimCategory.SKILL_TECHNOLOGY,
        ClaimCategory.ACHIEVEMENT_OUTCOME,
        ClaimCategory.CREDENTIAL_CERTIFICATION,
        ClaimCategory.NAMED_CLIENT_EMPLOYER,
        ClaimCategory.EXPERIENCE_DURATION,
    ]))

    claim = Claim(
        id=str(uuid.uuid4()),
        material_id="mat-prop12",
        category=category,
        claim_text=claim_text,
        source_span=claim_text,
        source_span_start=0,
        source_span_end=len(claim_text),
        grounding_status=None,
        source_pointer=None,
        discrepancy=None,
        is_prospect_side=False,
    )

    asset_type = draw(st.sampled_from(["resume", "cover_letter", "consultant_profiles"]))
    baseline_assets = {asset_type: asset_text}

    return claim, baseline_assets


@st.composite
def ungrounded_claim_and_assets_st(draw):
    """Generate a claim that will NOT be grounded (claim_text not in any asset).

    Generates a claim_text and assets where the claim_text keywords do NOT
    appear in the assets.
    """
    # Generate a unique claim text that won't match any asset
    unique_prefix = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L",)),
        min_size=8, max_size=15,
    ))
    claim_text = f"xyzzy{unique_prefix}plugh"  # Use unlikely sequences

    # Generate assets that definitely don't contain the claim text
    asset_text = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z"),
                               blacklist_characters="\x00"),
        min_size=30, max_size=100,
    ))
    assume(claim_text.lower() not in asset_text.lower())
    # Also ensure no keyword overlap (keywords are words > 3 chars from claim_text)
    claim_keywords = [w for w in claim_text.lower().split() if len(w) > 3]
    for kw in claim_keywords:
        assume(kw not in asset_text.lower())

    category = draw(st.sampled_from([
        ClaimCategory.SKILL_TECHNOLOGY,
        ClaimCategory.ACHIEVEMENT_OUTCOME,
        ClaimCategory.CREDENTIAL_CERTIFICATION,
        ClaimCategory.NAMED_CLIENT_EMPLOYER,
        ClaimCategory.EXPERIENCE_DURATION,
    ]))

    claim = Claim(
        id=str(uuid.uuid4()),
        material_id="mat-prop12",
        category=category,
        claim_text=claim_text,
        source_span=claim_text,
        source_span_start=0,
        source_span_end=len(claim_text),
        grounding_status=None,
        source_pointer=None,
        discrepancy=None,
        is_prospect_side=False,
    )

    baseline_assets = {"resume": asset_text}

    return claim, baseline_assets


@st.composite
def partially_grounded_metric_claim_st(draw):
    """Generate a QUANTIFIED_METRIC claim that will be partially_grounded.

    Creates a claim with a number that differs from the number in the asset,
    but where the underlying achievement text matches.
    """
    # The achievement text (without numbers)
    achievement_word = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L",)),
        min_size=5, max_size=20,
    ))
    assume(len(achievement_word.strip()) >= 5)

    # Two different numbers
    claim_number = draw(st.integers(min_value=100, max_value=999))
    asset_number = draw(st.integers(min_value=1000, max_value=9999))
    assume(str(claim_number) != str(asset_number))

    claim_text = f"{claim_number} {achievement_word} completed"
    asset_text = f"We have {asset_number} {achievement_word} completed successfully in our portfolio"

    claim = Claim(
        id=str(uuid.uuid4()),
        material_id="mat-prop12",
        category=ClaimCategory.QUANTIFIED_METRIC,
        claim_text=claim_text,
        source_span=claim_text,
        source_span_start=0,
        source_span_end=len(claim_text),
        grounding_status=None,
        source_pointer=None,
        discrepancy=None,
        is_prospect_side=False,
    )

    baseline_assets = {"resume": asset_text}

    return claim, baseline_assets


class TestProperty12SourcePointerPopulation:
    """Property 12: Grounded and partially_grounded claims have source pointers.

    **Validates: Requirement 2, AC 1**

    Key invariants:
    - Every claim with grounding_status == GROUNDED has a non-None source_pointer
    - Every claim with grounding_status == PARTIALLY_GROUNDED has a non-None source_pointer
    - Claims with grounding_status == UNGROUNDED have source_pointer == None
    """

    @given(data=st.data(), enrichment=enrichment_st())
    @settings(max_examples=100)
    def test_grounded_claims_have_source_pointer(
        self, data, enrichment,
    ) -> None:
        """WHEN verify_claims produces a claim with grounding_status == GROUNDED,
        THEN that claim's source_pointer is not None.

        **Validates: Requirement 2, AC 1**
        """
        claim, baseline_assets = data.draw(grounded_claim_and_assets_st())

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        results = verifier.verify_claims(
            claims=[claim],
            baseline_assets=baseline_assets,
            offerings_assets={},
            enrichment=enrichment,
        )

        for result_claim in results:
            if result_claim.grounding_status == GroundingStatus.GROUNDED:
                assert result_claim.source_pointer is not None, (
                    f"Claim with status GROUNDED must have source_pointer, "
                    f"but source_pointer is None. "
                    f"Claim text: {result_claim.claim_text!r}"
                )
                assert isinstance(result_claim.source_pointer, SourcePointer)
                assert result_claim.source_pointer.asset_type != ""
                assert result_claim.source_pointer.passage != ""

    @given(data=st.data(), enrichment=enrichment_st())
    @settings(max_examples=100)
    def test_ungrounded_claims_have_no_source_pointer(
        self, data, enrichment,
    ) -> None:
        """WHEN verify_claims produces a claim with grounding_status == UNGROUNDED,
        THEN that claim's source_pointer is None.

        **Validates: Requirement 2, AC 1**
        """
        claim, baseline_assets = data.draw(ungrounded_claim_and_assets_st())

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        results = verifier.verify_claims(
            claims=[claim],
            baseline_assets=baseline_assets,
            offerings_assets={},
            enrichment=enrichment,
        )

        for result_claim in results:
            if result_claim.grounding_status == GroundingStatus.UNGROUNDED:
                assert result_claim.source_pointer is None, (
                    f"Claim with status UNGROUNDED must have source_pointer == None, "
                    f"but got source_pointer={result_claim.source_pointer}. "
                    f"Claim text: {result_claim.claim_text!r}"
                )

    @given(data=st.data(), enrichment=enrichment_st())
    @settings(max_examples=100)
    def test_partially_grounded_claims_have_source_pointer(
        self, data, enrichment,
    ) -> None:
        """WHEN verify_claims produces a claim with grounding_status == PARTIALLY_GROUNDED,
        THEN that claim's source_pointer is not None.

        **Validates: Requirement 2, AC 1**
        """
        claim, baseline_assets = data.draw(partially_grounded_metric_claim_st())

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        results = verifier.verify_claims(
            claims=[claim],
            baseline_assets=baseline_assets,
            offerings_assets={},
            enrichment=enrichment,
        )

        for result_claim in results:
            if result_claim.grounding_status == GroundingStatus.PARTIALLY_GROUNDED:
                assert result_claim.source_pointer is not None, (
                    f"Claim with status PARTIALLY_GROUNDED must have source_pointer, "
                    f"but source_pointer is None. "
                    f"Claim text: {result_claim.claim_text!r}"
                )
                assert isinstance(result_claim.source_pointer, SourcePointer)
                assert result_claim.source_pointer.asset_type != ""
                assert result_claim.source_pointer.passage != ""

    @given(data=st.data(), enrichment=enrichment_st())
    @settings(max_examples=100)
    def test_source_pointer_invariant_across_mixed_claims(
        self, data, enrichment,
    ) -> None:
        """WHEN verify_claims processes a mix of claims that will be grounded,
        partially_grounded, and ungrounded, THEN:
        - All GROUNDED claims have non-None source_pointer
        - All PARTIALLY_GROUNDED claims have non-None source_pointer
        - All UNGROUNDED claims have source_pointer == None

        **Validates: Requirement 2, AC 1**
        """
        # Build a mixed set of claims and combined assets
        grounded_claim, grounded_assets = data.draw(grounded_claim_and_assets_st())
        ungrounded_claim, ungrounded_assets = data.draw(ungrounded_claim_and_assets_st())

        # Combine assets — grounded claim's assets plus ungrounded's separate assets
        combined_baseline = {}
        for k, v in grounded_assets.items():
            combined_baseline[k] = v
        # Add ungrounded assets under a different key to avoid interference
        for k, v in ungrounded_assets.items():
            combined_baseline[f"{k}_extra"] = v

        # Ensure the ungrounded claim remains ungrounded with combined assets
        assume(ungrounded_claim.claim_text.lower() not in " ".join(combined_baseline.values()).lower())
        ungrounded_keywords = [
            w for w in ungrounded_claim.claim_text.lower().split() if len(w) > 3
        ]
        combined_text_lower = " ".join(combined_baseline.values()).lower()
        matching_kw_count = sum(1 for kw in ungrounded_keywords if kw in combined_text_lower)
        # Must not match >= 70% of keywords
        if ungrounded_keywords:
            assume(matching_kw_count < max(1, len(ungrounded_keywords) * 0.7))

        claims = [grounded_claim, ungrounded_claim]

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=MagicMock(),
            personalization_engine=MagicMock(),
        )

        results = verifier.verify_claims(
            claims=claims,
            baseline_assets=combined_baseline,
            offerings_assets={},
            enrichment=enrichment,
        )

        # Verify the invariant for each status
        for result_claim in results:
            if result_claim.grounding_status == GroundingStatus.GROUNDED:
                assert result_claim.source_pointer is not None, (
                    f"GROUNDED claim must have source_pointer. "
                    f"Claim: {result_claim.claim_text!r}"
                )
            elif result_claim.grounding_status == GroundingStatus.PARTIALLY_GROUNDED:
                assert result_claim.source_pointer is not None, (
                    f"PARTIALLY_GROUNDED claim must have source_pointer. "
                    f"Claim: {result_claim.claim_text!r}"
                )
            elif result_claim.grounding_status == GroundingStatus.UNGROUNDED:
                assert result_claim.source_pointer is None, (
                    f"UNGROUNDED claim must have source_pointer == None. "
                    f"Claim: {result_claim.claim_text!r}, "
                    f"source_pointer: {result_claim.source_pointer}"
                )



# ─── Property 8: Extraction failure after retries marks material grounding_unverified ─

from app.core.grounding_verifier import (
    GroundingResult,
    MaterialGroundingStatus,
)
from app.core.errors import APITimeoutError


# ─── Strategies for Property 8 ───────────────────────────────────────────────

# Strategy for generating error types that trigger retry exhaustion
error_type_st = st.sampled_from(["json_decode_error", "api_timeout_error"])

# Strategy for generating material-like text (non-empty)
material_for_extraction_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z", "S"),
        blacklist_characters="\x00",
    ),
    min_size=10,
    max_size=200,
)

# Strategy for generating material IDs
material_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters="\x00"),
    min_size=3,
    max_size=30,
).filter(lambda s: s.strip() != "")

# Strategy for generating pipeline record IDs
pipeline_record_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters="\x00"),
    min_size=3,
    max_size=30,
).filter(lambda s: s.strip() != "")


@st.composite
def reviewed_material_st(draw):
    """Generate a mock reviewed material with id, pipeline_record_id, and text."""
    material = MagicMock()
    material.id = draw(material_id_st)
    material.pipeline_record_id = draw(pipeline_record_id_st)
    material.text = draw(material_for_extraction_st)
    return material


@st.composite
def beneficiary_st(draw):
    """Generate a mock beneficiary with baseline_assets and offerings_assets."""
    beneficiary = MagicMock()
    # Use draw to make this a proper composite strategy
    resume_content = draw(st.just("Some resume content for testing."))
    beneficiary.baseline_assets = {"resume": resume_content}
    beneficiary.offerings_assets = {"consultant_profiles": "Some profile content."}
    return beneficiary


def _make_error_raiser(error_type: str):
    """Create a side_effect function that raises the specified error type.

    Returns an async callable suitable for use as AsyncMock side_effect.
    """
    if error_type == "json_decode_error":
        async def raise_json_decode_error(*args, **kwargs):
            raise json.JSONDecodeError("Expecting value", "doc", 0)
        return raise_json_decode_error
    else:
        async def raise_api_timeout_error(*args, **kwargs):
            raise APITimeoutError(
                "API request timed out",
                service="llm_router",
                timeout_seconds=60.0,
            )
        return raise_api_timeout_error


def _run_verify_material_with_mocked_sleep(verifier, reviewed_material, beneficiary, enrichment):
    """Run verify_material with asyncio.sleep patched to be instant."""
    from unittest.mock import patch
    import asyncio as _asyncio

    _original_sleep = _asyncio.sleep

    async def _instant_sleep(*args, **kwargs):
        """No-op replacement for asyncio.sleep to speed up retry tests."""
        return

    async def _run():
        with patch.object(_asyncio, "sleep", _instant_sleep):
            return await verifier.verify_material(reviewed_material, beneficiary, enrichment)

    return asyncio.run(_run())


class TestProperty8ExtractionFailureHandling:
    """Property 8: Extraction failure after retries marks material grounding_unverified.

    **Validates: Requirement 1, AC 4**

    Key invariants:
    - When extraction fails after all retries (3 attempts), verify_material returns
      a GroundingResult with material_grounding_status == GROUNDING_UNVERIFIED
    - The grounding report has total_claims == 0
    - requires_action == True
    - blocked_states is empty (not blocking pipeline)
    """

    @given(
        data=st.data(),
        error_type=error_type_st,
    )
    @settings(max_examples=50, deadline=30000)
    def test_extraction_failure_produces_grounding_unverified(
        self, data, error_type: str,
    ) -> None:
        """WHEN extraction fails after all retries (3 total attempts), THEN
        verify_material returns a GroundingResult with
        material_grounding_status == GROUNDING_UNVERIFIED.

        **Validates: Requirement 1, AC 4**
        """
        reviewed_material = data.draw(reviewed_material_st())
        beneficiary = data.draw(beneficiary_st())
        enrichment = data.draw(enrichment_st())

        # Mock LLM router to always raise the specified error
        mock_llm = MagicMock()
        mock_llm.dispatch_extraction = AsyncMock(
            side_effect=_make_error_raiser(error_type)
        )

        # Mock db_repo to track store calls
        mock_db = MagicMock()
        mock_db.store_grounding_report = AsyncMock()

        verifier = GroundingVerifier(
            llm_router=mock_llm,
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        result = _run_verify_material_with_mocked_sleep(
            verifier, reviewed_material, beneficiary, enrichment
        )

        # PROPERTY: material_grounding_status is GROUNDING_UNVERIFIED
        assert result.material_grounding_status == MaterialGroundingStatus.GROUNDING_UNVERIFIED, (
            f"Expected GROUNDING_UNVERIFIED but got {result.material_grounding_status} "
            f"for error type {error_type}"
        )

    @given(
        data=st.data(),
        error_type=error_type_st,
    )
    @settings(max_examples=50, deadline=30000)
    def test_extraction_failure_report_has_zero_claims(
        self, data, error_type: str,
    ) -> None:
        """WHEN extraction fails after all retries, THEN the grounding_report
        in the result has total_claims == 0.

        **Validates: Requirement 1, AC 4**
        """
        reviewed_material = data.draw(reviewed_material_st())
        beneficiary = data.draw(beneficiary_st())
        enrichment = data.draw(enrichment_st())

        mock_llm = MagicMock()
        mock_llm.dispatch_extraction = AsyncMock(
            side_effect=_make_error_raiser(error_type)
        )

        mock_db = MagicMock()
        mock_db.store_grounding_report = AsyncMock()

        verifier = GroundingVerifier(
            llm_router=mock_llm,
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        result = _run_verify_material_with_mocked_sleep(
            verifier, reviewed_material, beneficiary, enrichment
        )

        # PROPERTY: grounding_report.total_claims == 0
        assert result.grounding_report.total_claims == 0, (
            f"Expected total_claims == 0 but got {result.grounding_report.total_claims} "
            f"for error type {error_type}"
        )
        # Also verify the claims list is empty
        assert result.grounding_report.claims == [], (
            f"Expected empty claims list but got {len(result.grounding_report.claims)} claims"
        )

    @given(
        data=st.data(),
        error_type=error_type_st,
    )
    @settings(max_examples=50, deadline=30000)
    def test_extraction_failure_requires_action_is_true(
        self, data, error_type: str,
    ) -> None:
        """WHEN extraction fails after all retries, THEN requires_action == True
        (material surfaces in Dashboard "Requires Action" section).

        **Validates: Requirement 1, AC 4**
        """
        reviewed_material = data.draw(reviewed_material_st())
        beneficiary = data.draw(beneficiary_st())
        enrichment = data.draw(enrichment_st())

        mock_llm = MagicMock()
        mock_llm.dispatch_extraction = AsyncMock(
            side_effect=_make_error_raiser(error_type)
        )

        mock_db = MagicMock()
        mock_db.store_grounding_report = AsyncMock()

        verifier = GroundingVerifier(
            llm_router=mock_llm,
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        result = _run_verify_material_with_mocked_sleep(
            verifier, reviewed_material, beneficiary, enrichment
        )

        # PROPERTY: requires_action is True
        assert result.requires_action is True, (
            f"Expected requires_action == True but got {result.requires_action} "
            f"for error type {error_type}"
        )

    @given(
        data=st.data(),
        error_type=error_type_st,
    )
    @settings(max_examples=50, deadline=30000)
    def test_extraction_failure_blocked_states_is_empty(
        self, data, error_type: str,
    ) -> None:
        """WHEN extraction fails after all retries, THEN blocked_states is empty
        (extraction failure does NOT block pipeline advancement).

        **Validates: Requirement 1, AC 4**
        """
        reviewed_material = data.draw(reviewed_material_st())
        beneficiary = data.draw(beneficiary_st())
        enrichment = data.draw(enrichment_st())

        mock_llm = MagicMock()
        mock_llm.dispatch_extraction = AsyncMock(
            side_effect=_make_error_raiser(error_type)
        )

        mock_db = MagicMock()
        mock_db.store_grounding_report = AsyncMock()

        verifier = GroundingVerifier(
            llm_router=mock_llm,
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        result = _run_verify_material_with_mocked_sleep(
            verifier, reviewed_material, beneficiary, enrichment
        )

        # PROPERTY: blocked_states is empty — extraction failure doesn't block pipeline
        assert result.blocked_states == [], (
            f"Expected blocked_states == [] but got {result.blocked_states} "
            f"for error type {error_type}"
        )

    @given(
        data=st.data(),
        error_types=st.lists(
            error_type_st,
            min_size=3,
            max_size=3,
        ),
    )
    @settings(max_examples=30, deadline=30000)
    def test_extraction_failure_with_mixed_error_types_across_retries(
        self, data, error_types: list[str],
    ) -> None:
        """WHEN extraction fails with different error types across retries
        (e.g., JSONDecodeError on attempt 1, APITimeoutError on attempt 2,
        JSONDecodeError on attempt 3), THEN verify_material still returns
        GROUNDING_UNVERIFIED with all invariants holding.

        **Validates: Requirement 1, AC 4**
        """
        reviewed_material = data.draw(reviewed_material_st())
        beneficiary = data.draw(beneficiary_st())
        enrichment = data.draw(enrichment_st())

        # Create a sequence of errors matching the drawn error types
        call_count = 0

        async def mixed_error_raiser(*args, **kwargs):
            nonlocal call_count
            error_type = error_types[min(call_count, len(error_types) - 1)]
            call_count += 1
            if error_type == "json_decode_error":
                raise json.JSONDecodeError("Expecting value", "doc", 0)
            else:
                raise APITimeoutError(
                    "API request timed out",
                    service="llm_router",
                    timeout_seconds=60.0,
                )

        mock_llm = MagicMock()
        mock_llm.dispatch_extraction = AsyncMock(side_effect=mixed_error_raiser)

        mock_db = MagicMock()
        mock_db.store_grounding_report = AsyncMock()

        verifier = GroundingVerifier(
            llm_router=mock_llm,
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        result = _run_verify_material_with_mocked_sleep(
            verifier, reviewed_material, beneficiary, enrichment
        )

        # ALL invariants must hold regardless of error type mix
        assert result.material_grounding_status == MaterialGroundingStatus.GROUNDING_UNVERIFIED
        assert result.grounding_report.total_claims == 0
        assert result.requires_action is True
        assert result.blocked_states == []


# ─── Property 11: Three resolution paths are always offered for blocked materials ─

from app.core.grounding_verifier import (
    ResolutionPath,
)

import inspect


# ─── Strategies for Property 11 ──────────────────────────────────────────────

# Strategy for generating a random subset of ResolutionPath values
resolution_path_subset_st = st.lists(
    st.sampled_from(list(ResolutionPath)),
    min_size=1,
    max_size=3,
    unique=True,
)

# The exact three paths that must always be available
EXPECTED_RESOLUTION_PATHS = {
    ResolutionPath.REGENERATE,
    ResolutionPath.MANUAL_EDIT,
    ResolutionPath.CONFIRM_AND_ADD,
}

# Mapping from resolution paths to their corresponding GroundingVerifier methods
RESOLUTION_PATH_METHOD_MAP = {
    ResolutionPath.REGENERATE: "resolve_regenerate",
    ResolutionPath.MANUAL_EDIT: "re_verify_claims",
    ResolutionPath.CONFIRM_AND_ADD: "resolve_confirm_and_add",
}


class TestProperty11ResolutionPathAvailability:
    """Property 11: Three resolution paths are always offered for blocked materials.

    **Validates: Requirement 3, AC 2**

    Key invariants:
    - ResolutionPath enum has exactly 3 members: REGENERATE, MANUAL_EDIT, CONFIRM_AND_ADD
    - GroundingVerifier has the corresponding method for each resolution path:
      - REGENERATE → resolve_regenerate
      - MANUAL_EDIT → re_verify_claims (handles re-verification after manual edit)
      - CONFIRM_AND_ADD → resolve_confirm_and_add
    """

    @given(path=st.sampled_from(list(ResolutionPath)))
    @settings(max_examples=50)
    def test_resolution_path_enum_has_exactly_three_values(
        self, path: ResolutionPath,
    ) -> None:
        """FOR ANY sampled ResolutionPath value, the total set of enum members
        is exactly {REGENERATE, MANUAL_EDIT, CONFIRM_AND_ADD} — no more, no less.

        **Validates: Requirement 3, AC 2**
        """
        all_paths = set(ResolutionPath)
        assert len(all_paths) == 3, (
            f"ResolutionPath enum must have exactly 3 members, "
            f"but has {len(all_paths)}: {all_paths}"
        )
        assert all_paths == EXPECTED_RESOLUTION_PATHS, (
            f"ResolutionPath enum must contain exactly "
            f"{EXPECTED_RESOLUTION_PATHS}, but contains {all_paths}"
        )

    @given(path=st.sampled_from(list(ResolutionPath)))
    @settings(max_examples=50)
    def test_every_resolution_path_has_corresponding_verifier_method(
        self, path: ResolutionPath,
    ) -> None:
        """FOR ANY ResolutionPath value, the GroundingVerifier class has a
        corresponding callable method that implements that resolution path.

        **Validates: Requirement 3, AC 2**
        """
        method_name = RESOLUTION_PATH_METHOD_MAP[path]
        assert hasattr(GroundingVerifier, method_name), (
            f"GroundingVerifier must have method '{method_name}' "
            f"for resolution path {path.value}, but it does not."
        )
        method = getattr(GroundingVerifier, method_name)
        assert callable(method), (
            f"GroundingVerifier.{method_name} must be callable, "
            f"but got type {type(method)}"
        )

    @given(path=st.sampled_from(list(ResolutionPath)))
    @settings(max_examples=50)
    def test_resolution_path_methods_are_async(
        self, path: ResolutionPath,
    ) -> None:
        """FOR ANY ResolutionPath value, the corresponding GroundingVerifier
        method is an async coroutine function (since resolution involves I/O).

        **Validates: Requirement 3, AC 2**
        """
        method_name = RESOLUTION_PATH_METHOD_MAP[path]
        method = getattr(GroundingVerifier, method_name)
        assert inspect.iscoroutinefunction(method), (
            f"GroundingVerifier.{method_name} must be an async method "
            f"(coroutine function), but it is not."
        )

    @given(paths=resolution_path_subset_st)
    @settings(max_examples=50)
    def test_all_resolution_paths_are_distinct_string_values(
        self, paths: list[ResolutionPath],
    ) -> None:
        """FOR ANY subset of ResolutionPath members, their string values
        are distinct and non-empty — ensuring each path is uniquely
        identifiable in API responses and UI rendering.

        **Validates: Requirement 3, AC 2**
        """
        values = [p.value for p in paths]
        # All values must be non-empty strings
        for v in values:
            assert isinstance(v, str)
            assert len(v) > 0, f"ResolutionPath value must be non-empty, got: {v!r}"
        # All values must be distinct
        assert len(values) == len(set(values)), (
            f"ResolutionPath values must be distinct, but got duplicates: {values}"
        )

    @given(path=st.sampled_from(list(ResolutionPath)))
    @settings(max_examples=50)
    def test_resolution_path_values_match_expected_strings(
        self, path: ResolutionPath,
    ) -> None:
        """FOR ANY ResolutionPath value, it matches one of the expected
        string representations: "regenerate", "manual_edit", "confirm_and_add".

        **Validates: Requirement 3, AC 2**
        """
        expected_values = {"regenerate", "manual_edit", "confirm_and_add"}
        assert path.value in expected_values, (
            f"ResolutionPath.{path.name} has value {path.value!r} which "
            f"is not in the expected set {expected_values}"
        )

    @given(data=st.data())
    @settings(max_examples=50)
    def test_resolution_path_method_map_is_complete(
        self, data,
    ) -> None:
        """The RESOLUTION_PATH_METHOD_MAP covers every ResolutionPath member
        — no path is left without a corresponding implementation method.

        **Validates: Requirement 3, AC 2**
        """
        all_paths = set(ResolutionPath)
        mapped_paths = set(RESOLUTION_PATH_METHOD_MAP.keys())
        assert all_paths == mapped_paths, (
            f"RESOLUTION_PATH_METHOD_MAP must cover all ResolutionPath members. "
            f"Missing: {all_paths - mapped_paths}, Extra: {mapped_paths - all_paths}"
        )

        # Additionally verify that each mapped method exists on GroundingVerifier
        path = data.draw(st.sampled_from(list(all_paths)))
        method_name = RESOLUTION_PATH_METHOD_MAP[path]
        assert hasattr(GroundingVerifier, method_name)



# ─── Property 4: Re-verification only checks affected claims ─────────────────

from copy import deepcopy

from app.core.grounding_verifier import (
    GroundingReport,
    GroundingResult,
    MaterialGroundingStatus,
)


# ─── Strategies for Property 4 ───────────────────────────────────────────────

@st.composite
def grounding_status_st(draw):
    """Generate a random GroundingStatus value."""
    return draw(st.sampled_from(list(GroundingStatus)))


@st.composite
def claim_with_status_st(draw, material_id: str = "mat-prop4"):
    """Generate a Claim with an assigned grounding_status and source_pointer."""
    status = draw(grounding_status_st())
    category = draw(st.sampled_from(list(ClaimCategory)))
    claim_text = draw(st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "Z"),
                               blacklist_characters="\x00"),
        min_size=5,
        max_size=60,
    ).filter(lambda s: s.strip() != ""))

    source_pointer = None
    discrepancy = None
    if status in (GroundingStatus.GROUNDED, GroundingStatus.PARTIALLY_GROUNDED):
        source_pointer = SourcePointer(
            asset_type="resume",
            asset_id="resume",
            passage=f"Supporting passage for: {claim_text[:20]}",
            confidence=0.9 if status == GroundingStatus.GROUNDED else 0.6,
        )
    if status == GroundingStatus.PARTIALLY_GROUNDED:
        discrepancy = f"Number differs for {claim_text[:20]}"

    return Claim(
        id=str(uuid.uuid4()),
        material_id=material_id,
        category=category,
        claim_text=claim_text,
        source_span=claim_text,
        source_span_start=0,
        source_span_end=len(claim_text),
        grounding_status=status,
        source_pointer=source_pointer,
        discrepancy=discrepancy,
        is_prospect_side=False,
    )


@st.composite
def existing_grounding_report_st(draw, min_claims: int = 3, max_claims: int = 8):
    """Generate a mock existing GroundingReport with multiple claims that have statuses set."""
    material_id = "mat-prop4"
    num_claims = draw(st.integers(min_value=min_claims, max_value=max_claims))

    claims = [draw(claim_with_status_st(material_id=material_id)) for _ in range(num_claims)]

    grounded_count = sum(1 for c in claims if c.grounding_status == GroundingStatus.GROUNDED)
    partially_grounded_count = sum(
        1 for c in claims if c.grounding_status == GroundingStatus.PARTIALLY_GROUNDED
    )
    ungrounded_count = sum(
        1 for c in claims if c.grounding_status == GroundingStatus.UNGROUNDED
    )

    if ungrounded_count > 0:
        material_status = MaterialGroundingStatus.GROUNDING_BLOCKED
    else:
        material_status = MaterialGroundingStatus.GROUNDING_VERIFIED

    report = GroundingReport(
        id=str(uuid.uuid4()),
        material_id=material_id,
        pipeline_record_id="pipe-prop4",
        claims=claims,
        total_claims=len(claims),
        grounded_count=grounded_count,
        partially_grounded_count=partially_grounded_count,
        ungrounded_count=ungrounded_count,
        material_grounding_status=material_status,
        extraction_duration_ms=100,
        verification_duration_ms=50,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    return report


from datetime import datetime, timezone


class TestProperty4ReVerificationScope:
    """Property 4: Re-verification only checks affected claims.

    **Validates: Requirement 3, AC 3**

    Key invariants:
    - When re_verify_claims is called with a subset of claim IDs,
      ONLY those claims are re-verified (their status may change).
    - Claims NOT in affected_claim_ids retain their original
      grounding_status unchanged.
    - Claims NOT in affected_claim_ids retain their original
      source_pointer and discrepancy unchanged.
    """

    @given(data=st.data())
    @settings(max_examples=100, deadline=30000)
    def test_unaffected_claims_retain_original_status(
        self, data,
    ) -> None:
        """WHEN re_verify_claims is called with a subset of claim IDs, THEN
        claims NOT in affected_claim_ids retain their original grounding_status.

        **Validates: Requirement 3, AC 3**
        """
        report = data.draw(existing_grounding_report_st(min_claims=3, max_claims=8))
        assume(len(report.claims) >= 3)

        # Select a strict subset of claim IDs as "affected"
        all_claim_ids = [c.id for c in report.claims]
        num_affected = data.draw(
            st.integers(min_value=1, max_value=len(all_claim_ids) - 1)
        )
        affected_ids = list(all_claim_ids[:num_affected])
        unaffected_ids = list(all_claim_ids[num_affected:])
        assume(len(unaffected_ids) >= 1)

        # Record the original statuses of unaffected claims
        original_unaffected_statuses = {
            c.id: c.grounding_status
            for c in report.claims
            if c.id in unaffected_ids
        }

        # Build assets that will cause affected claims to be re-verified
        # (the specifics of grounding don't matter — we only check that
        #  unaffected claims are untouched)
        updated_assets = {"resume": "New supporting content for re-verification testing"}

        # Mock enrichment
        mock_enrichment = MagicMock()
        mock_enrichment.company_name = None
        mock_enrichment.industry = None
        mock_enrichment.revenue_range = None
        mock_enrichment.funding_stage = None
        mock_enrichment.headquarters_city = None
        mock_enrichment.headquarters_country = None
        mock_enrichment.employee_count = None
        mock_enrichment.tech_stack = []

        # Mock beneficiary
        mock_beneficiary = MagicMock()
        mock_beneficiary.baseline_assets = {"resume": "Original resume content"}
        mock_beneficiary.offerings_assets = {}

        # Mock db_repo
        mock_db = MagicMock()
        mock_db.get_latest_grounding_report_by_material = AsyncMock(
            return_value=deepcopy(report)
        )
        mock_db.update_grounding_report = AsyncMock()
        mock_db.store_resolution = AsyncMock()

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        result = asyncio.run(
            verifier.re_verify_claims(
                material_id="mat-prop4",
                affected_claim_ids=affected_ids,
                updated_assets=updated_assets,
                beneficiary=mock_beneficiary,
                enrichment=mock_enrichment,
            )
        )

        # PROPERTY: Unaffected claims retain their original grounding_status
        result_claims_by_id = {c.id: c for c in result.grounding_report.claims}
        for claim_id, original_status in original_unaffected_statuses.items():
            assert claim_id in result_claims_by_id, (
                f"Unaffected claim {claim_id} is missing from result"
            )
            result_status = result_claims_by_id[claim_id].grounding_status
            assert result_status == original_status, (
                f"Unaffected claim {claim_id} had status {original_status} "
                f"but after re_verify_claims got {result_status}. "
                f"Only affected claims should change."
            )

    @given(data=st.data())
    @settings(max_examples=100, deadline=30000)
    def test_unaffected_claims_retain_source_pointer_and_discrepancy(
        self, data,
    ) -> None:
        """WHEN re_verify_claims is called with a subset of claim IDs, THEN
        claims NOT in affected_claim_ids retain their original source_pointer
        and discrepancy values unchanged.

        **Validates: Requirement 3, AC 3**
        """
        report = data.draw(existing_grounding_report_st(min_claims=3, max_claims=8))
        assume(len(report.claims) >= 3)

        all_claim_ids = [c.id for c in report.claims]
        num_affected = data.draw(
            st.integers(min_value=1, max_value=len(all_claim_ids) - 1)
        )
        affected_ids = list(all_claim_ids[:num_affected])
        unaffected_ids = list(all_claim_ids[num_affected:])
        assume(len(unaffected_ids) >= 1)

        # Record original source_pointer and discrepancy for unaffected claims
        original_unaffected_data = {}
        for c in report.claims:
            if c.id in unaffected_ids:
                original_unaffected_data[c.id] = {
                    "source_pointer": deepcopy(c.source_pointer),
                    "discrepancy": c.discrepancy,
                }

        updated_assets = {"resume": "Updated content for testing scope isolation"}

        mock_enrichment = MagicMock()
        mock_enrichment.company_name = None
        mock_enrichment.industry = None
        mock_enrichment.revenue_range = None
        mock_enrichment.funding_stage = None
        mock_enrichment.headquarters_city = None
        mock_enrichment.headquarters_country = None
        mock_enrichment.employee_count = None
        mock_enrichment.tech_stack = []

        mock_beneficiary = MagicMock()
        mock_beneficiary.baseline_assets = {"resume": "Original resume content"}
        mock_beneficiary.offerings_assets = {}

        mock_db = MagicMock()
        mock_db.get_latest_grounding_report_by_material = AsyncMock(
            return_value=deepcopy(report)
        )
        mock_db.update_grounding_report = AsyncMock()
        mock_db.store_resolution = AsyncMock()

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        result = asyncio.run(
            verifier.re_verify_claims(
                material_id="mat-prop4",
                affected_claim_ids=affected_ids,
                updated_assets=updated_assets,
                beneficiary=mock_beneficiary,
                enrichment=mock_enrichment,
            )
        )

        # PROPERTY: Unaffected claims retain source_pointer and discrepancy
        result_claims_by_id = {c.id: c for c in result.grounding_report.claims}
        for claim_id, original_data in original_unaffected_data.items():
            assert claim_id in result_claims_by_id, (
                f"Unaffected claim {claim_id} is missing from result"
            )
            result_claim = result_claims_by_id[claim_id]

            original_sp = original_data["source_pointer"]
            if original_sp is None:
                assert result_claim.source_pointer is None, (
                    f"Unaffected claim {claim_id} had source_pointer=None "
                    f"but after re_verify got {result_claim.source_pointer}"
                )
            else:
                assert result_claim.source_pointer is not None, (
                    f"Unaffected claim {claim_id} had source_pointer set "
                    f"but after re_verify got None"
                )
                assert result_claim.source_pointer.asset_type == original_sp.asset_type
                assert result_claim.source_pointer.passage == original_sp.passage
                assert result_claim.source_pointer.confidence == original_sp.confidence

            assert result_claim.discrepancy == original_data["discrepancy"], (
                f"Unaffected claim {claim_id} had discrepancy "
                f"{original_data['discrepancy']!r} but after re_verify got "
                f"{result_claim.discrepancy!r}"
            )

    @given(data=st.data())
    @settings(max_examples=100, deadline=30000)
    def test_only_affected_claims_are_passed_to_verify_claims(
        self, data,
    ) -> None:
        """WHEN re_verify_claims is called, THEN the internal verify_claims call
        receives ONLY the affected claims (by count), proving that unaffected
        claims are never re-processed.

        **Validates: Requirement 3, AC 3**
        """
        report = data.draw(existing_grounding_report_st(min_claims=3, max_claims=8))
        assume(len(report.claims) >= 3)

        all_claim_ids = [c.id for c in report.claims]
        num_affected = data.draw(
            st.integers(min_value=1, max_value=len(all_claim_ids) - 1)
        )
        affected_ids = list(all_claim_ids[:num_affected])

        updated_assets = {"resume": "Some updated resume content"}

        mock_enrichment = MagicMock()
        mock_enrichment.company_name = None
        mock_enrichment.industry = None
        mock_enrichment.revenue_range = None
        mock_enrichment.funding_stage = None
        mock_enrichment.headquarters_city = None
        mock_enrichment.headquarters_country = None
        mock_enrichment.employee_count = None
        mock_enrichment.tech_stack = []

        mock_beneficiary = MagicMock()
        mock_beneficiary.baseline_assets = {"resume": "Original resume content"}
        mock_beneficiary.offerings_assets = {}

        mock_db = MagicMock()
        mock_db.get_latest_grounding_report_by_material = AsyncMock(
            return_value=deepcopy(report)
        )
        mock_db.update_grounding_report = AsyncMock()
        mock_db.store_resolution = AsyncMock()

        # Create the verifier and spy on verify_claims
        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        # Patch verify_claims to track what claims are passed to it
        original_verify_claims = verifier.verify_claims
        claims_passed_to_verify = []

        def patched_verify_claims(claims, baseline_assets, offerings_assets, enrichment):
            claims_passed_to_verify.extend(claims)
            return original_verify_claims(claims, baseline_assets, offerings_assets, enrichment)

        verifier.verify_claims = patched_verify_claims

        asyncio.run(
            verifier.re_verify_claims(
                material_id="mat-prop4",
                affected_claim_ids=affected_ids,
                updated_assets=updated_assets,
                beneficiary=mock_beneficiary,
                enrichment=mock_enrichment,
            )
        )

        # PROPERTY: Only affected claims were passed to verify_claims
        passed_claim_ids = {c.id for c in claims_passed_to_verify}
        for claim_id in passed_claim_ids:
            assert claim_id in affected_ids, (
                f"Claim {claim_id} was passed to verify_claims but is NOT "
                f"in affected_claim_ids. Only affected claims should be re-verified."
            )

        # All affected claims should have been passed
        for claim_id in affected_ids:
            assert claim_id in passed_claim_ids, (
                f"Affected claim {claim_id} was NOT passed to verify_claims. "
                f"All affected claims should be re-verified."
            )

    @given(data=st.data())
    @settings(max_examples=100, deadline=30000)
    def test_total_claim_count_preserved_after_re_verification(
        self, data,
    ) -> None:
        """WHEN re_verify_claims is called, THEN the total number of claims
        in the resulting report equals the original count (no claims are
        lost or duplicated).

        **Validates: Requirement 3, AC 3**
        """
        report = data.draw(existing_grounding_report_st(min_claims=3, max_claims=8))
        assume(len(report.claims) >= 3)

        all_claim_ids = [c.id for c in report.claims]
        num_affected = data.draw(
            st.integers(min_value=1, max_value=len(all_claim_ids) - 1)
        )
        affected_ids = list(all_claim_ids[:num_affected])
        original_total = len(report.claims)

        updated_assets = {"resume": "Content for total count preservation test"}

        mock_enrichment = MagicMock()
        mock_enrichment.company_name = None
        mock_enrichment.industry = None
        mock_enrichment.revenue_range = None
        mock_enrichment.funding_stage = None
        mock_enrichment.headquarters_city = None
        mock_enrichment.headquarters_country = None
        mock_enrichment.employee_count = None
        mock_enrichment.tech_stack = []

        mock_beneficiary = MagicMock()
        mock_beneficiary.baseline_assets = {"resume": "Resume content"}
        mock_beneficiary.offerings_assets = {}

        mock_db = MagicMock()
        mock_db.get_latest_grounding_report_by_material = AsyncMock(
            return_value=deepcopy(report)
        )
        mock_db.update_grounding_report = AsyncMock()
        mock_db.store_resolution = AsyncMock()

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        result = asyncio.run(
            verifier.re_verify_claims(
                material_id="mat-prop4",
                affected_claim_ids=affected_ids,
                updated_assets=updated_assets,
                beneficiary=mock_beneficiary,
                enrichment=mock_enrichment,
            )
        )

        # PROPERTY: Total claim count is preserved
        assert result.grounding_report.total_claims == original_total, (
            f"Expected total_claims == {original_total} but got "
            f"{result.grounding_report.total_claims}. "
            f"Re-verification should not add or remove claims."
        )
        assert len(result.grounding_report.claims) == original_total, (
            f"Expected {original_total} claims in list but got "
            f"{len(result.grounding_report.claims)}."
        )


# ─── Property 5: Re-verification completes within 30 seconds ─────────────────


class TestProperty5ReVerificationTimeout:
    """Property 5: Re-verification completes within 30 seconds.

    **Validates: Requirement 3, AC 3**

    Key invariants:
    - The VERIFICATION_TIMEOUT constant on GroundingVerifier is exactly 30.0
    - re_verify_claims uses asyncio.wait_for with a 30-second timeout
    - If the inner operation exceeds 30 seconds, asyncio.TimeoutError is raised
    """

    def test_verification_timeout_constant_is_30(self) -> None:
        """The VERIFICATION_TIMEOUT class constant is exactly 30.0 seconds.

        **Validates: Requirement 3, AC 3**
        """
        assert GroundingVerifier.VERIFICATION_TIMEOUT == 30.0, (
            f"Expected VERIFICATION_TIMEOUT == 30.0, "
            f"got {GroundingVerifier.VERIFICATION_TIMEOUT}"
        )

    @given(
        num_affected_claims=st.integers(min_value=1, max_value=5),
        num_unaffected_claims=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=50, deadline=30000)
    def test_re_verify_raises_timeout_error_when_exceeding_timeout(
        self,
        num_affected_claims: int,
        num_unaffected_claims: int,
    ) -> None:
        """WHEN the inner re-verification operation takes longer than
        VERIFICATION_TIMEOUT, THEN asyncio.TimeoutError is raised by
        re_verify_claims. We override VERIFICATION_TIMEOUT to a small value
        to avoid actual 30s waits, confirming the mechanism works.

        **Validates: Requirement 3, AC 3**
        """
        import asyncio as _asyncio

        material_id = "mat-timeout-test"
        affected_claim_ids = [f"claim-{i}" for i in range(num_affected_claims)]

        # Build existing claims for the report
        all_claim_ids = affected_claim_ids + [
            f"unaffected-{i}" for i in range(num_unaffected_claims)
        ]
        existing_claims = [
            Claim(
                id=cid,
                material_id=material_id,
                category=ClaimCategory.SKILL_TECHNOLOGY,
                claim_text=f"Claim text for {cid}",
                source_span=f"Span for {cid}",
                source_span_start=0,
                source_span_end=20,
                grounding_status=GroundingStatus.UNGROUNDED,
                is_prospect_side=False,
            )
            for cid in all_claim_ids
        ]

        # Build a mock existing report
        from datetime import datetime, timezone

        existing_report = GroundingReport(
            id="report-001",
            material_id=material_id,
            pipeline_record_id="pipeline-001",
            claims=existing_claims,
            total_claims=len(existing_claims),
            grounded_count=0,
            partially_grounded_count=0,
            ungrounded_count=len(existing_claims),
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            extraction_duration_ms=100,
            verification_duration_ms=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Mock DB that introduces a deliberate delay exceeding the timeout
        async def slow_get_report(*args, **kwargs):
            await _asyncio.sleep(0.5)  # 500ms, will exceed our small timeout
            return existing_report

        mock_db = MagicMock()
        mock_db.get_latest_grounding_report_by_material = AsyncMock(
            side_effect=slow_get_report
        )
        mock_db.update_grounding_report = AsyncMock()
        mock_db.store_resolution = AsyncMock()

        # Mock enrichment (no prospect-side matching)
        mock_enrichment = MagicMock()
        mock_enrichment.company_name = None
        mock_enrichment.industry = None
        mock_enrichment.revenue_range = None
        mock_enrichment.funding_stage = None
        mock_enrichment.headquarters_city = None
        mock_enrichment.headquarters_country = None
        mock_enrichment.employee_count = None
        mock_enrichment.tech_stack = []

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        # Override VERIFICATION_TIMEOUT to a tiny value so the 500ms sleep triggers it
        verifier.VERIFICATION_TIMEOUT = 0.01  # 10ms

        async def _run():
            return await verifier.re_verify_claims(
                material_id=material_id,
                affected_claim_ids=affected_claim_ids,
                updated_assets={"resume": "Some content"},
                beneficiary=None,
                enrichment=mock_enrichment,
            )

        with pytest.raises(_asyncio.TimeoutError):
            asyncio.run(_run())

    @given(
        num_affected_claims=st.integers(min_value=1, max_value=5),
        num_unaffected_claims=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=50, deadline=30000)
    def test_re_verify_completes_when_within_timeout(
        self,
        num_affected_claims: int,
        num_unaffected_claims: int,
    ) -> None:
        """WHEN the inner re-verification operation completes within 30 seconds,
        THEN re_verify_claims returns a valid GroundingResult without raising.

        **Validates: Requirement 3, AC 3**
        """
        from datetime import datetime, timezone

        material_id = "mat-fast-test"
        affected_claim_ids = [f"claim-{i}" for i in range(num_affected_claims)]

        all_claim_ids = affected_claim_ids + [
            f"unaffected-{i}" for i in range(num_unaffected_claims)
        ]
        existing_claims = [
            Claim(
                id=cid,
                material_id=material_id,
                category=ClaimCategory.SKILL_TECHNOLOGY,
                claim_text=f"Proficient in Python",
                source_span=f"Proficient in Python",
                source_span_start=0,
                source_span_end=20,
                grounding_status=GroundingStatus.UNGROUNDED,
                is_prospect_side=False,
            )
            for cid in all_claim_ids
        ]

        existing_report = GroundingReport(
            id="report-002",
            material_id=material_id,
            pipeline_record_id="pipeline-002",
            claims=existing_claims,
            total_claims=len(existing_claims),
            grounded_count=0,
            partially_grounded_count=0,
            ungrounded_count=len(existing_claims),
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            extraction_duration_ms=100,
            verification_duration_ms=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        mock_db = MagicMock()
        mock_db.get_latest_grounding_report_by_material = AsyncMock(
            return_value=existing_report
        )
        mock_db.update_grounding_report = AsyncMock()
        mock_db.store_resolution = AsyncMock()

        mock_enrichment = MagicMock()
        mock_enrichment.company_name = None
        mock_enrichment.industry = None
        mock_enrichment.revenue_range = None
        mock_enrichment.funding_stage = None
        mock_enrichment.headquarters_city = None
        mock_enrichment.headquarters_country = None
        mock_enrichment.employee_count = None
        mock_enrichment.tech_stack = []

        # Mock beneficiary with assets that WILL ground the claims
        mock_beneficiary = MagicMock()
        mock_beneficiary.baseline_assets = {"resume": "Proficient in Python and Java"}
        mock_beneficiary.offerings_assets = {}

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        # Run re_verify_claims with updated_assets (no extraction needed, fast path)
        async def _run():
            return await verifier.re_verify_claims(
                material_id=material_id,
                affected_claim_ids=affected_claim_ids,
                updated_assets={"resume": "Proficient in Python and Java development"},
                beneficiary=mock_beneficiary,
                enrichment=mock_enrichment,
            )

        # Should complete without raising TimeoutError
        result = asyncio.run(_run())

        assert isinstance(result, GroundingResult)
        assert result.material_id == material_id
        assert result.material_grounding_status in (
            MaterialGroundingStatus.GROUNDING_VERIFIED,
            MaterialGroundingStatus.GROUNDING_BLOCKED,
        )

    @given(
        timeout_value=st.floats(min_value=0.001, max_value=0.05),
    )
    @settings(max_examples=30, deadline=30000)
    def test_timeout_is_enforced_via_asyncio_wait_for(
        self,
        timeout_value: float,
    ) -> None:
        """WHEN we override VERIFICATION_TIMEOUT to a very small value and the
        inner operation takes longer than that, THEN asyncio.TimeoutError is raised.
        This confirms that asyncio.wait_for is used with VERIFICATION_TIMEOUT.

        **Validates: Requirement 3, AC 3**
        """
        import asyncio as _asyncio
        from datetime import datetime, timezone

        material_id = "mat-wait-for-test"
        affected_claim_ids = ["claim-0"]

        existing_claims = [
            Claim(
                id="claim-0",
                material_id=material_id,
                category=ClaimCategory.SKILL_TECHNOLOGY,
                claim_text="Expert in Rust",
                source_span="Expert in Rust",
                source_span_start=0,
                source_span_end=14,
                grounding_status=GroundingStatus.UNGROUNDED,
                is_prospect_side=False,
            ),
        ]

        existing_report = GroundingReport(
            id="report-wait-for",
            material_id=material_id,
            pipeline_record_id="pipeline-wf",
            claims=existing_claims,
            total_claims=1,
            grounded_count=0,
            partially_grounded_count=0,
            ungrounded_count=1,
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            extraction_duration_ms=100,
            verification_duration_ms=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        # Mock DB that introduces a delay exceeding the short timeout
        async def slow_get_report(*args, **kwargs):
            await _asyncio.sleep(0.1)  # 100ms, exceeds our tiny timeout
            return existing_report

        mock_db = MagicMock()
        mock_db.get_latest_grounding_report_by_material = AsyncMock(
            side_effect=slow_get_report
        )
        mock_db.update_grounding_report = AsyncMock()
        mock_db.store_resolution = AsyncMock()

        verifier = GroundingVerifier(
            llm_router=MagicMock(),
            schema_registry=MagicMock(),
            db_repo=mock_db,
            personalization_engine=MagicMock(),
        )

        # Override the timeout to a very small value
        verifier.VERIFICATION_TIMEOUT = timeout_value

        mock_enrichment = MagicMock()
        mock_enrichment.company_name = None
        mock_enrichment.industry = None
        mock_enrichment.revenue_range = None
        mock_enrichment.funding_stage = None
        mock_enrichment.headquarters_city = None
        mock_enrichment.headquarters_country = None
        mock_enrichment.employee_count = None
        mock_enrichment.tech_stack = []

        async def _run():
            return await verifier.re_verify_claims(
                material_id=material_id,
                affected_claim_ids=affected_claim_ids,
                updated_assets={"resume": "Expert in Rust programming"},
                beneficiary=None,
                enrichment=mock_enrichment,
            )

        with pytest.raises(_asyncio.TimeoutError):
            asyncio.run(_run())
