"""Base error classes for the GKIM Opportunity Finder v2 system.

Requirements 1.3: Apollo API error/timeout handling with specific error states.
Requirements 10.5: Discovery pipeline consecutive source failure tracking.

These errors are raised by integration clients and core services to signal
specific failure modes that drive retry logic, source suspension, and
dashboard surfacing.
"""

from typing import Any


class BaseServiceError(Exception):
    """Base class for all service-level errors in the system.

    Provides a consistent interface for error handling across integration
    clients and core services, including optional context for logging and
    dashboard surfacing.
    """

    def __init__(
        self,
        message: str,
        *,
        service: str | None = None,
        entity_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.service = service
        self.entity_id = entity_id
        self.details = details or {}

    def __str__(self) -> str:
        parts = [self.message]
        if self.service:
            parts.append(f"[service={self.service}]")
        if self.entity_id:
            parts.append(f"[entity_id={self.entity_id}]")
        return " ".join(parts)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"service={self.service!r}, "
            f"entity_id={self.entity_id!r})"
        )


class APITimeoutError(BaseServiceError):
    """Raised when an external API call exceeds its configured timeout.

    Used by Apollo Client (15s timeout), Lemlist Engine (10s timeout),
    and Config Manager (10s validation timeout). Triggers retry scheduling
    with the configured delay (e.g., 5 minutes for Apollo).
    """

    def __init__(
        self,
        message: str = "API request timed out",
        *,
        service: str | None = None,
        entity_id: str | None = None,
        timeout_seconds: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message, service=service, entity_id=entity_id, details=details
        )
        self.timeout_seconds = timeout_seconds


class APIAuthError(BaseServiceError):
    """Raised when an API returns an authentication or authorization failure.

    Indicates invalid credentials, expired tokens, or insufficient permissions.
    Used by integration clients and tracked by source health for consecutive
    failure counting (Requirement 10.5).
    """

    def __init__(
        self,
        message: str = "API authentication failed",
        *,
        service: str | None = None,
        entity_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message, service=service, entity_id=entity_id, details=details
        )


class RateLimitError(BaseServiceError):
    """Raised when an external API returns a rate limit response (HTTP 429).

    Used by integration clients to signal that the request should be retried
    after the specified delay. The Apollo Client enforces max 5 req/sec for
    batch operations (Requirement 1.6).
    """

    def __init__(
        self,
        message: str = "API rate limit exceeded",
        *,
        service: str | None = None,
        entity_id: str | None = None,
        retry_after_seconds: float | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message, service=service, entity_id=entity_id, details=details
        )
        self.retry_after_seconds = retry_after_seconds


class QuotaExhaustedError(BaseServiceError):
    """Raised when an integration's usage quota reaches 100%.

    The Config Manager blocks all API calls to the affected integration
    when quota is fully consumed (Requirement 18.5). This prevents
    unnecessary failed requests and protects against overage charges.
    """

    def __init__(
        self,
        message: str = "Integration quota exhausted",
        *,
        service: str | None = None,
        entity_id: str | None = None,
        usage_current: int | None = None,
        usage_limit: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message, service=service, entity_id=entity_id, details=details
        )
        self.usage_current = usage_current
        self.usage_limit = usage_limit


class SchemaValidationError(BaseServiceError):
    """Raised when the Schema Registry fails validation at startup.

    The system refuses to start if the YAML schema contains structural
    errors, missing required keys, invalid cross-references, or opportunity
    types without pipeline states (Requirement 12.6). Always includes the
    entity_id identifying the problematic schema entry.
    """

    def __init__(
        self,
        message: str,
        *,
        entity_id: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message, service="schema_registry", entity_id=entity_id, details=details
        )
