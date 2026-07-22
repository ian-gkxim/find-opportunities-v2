"""Async Redis connection pool and pub/sub channel configuration.

Requirements 8.4, 16.2: Real-time pipeline updates via WebSocket, reflecting
status changes within 10 seconds. Redis pub/sub enables broadcasting across
multiple worker processes and WebSocket server instances.
"""

from typing import AsyncGenerator

import redis.asyncio as redis

from app.core.config import get_settings

# Pub/sub channel names for WebSocket broadcasting
CHANNEL_PIPELINE_UPDATES = "pipeline_updates"
CHANNEL_NOTIFICATIONS = "notifications"
CHANNEL_SCORE_CHANGES = "score_changes"
CHANNEL_GAP_UPDATES = "gap_updates"

ALL_CHANNELS = [
    CHANNEL_PIPELINE_UPDATES,
    CHANNEL_NOTIFICATIONS,
    CHANNEL_SCORE_CHANGES,
    CHANNEL_GAP_UPDATES,
]

# Module-level connection pool (initialized on first use)
_pool: redis.ConnectionPool | None = None


def get_redis_pool() -> redis.ConnectionPool:
    """Get or create the shared Redis connection pool.

    Returns a connection pool configured for async usage. The pool is created
    once and reused across the application lifetime.
    """
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = redis.ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
        )
    return _pool


def get_redis_client() -> redis.Redis:
    """Create an async Redis client from the shared connection pool.

    Use this for general caching and pub/sub publishing operations.
    """
    pool = get_redis_pool()
    return redis.Redis(connection_pool=pool)


async def get_redis_dependency() -> AsyncGenerator[redis.Redis, None]:
    """FastAPI dependency that yields a Redis client and handles cleanup."""
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


async def publish_event(channel: str, message: str) -> int:
    """Publish a message to a Redis pub/sub channel.

    Args:
        channel: One of the defined channel constants (e.g. CHANNEL_PIPELINE_UPDATES).
        message: JSON-serialized message string.

    Returns:
        Number of subscribers that received the message.
    """
    client = get_redis_client()
    try:
        return await client.publish(channel, message)
    finally:
        await client.aclose()


async def subscribe_channels(
    channels: list[str] | None = None,
) -> redis.client.PubSub:
    """Create a pub/sub subscription to the specified channels.

    Args:
        channels: List of channel names. Defaults to ALL_CHANNELS if not specified.

    Returns:
        An async PubSub instance ready to receive messages.
    """
    if channels is None:
        channels = ALL_CHANNELS
    client = get_redis_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(*channels)
    return pubsub


async def close_redis_pool() -> None:
    """Close the Redis connection pool during application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
