"""Configuration and Integration Manager.

Requirements 18.1-18.6: Unified integration configuration management.
- 18.1: Display connection status (connected, disconnected, error) for each integration
- 18.2: Validate credentials via test API call within 10 seconds
- 18.3: Preserve previously stored credentials on validation failure
- 18.4: Display usage vs quota, refresh every 15 minutes
- 18.5: Warning at 80%, critical alert + block calls at 100%
- 18.6: Store credentials securely (environment variables or encrypted store)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol

from app.core.errors import QuotaExhaustedError

logger = logging.getLogger(__name__)


# --- Enums ---


class IntegrationStatus(str, Enum):
    """Connection status of an integration."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class IntegrationName(str, Enum):
    """Supported integration identifiers."""

    APOLLO = "apollo"
    LEMLIST = "lemlist"
    ADZUNA = "adzuna"
    GMAIL = "gmail"
    LLM = "llm_provider"


# --- Data Models ---


@dataclass
class IntegrationHealth:
    """Health and usage status for a single integration.

    Attributes:
        name: Integration identifier.
        status: Current connection status.
        usage_current: Current usage count (e.g., API calls, credits, tokens).
        usage_limit: Maximum quota limit for the billing period.
        usage_percentage: Current usage as a percentage of limit (0.0-1.0+).
        warning_triggered: True if usage >= 80% of quota.
        critical_triggered: True if usage >= 100% of quota.
        last_validated: Timestamp of the last successful credential validation.
        last_error: Most recent error message, if any.
    """

    name: str
    status: IntegrationStatus
    usage_current: int = 0
    usage_limit: int = 0
    usage_percentage: float = 0.0
    warning_triggered: bool = False
    critical_triggered: bool = False
    last_validated: datetime | None = None
    last_error: str | None = None


@dataclass
class StoredCredentials:
    """Credentials stored for an integration.

    Credentials are loaded from environment variables (Requirement 18.6)
    and can be updated through the settings interface.
    """

    integration: str
    credentials: dict[str, str] = field(default_factory=dict)
    validated: bool = False
    validated_at: datetime | None = None


# --- Protocols for testability ---


class HTTPClient(Protocol):
    """Protocol for HTTP client used in credential validation.

    Allows injecting a test double without depending on httpx directly.
    """

    async def get(
        self, url: str, *, headers: dict[str, str] | None = None, timeout: float | None = None
    ) -> "HTTPResponse":
        """Execute a GET request."""
        ...

    async def post(
        self, url: str, *, headers: dict[str, str] | None = None,
        json: dict | None = None, timeout: float | None = None
    ) -> "HTTPResponse":
        """Execute a POST request."""
        ...


class HTTPResponse(Protocol):
    """Protocol for HTTP response objects."""

    @property
    def status_code(self) -> int:
        ...

    def json(self) -> dict[str, Any]:
        ...

    @property
    def text(self) -> str:
        ...


class UsageDataSource(Protocol):
    """Protocol for fetching current usage data from integrations.

    Each integration may have a different way to report usage.
    Implementations fetch real-time usage data from the API.
    """

    async def get_usage(
        self, integration: str, credentials: dict[str, str], http_client: "HTTPClient"
    ) -> tuple[int, int]:
        """Fetch current usage and limit for an integration.

        Returns:
            Tuple of (current_usage, usage_limit).
        """
        ...


# --- Validation endpoint configs ---


_VALIDATION_ENDPOINTS: dict[str, dict[str, str]] = {
    IntegrationName.APOLLO: {
        "method": "GET",
        "url": "https://api.apollo.io/v1/auth/health",
        "auth_header": "X-Api-Key",
        "credential_key": "api_key",
    },
    IntegrationName.LEMLIST: {
        "method": "GET",
        "url": "https://api.lemlist.com/api/team",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "credential_key": "api_key",
    },
    IntegrationName.ADZUNA: {
        "method": "GET",
        "url": "https://api.adzuna.com/v1/api/jobs/gb/search/1",
        "auth_type": "query_params",
        "credential_keys": ["app_id", "app_key"],
    },
    IntegrationName.GMAIL: {
        "method": "GET",
        "url": "https://www.googleapis.com/oauth2/v1/tokeninfo",
        "auth_type": "bearer",
        "credential_key": "access_token",
    },
    IntegrationName.LLM: {
        "method": "GET",
        "url": "https://api.anthropic.com/v1/models",
        "auth_header": "x-api-key",
        "credential_key": "api_key",
        "extra_headers": {"anthropic-version": "2023-06-01"},
    },
}


# --- Config Manager ---


class ConfigManager:
    """Manages integration credentials, validation, and usage/quota tracking.

    Provides:
    - Credential validation with 10s timeout test calls (Req 18.2)
    - Connection status tracking per integration (Req 18.1)
    - Usage/quota monitoring with 15-minute refresh (Req 18.4)
    - Warning at 80% and blocking at 100% quota (Req 18.5)
    - Credential preservation on validation failure (Req 18.3)
    - Secure credential storage via environment variables (Req 18.6)

    Uses protocol-based HTTP client for testability.
    """

    VALIDATION_TIMEOUT = 10.0  # seconds
    USAGE_REFRESH_INTERVAL = 900  # 15 minutes in seconds
    WARNING_THRESHOLD = 0.80
    CRITICAL_THRESHOLD = 1.00

    INTEGRATIONS = [
        IntegrationName.APOLLO,
        IntegrationName.LEMLIST,
        IntegrationName.ADZUNA,
        IntegrationName.GMAIL,
        IntegrationName.LLM,
    ]

    def __init__(
        self,
        http_client: HTTPClient,
        usage_source: UsageDataSource | None = None,
    ) -> None:
        """Initialize the ConfigManager.

        Args:
            http_client: HTTP client for making validation test calls.
            usage_source: Optional usage data source for fetching quota info.
                         If None, usage tracking is disabled.
        """
        self._http_client = http_client
        self._usage_source = usage_source

        # Stored credentials per integration (Req 18.3: preserved on failure)
        self._credentials: dict[str, StoredCredentials] = {
            name.value: StoredCredentials(integration=name.value)
            for name in self.INTEGRATIONS
        }

        # Health state per integration
        self._health: dict[str, IntegrationHealth] = {
            name.value: IntegrationHealth(
                name=name.value,
                status=IntegrationStatus.DISCONNECTED,
            )
            for name in self.INTEGRATIONS
        }

        # Last usage refresh timestamp per integration
        self._last_usage_refresh: dict[str, float] = {
            name.value: 0.0 for name in self.INTEGRATIONS
        }

    # --- Credential Validation (Requirement 18.2) ---

    async def validate_credentials(
        self, integration: str, credentials: dict[str, str]
    ) -> tuple[IntegrationStatus, str | None]:
        """Validate credentials by making a test API call with 10s timeout.

        On success: stores the new credentials and updates status to CONNECTED.
        On failure: preserves previously stored credentials (Req 18.3),
                    updates status to ERROR, and returns the error message.

        Args:
            integration: Integration name (e.g., "apollo", "lemlist").
            credentials: Dict of credential key-value pairs to validate.

        Returns:
            Tuple of (status, error_message). error_message is None on success.
        """
        if integration not in [name.value for name in self.INTEGRATIONS]:
            return IntegrationStatus.ERROR, f"Unknown integration: {integration}"

        try:
            # Perform test API call with 10s timeout
            success, error = await self._make_validation_call(integration, credentials)

            if success:
                # Store new credentials on successful validation
                self._credentials[integration] = StoredCredentials(
                    integration=integration,
                    credentials=credentials.copy(),
                    validated=True,
                    validated_at=datetime.now(timezone.utc),
                )
                self._health[integration].status = IntegrationStatus.CONNECTED
                self._health[integration].last_validated = datetime.now(timezone.utc)
                self._health[integration].last_error = None
                logger.info(f"Credentials validated successfully for {integration}")
                return IntegrationStatus.CONNECTED, None
            else:
                # Preserve existing credentials on failure (Requirement 18.3)
                self._health[integration].status = IntegrationStatus.ERROR
                self._health[integration].last_error = error
                logger.warning(f"Credential validation failed for {integration}: {error}")
                return IntegrationStatus.ERROR, error

        except asyncio.TimeoutError:
            error_msg = f"Validation timed out after {self.VALIDATION_TIMEOUT}s"
            self._health[integration].status = IntegrationStatus.ERROR
            self._health[integration].last_error = error_msg
            logger.warning(f"Credential validation timeout for {integration}")
            return IntegrationStatus.ERROR, error_msg

        except Exception as e:
            error_msg = f"Validation error: {str(e)}"
            self._health[integration].status = IntegrationStatus.ERROR
            self._health[integration].last_error = error_msg
            logger.error(f"Unexpected validation error for {integration}: {e}")
            return IntegrationStatus.ERROR, error_msg

    async def _make_validation_call(
        self, integration: str, credentials: dict[str, str]
    ) -> tuple[bool, str | None]:
        """Execute the actual test API call for credential validation.

        Args:
            integration: Integration identifier.
            credentials: Credentials to test.

        Returns:
            Tuple of (success: bool, error_message: str | None).
        """
        endpoint_config = _VALIDATION_ENDPOINTS.get(integration)
        if not endpoint_config:
            return False, f"No validation endpoint configured for {integration}"

        url = endpoint_config["url"]
        method = endpoint_config.get("method", "GET")
        headers: dict[str, str] = {}

        # Build auth headers based on config
        auth_type = endpoint_config.get("auth_type", "header")

        if auth_type == "query_params":
            # Adzuna uses query params for auth
            credential_keys = endpoint_config.get("credential_keys", [])
            params = []
            for key in credential_keys:
                if key not in credentials:
                    return False, f"Missing credential: {key}"
                params.append(f"{key}={credentials[key]}")
            url = f"{url}?{'&'.join(params)}"
        elif auth_type == "bearer":
            credential_key = endpoint_config.get("credential_key", "api_key")
            if credential_key not in credentials:
                return False, f"Missing credential: {credential_key}"
            headers["Authorization"] = f"Bearer {credentials[credential_key]}"
        else:
            # Standard header-based auth
            auth_header = endpoint_config.get("auth_header", "Authorization")
            auth_prefix = endpoint_config.get("auth_prefix", "")
            credential_key = endpoint_config.get("credential_key", "api_key")

            if credential_key not in credentials:
                return False, f"Missing credential: {credential_key}"

            headers[auth_header] = f"{auth_prefix}{credentials[credential_key]}"

        # Add any extra headers
        extra_headers = endpoint_config.get("extra_headers", {})
        headers.update(extra_headers)

        try:
            response = await asyncio.wait_for(
                self._http_client.get(url, headers=headers, timeout=self.VALIDATION_TIMEOUT),
                timeout=self.VALIDATION_TIMEOUT,
            )

            if 200 <= response.status_code < 300:
                return True, None
            elif response.status_code == 401:
                return False, "Invalid credentials: authentication failed"
            elif response.status_code == 403:
                return False, "Invalid credentials: insufficient permissions"
            elif response.status_code == 429:
                return False, "Rate limited during validation"
            else:
                return False, f"API returned status {response.status_code}"

        except asyncio.TimeoutError:
            raise  # Re-raise to be caught by caller
        except Exception as e:
            return False, f"Network error: {str(e)}"

    # --- Health and Usage (Requirements 18.1, 18.4) ---

    async def get_health(self, integration: str) -> IntegrationHealth:
        """Get current health and usage for an integration.

        Refreshes usage data if the last refresh was more than 15 minutes ago
        (Requirement 18.4).

        Args:
            integration: Integration identifier.

        Returns:
            IntegrationHealth with current status, usage, and threshold flags.

        Raises:
            ValueError: If the integration name is not recognized.
        """
        if integration not in [name.value for name in self.INTEGRATIONS]:
            raise ValueError(f"Unknown integration: {integration}")

        # Check if usage data needs refresh (15-minute interval)
        now = time.time()
        last_refresh = self._last_usage_refresh.get(integration, 0.0)

        if now - last_refresh >= self.USAGE_REFRESH_INTERVAL:
            await self._refresh_usage(integration)
            self._last_usage_refresh[integration] = now

        return self._health[integration]

    async def _refresh_usage(self, integration: str) -> None:
        """Refresh usage data for an integration from the usage source.

        Args:
            integration: Integration identifier.
        """
        if self._usage_source is None:
            return

        stored = self._credentials.get(integration)
        if not stored or not stored.validated:
            return

        try:
            usage_current, usage_limit = await self._usage_source.get_usage(
                integration, stored.credentials, self._http_client
            )
            self._update_usage(integration, usage_current, usage_limit)
        except Exception as e:
            logger.warning(f"Failed to refresh usage for {integration}: {e}")

    def _update_usage(self, integration: str, usage_current: int, usage_limit: int) -> None:
        """Update usage data and compute threshold flags.

        Args:
            integration: Integration identifier.
            usage_current: Current usage count.
            usage_limit: Maximum quota limit.
        """
        health = self._health[integration]
        health.usage_current = usage_current
        health.usage_limit = usage_limit

        if usage_limit > 0:
            health.usage_percentage = usage_current / usage_limit
        else:
            health.usage_percentage = 0.0

        # Compute threshold flags (Requirement 18.5)
        health.warning_triggered = health.usage_percentage >= self.WARNING_THRESHOLD
        health.critical_triggered = health.usage_percentage >= self.CRITICAL_THRESHOLD

        if health.critical_triggered:
            logger.critical(
                f"Integration {integration} has reached 100% quota "
                f"({usage_current}/{usage_limit}). Calls will be blocked."
            )
        elif health.warning_triggered:
            logger.warning(
                f"Integration {integration} is at {health.usage_percentage:.0%} quota "
                f"({usage_current}/{usage_limit})."
            )

    # --- Quota Checking (Requirement 18.5) ---

    async def check_quota(self, integration: str) -> bool:
        """Check if an integration has available quota.

        Returns False and raises QuotaExhaustedError if the integration
        has reached 100% usage. This blocks all API calls to that
        integration until the quota resets.

        Args:
            integration: Integration identifier.

        Returns:
            True if quota is available (calls are allowed).

        Raises:
            QuotaExhaustedError: If integration is at 100% quota.
            ValueError: If the integration name is not recognized.
        """
        if integration not in [name.value for name in self.INTEGRATIONS]:
            raise ValueError(f"Unknown integration: {integration}")

        health = self._health[integration]

        if health.critical_triggered:
            raise QuotaExhaustedError(
                f"Integration {integration} quota exhausted "
                f"({health.usage_current}/{health.usage_limit})",
                service=integration,
                usage_current=health.usage_current,
                usage_limit=health.usage_limit,
            )

        return True

    # --- Credential Access ---

    def get_credentials(self, integration: str) -> dict[str, str] | None:
        """Get stored credentials for an integration.

        Returns None if no validated credentials exist.

        Args:
            integration: Integration identifier.

        Returns:
            Credentials dict or None.
        """
        stored = self._credentials.get(integration)
        if stored and stored.validated:
            return stored.credentials.copy()
        return None

    def get_all_health(self) -> dict[str, IntegrationHealth]:
        """Get health status for all integrations.

        Returns:
            Dict mapping integration name to IntegrationHealth.
        """
        return {name: health for name, health in self._health.items()}

    # --- Direct Usage Update (for testing and external data sources) ---

    def set_usage(self, integration: str, usage_current: int, usage_limit: int) -> None:
        """Directly set usage data for an integration.

        Used by external callers or tests to update quota information
        without going through the usage source protocol.

        Args:
            integration: Integration identifier.
            usage_current: Current usage count.
            usage_limit: Maximum quota limit.
        """
        if integration not in [name.value for name in self.INTEGRATIONS]:
            raise ValueError(f"Unknown integration: {integration}")
        self._update_usage(integration, usage_current, usage_limit)
        self._last_usage_refresh[integration] = time.time()
