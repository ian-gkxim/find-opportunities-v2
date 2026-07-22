"""Unit tests for DomainThrottler.

Tests per-domain rate limiting with Redis-backed timestamps, domain
extraction, and graceful fallback when Redis is unavailable.

Validates: Requirements 1.3
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.core.domain_throttler import DomainThrottler


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


class FakeRedis:
    """Lightweight in-memory Redis mock for throttler tests."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value


class FailingRedis:
    """Redis mock that always raises ConnectionError."""

    async def get(self, key: str):
        raise ConnectionError("Redis unavailable")

    async def set(self, key: str, value: str, ex: int | None = None):
        raise ConnectionError("Redis unavailable")


@pytest.fixture
def fake_redis():
    return FakeRedis()


@pytest.fixture
def failing_redis():
    return FailingRedis()


@pytest.fixture
def throttler(fake_redis):
    return DomainThrottler(redis_client=fake_redis)


@pytest.fixture
def throttler_no_redis(failing_redis):
    return DomainThrottler(redis_client=failing_redis)


# ─── TEST: Domain extraction ──────────────────────────────────────────────────


class TestExtractDomain:
    """Tests for _extract_domain static method."""

    def test_extracts_domain_from_full_url(self):
        assert DomainThrottler._extract_domain("https://github.com/user") == "github.com"

    def test_extracts_domain_with_port(self):
        assert DomainThrottler._extract_domain("https://example.com:8080/path") == "example.com:8080"

    def test_extracts_domain_without_scheme(self):
        assert DomainThrottler._extract_domain("example.com/path") == "example.com"

    def test_extracts_domain_http(self):
        assert DomainThrottler._extract_domain("http://scholar.google.com/citations") == "scholar.google.com"

    def test_returns_unknown_for_empty_string(self):
        assert DomainThrottler._extract_domain("") == "unknown"

    def test_returns_unknown_for_whitespace(self):
        assert DomainThrottler._extract_domain("   ") == "unknown"

    def test_lowercases_domain(self):
        assert DomainThrottler._extract_domain("https://GitHub.COM/user") == "github.com"

    def test_handles_subdomain(self):
        assert DomainThrottler._extract_domain("https://api.github.com/repos") == "api.github.com"


# ─── TEST: Acquire — first request passes immediately ─────────────────────────


class TestAcquireFirstRequest:
    """First request to a domain should return immediately."""

    @pytest.mark.asyncio
    async def test_first_request_returns_immediately(self, throttler, fake_redis):
        start = time.time()
        await throttler.acquire("https://github.com/user/repo")
        elapsed = time.time() - start

        # Should be nearly instant (< 100ms)
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_first_request_stores_timestamp(self, throttler, fake_redis):
        await throttler.acquire("https://github.com/user/repo")

        key = "throttle:domain:github.com"
        stored = await fake_redis.get(key)
        assert stored is not None
        assert float(stored) > 0


# ─── TEST: Acquire — subsequent requests throttled ────────────────────────────


class TestAcquireThrottling:
    """Subsequent requests to the same domain wait for the rate limit interval."""

    @pytest.mark.asyncio
    async def test_second_request_waits(self, throttler, fake_redis):
        await throttler.acquire("https://github.com/user/repo")

        start = time.time()
        await throttler.acquire("https://github.com/user/other-repo")
        elapsed = time.time() - start

        # Should wait approximately RATE_LIMIT_INTERVAL (1s)
        assert elapsed >= 0.9

    @pytest.mark.asyncio
    async def test_different_domains_not_throttled(self, throttler):
        """Requests to different domains should not be throttled by each other."""
        await throttler.acquire("https://github.com/user")

        start = time.time()
        await throttler.acquire("https://scholar.google.com/profile")
        elapsed = time.time() - start

        # Different domain — should return immediately
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_allows_after_interval_elapsed(self, throttler, fake_redis):
        """If enough time has passed, request returns immediately."""
        # Simulate a request that happened 2 seconds ago
        key = "throttle:domain:github.com"
        await fake_redis.set(key, str(time.time() - 2.0))

        start = time.time()
        await throttler.acquire("https://github.com/user/repo")
        elapsed = time.time() - start

        assert elapsed < 0.1


# ─── TEST: Redis unavailability fallback ──────────────────────────────────────


class TestRedisFallback:
    """When Redis is unavailable, throttler falls back to a fixed delay."""

    @pytest.mark.asyncio
    async def test_fallback_delay_on_connection_error(self, throttler_no_redis):
        start = time.time()
        await throttler_no_redis.acquire("https://github.com/user")
        elapsed = time.time() - start

        # Should wait approximately FALLBACK_DELAY (2s)
        assert elapsed >= 1.9
        assert elapsed < 2.5

    @pytest.mark.asyncio
    async def test_fallback_does_not_raise(self, throttler_no_redis):
        """Redis failure should not propagate as an exception."""
        # Should not raise
        await throttler_no_redis.acquire("https://example.com/page")
