"""Deduplication logic for competency proposals.

Deduplicates candidates against:
1. Existing profile assets (exact and fuzzy match on name)
2. Previously rejected proposals (exact match on name + category)
3. Currently pending proposals (prevent duplicates within same cycle)

Requirements: 2.2, 3.3
"""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Protocol


# ─── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class CompetencyCandidate:
    """A single extracted competency candidate before deduplication."""

    category: str  # "technology", "publication", "certification",
    # "course", "project", "community_role"
    name: str  # e.g. "Kubernetes", "RFC 9114 co-author"
    evidence_summary: str  # e.g. "Owner of 'k8s-operator' repo (142 stars)"
    confidence: str  # "strong" or "inferred"
    source_url: str  # The Public_Source URL it came from
    raw_evidence: str  # Verbatim snippet from source content


@dataclass
class ProfileAsset:
    """A competency already present in the Consultant's profile."""

    name: str
    category: str


@dataclass
class ProposalRecord:
    """A previously created proposal (rejected or pending)."""

    name: str
    category: str


# ─── Repository Protocol ─────────────────────────────────────────────────────


class DeduplicationRepository(Protocol):
    """Protocol for the data access layer used by the deduplicator.

    Implementations must provide methods to query existing profile assets,
    rejected proposals, and pending proposals for a given consultant.
    """

    async def get_profile_assets(self, consultant_id: str) -> list[ProfileAsset]:
        """Return all existing profile assets for the consultant."""
        ...

    async def get_rejected_proposals(
        self, consultant_id: str
    ) -> list[ProposalRecord]:
        """Return all previously rejected proposals for the consultant."""
        ...

    async def get_pending_proposals(
        self, consultant_id: str
    ) -> list[ProposalRecord]:
        """Return all currently pending proposals for the consultant."""
        ...


# ─── Deduplicator ────────────────────────────────────────────────────────────


class ProposalDeduplicator:
    """Deduplicates competency candidates against profile and history.

    Checks in order for each candidate:
    1. Exact normalized name match against existing profile assets → skip
    2. Fuzzy match (SequenceMatcher ratio >= 0.85) against existing assets → skip
    3. Exact (normalized name, category) match against rejected proposals → skip
    4. Exact (normalized name, category) match against pending proposals → skip

    Only genuinely new candidates pass through.
    """

    FUZZY_THRESHOLD = 0.85  # Normalized similarity score for fuzzy matching

    def __init__(self, db_repo: DeduplicationRepository):
        self._db = db_repo

    async def deduplicate(
        self,
        candidates: list[CompetencyCandidate],
        consultant_id: str,
    ) -> list[CompetencyCandidate]:
        """Filter out candidates that are duplicates.

        Checks in order:
        1. Exact name match against existing profile assets
        2. Fuzzy name match against existing profile assets (≥85% similarity)
        3. Exact name+category match against rejected proposals
        4. Exact name+category match against pending proposals

        Args:
            candidates: Raw competency candidates from extraction.
            consultant_id: The Consultant whose profile to check against.

        Returns:
            Filtered list containing only genuinely new candidates.
        """
        existing_assets = await self._db.get_profile_assets(consultant_id)
        rejected_proposals = await self._db.get_rejected_proposals(consultant_id)
        pending_proposals = await self._db.get_pending_proposals(consultant_id)

        existing_names = {self._normalize(a.name) for a in existing_assets}
        rejected_keys = {
            (self._normalize(p.name), p.category) for p in rejected_proposals
        }
        pending_keys = {
            (self._normalize(p.name), p.category) for p in pending_proposals
        }

        new_candidates: list[CompetencyCandidate] = []
        for candidate in candidates:
            norm_name = self._normalize(candidate.name)

            # 1. Check exact match against existing profile
            if norm_name in existing_names:
                continue

            # 2. Check fuzzy match against existing profile
            if self._fuzzy_match_any(norm_name, existing_names):
                continue

            # 3. Check against rejected proposals
            if (norm_name, candidate.category) in rejected_keys:
                continue

            # 4. Check against pending proposals
            if (norm_name, candidate.category) in pending_keys:
                continue

            new_candidates.append(candidate)

        return new_candidates

    @staticmethod
    def _normalize(name: str) -> str:
        """Normalize a competency name for comparison.

        Lowercases, strips whitespace, and removes version suffixes
        such as "v3", "3.x", "14.0", " v2.1", etc.

        Args:
            name: The raw competency name.

        Returns:
            A normalized string suitable for exact or fuzzy comparison.
        """
        normalized = name.lower().strip()
        # Remove version suffixes like "v3", "3.x", "14.0", " v2.1.3"
        normalized = re.sub(r"\s*v?\d+(\.\d+)*\.?[x*]?\s*$", "", normalized)
        return normalized.strip()

    def _fuzzy_match_any(self, name: str, existing: set[str]) -> bool:
        """Check if name fuzzy-matches any item in the existing set.

        Uses difflib.SequenceMatcher with a threshold of 0.85.

        Args:
            name: The normalized candidate name to check.
            existing: Set of normalized existing profile asset names.

        Returns:
            True if any existing name has a similarity ratio >= FUZZY_THRESHOLD.
        """
        for existing_name in existing:
            ratio = SequenceMatcher(None, name, existing_name).ratio()
            if ratio >= self.FUZZY_THRESHOLD:
                return True
        return False
