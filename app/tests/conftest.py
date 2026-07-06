"""Root conftest with async database fixtures, test client, and Redis mock.

Provides shared fixtures for the entire test suite including:
- Async SQLAlchemy test database session (SQLite async for isolation)
- FastAPI TestClient via httpx.AsyncClient
- Redis mock fixture
- Settings override for test configuration
- Hypothesis profile configuration
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import hypothesis
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.main import create_app

# ---------------------------------------------------------------------------
# Hypothesis profile configuration
# ---------------------------------------------------------------------------
hypothesis.settings.register_profile(
    "default",
    max_examples=100,
    deadline=None,
)
hypothesis.settings.register_profile(
    "ci",
    max_examples=200,
    deadline=None,
)
hypothesis.settings.register_profile(
    "dev",
    max_examples=10,
    deadline=None,
)
hypothesis.settings.load_profile("default")


# ---------------------------------------------------------------------------
# Test settings
# ---------------------------------------------------------------------------
@pytest.fixture
def test_settings() -> Settings:
    """Provide test-specific settings that don't require real services."""
    return Settings(
        app_name="GKIM Opportunity Finder v2 - Test",
        app_env="testing",
        debug=True,
        secret_key="test-secret-key",
        database_url="sqlite+aiosqlite:///",  # in-memory
        redis_url="redis://localhost:6379/15",  # test DB index
        apollo_api_key="test-apollo-key",
        lemlist_api_key="test-lemlist-key",
        adzuna_app_id="test-adzuna-id",
        adzuna_app_key="test-adzuna-key",
        google_client_id="test-google-id",
        google_client_secret="test-google-secret",
        google_refresh_token="test-google-token",
        anthropic_api_key="test-anthropic-key",
        openai_api_key="test-openai-key",
    )


# ---------------------------------------------------------------------------
# Async database fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
async def async_engine():
    """Create an async SQLAlchemy engine for testing (in-memory SQLite)."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///",
        echo=False,
    )
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session for testing.

    Each test gets a fresh session that is rolled back after the test completes.
    """
    session_factory = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Redis mock fixture
# ---------------------------------------------------------------------------
class FakeRedis:
    """Lightweight Redis mock for testing without a real Redis server."""

    def __init__(self):
        self._store: dict[str, bytes | str] = {}
        self._expiry: dict[str, int] = {}
        self._pubsub_channels: dict[str, list] = {}

    async def get(self, key: str) -> bytes | None:
        return self._store.get(key)

    async def set(self, key: str, value: str | bytes, ex: int | None = None) -> None:
        self._store[key] = value
        if ex is not None:
            self._expiry[key] = ex

    async def delete(self, *keys: str) -> int:
        count = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                self._expiry.pop(key, None)
                count += 1
        return count

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def keys(self, pattern: str = "*") -> list[str]:
        if pattern == "*":
            return list(self._store.keys())
        # Simple glob matching for tests
        import fnmatch

        return [k for k in self._store if fnmatch.fnmatch(k, pattern)]

    async def publish(self, channel: str, message: str) -> int:
        subscribers = self._pubsub_channels.get(channel, [])
        for callback in subscribers:
            await callback(message)
        return len(subscribers)

    async def subscribe(self, channel: str, callback) -> None:
        self._pubsub_channels.setdefault(channel, []).append(callback)

    async def close(self) -> None:
        self._store.clear()
        self._expiry.clear()
        self._pubsub_channels.clear()

    def pipeline(self):
        """Return a mock pipeline for batch operations."""
        return FakeRedisPipeline(self)


class FakeRedisPipeline:
    """Mock Redis pipeline for batch operations."""

    def __init__(self, redis: FakeRedis):
        self._redis = redis
        self._commands: list[tuple] = []

    async def execute(self) -> list:
        results = []
        for cmd, args, kwargs in self._commands:
            method = getattr(self._redis, cmd)
            result = await method(*args, **kwargs)
            results.append(result)
        self._commands.clear()
        return results

    def set(self, key: str, value: str | bytes, ex: int | None = None):
        self._commands.append(("set", (key, value), {"ex": ex}))
        return self

    def get(self, key: str):
        self._commands.append(("get", (key,), {}))
        return self

    def delete(self, *keys: str):
        self._commands.append(("delete", keys, {}))
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


@pytest.fixture
def redis_mock() -> FakeRedis:
    """Provide an in-memory Redis mock for testing."""
    return FakeRedis()


# ---------------------------------------------------------------------------
# FastAPI test client
# ---------------------------------------------------------------------------
@pytest.fixture
async def app(test_settings):
    """Create a FastAPI application instance configured for testing."""
    application = create_app(settings=test_settings)
    return application


@pytest.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP client for testing API endpoints.

    Uses httpx.AsyncClient with ASGITransport for async test support.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
