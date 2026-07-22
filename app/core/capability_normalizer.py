"""Capability Normalizer — handles synonym resolution and canonical name mapping.

Normalizes raw capability names extracted from opportunities to canonical
forms using a pre-loaded synonym map. Unknown capabilities are stored as-is
(self-canonical) and flagged for manual review/grouping.

Requirements: 1.2
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class SynonymMapping:
    """A synonym-to-canonical mapping entry."""

    alias: str  # The synonym or variant spelling
    canonical_name: str  # The canonical capability name


class CapabilityNormalizer:
    """Normalizes raw capability names to canonical forms using synonym mappings.

    Synonym mappings are loaded from the database at startup and cached.
    New unknown capabilities are stored as-is (self-canonical) and flagged
    for manual review/grouping.

    This is a pure computation class for the normalization logic itself.
    """

    def __init__(self, synonym_map: dict[str, str]) -> None:
        """Initialize with a pre-loaded synonym map.

        Args:
            synonym_map: Dict of lowercase alias -> canonical_name.
        """
        self._synonyms = synonym_map

    def normalize(self, raw_name: str) -> str:
        """Normalize a raw capability name to its canonical form.

        Steps:
        1. Strip whitespace, lowercase
        2. Lookup in synonym map
        3. If not found, return the cleaned name (self-canonical)

        Args:
            raw_name: Raw capability name from LLM extraction.

        Returns:
            Canonical capability name.
        """
        cleaned = raw_name.strip().lower()
        return self._synonyms.get(cleaned, cleaned)

    def batch_normalize(self, raw_names: list[str]) -> list[str]:
        """Normalize a batch of capability names.

        Args:
            raw_names: List of raw capability names.

        Returns:
            List of canonical names (same order).
        """
        return [self.normalize(name) for name in raw_names]

    def add_synonym(self, alias: str, canonical_name: str) -> None:
        """Register a new synonym mapping (in-memory; caller persists).

        Args:
            alias: The new alias to register.
            canonical_name: The canonical name it maps to.
        """
        self._synonyms[alias.strip().lower()] = canonical_name.strip().lower()

    def is_known(self, raw_name: str) -> bool:
        """Check if a capability name has a known canonical mapping.

        Args:
            raw_name: Raw capability name.

        Returns:
            True if the name (or a synonym) is in the mapping.
        """
        cleaned = raw_name.strip().lower()
        return cleaned in self._synonyms


async def load_normalizer_from_db(db_session: "AsyncSession") -> CapabilityNormalizer:
    """Factory: load synonym mappings from DB and return a CapabilityNormalizer.

    Queries the `capability_synonyms` table joined with `canonical_capabilities`
    to build the full alias -> canonical_name mapping. Also includes canonical
    names mapped to themselves so that `is_known()` returns True for canonicals.

    Args:
        db_session: An active async SQLAlchemy session.

    Returns:
        A CapabilityNormalizer initialized with the full synonym map.
    """
    from sqlalchemy import select

    from app.models.gap_analytics import CanonicalCapability, CapabilitySynonym

    synonym_map: dict[str, str] = {}

    # Load all synonym -> canonical mappings
    stmt = select(CapabilitySynonym.alias, CanonicalCapability.canonical_name).join(
        CanonicalCapability, CapabilitySynonym.canonical_id == CanonicalCapability.id
    )
    result = await db_session.execute(stmt)
    for alias, canonical_name in result:
        synonym_map[alias.lower()] = canonical_name.lower()

    # Also map canonical names to themselves so is_known() works for canonical entries
    stmt_canonical = select(CanonicalCapability.canonical_name)
    result_canonical = await db_session.execute(stmt_canonical)
    for (canonical_name,) in result_canonical:
        synonym_map[canonical_name.lower()] = canonical_name.lower()

    return CapabilityNormalizer(synonym_map)
