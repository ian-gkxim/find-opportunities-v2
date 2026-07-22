# Feature: capability-gap-analytics, Property 2: Synonym normalization convergence
"""Property-based tests for CapabilityNormalizer synonym convergence.

Tests that:
1. All aliases mapping to the same canonical name produce the exact same
   normalized output (convergence).
2. Normalization is idempotent: normalize(normalize(x)) == normalize(x).

**Validates: Requirements 1.2**
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.capability_normalizer import CapabilityNormalizer


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for valid capability name characters (ASCII letters, digits, spaces, hyphens, dots)
# We restrict to ASCII to avoid Unicode casing issues (e.g. ß → SS)
_CAPABILITY_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789 -._"

capability_name_st = st.text(
    alphabet=_CAPABILITY_ALPHABET,
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip() != "")

# Strategy for canonical capability names (non-empty, stripped, lowercase ASCII)
canonical_name_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-._",
    min_size=1,
    max_size=20,
).filter(lambda s: s.strip() != "")


@st.composite
def synonym_map_st(draw) -> dict[str, str]:
    """Generate a random synonym map where multiple aliases map to the same canonical.

    Generates 1-5 canonical names, each with 1-5 aliases. The alias keys are
    stored lowercase (as the normalizer expects).

    IMPORTANT: Ensures canonical values are self-mapped (canonical → canonical)
    so that normalization is idempotent. Canonical names never point to a
    different canonical.
    """
    num_canonicals = draw(st.integers(min_value=1, max_value=5))
    synonym_map: dict[str, str] = {}
    canonicals: set[str] = set()

    for _ in range(num_canonicals):
        canonical = draw(canonical_name_st)
        assume(canonical != "")
        canonicals.add(canonical)

    # For idempotence, map each canonical to itself
    for canonical in canonicals:
        synonym_map[canonical] = canonical

    # Now add aliases that are distinct from any canonical
    for canonical in canonicals:
        num_aliases = draw(st.integers(min_value=1, max_value=5))
        for _ in range(num_aliases):
            alias = draw(capability_name_st)
            alias_key = alias.strip().lower()
            # Aliases must not collide with canonicals or existing aliases
            if alias_key not in synonym_map and alias_key not in canonicals:
                synonym_map[alias_key] = canonical

    assume(len(synonym_map) >= 1)
    return synonym_map


@st.composite
def synonym_map_with_aliases_st(draw) -> tuple[dict[str, str], str, list[str]]:
    """Generate a synonym map and pick one canonical with all its aliases.

    Returns:
        Tuple of (synonym_map, chosen_canonical, list_of_aliases_for_that_canonical)

    Ensures canonical names map to themselves for idempotence.
    """
    num_canonicals = draw(st.integers(min_value=1, max_value=4))
    synonym_map: dict[str, str] = {}
    canonicals: set[str] = set()
    canonical_to_aliases: dict[str, list[str]] = {}

    for _ in range(num_canonicals):
        canonical = draw(canonical_name_st)
        assume(canonical != "")
        canonicals.add(canonical)

    # Self-map all canonicals
    for canonical in canonicals:
        synonym_map[canonical] = canonical

    # Add aliases for each canonical
    for canonical in canonicals:
        num_aliases = draw(st.integers(min_value=2, max_value=5))
        aliases_for_canonical: list[str] = []

        for _ in range(num_aliases):
            alias = draw(capability_name_st)
            alias_key = alias.strip().lower()
            if alias_key not in synonym_map and alias_key not in canonicals:
                synonym_map[alias_key] = canonical
                aliases_for_canonical.append(alias)

        if aliases_for_canonical:
            canonical_to_aliases[canonical] = aliases_for_canonical

    assume(len(canonical_to_aliases) >= 1)

    # Pick one canonical that has at least 2 aliases
    canonicals_with_multiple = {
        c: aliases for c, aliases in canonical_to_aliases.items() if len(aliases) >= 2
    }
    assume(len(canonicals_with_multiple) >= 1)

    chosen_canonical = draw(st.sampled_from(sorted(canonicals_with_multiple.keys())))
    chosen_aliases = canonicals_with_multiple[chosen_canonical]

    return synonym_map, chosen_canonical, chosen_aliases


# ─── Property 2: Synonym normalization convergence ────────────────────────────


class TestProperty2SynonymNormalizationConvergence:
    """Property 2: Synonym normalization convergence.

    **Validates: Requirements 1.2**

    Key invariants:
    - All aliases that map to the same canonical produce the exact same
      normalized output.
    - Normalization is idempotent: normalize(normalize(x)) == normalize(x).
    """

    @given(data=synonym_map_with_aliases_st())
    @settings(max_examples=200)
    def test_all_aliases_converge_to_same_canonical(
        self,
        data: tuple[dict[str, str], str, list[str]],
    ) -> None:
        """FOR ANY synonym map where multiple aliases map to the same canonical,
        normalizing any alias produces the exact same output string.

        **Validates: Requirements 1.2**
        """
        synonym_map, expected_canonical, aliases = data
        normalizer = CapabilityNormalizer(synonym_map)

        results = [normalizer.normalize(alias) for alias in aliases]

        # All aliases must produce the same canonical
        assert all(r == expected_canonical for r in results), (
            f"Not all aliases converge to the same canonical.\n"
            f"Expected: {expected_canonical!r}\n"
            f"Aliases: {aliases!r}\n"
            f"Results: {results!r}"
        )

    @given(
        synonym_map=synonym_map_st(),
        raw_name=capability_name_st,
    )
    @settings(max_examples=200)
    def test_normalization_is_idempotent(
        self,
        synonym_map: dict[str, str],
        raw_name: str,
    ) -> None:
        """FOR ANY raw capability name and synonym map,
        normalize(normalize(x)) == normalize(x).

        **Validates: Requirements 1.2**
        """
        normalizer = CapabilityNormalizer(synonym_map)

        first_pass = normalizer.normalize(raw_name)
        second_pass = normalizer.normalize(first_pass)

        assert first_pass == second_pass, (
            f"Normalization is not idempotent.\n"
            f"Input: {raw_name!r}\n"
            f"First pass: {first_pass!r}\n"
            f"Second pass: {second_pass!r}\n"
            f"Synonym map sample: {dict(list(synonym_map.items())[:5])}"
        )

    @given(data=synonym_map_with_aliases_st())
    @settings(max_examples=200)
    def test_aliases_with_whitespace_variations_converge(
        self,
        data: tuple[dict[str, str], str, list[str]],
    ) -> None:
        """FOR ANY alias, adding leading/trailing whitespace still converges
        to the same canonical as the base alias.

        **Validates: Requirements 1.2**
        """
        synonym_map, expected_canonical, aliases = data
        normalizer = CapabilityNormalizer(synonym_map)

        for alias in aliases:
            # Add various whitespace variations
            padded_alias = f"  {alias}  "
            result = normalizer.normalize(padded_alias)
            assert result == expected_canonical, (
                f"Whitespace-padded alias did not converge.\n"
                f"Original alias: {alias!r}\n"
                f"Padded alias: {padded_alias!r}\n"
                f"Expected: {expected_canonical!r}\n"
                f"Got: {result!r}"
            )

    @given(data=synonym_map_with_aliases_st())
    @settings(max_examples=200)
    def test_aliases_with_case_variations_converge(
        self,
        data: tuple[dict[str, str], str, list[str]],
    ) -> None:
        """FOR ANY alias, changing case (upper, mixed) still converges
        to the same canonical.

        **Validates: Requirements 1.2**
        """
        synonym_map, expected_canonical, aliases = data
        normalizer = CapabilityNormalizer(synonym_map)

        for alias in aliases:
            # Test uppercase variant
            upper_alias = alias.upper()
            result = normalizer.normalize(upper_alias)
            assert result == expected_canonical, (
                f"Uppercased alias did not converge.\n"
                f"Original alias: {alias!r}\n"
                f"Upper alias: {upper_alias!r}\n"
                f"Expected: {expected_canonical!r}\n"
                f"Got: {result!r}"
            )
