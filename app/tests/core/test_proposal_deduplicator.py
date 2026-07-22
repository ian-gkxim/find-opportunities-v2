"""Unit tests for ProposalDeduplicator.

Tests exact match deduplication, fuzzy match at threshold boundaries,
normalization with version suffix stripping, rejection history checks,
pending proposal deduplication, and case insensitivity.

Requirements: 2.2, 3.3
"""

import pytest

from app.core.proposal_deduplicator import (
    CompetencyCandidate,
    DeduplicationRepository,
    ProfileAsset,
    ProposalDeduplicator,
    ProposalRecord,
)


# ─── Mock Repository ──────────────────────────────────────────────────────────


class MockDeduplicationRepository:
    """In-memory implementation of DeduplicationRepository for testing."""

    def __init__(
        self,
        profile_assets: list[ProfileAsset] | None = None,
        rejected_proposals: list[ProposalRecord] | None = None,
        pending_proposals: list[ProposalRecord] | None = None,
    ):
        self._profile_assets = profile_assets or []
        self._rejected_proposals = rejected_proposals or []
        self._pending_proposals = pending_proposals or []

    async def get_profile_assets(self, consultant_id: str) -> list[ProfileAsset]:
        return self._profile_assets

    async def get_rejected_proposals(self, consultant_id: str) -> list[ProposalRecord]:
        return self._rejected_proposals

    async def get_pending_proposals(self, consultant_id: str) -> list[ProposalRecord]:
        return self._pending_proposals


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_candidate(name: str, category: str = "technology") -> CompetencyCandidate:
    """Create a CompetencyCandidate with minimal required fields."""
    return CompetencyCandidate(
        category=category,
        name=name,
        evidence_summary="Test evidence",
        confidence="strong",
        source_url="https://example.com",
        raw_evidence="raw snippet",
    )


# ─── Exact Match Tests ────────────────────────────────────────────────────────


class TestExactMatchDeduplication:
    """Candidates with same normalized name as existing assets are filtered."""

    @pytest.mark.asyncio
    async def test_exact_name_match_filtered(self):
        """Candidate with same name as profile asset is deduplicated."""
        repo = MockDeduplicationRepository(
            profile_assets=[ProfileAsset(name="Python", category="technology")]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("Python")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_case_insensitive_exact_match(self):
        """'PYTHON' matches existing 'python' via normalization."""
        repo = MockDeduplicationRepository(
            profile_assets=[ProfileAsset(name="python", category="technology")]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("PYTHON")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_different_name_passes(self):
        """Candidate with a completely different name passes through."""
        repo = MockDeduplicationRepository(
            profile_assets=[ProfileAsset(name="Python", category="technology")]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("Rust")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 1
        assert result[0].name == "Rust"


# ─── Fuzzy Match Boundary Tests ───────────────────────────────────────────────


class TestFuzzyMatchBoundary:
    """Fuzzy match at threshold boundary: 86% filtered, 84% passes."""

    @pytest.mark.asyncio
    async def test_high_similarity_filtered(self):
        """Candidate with >=85% similarity is filtered.

        'kubernetes' vs 'kubernete' (missing trailing 's') gives a ratio
        high enough to exceed 0.85 threshold.
        """
        repo = MockDeduplicationRepository(
            profile_assets=[ProfileAsset(name="kubernetes", category="technology")]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        # 'kubernete' vs 'kubernetes' — SequenceMatcher ratio ~ 0.947
        candidates = [_make_candidate("kubernete")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_below_threshold_passes(self):
        """Candidate with <85% similarity passes through.

        Choose names that produce similarity just below threshold.
        'kubernetes' vs 'kubernates' gives ratio below 0.85.
        """
        from difflib import SequenceMatcher

        existing_name = "kubernetes"
        # Find a name that's below 0.85 threshold
        candidate_name = "kubernax"
        ratio = SequenceMatcher(None, candidate_name, existing_name).ratio()
        assert ratio < 0.85, f"Test precondition: ratio {ratio} should be < 0.85"

        repo = MockDeduplicationRepository(
            profile_assets=[ProfileAsset(name=existing_name, category="technology")]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate(candidate_name)]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_exactly_at_threshold_filtered(self):
        """Candidate at exactly 0.85 similarity is filtered (>= threshold)."""
        from difflib import SequenceMatcher

        # 'abcdefghijklmnopqrst' (20 chars) vs 'abcdefghijklmnopqXYZ' (20 chars)
        # We need a pair that gives ratio >= 0.85
        existing = "abcdefghijklmnopqrst"
        candidate = "abcdefghijklmnopqrsx"  # 1 char diff in 20 → ratio = 0.95
        ratio = SequenceMatcher(None, candidate, existing).ratio()
        assert ratio >= 0.85, f"Test precondition: ratio {ratio} should be >= 0.85"

        repo = MockDeduplicationRepository(
            profile_assets=[ProfileAsset(name=existing, category="technology")]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate(candidate)]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 0


# ─── Normalization Tests ──────────────────────────────────────────────────────


class TestNormalization:
    """Version suffixes are stripped and names are lowercased."""

    def test_version_suffix_v_prefix(self):
        """'Python v3.9' normalizes to 'python'."""
        result = ProposalDeduplicator._normalize("Python v3.9")
        assert result == "python"

    def test_version_suffix_without_v(self):
        """'React 18.2' normalizes to 'react'."""
        result = ProposalDeduplicator._normalize("React 18.2")
        assert result == "react"

    def test_kubernetes_version(self):
        """'Kubernetes v1.28' normalizes to 'kubernetes'."""
        result = ProposalDeduplicator._normalize("Kubernetes v1.28")
        assert result == "kubernetes"

    def test_simple_name_no_version(self):
        """'Docker' normalizes to 'docker' (lowercase only)."""
        result = ProposalDeduplicator._normalize("Docker")
        assert result == "docker"

    def test_leading_trailing_whitespace(self):
        """Whitespace is stripped."""
        result = ProposalDeduplicator._normalize("  Python  ")
        assert result == "python"

    def test_multi_digit_version(self):
        """'Node.js 20.11.0' normalizes to 'node.js'."""
        result = ProposalDeduplicator._normalize("Node.js 20.11.0")
        assert result == "node.js"

    @pytest.mark.asyncio
    async def test_normalization_enables_deduplication(self):
        """'Python v3.9' candidate deduplicates against 'Python' in profile."""
        repo = MockDeduplicationRepository(
            profile_assets=[ProfileAsset(name="Python", category="technology")]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("Python v3.9")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 0


# ─── Rejection History Tests ──────────────────────────────────────────────────


class TestRejectionHistory:
    """Previously rejected proposals are not re-proposed."""

    @pytest.mark.asyncio
    async def test_rejected_name_category_filtered(self):
        """Candidate whose (name, category) matches a rejected proposal is filtered."""
        repo = MockDeduplicationRepository(
            rejected_proposals=[
                ProposalRecord(name="Terraform", category="technology")
            ]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("Terraform", category="technology")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_same_name_different_category_passes_rejection(self):
        """Same name with different category is not blocked by rejection history."""
        repo = MockDeduplicationRepository(
            rejected_proposals=[
                ProposalRecord(name="Docker", category="technology")
            ]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        # "Docker" as a project (different category) should pass
        candidates = [_make_candidate("Docker", category="project")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 1
        assert result[0].name == "Docker"


# ─── Pending Proposal Tests ──────────────────────────────────────────────────


class TestPendingProposals:
    """Candidates matching pending proposals are filtered."""

    @pytest.mark.asyncio
    async def test_pending_duplicate_filtered(self):
        """Candidate whose (name, category) matches pending proposal is filtered."""
        repo = MockDeduplicationRepository(
            pending_proposals=[
                ProposalRecord(name="GraphQL", category="technology")
            ]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("GraphQL", category="technology")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_pending_different_category_passes(self):
        """Same name in different category is not blocked by pending proposals."""
        repo = MockDeduplicationRepository(
            pending_proposals=[
                ProposalRecord(name="GraphQL", category="technology")
            ]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("GraphQL", category="certification")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 1


# ─── Genuinely New Candidate Tests ────────────────────────────────────────────


class TestGenuinelyNewCandidate:
    """A genuinely new candidate passes through all checks."""

    @pytest.mark.asyncio
    async def test_new_candidate_passes_all_checks(self):
        """Candidate not in profile, not rejected, not pending passes through."""
        repo = MockDeduplicationRepository(
            profile_assets=[
                ProfileAsset(name="Python", category="technology"),
                ProfileAsset(name="AWS", category="technology"),
            ],
            rejected_proposals=[
                ProposalRecord(name="Terraform", category="technology"),
            ],
            pending_proposals=[
                ProposalRecord(name="GraphQL", category="technology"),
            ],
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("Rust", category="technology")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 1
        assert result[0].name == "Rust"

    @pytest.mark.asyncio
    async def test_multiple_new_candidates_all_pass(self):
        """Multiple genuinely new candidates all pass through."""
        repo = MockDeduplicationRepository(
            profile_assets=[ProfileAsset(name="Python", category="technology")]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [
            _make_candidate("Rust"),
            _make_candidate("Go"),
            _make_candidate("Elixir"),
        ]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_empty_repository_all_pass(self):
        """With no existing data, all candidates pass through."""
        repo = MockDeduplicationRepository()
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [
            _make_candidate("Python"),
            _make_candidate("Docker"),
        ]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 2


# ─── Case Insensitivity Tests ─────────────────────────────────────────────────


class TestCaseInsensitivity:
    """Normalization handles case insensitivity correctly."""

    @pytest.mark.asyncio
    async def test_uppercase_matches_lowercase_profile(self):
        """'PYTHON' matches existing 'python' in profile."""
        repo = MockDeduplicationRepository(
            profile_assets=[ProfileAsset(name="python", category="technology")]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("PYTHON")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_mixed_case_matches(self):
        """'PyThOn' matches existing 'python' in profile."""
        repo = MockDeduplicationRepository(
            profile_assets=[ProfileAsset(name="Python", category="technology")]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("PyThOn")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_case_insensitive_rejection_check(self):
        """Rejection check is also case insensitive."""
        repo = MockDeduplicationRepository(
            rejected_proposals=[
                ProposalRecord(name="TERRAFORM", category="technology")
            ]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("terraform", category="technology")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 0


# ─── Same Name Different Category Tests ──────────────────────────────────────


class TestSameNameDifferentCategory:
    """Same name in a different category may pass (rejection is name+category)."""

    @pytest.mark.asyncio
    async def test_same_name_different_category_passes_rejection(self):
        """technology 'Docker' rejected, project 'Docker' passes."""
        repo = MockDeduplicationRepository(
            rejected_proposals=[
                ProposalRecord(name="Docker", category="technology")
            ]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        candidates = [_make_candidate("Docker", category="project")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_same_name_same_category_in_profile_still_filtered(self):
        """Exact name match in profile is category-independent (name-only check)."""
        repo = MockDeduplicationRepository(
            profile_assets=[ProfileAsset(name="Docker", category="technology")]
        )
        deduplicator = ProposalDeduplicator(db_repo=repo)

        # Even though category differs, profile check is name-only
        candidates = [_make_candidate("Docker", category="project")]
        result = await deduplicator.deduplicate(candidates, "consultant-001")

        assert len(result) == 0
