# Feature: internal-profile-enrichment, Property 6: Deduplication Soundness
"""Property-based tests for deduplication soundness.

Tests the ProposalDeduplicator's core guarantee: output contains only
candidates whose normalized name doesn't match existing (exact or ≥85%
fuzzy) and whose (name, category) doesn't match rejected or pending
proposals. No genuinely new candidates are incorrectly filtered out.

**Validates: Requirements 2.2, 3.3**
"""

from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.proposal_deduplicator import (
    CompetencyCandidate,
    DeduplicationRepository,
    ProfileAsset,
    ProposalDeduplicator,
    ProposalRecord,
)


# ─── Mock Repository ─────────────────────────────────────────────────────────


class InMemoryDeduplicationRepository:
    """In-memory implementation of DeduplicationRepository for testing."""

    def __init__(
        self,
        profile_assets: list[ProfileAsset],
        rejected_proposals: list[ProposalRecord],
        pending_proposals: list[ProposalRecord],
    ):
        self._profile_assets = profile_assets
        self._rejected_proposals = rejected_proposals
        self._pending_proposals = pending_proposals

    async def get_profile_assets(self, consultant_id: str) -> list[ProfileAsset]:
        return self._profile_assets

    async def get_rejected_proposals(self, consultant_id: str) -> list[ProposalRecord]:
        return self._rejected_proposals

    async def get_pending_proposals(self, consultant_id: str) -> list[ProposalRecord]:
        return self._pending_proposals


# ─── Strategies ───────────────────────────────────────────────────────────────

# Categories used across the system
CATEGORIES = [
    "technology",
    "publication",
    "certification",
    "course",
    "project",
    "community_role",
]

category_st = st.sampled_from(CATEGORIES)

# Strategy for competency names: printable strings without leading/trailing whitespace
# that are not empty. We use a restricted alphabet to make fuzzy matching meaningful.
name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs"), min_codepoint=32, max_codepoint=122),
    min_size=2,
    max_size=30,
).map(lambda s: s.strip()).filter(lambda s: len(s) >= 2)

# Strategy for ProfileAsset
profile_asset_st = st.builds(
    ProfileAsset,
    name=name_st,
    category=category_st,
)

# Strategy for ProposalRecord
proposal_record_st = st.builds(
    ProposalRecord,
    name=name_st,
    category=category_st,
)

# Strategy for CompetencyCandidate
candidate_st = st.builds(
    CompetencyCandidate,
    category=category_st,
    name=name_st,
    evidence_summary=st.just("Test evidence"),
    confidence=st.sampled_from(["strong", "inferred"]),
    source_url=st.just("https://example.com/source"),
    raw_evidence=st.just("Raw test evidence"),
)


# ─── Helper functions ─────────────────────────────────────────────────────────


def normalize(name: str) -> str:
    """Mirror the deduplicator's normalization logic."""
    normalized = name.lower().strip()
    normalized = re.sub(r"\s*v?\d+(\.\d+)*\.?[x*]?\s*$", "", normalized)
    return normalized.strip()


def is_fuzzy_match(name: str, existing_names: set[str], threshold: float = 0.85) -> bool:
    """Check if a normalized name fuzzy-matches any in the existing set."""
    for existing in existing_names:
        ratio = SequenceMatcher(None, name, existing).ratio()
        if ratio >= threshold:
            return True
    return False


def is_genuinely_new(
    candidate: CompetencyCandidate,
    existing_names: set[str],
    rejected_keys: set[tuple[str, str]],
    pending_keys: set[tuple[str, str]],
) -> bool:
    """Determine if a candidate is genuinely new (should pass deduplication)."""
    norm_name = normalize(candidate.name)

    # Exact match against existing profile
    if norm_name in existing_names:
        return False

    # Fuzzy match against existing profile
    if is_fuzzy_match(norm_name, existing_names):
        return False

    # Match against rejected proposals (name + category)
    if (norm_name, candidate.category) in rejected_keys:
        return False

    # Match against pending proposals (name + category)
    if (norm_name, candidate.category) in pending_keys:
        return False

    return True


def run_async(coro):
    """Helper to run async code in tests."""
    return asyncio.run(coro)


# ─── Property 6: Deduplication Soundness ──────────────────────────────────────


class TestProperty6DeduplicationSoundness:
    """Property 6: Deduplication Soundness.

    **Validates: Requirements 2.2, 3.3**

    Key invariants:
    - Every returned candidate is genuinely new (not in existing, not rejected, not pending)
    - No genuinely new candidate is incorrectly filtered out
    - Candidates matching existing assets (exact or fuzzy ≥ 0.85) are NOT in output
    - Candidates matching rejected proposals are NOT in output
    """

    @given(
        existing_assets=st.lists(profile_asset_st, min_size=0, max_size=10),
        rejected_proposals=st.lists(proposal_record_st, min_size=0, max_size=10),
        pending_proposals=st.lists(proposal_record_st, min_size=0, max_size=10),
        candidates=st.lists(candidate_st, min_size=1, max_size=15),
    )
    @settings(max_examples=200)
    def test_output_contains_only_genuinely_new_candidates(
        self,
        existing_assets: list[ProfileAsset],
        rejected_proposals: list[ProposalRecord],
        pending_proposals: list[ProposalRecord],
        candidates: list[CompetencyCandidate],
    ) -> None:
        """FOR ANY inputs, every candidate in the output is genuinely new.

        No candidate that matches an existing asset (exact or fuzzy),
        a rejected proposal, or a pending proposal should appear in the output.

        **Validates: Requirements 2.2, 3.3**
        """
        repo = InMemoryDeduplicationRepository(
            profile_assets=existing_assets,
            rejected_proposals=rejected_proposals,
            pending_proposals=pending_proposals,
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        result = run_async(deduplicator.deduplicate(candidates, "test-consultant"))

        # Compute reference sets
        existing_names = {normalize(a.name) for a in existing_assets}
        rejected_keys = {
            (normalize(p.name), p.category) for p in rejected_proposals
        }
        pending_keys = {
            (normalize(p.name), p.category) for p in pending_proposals
        }

        # Every output candidate must be genuinely new
        for candidate in result:
            norm_name = normalize(candidate.name)

            # Must not exact-match existing
            assert norm_name not in existing_names, (
                f"Candidate '{candidate.name}' (normalized: '{norm_name}') "
                f"matches existing asset but was not filtered."
            )

            # Must not fuzzy-match existing
            assert not is_fuzzy_match(norm_name, existing_names), (
                f"Candidate '{candidate.name}' (normalized: '{norm_name}') "
                f"fuzzy-matches an existing asset but was not filtered."
            )

            # Must not match rejected
            assert (norm_name, candidate.category) not in rejected_keys, (
                f"Candidate '{candidate.name}' category='{candidate.category}' "
                f"matches rejected proposal but was not filtered."
            )

            # Must not match pending
            assert (norm_name, candidate.category) not in pending_keys, (
                f"Candidate '{candidate.name}' category='{candidate.category}' "
                f"matches pending proposal but was not filtered."
            )

    @given(
        existing_assets=st.lists(profile_asset_st, min_size=0, max_size=10),
        rejected_proposals=st.lists(proposal_record_st, min_size=0, max_size=10),
        pending_proposals=st.lists(proposal_record_st, min_size=0, max_size=10),
        candidates=st.lists(candidate_st, min_size=1, max_size=15),
    )
    @settings(max_examples=200)
    def test_no_genuinely_new_candidate_is_filtered_out(
        self,
        existing_assets: list[ProfileAsset],
        rejected_proposals: list[ProposalRecord],
        pending_proposals: list[ProposalRecord],
        candidates: list[CompetencyCandidate],
    ) -> None:
        """FOR ANY inputs, no genuinely new candidate is incorrectly filtered.

        If a candidate does not match existing (exact or fuzzy), does not match
        rejected, and does not match pending, it MUST appear in the output.

        **Validates: Requirements 2.2, 3.3**
        """
        repo = InMemoryDeduplicationRepository(
            profile_assets=existing_assets,
            rejected_proposals=rejected_proposals,
            pending_proposals=pending_proposals,
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        result = run_async(deduplicator.deduplicate(candidates, "test-consultant"))

        # Compute reference sets
        existing_names = {normalize(a.name) for a in existing_assets}
        rejected_keys = {
            (normalize(p.name), p.category) for p in rejected_proposals
        }
        pending_keys = {
            (normalize(p.name), p.category) for p in pending_proposals
        }

        # Every genuinely new candidate must appear in the output
        result_identities = [
            (normalize(c.name), c.category, c.source_url) for c in result
        ]

        for candidate in candidates:
            if is_genuinely_new(candidate, existing_names, rejected_keys, pending_keys):
                candidate_identity = (
                    normalize(candidate.name),
                    candidate.category,
                    candidate.source_url,
                )
                assert candidate_identity in result_identities, (
                    f"Genuinely new candidate '{candidate.name}' "
                    f"category='{candidate.category}' was incorrectly filtered out."
                )

    @given(
        existing_assets=st.lists(profile_asset_st, min_size=1, max_size=10),
        candidates=st.lists(candidate_st, min_size=1, max_size=10),
    )
    @settings(max_examples=200)
    def test_exact_match_against_existing_is_filtered(
        self,
        existing_assets: list[ProfileAsset],
        candidates: list[CompetencyCandidate],
    ) -> None:
        """FOR ANY candidate whose normalized name exactly matches an existing
        asset, that candidate is NOT in the output.

        **Validates: Requirements 2.2, 3.3**
        """
        # Force at least one candidate to be an exact match
        target_asset = existing_assets[0]
        exact_duplicate = CompetencyCandidate(
            category="technology",
            name=target_asset.name,
            evidence_summary="Duplicate evidence",
            confidence="strong",
            source_url="https://example.com/dup",
            raw_evidence="Raw dup",
        )
        test_candidates = [exact_duplicate] + candidates

        repo = InMemoryDeduplicationRepository(
            profile_assets=existing_assets,
            rejected_proposals=[],
            pending_proposals=[],
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        result = run_async(deduplicator.deduplicate(test_candidates, "test-consultant"))

        # The exact duplicate must not be in the output
        result_norm_names = {normalize(c.name) for c in result}
        target_norm = normalize(target_asset.name)
        assert target_norm not in result_norm_names, (
            f"Candidate with name '{target_asset.name}' (normalized: '{target_norm}') "
            f"matches an existing asset but was not filtered."
        )

    @given(
        rejected_proposals=st.lists(proposal_record_st, min_size=1, max_size=10),
        candidates=st.lists(candidate_st, min_size=1, max_size=10),
    )
    @settings(max_examples=200)
    def test_rejected_proposals_are_filtered(
        self,
        rejected_proposals: list[ProposalRecord],
        candidates: list[CompetencyCandidate],
    ) -> None:
        """FOR ANY candidate whose (name, category) matches a rejected proposal,
        that candidate is NOT in the output.

        **Validates: Requirements 2.2, 3.3**
        """
        # Force at least one candidate to match a rejected proposal
        target_rejected = rejected_proposals[0]
        rejected_duplicate = CompetencyCandidate(
            category=target_rejected.category,
            name=target_rejected.name,
            evidence_summary="Re-proposed evidence",
            confidence="inferred",
            source_url="https://example.com/rejected",
            raw_evidence="Raw rejected",
        )
        test_candidates = [rejected_duplicate] + candidates

        repo = InMemoryDeduplicationRepository(
            profile_assets=[],
            rejected_proposals=rejected_proposals,
            pending_proposals=[],
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        result = run_async(deduplicator.deduplicate(test_candidates, "test-consultant"))

        # The rejected duplicate must not be in the output
        target_key = (normalize(target_rejected.name), target_rejected.category)
        result_keys = {(normalize(c.name), c.category) for c in result}
        assert target_key not in result_keys, (
            f"Candidate with name='{target_rejected.name}' "
            f"category='{target_rejected.category}' matches a rejected proposal "
            f"but was not filtered."
        )

    @given(
        existing_assets=st.lists(profile_asset_st, min_size=0, max_size=10),
        rejected_proposals=st.lists(proposal_record_st, min_size=0, max_size=10),
        pending_proposals=st.lists(proposal_record_st, min_size=0, max_size=10),
        candidates=st.lists(candidate_st, min_size=1, max_size=15),
    )
    @settings(max_examples=200)
    def test_output_is_subset_of_input(
        self,
        existing_assets: list[ProfileAsset],
        rejected_proposals: list[ProposalRecord],
        pending_proposals: list[ProposalRecord],
        candidates: list[CompetencyCandidate],
    ) -> None:
        """FOR ANY inputs, the output is always a subset of the input candidates.

        The deduplicator must only filter — never add or modify candidates.

        **Validates: Requirements 2.2, 3.3**
        """
        repo = InMemoryDeduplicationRepository(
            profile_assets=existing_assets,
            rejected_proposals=rejected_proposals,
            pending_proposals=pending_proposals,
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        result = run_async(deduplicator.deduplicate(candidates, "test-consultant"))

        # Output must be a subset of input (by identity)
        assert len(result) <= len(candidates), (
            f"Output ({len(result)}) has more items than input ({len(candidates)})"
        )

        # Each result item must be one of the original candidates (same object)
        for r in result:
            assert r in candidates, (
                f"Output contains candidate '{r.name}' that was not in input."
            )
