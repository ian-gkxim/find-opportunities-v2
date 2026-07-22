# Feature: internal-profile-enrichment, Property 3: Domain extraction determinism
"""Property-based tests for DomainThrottler._extract_domain determinism.

Tests that:
1. For any valid URL, _extract_domain() always returns the same result
   when called multiple times (determinism/idempotence).
2. Same-host URLs with different paths produce the same domain key.
3. Different-host URLs produce different domain keys.

**Validates: Requirements 1.3**
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.domain_throttler import DomainThrottler


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for valid domain name segments (lowercase alpha + digits)
_DOMAIN_LABEL_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"

domain_label_st = st.text(
    alphabet=_DOMAIN_LABEL_CHARS,
    min_size=1,
    max_size=15,
)

# Strategy for top-level domains
tld_st = st.sampled_from(["com", "org", "net", "io", "co", "dev", "ai", "uk", "de"])

# Strategy for valid domain names (e.g., "example.com", "sub.domain.org")
@st.composite
def domain_st(draw) -> str:
    """Generate a valid domain name like 'example.com' or 'sub.example.org'."""
    num_labels = draw(st.integers(min_value=1, max_value=3))
    labels = [draw(domain_label_st) for _ in range(num_labels)]
    tld = draw(tld_st)
    return ".".join(labels) + "." + tld


# Strategy for URL paths
path_segment_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_",
    min_size=1,
    max_size=20,
)


@st.composite
def url_path_st(draw) -> str:
    """Generate a random URL path like '/foo/bar/baz'."""
    num_segments = draw(st.integers(min_value=0, max_value=4))
    segments = [draw(path_segment_st) for _ in range(num_segments)]
    return "/" + "/".join(segments) if segments else ""


# Strategy for URL schemes
scheme_st = st.sampled_from(["http", "https"])


@st.composite
def valid_url_st(draw) -> str:
    """Generate a valid URL with scheme, domain, and optional path."""
    scheme = draw(scheme_st)
    domain = draw(domain_st())
    path = draw(url_path_st())
    return f"{scheme}://{domain}{path}"


@st.composite
def same_host_different_paths_st(draw) -> tuple[str, str, str]:
    """Generate two URLs with the same host but different paths.

    Returns:
        Tuple of (url1, url2, shared_domain)
    """
    scheme = draw(scheme_st)
    domain = draw(domain_st())
    path1 = draw(url_path_st())
    path2 = draw(url_path_st())
    # Ensure paths are actually different
    assume(path1 != path2)
    url1 = f"{scheme}://{domain}{path1}"
    url2 = f"{scheme}://{domain}{path2}"
    return url1, url2, domain


@st.composite
def different_hosts_st(draw) -> tuple[str, str]:
    """Generate two URLs with guaranteed different hosts.

    Returns:
        Tuple of (url1, url2) with different domains.
    """
    scheme1 = draw(scheme_st)
    scheme2 = draw(scheme_st)
    domain1 = draw(domain_st())
    domain2 = draw(domain_st())
    # Ensure domains are actually different
    assume(domain1.lower() != domain2.lower())
    path1 = draw(url_path_st())
    path2 = draw(url_path_st())
    url1 = f"{scheme1}://{domain1}{path1}"
    url2 = f"{scheme2}://{domain2}{path2}"
    return url1, url2


# ─── Property 3: Domain extraction determinism ────────────────────────────────


class TestProperty3DomainExtractionDeterminism:
    """Property 3: Domain extraction determinism.

    **Validates: Requirements 1.3**

    Key invariants:
    - For any valid URL, _extract_domain() always returns the same result
      (determinism).
    - Same-host URLs with different paths produce the same domain key.
    - Different-host URLs produce different domain keys.
    """

    @given(url=valid_url_st())
    @settings(max_examples=200)
    def test_extract_domain_is_deterministic(self, url: str) -> None:
        """FOR ANY valid URL, calling _extract_domain() multiple times
        always returns the exact same result.

        **Validates: Requirements 1.3**
        """
        result1 = DomainThrottler._extract_domain(url)
        result2 = DomainThrottler._extract_domain(url)
        result3 = DomainThrottler._extract_domain(url)

        assert result1 == result2 == result3, (
            f"_extract_domain is not deterministic.\n"
            f"URL: {url!r}\n"
            f"Results: {result1!r}, {result2!r}, {result3!r}"
        )

    @given(data=same_host_different_paths_st())
    @settings(max_examples=200)
    def test_same_host_produces_same_domain_key(
        self,
        data: tuple[str, str, str],
    ) -> None:
        """FOR ANY two URLs sharing the same host but with different paths,
        _extract_domain() produces the same domain key.

        **Validates: Requirements 1.3**
        """
        url1, url2, _shared_domain = data

        domain1 = DomainThrottler._extract_domain(url1)
        domain2 = DomainThrottler._extract_domain(url2)

        assert domain1 == domain2, (
            f"Same-host URLs produced different domain keys.\n"
            f"URL1: {url1!r} -> {domain1!r}\n"
            f"URL2: {url2!r} -> {domain2!r}"
        )

    @given(data=different_hosts_st())
    @settings(max_examples=200)
    def test_different_hosts_produce_different_domain_keys(
        self,
        data: tuple[str, str],
    ) -> None:
        """FOR ANY two URLs with different hosts,
        _extract_domain() produces different domain keys.

        **Validates: Requirements 1.3**
        """
        url1, url2 = data

        domain1 = DomainThrottler._extract_domain(url1)
        domain2 = DomainThrottler._extract_domain(url2)

        assert domain1 != domain2, (
            f"Different-host URLs produced the same domain key.\n"
            f"URL1: {url1!r} -> {domain1!r}\n"
            f"URL2: {url2!r} -> {domain2!r}"
        )

    @given(url=valid_url_st())
    @settings(max_examples=200)
    def test_extract_domain_returns_lowercase_string(self, url: str) -> None:
        """FOR ANY valid URL, _extract_domain() returns a lowercase string
        (consistent casing for key grouping).

        **Validates: Requirements 1.3**
        """
        result = DomainThrottler._extract_domain(url)

        assert result == result.lower(), (
            f"_extract_domain did not return a lowercase string.\n"
            f"URL: {url!r}\n"
            f"Result: {result!r}"
        )

    @given(url=valid_url_st())
    @settings(max_examples=200)
    def test_extract_domain_never_returns_empty(self, url: str) -> None:
        """FOR ANY valid URL, _extract_domain() never returns an empty string.

        **Validates: Requirements 1.3**
        """
        result = DomainThrottler._extract_domain(url)

        assert result != "", (
            f"_extract_domain returned empty string.\n"
            f"URL: {url!r}"
        )
        assert result != "unknown", (
            f"_extract_domain returned 'unknown' for a valid URL.\n"
            f"URL: {url!r}"
        )
