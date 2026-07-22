"""Error hierarchy and retry logic for the Capability Gap Analytics system.

Requirements 1.1, 1.2, 1.3, 3.4: Graceful degradation when LLM is
unavailable (use cached extractions), retry logic for LLM failures
(3 retries with backoff for timeout, 5 for rate limit), and on-demand
timeout enforcement.

These errors are raised by the GapAnalyzer during capability extraction,
normalization, and on-demand analysis flows to drive retry logic and
graceful degradation.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable, TypeVar

from app.core.errors import APITimeoutError, BaseServiceError, RateLimitError

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ─── Exception Classes ────────────────────────────────────────────────────────


class GapAnalysisError(BaseServiceError):
    """Base error class for all gap-analysis-related errors.

    All gap analysis errors carry an optional opportunity_id and a retryable
    flag indicating whether the operation can be retried.
    """

    def __init__(
        self,
        message: str,
        *,
        opportunity_id: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            service="gap_analyzer",
            entity_id=opportunity_id,
            details=details,
        )
        self.opportunity_id = opportunity_id
        self.retryable = retryable

    def __str__(self) -> str:
        parts = [self.message]
        if self.opportunity_id:
            parts.append(f"[opportunity_id={self.opportunity_id}]")
        parts.append(f"[retryable={self.retryable}]")
        return " ".join(parts)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"opportunity_id={self.opportunity_id!r}, "
            f"retryable={self.retryable!r})"
        )


class ExtractionError(GapAnalysisError):
    """Raised when capability extraction fails after all retries are exhausted.

    Tracks the number of attempts made before failure. When this error
    is raised, the nightly cycle should skip the opportunity and continue
    with the next one (graceful degradation).
    """

    def __init__(
        self,
        message: str = "Capability extraction failed after all retries",
        *,
        opportunity_id: str | None = None,
        attempts: int = 0,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            opportunity_id=opportunity_id,
            retryable=retryable,
            details=details,
        )
        self.attempts = attempts

    def __str__(self) -> str:
        parts = [self.message]
        if self.opportunity_id:
            parts.append(f"[opportunity_id={self.opportunity_id}]")
        parts.append(f"[attempts={self.attempts}]")
        parts.append(f"[retryable={self.retryable}]")
        return " ".join(parts)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"opportunity_id={self.opportunity_id!r}, "
            f"attempts={self.attempts!r})"
        )


class NormalizationError(GapAnalysisError):
    """Raised when capability normalization encounters an unrecoverable error.

    Graceful degradation: if the synonym table is empty or unavailable,
    the normalizer falls back to self-canonical names (lowercased, stripped).
    This error is raised only for truly unrecoverable scenarios (e.g., invalid
    input that cannot be processed at all).
    """

    def __init__(
        self,
        message: str = "Capability normalization failed",
        *,
        opportunity_id: str | None = None,
        raw_name: str | None = None,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            opportunity_id=opportunity_id,
            retryable=retryable,
            details=details,
        )
        self.raw_name = raw_name

    def __str__(self) -> str:
        parts = [self.message]
        if self.raw_name:
            parts.append(f"[raw_name={self.raw_name}]")
        if self.opportunity_id:
            parts.append(f"[opportunity_id={self.opportunity_id}]")
        return " ".join(parts)


class OnDemandTimeoutError(GapAnalysisError):
    """Raised when on-demand gap analysis exceeds the 120-second SLA.

    This error is NOT retryable — the user should be informed that the
    analysis timed out and may retry manually.
    """

    def __init__(
        self,
        message: str = "On-demand gap analysis timed out",
        *,
        opportunity_id: str | None = None,
        timeout_seconds: float = 120.0,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            opportunity_id=opportunity_id,
            retryable=retryable,
            details=details,
        )
        self.timeout_seconds = timeout_seconds

    def __str__(self) -> str:
        parts = [self.message]
        parts.append(f"[timeout={self.timeout_seconds}s]")
        if self.opportunity_id:
            parts.append(f"[opportunity_id={self.opportunity_id}]")
        return " ".join(parts)


# ─── Retry Logic ──────────────────────────────────────────────────────────────

# Retry configuration constants
TIMEOUT_MAX_RETRIES = 3
TIMEOUT_BACKOFF_BASE = 1.0  # 1s, 2s, 4s

RATE_LIMIT_MAX_RETRIES = 5
RATE_LIMIT_BACKOFF_BASE = 2.0  # 2s, 4s, 8s, 16s, 32s


async def retry_llm_call(
    func: Callable[..., Any],
    *args: Any,
    opportunity_id: str | None = None,
    **kwargs: Any,
) -> Any:
    """Execute an async LLM call with retry logic for timeout and rate limit errors.

    Retry policy:
    - APITimeoutError: up to 3 retries with exponential backoff (1s, 2s, 4s)
    - RateLimitError: up to 5 retries with exponential backoff (2s, 4s, 8s, 16s, 32s)
    - Other errors: no retry, raise immediately as ExtractionError

    Args:
        func: The async callable to invoke (e.g., llm_router.dispatch_extraction).
        *args: Positional arguments to pass to the callable.
        opportunity_id: Optional ID for error context.
        **kwargs: Keyword arguments to pass to the callable.

    Returns:
        The result of the successful function call.

    Raises:
        ExtractionError: If all retries are exhausted or a non-retryable error occurs.
    """
    timeout_attempts = 0
    rate_limit_attempts = 0
    total_attempts = 0

    while True:
        total_attempts += 1
        try:
            return await func(*args, **kwargs)

        except APITimeoutError as exc:
            timeout_attempts += 1
            if timeout_attempts >= TIMEOUT_MAX_RETRIES:
                logger.error(
                    "LLM timeout after %d retries for opportunity %s: %s",
                    timeout_attempts,
                    opportunity_id,
                    str(exc),
                )
                raise ExtractionError(
                    f"LLM extraction timed out after {timeout_attempts} retries",
                    opportunity_id=opportunity_id,
                    attempts=total_attempts,
                    details={"last_error": str(exc), "error_type": "timeout"},
                ) from exc

            delay = TIMEOUT_BACKOFF_BASE * (2 ** (timeout_attempts - 1))
            logger.warning(
                "LLM timeout (attempt %d/%d) for opportunity %s, "
                "retrying in %.1fs",
                timeout_attempts,
                TIMEOUT_MAX_RETRIES,
                opportunity_id,
                delay,
            )
            await asyncio.sleep(delay)

        except RateLimitError as exc:
            rate_limit_attempts += 1
            if rate_limit_attempts >= RATE_LIMIT_MAX_RETRIES:
                logger.error(
                    "LLM rate limit after %d retries for opportunity %s: %s",
                    rate_limit_attempts,
                    opportunity_id,
                    str(exc),
                )
                raise ExtractionError(
                    f"LLM rate limit exceeded after {rate_limit_attempts} retries",
                    opportunity_id=opportunity_id,
                    attempts=total_attempts,
                    details={
                        "last_error": str(exc),
                        "error_type": "rate_limit",
                    },
                ) from exc

            delay = RATE_LIMIT_BACKOFF_BASE * (2 ** (rate_limit_attempts - 1))
            logger.warning(
                "LLM rate limited (attempt %d/%d) for opportunity %s, "
                "retrying in %.1fs",
                rate_limit_attempts,
                RATE_LIMIT_MAX_RETRIES,
                opportunity_id,
                delay,
            )
            await asyncio.sleep(delay)

        except (GapAnalysisError, ExtractionError):
            # Re-raise gap analysis errors as-is
            raise

        except Exception as exc:
            # Non-retryable error — raise immediately
            logger.error(
                "LLM call failed with non-retryable error for opportunity %s: %s",
                opportunity_id,
                str(exc),
            )
            raise ExtractionError(
                f"LLM extraction failed: {exc}",
                opportunity_id=opportunity_id,
                attempts=total_attempts,
                details={"last_error": str(exc), "error_type": "unknown"},
            ) from exc


def with_llm_retry(func: F) -> F:
    """Decorator that wraps an async LLM call with retry logic.

    Applies the same retry policy as retry_llm_call:
    - APITimeoutError: 3 retries with exponential backoff (1s, 2s, 4s)
    - RateLimitError: 5 retries with exponential backoff (2s, 4s, 8s, 16s, 32s)
    - Other errors: no retry, raise immediately

    Usage:
        @with_llm_retry
        async def my_llm_call(self, prompt: str) -> dict:
            return await self._llm.dispatch_extraction(prompt)
    """

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        timeout_attempts = 0
        rate_limit_attempts = 0
        total_attempts = 0

        while True:
            total_attempts += 1
            try:
                return await func(*args, **kwargs)

            except APITimeoutError as exc:
                timeout_attempts += 1
                if timeout_attempts >= TIMEOUT_MAX_RETRIES:
                    logger.error(
                        "LLM timeout after %d retries in %s: %s",
                        timeout_attempts,
                        func.__name__,
                        str(exc),
                    )
                    raise ExtractionError(
                        f"LLM timed out after {timeout_attempts} retries",
                        attempts=total_attempts,
                        details={
                            "last_error": str(exc),
                            "error_type": "timeout",
                            "function": func.__name__,
                        },
                    ) from exc

                delay = TIMEOUT_BACKOFF_BASE * (2 ** (timeout_attempts - 1))
                logger.warning(
                    "LLM timeout (attempt %d/%d) in %s, retrying in %.1fs",
                    timeout_attempts,
                    TIMEOUT_MAX_RETRIES,
                    func.__name__,
                    delay,
                )
                await asyncio.sleep(delay)

            except RateLimitError as exc:
                rate_limit_attempts += 1
                if rate_limit_attempts >= RATE_LIMIT_MAX_RETRIES:
                    logger.error(
                        "LLM rate limit after %d retries in %s: %s",
                        rate_limit_attempts,
                        func.__name__,
                        str(exc),
                    )
                    raise ExtractionError(
                        f"LLM rate limit exceeded after {rate_limit_attempts} retries",
                        attempts=total_attempts,
                        details={
                            "last_error": str(exc),
                            "error_type": "rate_limit",
                            "function": func.__name__,
                        },
                    ) from exc

                delay = RATE_LIMIT_BACKOFF_BASE * (2 ** (rate_limit_attempts - 1))
                logger.warning(
                    "LLM rate limited (attempt %d/%d) in %s, retrying in %.1fs",
                    rate_limit_attempts,
                    RATE_LIMIT_MAX_RETRIES,
                    func.__name__,
                    delay,
                )
                await asyncio.sleep(delay)

            except (GapAnalysisError, ExtractionError):
                # Re-raise gap analysis errors as-is
                raise

            except Exception as exc:
                logger.error(
                    "LLM call failed with non-retryable error in %s: %s",
                    func.__name__,
                    str(exc),
                )
                raise ExtractionError(
                    f"LLM call failed: {exc}",
                    attempts=total_attempts,
                    details={
                        "last_error": str(exc),
                        "error_type": "unknown",
                        "function": func.__name__,
                    },
                ) from exc

    return wrapper  # type: ignore[return-value]
