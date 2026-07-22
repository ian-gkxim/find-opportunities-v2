"""Error hierarchy for the Claim Grounding Verification system.

Requirements 1.4: Extraction failure after 2 retries marks material
"grounding_unverified" and surfaces it in Dashboard "Requires Action".

These errors are raised by the GroundingVerifier during claim extraction
and re-verification flows to drive retry logic and graceful degradation.
"""

from typing import Any


class GroundingError(Exception):
    """Base error class for all grounding-related errors.

    All grounding errors carry a material_id (the material being verified)
    and a retryable flag indicating whether the operation can be retried.
    """

    def __init__(
        self,
        message: str,
        *,
        material_id: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.material_id = material_id
        self.retryable = retryable
        self.details = details or {}

    def __str__(self) -> str:
        return (
            f"{self.message} [material_id={self.material_id}, "
            f"retryable={self.retryable}]"
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"material_id={self.material_id!r}, "
            f"retryable={self.retryable!r})"
        )


class ExtractionError(GroundingError):
    """Raised when claim extraction fails after all retries are exhausted.

    Tracks the number of attempts made before failure. When this error
    is raised, the material should be marked "grounding_unverified" and
    surfaced in the Dashboard "Requires Action" section without blocking
    pipeline advancement (Requirement 1.4).
    """

    def __init__(
        self,
        message: str = "Claim extraction failed after all retries",
        *,
        material_id: str,
        attempts: int,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            material_id=material_id,
            retryable=retryable,
            details=details,
        )
        self.attempts = attempts

    def __str__(self) -> str:
        return (
            f"{self.message} [material_id={self.material_id}, "
            f"attempts={self.attempts}, retryable={self.retryable}]"
        )

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"message={self.message!r}, "
            f"material_id={self.material_id!r}, "
            f"attempts={self.attempts!r}, "
            f"retryable={self.retryable!r})"
        )


class ExtractionTimeoutError(GroundingError):
    """Raised when an LLM extraction call exceeds the 60-second timeout.

    This error is retryable — the GroundingVerifier will retry extraction
    up to MAX_RETRIES times before raising ExtractionError.
    """

    def __init__(
        self,
        message: str = "Claim extraction timed out",
        *,
        material_id: str,
        retryable: bool = True,
        timeout_seconds: float = 60.0,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            material_id=material_id,
            retryable=retryable,
            details=details,
        )
        self.timeout_seconds = timeout_seconds


class ExtractionParseError(GroundingError):
    """Raised when the LLM returns malformed JSON during claim extraction.

    This error is retryable — the GroundingVerifier will retry extraction
    up to MAX_RETRIES times before raising ExtractionError.
    """

    def __init__(
        self,
        message: str = "Failed to parse extraction response as JSON",
        *,
        material_id: str,
        retryable: bool = True,
        raw_response: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            material_id=material_id,
            retryable=retryable,
            details=details,
        )
        self.raw_response = raw_response


class VerificationTimeoutError(GroundingError):
    """Raised when re-verification exceeds the 30-second timeout.

    This occurs during resolution flows (regenerate, manual edit,
    confirm and add) when re-verifying only the affected claims.
    """

    def __init__(
        self,
        message: str = "Re-verification timed out",
        *,
        material_id: str,
        retryable: bool = False,
        timeout_seconds: float = 30.0,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            material_id=material_id,
            retryable=retryable,
            details=details,
        )
        self.timeout_seconds = timeout_seconds
