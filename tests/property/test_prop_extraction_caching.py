# Feature: capability-gap-analytics, Property 3: Extraction caching idempotence
"""Property-based tests for GapAnalyzer extraction caching idempotence.

Tests that calling `extract_capabilities()` twice with the same opportunity_id
returns identical results, with the second call served from cache (cached=True)
without invoking the LLM a second time.

**Validates: Requirements 1.2**
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.gap_analyzer import (
    ExtractionResult,
    GapAnalysisConfig,
    GapAnalyzer,
)


# ─── Strategies ───────────────────────────────────────────────────────────────

# Strategy for opportunity IDs — UUID-like strings
opportunity_id_st = st.uuids().map(str)

# Strategy for opportunity text — non-empty text simulating opportunity descriptions
opportunity_text_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Z", "S"),
        blacklist_characters="\x00",
    ),
    min_size=10,
    max_size=500,
).filter(lambda s: s.strip() != "")

# Strategy for capability names — simple lowercase strings representing skills
capability_name_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), blacklist_characters="\x00"),
    min_size=2,
    max_size=30,
).filter(lambda s: s.strip() != "")

# Strategy for lists of capabilities returned by the mock LLM
capabilities_list_st = st.lists(capability_name_st, min_size=1, max_size=8, unique=True)


# ─── Dict-based Redis Mock ────────────────────────────────────────────────────


class FakeRedis:
    """Simple dict-based async Redis mock that supports get/set with expiry."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value


# ─── Property 3: Extraction caching idempotence ──────────────────────────────


class TestProperty3ExtractionCachingIdempotence:
    """Property 3: Extraction caching idempotence.

    **Validates: Requirements 1.2**

    Key invariant: Extracting capabilities for the same opportunity_id twice
    yields:
    1. First call: cached=False, LLM called exactly once
    2. Second call: cached=True, LLM NOT called again
    3. Both results have identical required/preferred capability lists
    """

    @given(
        opportunity_id=opportunity_id_st,
        opportunity_text=opportunity_text_st,
        required_caps=capabilities_list_st,
        preferred_caps=capabilities_list_st,
    )
    @settings(max_examples=100)
    async def test_second_extraction_uses_cache_without_llm_call(
        self,
        opportunity_id: str,
        opportunity_text: str,
        required_caps: list[str],
        preferred_caps: list[str],
    ) -> None:
        """FOR ANY opportunity_id and text, extracting twice returns cached=True
        on the second call and does NOT invoke the LLM again.

        **Validates: Requirements 1.2**
        """
        # Setup mock LLM that returns the generated capabilities
        mock_llm = MagicMock()
        mock_llm.dispatch_extraction = AsyncMock(
            return_value={"required": required_caps, "preferred": preferred_caps}
        )

        # Setup fake Redis for caching
        fake_redis = FakeRedis()

        # Create GapAnalyzer with db_session=None (skip DB storage)
        config = GapAnalysisConfig()
        analyzer = GapAnalyzer(
            config=config,
            llm_router=mock_llm,
            schema_registry=None,
            db_session=None,
            redis_client=fake_redis,
            ws_manager=None,
        )

        # First extraction — should call LLM
        result1 = await analyzer.extract_capabilities(opportunity_id, opportunity_text)

        assert result1.cached is False, (
            f"First extraction should NOT be cached, got cached=True "
            f"for opportunity_id={opportunity_id!r}"
        )
        assert mock_llm.dispatch_extraction.call_count == 1, (
            f"LLM should be called exactly once on first extraction, "
            f"got {mock_llm.dispatch_extraction.call_count} calls"
        )

        # Second extraction — should use cache, no additional LLM call
        result2 = await analyzer.extract_capabilities(opportunity_id, opportunity_text)

        assert result2.cached is True, (
            f"Second extraction should be cached, got cached=False "
            f"for opportunity_id={opportunity_id!r}"
        )
        assert mock_llm.dispatch_extraction.call_count == 1, (
            f"LLM should NOT be called again on second extraction, "
            f"got {mock_llm.dispatch_extraction.call_count} calls (expected 1)"
        )

        # Results must be identical
        assert result1.required_capabilities == result2.required_capabilities, (
            f"Required capabilities differ between calls: "
            f"{result1.required_capabilities} != {result2.required_capabilities}"
        )
        assert result1.preferred_capabilities == result2.preferred_capabilities, (
            f"Preferred capabilities differ between calls: "
            f"{result1.preferred_capabilities} != {result2.preferred_capabilities}"
        )
        assert result1.opportunity_id == result2.opportunity_id

    @given(
        opportunity_id=opportunity_id_st,
        opportunity_text=opportunity_text_st,
        required_caps=capabilities_list_st,
        preferred_caps=capabilities_list_st,
    )
    @settings(max_examples=50)
    async def test_cache_stores_correct_data_retrievable_as_json(
        self,
        opportunity_id: str,
        opportunity_text: str,
        required_caps: list[str],
        preferred_caps: list[str],
    ) -> None:
        """FOR ANY extraction, the Redis cache entry contains valid JSON with
        correct required and preferred capability lists.

        **Validates: Requirements 1.2**
        """
        mock_llm = MagicMock()
        mock_llm.dispatch_extraction = AsyncMock(
            return_value={"required": required_caps, "preferred": preferred_caps}
        )

        fake_redis = FakeRedis()
        config = GapAnalysisConfig()
        analyzer = GapAnalyzer(
            config=config,
            llm_router=mock_llm,
            schema_registry=None,
            db_session=None,
            redis_client=fake_redis,
            ws_manager=None,
        )

        # Extract once to populate cache
        await analyzer.extract_capabilities(opportunity_id, opportunity_text)

        # Verify cache contents directly
        cache_key = f"{GapAnalyzer.REDIS_EXTRACTION_PREFIX}{opportunity_id}"
        cached_raw = await fake_redis.get(cache_key)

        assert cached_raw is not None, (
            f"Cache should contain entry for opportunity_id={opportunity_id!r}"
        )

        cached_data = json.loads(cached_raw)
        assert cached_data["required"] == required_caps, (
            f"Cached required capabilities don't match: "
            f"{cached_data['required']} != {required_caps}"
        )
        assert cached_data["preferred"] == preferred_caps, (
            f"Cached preferred capabilities don't match: "
            f"{cached_data['preferred']} != {preferred_caps}"
        )

    @given(
        opp_id_1=opportunity_id_st,
        opp_id_2=opportunity_id_st,
        opportunity_text=opportunity_text_st,
        required_caps_1=capabilities_list_st,
        preferred_caps_1=capabilities_list_st,
        required_caps_2=capabilities_list_st,
        preferred_caps_2=capabilities_list_st,
    )
    @settings(max_examples=50)
    async def test_different_opportunity_ids_are_cached_independently(
        self,
        opp_id_1: str,
        opp_id_2: str,
        opportunity_text: str,
        required_caps_1: list[str],
        preferred_caps_1: list[str],
        required_caps_2: list[str],
        preferred_caps_2: list[str],
    ) -> None:
        """FOR ANY two distinct opportunity_ids, caching one does not interfere
        with extracting the other — each has its own independent cache entry.

        **Validates: Requirements 1.2**
        """
        assume(opp_id_1 != opp_id_2)

        call_count = 0

        async def mock_dispatch(prompt: str) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"required": required_caps_1, "preferred": preferred_caps_1}
            return {"required": required_caps_2, "preferred": preferred_caps_2}

        mock_llm = MagicMock()
        mock_llm.dispatch_extraction = AsyncMock(side_effect=mock_dispatch)

        fake_redis = FakeRedis()
        config = GapAnalysisConfig()
        analyzer = GapAnalyzer(
            config=config,
            llm_router=mock_llm,
            schema_registry=None,
            db_session=None,
            redis_client=fake_redis,
            ws_manager=None,
        )

        # Extract for first opportunity
        result1 = await analyzer.extract_capabilities(opp_id_1, opportunity_text)
        assert result1.cached is False

        # Extract for second opportunity — should NOT use first's cache
        result2 = await analyzer.extract_capabilities(opp_id_2, opportunity_text)
        assert result2.cached is False, (
            f"Second distinct opportunity should NOT be cached; "
            f"opp_id_1={opp_id_1!r} opp_id_2={opp_id_2!r}"
        )

        # LLM should have been called twice (once per unique opportunity)
        assert call_count == 2, (
            f"LLM should be called twice for two distinct opportunities, "
            f"got {call_count} calls"
        )
