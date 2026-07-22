"""Per-domain request throttler.

Ensures no more than 1 request per second per source domain.
Uses Redis GET/SET to track the last request timestamp per domain.
Falls back to a fixed 2-second delay if Redis is unavailable.

Requirements: 1.3
"""

import asyncio
import logging
import time
from urllib.parse import urlparse

import redis.asyncio as redis

logger = logging.getLogger(__name__)


class DomainThrottler:
    """Enforces per-domain rate limiting (1 req/s max).

    Uses Redis keys to store the last request timestamp for each domain.
    If Redis is unavailable, falls back to a conservative 2-second fixed
    delay to avoid hammering source domains.
    """

    RATE_LIMIT_INTERVAL = 1.0  # seconds between requests to same domain
    REDIS_KEY_PREFIX = "throttle:domain:"
    TTL_SECONDS = 120  # auto-expire stale entries
    FALLBACK_DELAY = 2.0  # seconds to wait if Redis is unavailable

    def __init__(self, redis_client: redis.Redis):
        self._redis = redis_client

    async def acquire(self, url: str) -> None:
        """Wait until a request to this URL's domain is permitted.

        Blocks (async sleep) until at least RATE_LIMIT_INTERVAL seconds
        have elapsed since the last request to the same domain.

        If Redis is unreachable, falls back to a fixed 2-second delay
        to provide conservative rate limiting without blocking indefinitely.

        Args:
            url: The target URL whose domain to throttle.
        """
        domain = self._extract_domain(url)
        key = f"{self.REDIS_KEY_PREFIX}{domain}"

        try:
            now = time.time()
            last_request = await self._redis.get(key)

            if last_request is None:
                # No previous request recorded — allow immediately
                await self._redis.set(key, str(now), ex=self.TTL_SECONDS)
                return

            elapsed = now - float(last_request)
            if elapsed >= self.RATE_LIMIT_INTERVAL:
                # Enough time has passed — allow and update timestamp
                await self._redis.set(key, str(now), ex=self.TTL_SECONDS)
                return

            # Wait for the remaining interval
            remaining = self.RATE_LIMIT_INTERVAL - elapsed
            await asyncio.sleep(remaining)

            # Update timestamp after waiting
            await self._redis.set(
                key, str(time.time()), ex=self.TTL_SECONDS
            )

        except (redis.ConnectionError, redis.TimeoutError, OSError) as exc:
            logger.warning(
                "Redis unavailable for domain throttling (domain=%s): %s. "
                "Falling back to %ss fixed delay.",
                domain,
                exc,
                self.FALLBACK_DELAY,
            )
            await asyncio.sleep(self.FALLBACK_DELAY)

    @staticmethod
    def _extract_domain(url: str) -> str:
        """Extract domain from URL for throttle grouping.

        Handles URLs with and without schemes. For bare domains like
        'example.com/path', urlparse puts the domain in the path component,
        so we fall back to splitting the path.

        Args:
            url: A URL string (may or may not include a scheme).

        Returns:
            The domain portion of the URL, lowercased. Returns "unknown"
            for empty or unparseable URLs.
        """
        if not url or not url.strip():
            return "unknown"

        url = url.strip()
        parsed = urlparse(url)
        domain = parsed.netloc

        if not domain:
            # URL likely missing scheme (e.g., "example.com/path")
            path_part = parsed.path.split("/")[0]
            domain = path_part if path_part else "unknown"

        return domain.lower()
