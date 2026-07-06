"""Shared utility helpers for the GKIM Opportunity Finder v2 system.

Provides normalization and hashing utilities used across multiple services:
- Company name normalization for deduplication matching (Requirement 10.2)
- Content hashing for LLM cache invalidation (Design: LLM Router cache key)
"""

import hashlib
import re
import unicodedata


# Common company suffixes to strip during normalization
_COMPANY_SUFFIXES = re.compile(
    r"\b("
    r"inc|incorporated|corp|corporation|llc|ltd|limited|plc|gmbh|"
    r"ag|sa|sarl|srl|bv|nv|pty|co|company|group|holdings|"
    r"international|intl|technologies|technology|tech|"
    r"solutions|services|systems|consulting|consultants"
    r")\b",
    re.IGNORECASE,
)

# Punctuation and special characters to remove
_STRIP_CHARS = re.compile(r"[^\w\s]", re.UNICODE)

# Multiple whitespace collapse
_MULTI_SPACE = re.compile(r"\s+")


def normalize_company_name(name: str) -> str:
    """Normalize a company name for deduplication matching.

    Applies the following transformations:
    1. Unicode normalization (NFKD) and lowercasing
    2. Remove common company suffixes (Inc, LLC, Ltd, etc.)
    3. Strip punctuation and special characters
    4. Collapse whitespace
    5. Strip leading/trailing whitespace

    This enables matching "Acme Inc." with "ACME" or "Acme, Inc" with "acme"
    for the Discovery Pipeline's deduplication logic (Requirement 10.2).

    Args:
        name: Raw company name string.

    Returns:
        Normalized company name suitable for comparison/deduplication.
    """
    if not name:
        return ""

    # Unicode normalize and lowercase
    normalized = unicodedata.normalize("NFKD", name).lower()

    # Remove common suffixes
    normalized = _COMPANY_SUFFIXES.sub("", normalized)

    # Strip punctuation
    normalized = _STRIP_CHARS.sub(" ", normalized)

    # Collapse whitespace
    normalized = _MULTI_SPACE.sub(" ", normalized).strip()

    return normalized


def compute_content_hash(*parts: str) -> str:
    """Compute a SHA-256 hash from one or more content strings.

    Used by the LLM Router for cache key generation. The cache is
    invalidated when the prospect description or beneficiary profile
    changes (Design: LLM Router _get_cache_key).

    Args:
        *parts: One or more strings to combine and hash.
                Empty strings and None values are treated as empty.

    Returns:
        Hex-encoded SHA-256 digest (64 characters).
    """
    hasher = hashlib.sha256()
    for part in parts:
        content = part if part else ""
        hasher.update(content.encode("utf-8"))
    return hasher.hexdigest()


def truncate_string(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate a string to a maximum length, appending a suffix if truncated.

    Used for LLM reasoning output (max 500 chars) and content previews.

    Args:
        text: The string to truncate.
        max_length: Maximum allowed length (including suffix).
        suffix: String to append when truncating.

    Returns:
        The original string if within max_length, otherwise truncated with suffix.
    """
    if not text or len(text) <= max_length:
        return text
    return text[: max_length - len(suffix)] + suffix
