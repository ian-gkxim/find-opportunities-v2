"""Smoke tests to verify test infrastructure is working correctly."""

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


class TestInfrastructureSmoke:
    """Verify core test infrastructure works."""

    async def test_async_test_runs(self):
        """Verify async tests can be collected and executed."""
        result = await _async_add(1, 2)
        assert result == 3

    async def test_settings_fixture(self, test_settings):
        """Verify test settings fixture provides test configuration."""
        assert test_settings.app_env == "testing"
        assert test_settings.debug is True
        assert "Test" in test_settings.app_name

    async def test_redis_mock_fixture(self, redis_mock):
        """Verify Redis mock fixture works for basic operations."""
        await redis_mock.set("test_key", "test_value")
        result = await redis_mock.get("test_key")
        assert result == "test_value"

        await redis_mock.delete("test_key")
        result = await redis_mock.get("test_key")
        assert result is None

    async def test_client_fixture(self, client):
        """Verify FastAPI test client can hit the health endpoint."""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @given(a=st.integers(min_value=0, max_value=1000), b=st.integers(min_value=0, max_value=1000))
    @settings(max_examples=10)
    def test_hypothesis_works(self, a: int, b: int):
        """Verify Hypothesis property-based testing is functional."""
        assert a + b == b + a  # commutativity of addition


async def _async_add(a: int, b: int) -> int:
    """Simple async helper for testing."""
    return a + b
