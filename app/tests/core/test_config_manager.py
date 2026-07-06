"""Unit tests for ConfigManager.

Tests credential validation, health tracking, quota management,
credential preservation on failure, and usage refresh intervals.
"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config_manager import (
    ConfigManager,
    IntegrationHealth,
    IntegrationName,
    IntegrationStatus,
)
from app.core.errors import QuotaExhaustedError


# --- Test Doubles ---


@dataclass
class FakeHTTPResponse:
    """Fake HTTP response for testing."""

    status_code: int
    _json: dict | None = None
    _text: str = ""

    def json(self) -> dict:
        return self._json or {}

    @property
    def text(self) -> str:
        return self._text


class FakeHTTPClient:
    """Fake HTTP client that records calls and returns configured responses."""

    def __init__(self, response: FakeHTTPResponse | None = None):
        self.calls: list[dict] = []
        self._response = response or FakeHTTPResponse(status_code=200)
        self._should_timeout = False
        self._should_raise: Exception | None = None

    def set_response(self, response: FakeHTTPResponse) -> None:
        self._response = response

    def set_timeout(self) -> None:
        self._should_timeout = True

    def set_error(self, error: Exception) -> None:
        self._should_raise = error

    async def get(
        self, url: str, *, headers: dict | None = None, timeout: float | None = None
    ) -> FakeHTTPResponse:
        self.calls.append({"method": "GET", "url": url, "headers": headers, "timeout": timeout})
        if self._should_timeout:
            raise asyncio.TimeoutError()
        if self._should_raise:
            raise self._should_raise
        return self._response

    async def post(
        self, url: str, *, headers: dict | None = None,
        json: dict | None = None, timeout: float | None = None
    ) -> FakeHTTPResponse:
        self.calls.append({
            "method": "POST", "url": url, "headers": headers,
            "json": json, "timeout": timeout,
        })
        if self._should_timeout:
            raise asyncio.TimeoutError()
        if self._should_raise:
            raise self._should_raise
        return self._response


class FakeUsageSource:
    """Fake usage data source for testing."""

    def __init__(self, usage: int = 50, limit: int = 100):
        self._usage = usage
        self._limit = limit
        self.calls: list[str] = []

    async def get_usage(
        self, integration: str, credentials: dict, http_client
    ) -> tuple[int, int]:
        self.calls.append(integration)
        return self._usage, self._limit


# --- Fixtures ---


@pytest.fixture
def http_client() -> FakeHTTPClient:
    return FakeHTTPClient()


@pytest.fixture
def usage_source() -> FakeUsageSource:
    return FakeUsageSource()


@pytest.fixture
def config_manager(http_client: FakeHTTPClient) -> ConfigManager:
    return ConfigManager(http_client=http_client)


@pytest.fixture
def config_manager_with_usage(
    http_client: FakeHTTPClient, usage_source: FakeUsageSource
) -> ConfigManager:
    return ConfigManager(http_client=http_client, usage_source=usage_source)


# --- Credential Validation Tests ---


class TestValidateCredentials:
    """Tests for credential validation (Requirement 18.2)."""

    async def test_successful_apollo_validation(self, config_manager, http_client):
        """Successful validation sets status to CONNECTED and stores credentials."""
        http_client.set_response(FakeHTTPResponse(status_code=200))

        status, error = await config_manager.validate_credentials(
            "apollo", {"api_key": "test-key-123"}
        )

        assert status == IntegrationStatus.CONNECTED
        assert error is None
        assert config_manager.get_credentials("apollo") == {"api_key": "test-key-123"}

    async def test_successful_lemlist_validation(self, config_manager, http_client):
        """Lemlist validation uses Bearer auth."""
        http_client.set_response(FakeHTTPResponse(status_code=200))

        status, error = await config_manager.validate_credentials(
            "lemlist", {"api_key": "lemlist-key"}
        )

        assert status == IntegrationStatus.CONNECTED
        assert error is None
        # Verify the call used correct auth header
        assert len(http_client.calls) == 1
        assert "Bearer lemlist-key" in http_client.calls[0]["headers"].get("Authorization", "")

    async def test_successful_adzuna_validation(self, config_manager, http_client):
        """Adzuna validation uses query params for auth."""
        http_client.set_response(FakeHTTPResponse(status_code=200))

        status, error = await config_manager.validate_credentials(
            "adzuna", {"app_id": "my-id", "app_key": "my-key"}
        )

        assert status == IntegrationStatus.CONNECTED
        assert error is None
        # Verify URL has query params
        assert "app_id=my-id" in http_client.calls[0]["url"]
        assert "app_key=my-key" in http_client.calls[0]["url"]

    async def test_successful_gmail_validation(self, config_manager, http_client):
        """Gmail validation uses Bearer token."""
        http_client.set_response(FakeHTTPResponse(status_code=200))

        status, error = await config_manager.validate_credentials(
            "gmail", {"access_token": "gmail-token"}
        )

        assert status == IntegrationStatus.CONNECTED
        assert error is None

    async def test_successful_llm_validation(self, config_manager, http_client):
        """LLM validation uses x-api-key header with anthropic-version."""
        http_client.set_response(FakeHTTPResponse(status_code=200))

        status, error = await config_manager.validate_credentials(
            "llm_provider", {"api_key": "sk-ant-test"}
        )

        assert status == IntegrationStatus.CONNECTED
        assert error is None
        # Verify extra headers
        call = http_client.calls[0]
        assert call["headers"].get("anthropic-version") == "2023-06-01"
        assert call["headers"].get("x-api-key") == "sk-ant-test"

    async def test_validation_failure_401(self, config_manager, http_client):
        """401 response returns ERROR status with auth failure message."""
        http_client.set_response(FakeHTTPResponse(status_code=401))

        status, error = await config_manager.validate_credentials(
            "apollo", {"api_key": "bad-key"}
        )

        assert status == IntegrationStatus.ERROR
        assert error is not None
        assert "authentication failed" in error.lower()

    async def test_validation_failure_403(self, config_manager, http_client):
        """403 response returns ERROR with permissions message."""
        http_client.set_response(FakeHTTPResponse(status_code=403))

        status, error = await config_manager.validate_credentials(
            "apollo", {"api_key": "limited-key"}
        )

        assert status == IntegrationStatus.ERROR
        assert "permissions" in error.lower()

    async def test_validation_timeout(self, config_manager, http_client):
        """Timeout during validation returns ERROR with timeout message."""
        http_client.set_timeout()

        status, error = await config_manager.validate_credentials(
            "apollo", {"api_key": "timeout-key"}
        )

        assert status == IntegrationStatus.ERROR
        assert "timed out" in error.lower()

    async def test_validation_network_error(self, config_manager, http_client):
        """Network error during validation returns ERROR."""
        http_client.set_error(ConnectionError("Connection refused"))

        status, error = await config_manager.validate_credentials(
            "apollo", {"api_key": "error-key"}
        )

        assert status == IntegrationStatus.ERROR
        assert "network error" in error.lower() or "Connection refused" in error

    async def test_unknown_integration(self, config_manager):
        """Validation of unknown integration returns error."""
        status, error = await config_manager.validate_credentials(
            "unknown_service", {"api_key": "key"}
        )

        assert status == IntegrationStatus.ERROR
        assert "unknown" in error.lower()

    async def test_missing_credential_key(self, config_manager, http_client):
        """Missing required credential key returns error."""
        status, error = await config_manager.validate_credentials(
            "apollo", {"wrong_key": "value"}
        )

        assert status == IntegrationStatus.ERROR
        assert "missing credential" in error.lower()


# --- Credential Preservation Tests (Requirement 18.3) ---


class TestCredentialPreservation:
    """Tests for preserving credentials on validation failure."""

    async def test_preserves_credentials_on_failure(self, config_manager, http_client):
        """Previously stored credentials remain unchanged on validation failure."""
        # First, set up valid credentials
        http_client.set_response(FakeHTTPResponse(status_code=200))
        await config_manager.validate_credentials("apollo", {"api_key": "original-key"})
        assert config_manager.get_credentials("apollo") == {"api_key": "original-key"}

        # Now attempt validation with invalid credentials
        http_client.set_response(FakeHTTPResponse(status_code=401))
        status, error = await config_manager.validate_credentials(
            "apollo", {"api_key": "bad-new-key"}
        )

        assert status == IntegrationStatus.ERROR
        # Original credentials are preserved
        assert config_manager.get_credentials("apollo") == {"api_key": "original-key"}

    async def test_preserves_credentials_on_timeout(self, config_manager, http_client):
        """Credentials preserved when validation times out."""
        # Set up valid credentials
        http_client.set_response(FakeHTTPResponse(status_code=200))
        await config_manager.validate_credentials("apollo", {"api_key": "good-key"})

        # Timeout on new validation
        http_client.set_timeout()
        await config_manager.validate_credentials("apollo", {"api_key": "new-key"})

        # Original credentials preserved
        assert config_manager.get_credentials("apollo") == {"api_key": "good-key"}

    async def test_preserves_credentials_on_network_error(self, config_manager, http_client):
        """Credentials preserved when network error occurs."""
        http_client.set_response(FakeHTTPResponse(status_code=200))
        await config_manager.validate_credentials("lemlist", {"api_key": "working-key"})

        http_client.set_error(ConnectionError("Network down"))
        await config_manager.validate_credentials("lemlist", {"api_key": "new-key"})

        assert config_manager.get_credentials("lemlist") == {"api_key": "working-key"}

    async def test_no_credentials_if_never_validated(self, config_manager):
        """Returns None if no credentials have been successfully validated."""
        assert config_manager.get_credentials("apollo") is None


# --- Health and Usage Tests (Requirements 18.1, 18.4) ---


class TestGetHealth:
    """Tests for health status and usage tracking."""

    async def test_initial_health_is_disconnected(self, config_manager):
        """All integrations start in DISCONNECTED state."""
        health = await config_manager.get_health("apollo")
        assert health.status == IntegrationStatus.DISCONNECTED
        assert health.usage_current == 0
        assert health.usage_limit == 0

    async def test_health_reflects_validation_status(self, config_manager, http_client):
        """Health status reflects the last validation result."""
        http_client.set_response(FakeHTTPResponse(status_code=200))
        await config_manager.validate_credentials("apollo", {"api_key": "key"})

        health = await config_manager.get_health("apollo")
        assert health.status == IntegrationStatus.CONNECTED
        assert health.last_validated is not None

    async def test_health_reflects_error_status(self, config_manager, http_client):
        """Health shows error status with last error message."""
        http_client.set_response(FakeHTTPResponse(status_code=401))
        await config_manager.validate_credentials("apollo", {"api_key": "bad"})

        health = await config_manager.get_health("apollo")
        assert health.status == IntegrationStatus.ERROR
        assert health.last_error is not None

    async def test_health_unknown_integration_raises(self, config_manager):
        """Getting health for unknown integration raises ValueError."""
        with pytest.raises(ValueError, match="Unknown integration"):
            await config_manager.get_health("not_real")

    async def test_usage_refresh_called_when_stale(
        self, config_manager_with_usage, http_client, usage_source
    ):
        """Usage data is refreshed after 15 minutes."""
        # First validate credentials so usage source has something to query
        http_client.set_response(FakeHTTPResponse(status_code=200))
        await config_manager_with_usage.validate_credentials("apollo", {"api_key": "key"})

        # Force last refresh to be old
        config_manager_with_usage._last_usage_refresh["apollo"] = (
            time.time() - ConfigManager.USAGE_REFRESH_INTERVAL - 1
        )

        health = await config_manager_with_usage.get_health("apollo")

        assert "apollo" in usage_source.calls
        assert health.usage_current == 50
        assert health.usage_limit == 100

    async def test_usage_not_refreshed_within_interval(
        self, config_manager_with_usage, http_client, usage_source
    ):
        """Usage data is NOT refreshed if last refresh was within 15 minutes."""
        http_client.set_response(FakeHTTPResponse(status_code=200))
        await config_manager_with_usage.validate_credentials("apollo", {"api_key": "key"})

        # Set last refresh to recent (within interval)
        config_manager_with_usage._last_usage_refresh["apollo"] = time.time()

        await config_manager_with_usage.get_health("apollo")

        # Usage source should not have been called
        assert "apollo" not in usage_source.calls


# --- Quota Check Tests (Requirement 18.5) ---


class TestCheckQuota:
    """Tests for quota checking and blocking."""

    async def test_quota_available_returns_true(self, config_manager):
        """Returns True when quota is not exhausted."""
        config_manager.set_usage("apollo", 50, 100)
        result = await config_manager.check_quota("apollo")
        assert result is True

    async def test_quota_at_80_percent_allows_calls(self, config_manager):
        """At 80% usage, calls are still allowed (but warning is triggered)."""
        config_manager.set_usage("apollo", 80, 100)
        result = await config_manager.check_quota("apollo")
        assert result is True

    async def test_quota_at_100_percent_blocks_calls(self, config_manager):
        """At 100% usage, QuotaExhaustedError is raised."""
        config_manager.set_usage("apollo", 100, 100)

        with pytest.raises(QuotaExhaustedError) as exc_info:
            await config_manager.check_quota("apollo")

        assert exc_info.value.service == "apollo"
        assert exc_info.value.usage_current == 100
        assert exc_info.value.usage_limit == 100

    async def test_quota_over_100_percent_blocks_calls(self, config_manager):
        """Over 100% usage still blocks."""
        config_manager.set_usage("apollo", 120, 100)

        with pytest.raises(QuotaExhaustedError):
            await config_manager.check_quota("apollo")

    async def test_quota_zero_limit_does_not_block(self, config_manager):
        """Zero limit (no quota configured) does not block."""
        config_manager.set_usage("apollo", 0, 0)
        result = await config_manager.check_quota("apollo")
        assert result is True

    async def test_quota_unknown_integration_raises(self, config_manager):
        """Checking quota for unknown integration raises ValueError."""
        with pytest.raises(ValueError, match="Unknown integration"):
            await config_manager.check_quota("fake_service")


# --- Threshold Warning Tests (Requirement 18.5) ---


class TestThresholdAlerts:
    """Tests for 80% warning and 100% critical thresholds."""

    async def test_below_80_no_warning(self, config_manager):
        """Below 80% usage: no warning or critical flags."""
        config_manager.set_usage("apollo", 79, 100)
        health = await config_manager.get_health("apollo")
        assert health.warning_triggered is False
        assert health.critical_triggered is False

    async def test_at_80_percent_warning_triggered(self, config_manager):
        """At exactly 80% usage: warning triggered, no critical."""
        config_manager.set_usage("apollo", 80, 100)
        health = await config_manager.get_health("apollo")
        assert health.warning_triggered is True
        assert health.critical_triggered is False

    async def test_at_90_percent_warning_triggered(self, config_manager):
        """At 90% usage: warning triggered, no critical."""
        config_manager.set_usage("apollo", 90, 100)
        health = await config_manager.get_health("apollo")
        assert health.warning_triggered is True
        assert health.critical_triggered is False

    async def test_at_100_percent_both_triggered(self, config_manager):
        """At 100% usage: both warning and critical triggered."""
        config_manager.set_usage("apollo", 100, 100)
        health = await config_manager.get_health("apollo")
        assert health.warning_triggered is True
        assert health.critical_triggered is True

    async def test_over_100_percent_both_triggered(self, config_manager):
        """Over 100% usage: both flags triggered."""
        config_manager.set_usage("apollo", 150, 100)
        health = await config_manager.get_health("apollo")
        assert health.warning_triggered is True
        assert health.critical_triggered is True

    async def test_usage_percentage_computed_correctly(self, config_manager):
        """Usage percentage is computed as current/limit."""
        config_manager.set_usage("lemlist", 75, 200)
        health = await config_manager.get_health("lemlist")
        assert health.usage_percentage == pytest.approx(0.375)
        assert health.warning_triggered is False


# --- All Integrations Coverage ---


class TestAllIntegrations:
    """Ensure all 5 integrations are supported."""

    async def test_all_five_integrations_exist(self, config_manager):
        """All 5 integrations are tracked."""
        all_health = config_manager.get_all_health()
        assert len(all_health) == 5
        expected = {"apollo", "lemlist", "adzuna", "gmail", "llm_provider"}
        assert set(all_health.keys()) == expected

    async def test_each_integration_starts_disconnected(self, config_manager):
        """Each integration starts in DISCONNECTED state."""
        for name in ["apollo", "lemlist", "adzuna", "gmail", "llm_provider"]:
            health = await config_manager.get_health(name)
            assert health.status == IntegrationStatus.DISCONNECTED
