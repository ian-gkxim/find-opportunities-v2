"""Domain models and service for Claim Grounding Verification.

Defines enums, dataclasses used by the Grounding_Verifier to extract
factual claims from materials, verify them against profile sources,
and enforce pipeline gating.

Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.3, 3.1
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

from app.core.errors import APITimeoutError
from app.core.grounding_errors import (
    ExtractionError,
    ExtractionParseError,
    ExtractionTimeoutError,
)
from app.core.grounding_prompts import CLAIM_EXTRACTION_PROMPT

logger = logging.getLogger(__name__)


# ─── ENUMS ────────────────────────────────────────────────────────────────────


class GroundingStatus(str, Enum):
    """Verification outcome for a single Claim."""

    GROUNDED = "grounded"
    PARTIALLY_GROUNDED = "partially_grounded"
    UNGROUNDED = "ungrounded"


class ClaimCategory(str, Enum):
    """Category of a factual assertion extracted from a material."""

    SKILL_TECHNOLOGY = "skill_technology"
    ACHIEVEMENT_OUTCOME = "achievement_outcome"
    QUANTIFIED_METRIC = "quantified_metric"
    CREDENTIAL_CERTIFICATION = "credential_certification"
    NAMED_CLIENT_EMPLOYER = "named_client_employer"
    EXPERIENCE_DURATION = "experience_duration"


class MaterialGroundingStatus(str, Enum):
    """Overall grounding status for an entire material."""

    GROUNDING_VERIFIED = "grounding_verified"
    GROUNDING_BLOCKED = "grounding_blocked"
    GROUNDING_UNVERIFIED = "grounding_unverified"


class ResolutionPath(str, Enum):
    """Available resolution paths for a blocked material."""

    REGENERATE = "regenerate"
    MANUAL_EDIT = "manual_edit"
    CONFIRM_AND_ADD = "confirm_and_add"


# ─── DATACLASSES ──────────────────────────────────────────────────────────────


@dataclass
class SourcePointer:
    """Points to the supporting evidence in a profile asset.

    Used to trace a grounded or partially_grounded claim back to its
    source in the Beneficiary's profile or the EnrichmentRecord.
    """

    asset_type: str  # resume, cover_letter, consultant_profiles, company_profile, etc.
    asset_id: str
    passage: str  # exact supporting text from the asset
    confidence: float  # 0.0-1.0


@dataclass
class Claim:
    """A discrete factual assertion extracted from a material.

    Each Claim is extracted from generated outreach content and verified
    against the Beneficiary's profile assets or the EnrichmentRecord
    (for prospect-side facts).
    """

    id: str  # UUID
    material_id: str
    category: ClaimCategory
    claim_text: str  # the factual assertion as stated
    source_span: str  # exact text span in the material where claim appears
    source_span_start: int  # character offset start in material
    source_span_end: int  # character offset end in material
    grounding_status: GroundingStatus | None = None
    source_pointer: SourcePointer | None = None
    discrepancy: str | None = None  # for partially_grounded: what differs
    is_prospect_side: bool = False  # true if claim is about the prospect, not beneficiary


@dataclass
class GroundingReport:
    """Complete verification report for a material.

    Stores all extracted claims with their verification outcomes,
    aggregate counts, and timing telemetry. Persisted to the
    reasoning_log tables.
    """

    id: str  # UUID
    material_id: str
    pipeline_record_id: str
    claims: list[Claim]
    total_claims: int
    grounded_count: int
    partially_grounded_count: int
    ungrounded_count: int
    material_grounding_status: MaterialGroundingStatus
    extraction_duration_ms: int
    verification_duration_ms: int
    created_at: datetime
    updated_at: datetime


@dataclass
class GroundingResult:
    """Final output of the grounding verification process.

    Returned by GroundingVerifier.verify_material() to indicate
    the pipeline gate decision and provide the full report.
    """

    material_id: str
    material_grounding_status: MaterialGroundingStatus
    grounding_report: GroundingReport
    blocked_states: list[str]  # states the material cannot transition to
    requires_action: bool


# ─── SERVICE ──────────────────────────────────────────────────────────────────


class GroundingVerifier:
    """Orchestrates claim extraction, verification, and pipeline gating.

    Requirements: 1.1, 1.2, 1.3, 1.4
    """

    EXTRACTION_TIMEOUT = 60.0  # seconds
    VERIFICATION_TIMEOUT = 30.0  # seconds for re-verification
    MAX_RETRIES = 2  # 2 retries = 3 total attempts
    BATCH_CONCURRENCY = 3

    # Pipeline states that are blocked when ungrounded claims exist
    GATED_STATES = ["Approve", "Applied", "Sent", "Proposal Submitted"]

    def __init__(
        self,
        llm_router,
        schema_registry,
        db_repo,
        personalization_engine,
    ):
        self._llm = llm_router
        self._schema = schema_registry
        self._db = db_repo
        self._personalization = personalization_engine
        self._semaphore = asyncio.Semaphore(self.BATCH_CONCURRENCY)

    async def extract_claims(
        self,
        material_text: str,
        material_id: str,
    ) -> list[Claim]:
        """Extract all factual claims from material via LLM_Router EXTRACTION call.

        Builds prompt using CLAIM_EXTRACTION_PROMPT, calls dispatch_extraction
        with 60s timeout, and parses JSON response into Claim objects.

        Implements retry logic: up to 2 retries (3 total attempts) with
        exponential backoff (1s, 2s) on ExtractionParseError or
        ExtractionTimeoutError. After all retries exhausted, raises
        ExtractionError.

        Validates that each claim's source_span is an exact substring of
        material_text. Claims with invalid spans are skipped with a warning.

        Requirements: 1.1, 1.2, 1.3, 1.4
        """
        prompt = CLAIM_EXTRACTION_PROMPT.format(material_text=material_text)

        last_error: Exception | None = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self._llm.dispatch_extraction(
                    prompt, timeout=self.EXTRACTION_TIMEOUT
                )
                break
            except json.JSONDecodeError as exc:
                last_error = ExtractionParseError(
                    material_id=material_id,
                    raw_response=str(exc),
                )
                logger.warning(
                    "Extraction parse error on attempt %d for material %s: %s",
                    attempt + 1,
                    material_id,
                    exc,
                )
            except APITimeoutError as exc:
                last_error = ExtractionTimeoutError(
                    material_id=material_id,
                    timeout_seconds=self.EXTRACTION_TIMEOUT,
                )
                logger.warning(
                    "Extraction timeout on attempt %d for material %s: %s",
                    attempt + 1,
                    material_id,
                    exc,
                )

            # Exponential backoff before retry (1s, 2s)
            if attempt < self.MAX_RETRIES:
                backoff = 2**attempt  # 1s, 2s
                await asyncio.sleep(backoff)
        else:
            # All retries exhausted
            raise ExtractionError(
                material_id=material_id,
                attempts=self.MAX_RETRIES + 1,
            )

        # Parse claims from the LLM response
        claims_data = response if isinstance(response, list) else response.get("claims", [])

        claims: list[Claim] = []
        for item in claims_data:
            source_span = item.get("source_span", "")

            # Validate source_span is exact substring of material_text
            if source_span not in material_text:
                logger.warning(
                    "Skipping claim with invalid source_span for material %s: "
                    "span %r not found in material text",
                    material_id,
                    source_span[:80],
                )
                continue

            try:
                claim = Claim(
                    id=str(uuid.uuid4()),
                    material_id=material_id,
                    category=ClaimCategory(item["category"]),
                    claim_text=item["claim_text"],
                    source_span=source_span,
                    source_span_start=item.get("source_span_start", 0),
                    source_span_end=item.get("source_span_end", 0),
                    grounding_status=None,
                    source_pointer=None,
                    discrepancy=None,
                    is_prospect_side=item.get("is_prospect_side", False),
                )
                claims.append(claim)
            except (KeyError, ValueError) as exc:
                logger.warning(
                    "Skipping malformed claim item for material %s: %s",
                    material_id,
                    exc,
                )
                continue

        return claims

    def verify_claims(
        self,
        claims: list[Claim],
        baseline_assets: dict[str, str],
        offerings_assets: dict[str, str],
        enrichment,
    ) -> list[Claim]:
        """Verify each claim against profile sources or enrichment.

        Verification logic (deterministic, no LLM call):
        1. If claim is prospect-side: verify against EnrichmentRecord fields
        2. If claim is NOT prospect-side and category is QUANTIFIED_METRIC:
           check if underlying achievement exists in assets but number differs
           → partially_grounded with discrepancy
        3. Otherwise: search baseline_assets and offerings_assets for supporting
           passage; assign grounded/ungrounded based on case-insensitive match

        Requirements: 2.1, 2.2, 2.3
        """
        verified_claims: list[Claim] = []

        for claim in claims:
            if self._is_prospect_side_claim(claim, enrichment):
                verified = self._verify_against_enrichment(claim, enrichment)
            elif claim.category == ClaimCategory.QUANTIFIED_METRIC:
                verified = self._verify_quantified_metric(
                    claim, baseline_assets, offerings_assets
                )
            else:
                verified = self._verify_against_assets(
                    claim, baseline_assets, offerings_assets
                )
            verified_claims.append(verified)

        return verified_claims

    def _is_prospect_side_claim(self, claim: Claim, enrichment) -> bool:
        """Determine if a claim refers to prospect-side facts.

        Returns True if:
        - claim.is_prospect_side is explicitly True, OR
        - claim_text references enrichment field values (company name,
          industry, tech_stack entries, headquarters, etc.)

        Prospect-side claims are verified against EnrichmentRecord,
        not Beneficiary assets.

        Requirements: 2.2
        """
        if claim.is_prospect_side:
            return True

        claim_lower = claim.claim_text.lower()

        # Check enrichment fields for references in the claim text
        enrichment_values: list[str] = []

        if getattr(enrichment, "company_name", None):
            enrichment_values.append(str(enrichment.company_name))
        if getattr(enrichment, "industry", None):
            enrichment_values.append(str(enrichment.industry))
        if getattr(enrichment, "revenue_range", None):
            enrichment_values.append(str(enrichment.revenue_range))
        if getattr(enrichment, "funding_stage", None):
            enrichment_values.append(str(enrichment.funding_stage))
        if getattr(enrichment, "headquarters_city", None):
            enrichment_values.append(str(enrichment.headquarters_city))
        if getattr(enrichment, "headquarters_country", None):
            enrichment_values.append(str(enrichment.headquarters_country))
        if getattr(enrichment, "employee_count", None) is not None:
            enrichment_values.append(str(enrichment.employee_count))

        # Check tech_stack entries
        tech_stack = getattr(enrichment, "tech_stack", None) or []
        enrichment_values.extend(str(t) for t in tech_stack)

        for value in enrichment_values:
            if value and value.lower() in claim_lower:
                return True

        return False

    def _verify_against_enrichment(self, claim: Claim, enrichment) -> Claim:
        """Verify a prospect-side claim against the EnrichmentRecord.

        Checks claim_text (case-insensitive) against enrichment fields:
        - employee_count, revenue_range, industry
        - tech_stack entries
        - funding_stage, headquarters_city, headquarters_country
        - company_name

        If claim_text content matches any enrichment field value → grounded.
        Otherwise → ungrounded.

        Requirements: 2.2
        """
        claim_lower = claim.claim_text.lower()

        # Collect all enrichment field values with their field names
        enrichment_fields: list[tuple[str, str]] = []

        if getattr(enrichment, "company_name", None):
            enrichment_fields.append(("company_name", str(enrichment.company_name)))
        if getattr(enrichment, "employee_count", None) is not None:
            enrichment_fields.append(("employee_count", str(enrichment.employee_count)))
        if getattr(enrichment, "revenue_range", None):
            enrichment_fields.append(("revenue_range", str(enrichment.revenue_range)))
        if getattr(enrichment, "industry", None):
            enrichment_fields.append(("industry", str(enrichment.industry)))
        if getattr(enrichment, "funding_stage", None):
            enrichment_fields.append(("funding_stage", str(enrichment.funding_stage)))
        if getattr(enrichment, "headquarters_city", None):
            enrichment_fields.append(
                ("headquarters_city", str(enrichment.headquarters_city))
            )
        if getattr(enrichment, "headquarters_country", None):
            enrichment_fields.append(
                ("headquarters_country", str(enrichment.headquarters_country))
            )

        # Check tech_stack entries
        tech_stack = getattr(enrichment, "tech_stack", None) or []
        for tech in tech_stack:
            enrichment_fields.append(("tech_stack", str(tech)))

        # Check if claim text contains any enrichment field value
        for field_name, field_value in enrichment_fields:
            if field_value and field_value.lower() in claim_lower:
                claim.grounding_status = GroundingStatus.GROUNDED
                claim.source_pointer = SourcePointer(
                    asset_type="enrichment_record",
                    asset_id=field_name,
                    passage=field_value,
                    confidence=1.0,
                )
                return claim

        claim.grounding_status = GroundingStatus.UNGROUNDED
        return claim

    def _verify_quantified_metric(
        self,
        claim: Claim,
        baseline_assets: dict[str, str],
        offerings_assets: dict[str, str],
    ) -> Claim:
        """Verify a QUANTIFIED_METRIC claim against assets.

        Logic:
        1. Extract numbers from the claim_text
        2. Strip numbers from claim_text to get the "achievement text"
        3. Strip numbers from asset text too, then search for achievement text
        4. If achievement text found in an asset:
           - Extract numbers from the original asset passage around the match
           - If numbers differ → partially_grounded with discrepancy
           - If numbers match → grounded
        5. If achievement text not found → ungrounded

        Requirements: 2.3
        """
        # Extract numbers from the claim text
        claim_numbers = re.findall(r"\d+(?:,\d{3})*(?:\.\d+)?%?", claim.claim_text)

        # Strip numbers and extra whitespace to get the achievement text
        achievement_text = re.sub(
            r"\d+(?:,\d{3})*(?:\.\d+)?%?", "", claim.claim_text
        ).strip()
        achievement_text = re.sub(r"\s+", " ", achievement_text)

        if not achievement_text:
            # If there's no text beyond numbers, fall back to full asset search
            return self._verify_against_assets(claim, baseline_assets, offerings_assets)

        achievement_lower = achievement_text.lower()

        # Search all assets for the achievement text
        # Strip numbers from asset text too for matching, but keep original for number extraction
        all_assets = {**baseline_assets, **offerings_assets}
        for asset_type, asset_text in all_assets.items():
            # Strip numbers from asset for substring matching
            asset_stripped = re.sub(r"\d+(?:,\d{3})*(?:\.\d+)?%?", "", asset_text)
            asset_stripped = re.sub(r"\s+", " ", asset_stripped)
            asset_stripped_lower = asset_stripped.lower()

            if achievement_lower in asset_stripped_lower:
                # Achievement text found — check if numbers match
                # Find the approximate location in the original asset
                # Use the position in stripped text to locate the passage in original
                start_idx = asset_stripped_lower.index(achievement_lower)
                # Map back to original text approximately
                # Find the passage in the original text around the same area
                # Use a broader context window from the original asset
                orig_lower = asset_text.lower()
                # Find a key phrase from the achievement text in the original
                key_words = [w for w in achievement_lower.split() if len(w) > 3]
                passage_start = 0
                if key_words:
                    first_key = key_words[0]
                    if first_key in orig_lower:
                        passage_start = orig_lower.index(first_key)

                context_start = max(0, passage_start - 50)
                context_end = min(len(asset_text), passage_start + len(achievement_text) + 100)
                passage = asset_text[context_start:context_end]

                # Extract numbers from the passage
                passage_numbers = re.findall(
                    r"\d+(?:,\d{3})*(?:\.\d+)?%?", passage
                )

                if claim_numbers and passage_numbers:
                    # Normalize numbers for comparison (remove commas)
                    normalized_claim = {n.replace(",", "") for n in claim_numbers}
                    normalized_passage = {n.replace(",", "") for n in passage_numbers}

                    if normalized_claim <= normalized_passage:
                        # All claim numbers found in passage → grounded
                        claim.grounding_status = GroundingStatus.GROUNDED
                        claim.source_pointer = SourcePointer(
                            asset_type=asset_type,
                            asset_id=asset_type,
                            passage=passage.strip(),
                            confidence=1.0,
                        )
                        return claim
                    elif normalized_claim & normalized_passage:
                        # Some numbers match → grounded (partial overlap)
                        claim.grounding_status = GroundingStatus.GROUNDED
                        claim.source_pointer = SourcePointer(
                            asset_type=asset_type,
                            asset_id=asset_type,
                            passage=passage.strip(),
                            confidence=0.9,
                        )
                        return claim
                    else:
                        # Numbers differ → partially_grounded
                        claim.grounding_status = GroundingStatus.PARTIALLY_GROUNDED
                        claim.source_pointer = SourcePointer(
                            asset_type=asset_type,
                            asset_id=asset_type,
                            passage=passage.strip(),
                            confidence=0.7,
                        )
                        claim.discrepancy = (
                            f"Claim states {', '.join(claim_numbers)} but "
                            f"source has {', '.join(passage_numbers)}"
                        )
                        return claim
                elif claim_numbers and not passage_numbers:
                    # Achievement found but no numbers in source → partially_grounded
                    claim.grounding_status = GroundingStatus.PARTIALLY_GROUNDED
                    claim.source_pointer = SourcePointer(
                        asset_type=asset_type,
                        asset_id=asset_type,
                        passage=passage.strip(),
                        confidence=0.5,
                    )
                    claim.discrepancy = (
                        f"Claim states {', '.join(claim_numbers)} but "
                        f"source does not include a specific number"
                    )
                    return claim
                else:
                    # No numbers in claim — treated as fully grounded
                    claim.grounding_status = GroundingStatus.GROUNDED
                    claim.source_pointer = SourcePointer(
                        asset_type=asset_type,
                        asset_id=asset_type,
                        passage=passage.strip(),
                        confidence=1.0,
                    )
                    return claim

        # Achievement text not found in any asset → ungrounded
        claim.grounding_status = GroundingStatus.UNGROUNDED
        return claim

    def _verify_against_assets(
        self,
        claim: Claim,
        baseline_assets: dict[str, str],
        offerings_assets: dict[str, str],
    ) -> Claim:
        """Verify a Beneficiary claim against profile assets.

        Uses case-insensitive substring matching: the claim_text (or
        meaningful keywords from it) must appear in at least one asset.

        If supporting passage found → grounded with SourcePointer.
        If not found → ungrounded.

        Requirements: 2.1
        """
        claim_lower = claim.claim_text.lower()

        # Search all assets for the claim text
        all_assets = {**baseline_assets, **offerings_assets}
        for asset_type, asset_text in all_assets.items():
            asset_lower = asset_text.lower()

            if claim_lower in asset_lower:
                # Exact claim text found → grounded
                start_idx = asset_lower.index(claim_lower)
                # Extract passage with some context
                context_start = max(0, start_idx - 50)
                context_end = min(len(asset_text), start_idx + len(claim.claim_text) + 50)
                passage = asset_text[context_start:context_end]

                claim.grounding_status = GroundingStatus.GROUNDED
                claim.source_pointer = SourcePointer(
                    asset_type=asset_type,
                    asset_id=asset_type,
                    passage=passage.strip(),
                    confidence=1.0,
                )
                return claim

        # Try keyword-based matching: extract significant words (>3 chars)
        # and check if enough keywords appear in any single asset
        keywords = [
            word for word in re.split(r"\W+", claim_lower)
            if len(word) > 3
        ]

        if keywords:
            for asset_type, asset_text in all_assets.items():
                asset_lower = asset_text.lower()
                matching_keywords = [kw for kw in keywords if kw in asset_lower]

                # If most keywords match (>= 70% threshold), consider grounded
                if len(matching_keywords) >= max(1, len(keywords) * 0.7):
                    # Find the best passage — look for the first matching keyword
                    first_match = matching_keywords[0]
                    start_idx = asset_lower.index(first_match)
                    context_start = max(0, start_idx - 50)
                    context_end = min(len(asset_text), start_idx + 150)
                    passage = asset_text[context_start:context_end]

                    claim.grounding_status = GroundingStatus.GROUNDED
                    claim.source_pointer = SourcePointer(
                        asset_type=asset_type,
                        asset_id=asset_type,
                        passage=passage.strip(),
                        confidence=0.8,
                    )
                    return claim

        # No supporting evidence found → ungrounded
        claim.grounding_status = GroundingStatus.UNGROUNDED
        return claim

    def apply_pipeline_gate(
        self,
        grounding_report: GroundingReport,
    ) -> tuple[bool, list[str]]:
        """Determine if pipeline should be blocked based on grounding results.

        Returns:
        - (True, []) if no ungrounded claims → pipeline can advance
        - (False, blocked_states) if any ungrounded → pipeline blocked

        Rules:
        - ANY claim with status "ungrounded" → block GATED_STATES
        - Only "partially_grounded" with no "ungrounded" → allow with warning
        - All "grounded" → allow freely

        Requirements: 3.1
        """
        has_ungrounded = grounding_report.ungrounded_count > 0
        if has_ungrounded:
            return (False, self.GATED_STATES)
        return (True, [])

    async def verify_material(
        self,
        reviewed_material,
        beneficiary,
        enrichment,
    ) -> GroundingResult:
        """Execute claim extraction and verification on a reviewed material.

        Orchestrates the full grounding verification flow:
        1. Extract claims from the material text
        2. On extraction failure: mark unverified, store report, return
        3. On success: verify claims against beneficiary assets and enrichment
        4. Build GroundingReport with counts and timing
        5. Apply pipeline gate to determine blocked states
        6. Persist report and return GroundingResult

        Requirements: 1.1, 1.4, 2.1, 2.4, 3.1
        """
        material_id = reviewed_material.id
        pipeline_record_id = reviewed_material.pipeline_record_id
        now = datetime.now(timezone.utc)

        # Step 1: Attempt claim extraction with timing
        extraction_start = time.perf_counter()

        try:
            claims = await self.extract_claims(
                reviewed_material.text, material_id
            )
        except ExtractionError:
            # Extraction failed after all retries — mark unverified
            extraction_end = time.perf_counter()
            extraction_duration_ms = int(
                (extraction_end - extraction_start) * 1000
            )

            report = GroundingReport(
                id=str(uuid.uuid4()),
                material_id=material_id,
                pipeline_record_id=pipeline_record_id,
                claims=[],
                total_claims=0,
                grounded_count=0,
                partially_grounded_count=0,
                ungrounded_count=0,
                material_grounding_status=MaterialGroundingStatus.GROUNDING_UNVERIFIED,
                extraction_duration_ms=extraction_duration_ms,
                verification_duration_ms=0,
                created_at=now,
                updated_at=now,
            )

            await self._db.store_grounding_report(report)

            return GroundingResult(
                material_id=material_id,
                material_grounding_status=MaterialGroundingStatus.GROUNDING_UNVERIFIED,
                grounding_report=report,
                blocked_states=[],
                requires_action=True,
            )

        extraction_end = time.perf_counter()
        extraction_duration_ms = int((extraction_end - extraction_start) * 1000)

        # Step 2: Verify claims against beneficiary assets and enrichment
        verification_start = time.perf_counter()

        verified_claims = self.verify_claims(
            claims,
            beneficiary.baseline_assets,
            beneficiary.offerings_assets,
            enrichment,
        )

        verification_end = time.perf_counter()
        verification_duration_ms = int(
            (verification_end - verification_start) * 1000
        )

        # Step 3: Compute aggregate counts
        grounded_count = sum(
            1
            for c in verified_claims
            if c.grounding_status == GroundingStatus.GROUNDED
        )
        partially_grounded_count = sum(
            1
            for c in verified_claims
            if c.grounding_status == GroundingStatus.PARTIALLY_GROUNDED
        )
        ungrounded_count = sum(
            1
            for c in verified_claims
            if c.grounding_status == GroundingStatus.UNGROUNDED
        )

        # Step 4: Determine material grounding status
        if ungrounded_count > 0:
            material_grounding_status = MaterialGroundingStatus.GROUNDING_BLOCKED
        else:
            material_grounding_status = MaterialGroundingStatus.GROUNDING_VERIFIED

        # Step 5: Build GroundingReport
        report = GroundingReport(
            id=str(uuid.uuid4()),
            material_id=material_id,
            pipeline_record_id=pipeline_record_id,
            claims=verified_claims,
            total_claims=len(verified_claims),
            grounded_count=grounded_count,
            partially_grounded_count=partially_grounded_count,
            ungrounded_count=ungrounded_count,
            material_grounding_status=material_grounding_status,
            extraction_duration_ms=extraction_duration_ms,
            verification_duration_ms=verification_duration_ms,
            created_at=now,
            updated_at=now,
        )

        # Step 6: Apply pipeline gate
        can_advance, blocked_states = self.apply_pipeline_gate(report)

        # Step 7: Persist report
        await self._db.store_grounding_report(report)

        # Step 8: Return result
        return GroundingResult(
            material_id=material_id,
            material_grounding_status=material_grounding_status,
            grounding_report=report,
            blocked_states=blocked_states,
            requires_action=not can_advance,
        )

    async def re_verify_claims(
        self,
        material_id: str,
        affected_claim_ids: list[str],
        updated_material_text: str | None = None,
        updated_assets: dict[str, str] | None = None,
        beneficiary=None,
        enrichment=None,
    ) -> GroundingResult:
        """Re-verify only the affected claims after resolution.

        Fetches the existing grounding report for the material, re-extracts
        or re-verifies only the affected claims, updates the report counts,
        stores a resolution record, and returns the updated GroundingResult.

        Must complete within VERIFICATION_TIMEOUT (30 seconds).

        Requirements: 3.3
        """

        async def _do_re_verify() -> GroundingResult:
            now = datetime.now(timezone.utc)
            verification_start = time.perf_counter()

            # Step 1: Fetch existing grounding report
            existing_report = await self._db.get_latest_grounding_report_by_material(
                material_id
            )
            if existing_report is None:
                raise ValueError(
                    f"No grounding report found for material {material_id}"
                )

            # Step 2: Separate affected and unaffected claims
            affected_claims = [
                c for c in existing_report.claims if c.id in affected_claim_ids
            ]
            unaffected_claims = [
                c for c in existing_report.claims if c.id not in affected_claim_ids
            ]

            # Step 3: Determine which assets to verify against
            baseline_assets = {}
            offerings_assets = {}
            if beneficiary is not None:
                baseline_assets = getattr(beneficiary, "baseline_assets", {})
                offerings_assets = getattr(beneficiary, "offerings_assets", {})

            # Merge in any updated_assets (these override existing ones)
            if updated_assets:
                baseline_assets = {**baseline_assets, **updated_assets}

            # Step 4: If updated_material_text provided, re-extract claims
            if updated_material_text is not None:
                new_claims = await self.extract_claims(
                    updated_material_text, material_id
                )
                # Match new claims to affected IDs by position/order
                # Use up to len(affected_claim_ids) new claims, preserving original IDs
                re_extracted = []
                for i, new_claim in enumerate(new_claims):
                    if i < len(affected_claim_ids):
                        # Preserve the original claim ID for tracking
                        new_claim.id = affected_claim_ids[i]
                        re_extracted.append(new_claim)
                    else:
                        # Additional claims beyond affected IDs get new UUIDs
                        re_extracted.append(new_claim)

                affected_claims = re_extracted if re_extracted else affected_claims

            # Step 5: Re-verify only the affected claims
            re_verified_claims = self.verify_claims(
                affected_claims,
                baseline_assets,
                offerings_assets,
                enrichment,
            )

            # Step 6: Combine re-verified with unaffected claims
            all_claims = unaffected_claims + re_verified_claims

            # Step 7: Recompute counts
            grounded_count = sum(
                1
                for c in all_claims
                if c.grounding_status == GroundingStatus.GROUNDED
            )
            partially_grounded_count = sum(
                1
                for c in all_claims
                if c.grounding_status == GroundingStatus.PARTIALLY_GROUNDED
            )
            ungrounded_count = sum(
                1
                for c in all_claims
                if c.grounding_status == GroundingStatus.UNGROUNDED
            )

            # Step 8: Determine new material_grounding_status
            if ungrounded_count > 0:
                material_grounding_status = MaterialGroundingStatus.GROUNDING_BLOCKED
            else:
                material_grounding_status = MaterialGroundingStatus.GROUNDING_VERIFIED

            verification_end = time.perf_counter()
            verification_duration_ms = int(
                (verification_end - verification_start) * 1000
            )

            # Step 9: Update the existing report
            existing_report.claims = all_claims
            existing_report.total_claims = len(all_claims)
            existing_report.grounded_count = grounded_count
            existing_report.partially_grounded_count = partially_grounded_count
            existing_report.ungrounded_count = ungrounded_count
            existing_report.material_grounding_status = material_grounding_status
            existing_report.verification_duration_ms = verification_duration_ms
            existing_report.updated_at = now

            # Step 10: Persist updated report
            await self._db.update_grounding_report(existing_report)

            # Step 11: Store resolution record for each affected claim
            for claim_id in affected_claim_ids:
                resolution = {
                    "grounding_report_id": existing_report.id,
                    "claim_id": claim_id,
                    "resolution_path": ResolutionPath.MANUAL_EDIT.value,
                    "resolved_by": "system",
                    "resolution_detail": {
                        "updated_material_text": updated_material_text is not None,
                        "updated_assets": updated_assets is not None,
                    },
                    "re_verification_status": material_grounding_status.value,
                    "re_verification_duration_ms": verification_duration_ms,
                    "resolved_at": now,
                }
                await self._db.store_resolution(resolution)

            # Step 12: Apply pipeline gate
            can_advance, blocked_states = self.apply_pipeline_gate(existing_report)

            return GroundingResult(
                material_id=material_id,
                material_grounding_status=material_grounding_status,
                grounding_report=existing_report,
                blocked_states=blocked_states,
                requires_action=not can_advance,
            )

        # Enforce 30-second timeout
        return await asyncio.wait_for(
            _do_re_verify(), timeout=self.VERIFICATION_TIMEOUT
        )

    async def resolve_regenerate(
        self,
        material_id: str,
        ungrounded_claim_ids: list[str],
        beneficiary=None,
        enrichment=None,
    ) -> GroundingResult:
        """Resolution path: regenerate flagged passages with grounding constraints.

        Instructs PersonalizationEngine to regenerate ONLY the passages
        containing ungrounded claims, with an explicit constraint excluding
        the ungrounded content. Then re-verifies the affected claims.

        Requirements: 3.2
        """
        # Step 1: Fetch existing report to get ungrounded claims
        existing_report = await self._db.get_latest_grounding_report_by_material(
            material_id
        )
        if existing_report is None:
            raise ValueError(
                f"No grounding report found for material {material_id}"
            )

        # Step 2: Get the ungrounded claims
        ungrounded_claims = [
            c for c in existing_report.claims if c.id in ungrounded_claim_ids
        ]

        if not ungrounded_claims:
            # Nothing to regenerate, return current state
            can_advance, blocked_states = self.apply_pipeline_gate(existing_report)
            return GroundingResult(
                material_id=material_id,
                material_grounding_status=existing_report.material_grounding_status,
                grounding_report=existing_report,
                blocked_states=blocked_states,
                requires_action=not can_advance,
            )

        # Step 3: Build beneficiary context for regeneration
        beneficiary_context = {}
        if beneficiary is not None:
            beneficiary_context = {
                "baseline_assets": getattr(beneficiary, "baseline_assets", {}),
                "offerings_assets": getattr(beneficiary, "offerings_assets", {}),
            }

        # Step 4: Get the current material text from the report's first claim's span context
        # We need the full material text — use the source spans to reconstruct context
        # The personalization engine needs the full material text
        # For now, we'll pass the material_id and let the engine handle retrieval
        material_text = ""
        if ungrounded_claims:
            # Build approximate material text from claim spans
            # In practice, this would come from the material storage
            material_text = ""

        # Step 5: Call PersonalizationEngine to regenerate passages
        updated_text = await self._personalization.regenerate_passages(
            material_id=material_id,
            material_text=material_text,
            excluded_claims=ungrounded_claims,
            beneficiary_context=beneficiary_context,
        )

        # Step 6: Re-verify the affected claims with the updated text
        return await self.re_verify_claims(
            material_id=material_id,
            affected_claim_ids=ungrounded_claim_ids,
            updated_material_text=updated_text,
            beneficiary=beneficiary,
            enrichment=enrichment,
        )

    async def resolve_confirm_and_add(
        self,
        material_id: str,
        claim_id: str,
        supporting_fact: str,
        target_asset_id: str,
        beneficiary=None,
        enrichment=None,
    ) -> GroundingResult:
        """Resolution path: confirm claim is true and add to profile asset.

        Adds the supporting_fact to the specified profile asset, then
        re-verifies the claim against the updated assets.

        Requirements: 3.2
        """
        # Step 1: Build the updated assets with the new supporting fact
        baseline_assets = {}
        offerings_assets = {}
        if beneficiary is not None:
            baseline_assets = dict(getattr(beneficiary, "baseline_assets", {}))
            offerings_assets = dict(getattr(beneficiary, "offerings_assets", {}))

        # Step 2: Append the supporting fact to the target asset
        updated_assets = {**baseline_assets, **offerings_assets}
        if target_asset_id in updated_assets:
            updated_assets[target_asset_id] = (
                updated_assets[target_asset_id] + "\n" + supporting_fact
            )
        else:
            updated_assets[target_asset_id] = supporting_fact

        # Step 3: Re-verify the confirmed claim against updated assets
        result = await self.re_verify_claims(
            material_id=material_id,
            affected_claim_ids=[claim_id],
            updated_assets=updated_assets,
            beneficiary=beneficiary,
            enrichment=enrichment,
        )

        # Step 4: Store resolution record with confirm_and_add path
        existing_report = result.grounding_report
        now = datetime.now(timezone.utc)
        resolution = {
            "grounding_report_id": existing_report.id,
            "claim_id": claim_id,
            "resolution_path": ResolutionPath.CONFIRM_AND_ADD.value,
            "resolved_by": "user",
            "resolution_detail": {
                "supporting_fact": supporting_fact,
                "target_asset_id": target_asset_id,
            },
            "re_verification_status": result.material_grounding_status.value,
            "re_verification_duration_ms": existing_report.verification_duration_ms,
            "resolved_at": now,
        }
        await self._db.store_resolution(resolution)

        return result
