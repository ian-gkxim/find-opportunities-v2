"""Tests for app.core.gap_errors module.

Requirements: 1.1, 1.2, 1.3, 3.4
"""

import asyncio

import pytest

from app.core.errors import APITimeoutError, BaseServiceError, RateLimitError
from app.core.gap_errors import (
    RATE_LIMIT_BACKOFF_BASE,
    RATE_LIMIT_MAX_RETRIES,
    TIMEOUT_BACKOFF_BASE,
    TIMEOUT_MAX_RETRIES,
    ExtractionError,
    GapAnalysisError,
    NormalizationError,
    OnDemandTimeoutError,
    retry_llm_call,
    with_llm_retry,
)


# ─── Exception Class Tests ────────────────────────────────────────────────────


class TestGapAnalysisError:
    """Tests for GapAnalysisError base class."""

    def test_basic_instantiation(self):
        err = GapAnalysisError("something went wrong")
        assert err.message == "something went wrong"
        assert err.opportunity_id is None
        assert err.retryable is False
        assert err.details == {}
        assert err.service == "gap_analyzer"

    def test_with_opportunity_id(self):
        err = GapAnalysisError(
            "failure", opportunity_id="opp-123", retryable=True
        )
        assert err.opportunity_id == "opp-123"
        assert err.retryable is True
        assert "[opportunity_id=opp-123]" in str(err)
        assert "[retryable=True]" in str(err)

    def test_with_details(self):
        err = GapAnalysisError("oops", details={"context": "nightly"})
        assert err.details == {"context": "nightly"}

    def test_inherits_base_service_error(self):
        err = GapAnalysisError("test")
        assert isinstance(err, BaseServiceError)
        assert isinstance(err, Exception)

    def test_repr(self):
        err = GapAnalysisError("msg", opportunity_id="opp-1")
        r = repr(err)
        assert "GapAnalysisError" in r
        assert "msg" in r
        assert "opp-1" in r


class TestExtractionError:
    """Tests for ExtractionError."""

    def test_default_message(self):
        err = ExtractionError()
        assert "extraction failed" in err.message.lower()
        assert err.attempts == 0
        assert err.retryable is False

    def test_with_attempts_and_opportunity(self):
        err = ExtractionError(
            "LLM timed out",
            opportunity_id="opp-456",
            attempts=3,
        )
        assert err.attempts == 3
        assert err.opportunity_id == "opp-456"
        assert "[attempts=3]" in str(err)

    def test_inherits_gap_analysis_error(self):
        err = ExtractionError(opportunity_id="opp-1", attempts=1)
        assert isinstance(err, GapAnalysisError)
        assert isinstance(err, BaseServiceError)

    def test_repr(self):
        err = ExtractionError(opportunity_id="opp-1", attempts=2)
        r = repr(err)
        assert "ExtractionError" in r
        assert "opp-1" in r
        assert "2" in r


class TestNormalizationError:
    """Tests for NormalizationError."""

    def test_default_message(self):
        err = NormalizationError()
        assert "normalization" in err.message.lower()
        assert err.raw_name is None

    def test_with_raw_name(self):
        err = NormalizationError(
            "Cannot normalize empty string",
            raw_name="",
            opportunity_id="opp-789",
        )
        assert err.raw_name == ""
        assert err.opportunity_id == "opp-789"

    def test_inherits_gap_analysis_error(self):
        err = NormalizationError()
        assert isinstance(err, GapAnalysisError)
        assert isinstance(err, BaseServiceError)


class TestOnDemandTimeoutError:
    """Tests for OnDemandTimeoutError."""

    def test_default_message_and_timeout(self):
        err = OnDemandTimeoutError()
        assert "timed out" in err.message.lower()
        assert err.timeout_seconds == 120.0
        assert err.retryable is False

    def test_custom_timeout(self):
        err = OnDemandTimeoutError(
            timeout_seconds=60.0, opportunity_id="opp-on-demand"
        )
        assert err.timeout_seconds == 60.0
        assert err.opportunity_id == "opp-on-demand"
        assert "[timeout=60.0s]" in str(err)

    def test_inherits_gap_analysis_error(self):
        err = OnDemandTimeoutError()
        assert isinstance(err, GapAnalysisError)
        assert isinstance(err, BaseServiceError)


class TestErrorHierarchy:
    """Verify the exception hierarchy for gap errors."""

    @pytest.mark.parametrize(
        "error_class",
        [
            GapAnalysisError,
            ExtractionError,
            NormalizationError,
            OnDemandTimeoutError,
        ],
    )
    def test_all_catchable_as_base_service_error(self, error_class):
        err = error_class("test error")
        with pytest.raises(BaseServiceError):
            raise err

    def test_extraction_is_subclass_of_gap_analysis_error(self):
        assert issubclass(ExtractionError, GapAnalysisError)

    def test_normalization_is_subclass_of_gap_analysis_error(self):
        assert issubclass(NormalizationError, GapAnalysisError)

    def test_on_demand_timeout_is_subclass_of_gap_analysis_error(self):
        assert issubclass(OnDemandTimeoutError, GapAnalysisError)

    def test_gap_analysis_error_is_subclass_of_base_service_error(self):
        assert issubclass(GapAnalysisError, BaseServiceError)


# ─── Retry Logic Tests ────────────────────────────────────────────────────────


class TestRetryLlmCall:
    """Tests for the retry_llm_call function."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Successful call returns immediately without retry."""
        call_count = 0

        async def mock_llm(prompt):
            nonlocal call_count
            call_count += 1
            return {"required": ["python"], "preferred": ["django"]}

        result = await retry_llm_call(mock_llm, "test prompt")
        assert result == {"required": ["python"], "preferred": ["django"]}
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_timeout_retry_succeeds_on_second_attempt(self):
        """Timeout on first attempt, success on second."""
        call_count = 0

        async def mock_llm(prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise APITimeoutError(
                    "timed out", service="llm", timeout_seconds=60.0
                )
            return {"required": ["java"], "preferred": []}

        result = await retry_llm_call(
            mock_llm, "test prompt", opportunity_id="opp-1"
        )
        assert result == {"required": ["java"], "preferred": []}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_exhausts_retries(self):
        """Timeout on all attempts raises ExtractionError."""

        async def mock_llm(prompt):
            raise APITimeoutError(
                "timed out", service="llm", timeout_seconds=60.0
            )

        with pytest.raises(ExtractionError) as exc_info:
            await retry_llm_call(
                mock_llm, "test prompt", opportunity_id="opp-timeout"
            )

        err = exc_info.value
        assert err.attempts == TIMEOUT_MAX_RETRIES
        assert err.opportunity_id == "opp-timeout"
        assert err.details["error_type"] == "timeout"

    @pytest.mark.asyncio
    async def test_rate_limit_retry_succeeds_on_third_attempt(self):
        """Rate limit on first two attempts, success on third."""
        call_count = 0

        async def mock_llm(prompt):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RateLimitError(
                    "rate limited", service="llm", retry_after_seconds=5.0
                )
            return {"required": ["aws"], "preferred": ["gcp"]}

        result = await retry_llm_call(
            mock_llm, "test prompt", opportunity_id="opp-2"
        )
        assert result == {"required": ["aws"], "preferred": ["gcp"]}
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_rate_limit_exhausts_retries(self):
        """Rate limit on all attempts raises ExtractionError."""

        async def mock_llm(prompt):
            raise RateLimitError(
                "rate limited", service="llm", retry_after_seconds=5.0
            )

        with pytest.raises(ExtractionError) as exc_info:
            await retry_llm_call(
                mock_llm, "test prompt", opportunity_id="opp-rate"
            )

        err = exc_info.value
        assert err.attempts == RATE_LIMIT_MAX_RETRIES
        assert err.opportunity_id == "opp-rate"
        assert err.details["error_type"] == "rate_limit"

    @pytest.mark.asyncio
    async def test_non_retryable_error_raises_immediately(self):
        """Non-retryable errors raise ExtractionError without retry."""
        call_count = 0

        async def mock_llm(prompt):
            nonlocal call_count
            call_count += 1
            raise ValueError("invalid JSON response")

        with pytest.raises(ExtractionError) as exc_info:
            await retry_llm_call(
                mock_llm, "test prompt", opportunity_id="opp-bad"
            )

        assert call_count == 1  # No retry
        err = exc_info.value
        assert err.attempts == 1
        assert err.details["error_type"] == "unknown"

    @pytest.mark.asyncio
    async def test_gap_analysis_error_reraises(self):
        """GapAnalysisError subclasses are re-raised without wrapping."""

        async def mock_llm(prompt):
            raise ExtractionError(
                "already wrapped", opportunity_id="opp-x", attempts=1
            )

        with pytest.raises(ExtractionError) as exc_info:
            await retry_llm_call(mock_llm, "test prompt")

        assert exc_info.value.message == "already wrapped"

    @pytest.mark.asyncio
    async def test_mixed_timeout_and_rate_limit(self):
        """Mixed timeout and rate limit errors are tracked independently."""
        call_count = 0

        async def mock_llm(prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise APITimeoutError("timeout", service="llm")
            if call_count == 2:
                raise RateLimitError("rate limited", service="llm")
            return {"required": ["k8s"], "preferred": []}

        result = await retry_llm_call(mock_llm, "test prompt")
        assert result == {"required": ["k8s"], "preferred": []}
        assert call_count == 3


class TestWithLlmRetryDecorator:
    """Tests for the with_llm_retry decorator."""

    @pytest.mark.asyncio
    async def test_success_on_first_attempt(self):
        """Decorated function succeeds immediately."""

        @with_llm_retry
        async def my_llm_call(prompt: str) -> dict:
            return {"required": ["python"], "preferred": []}

        result = await my_llm_call("test")
        assert result == {"required": ["python"], "preferred": []}

    @pytest.mark.asyncio
    async def test_timeout_retry_with_decorator(self):
        """Decorated function retries on timeout."""
        call_count = 0

        @with_llm_retry
        async def my_llm_call(prompt: str) -> dict:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise APITimeoutError("timeout", service="llm")
            return {"required": ["react"], "preferred": []}

        result = await my_llm_call("test")
        assert result == {"required": ["react"], "preferred": []}
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_exhaustion_with_decorator(self):
        """Decorated function raises ExtractionError after exhausting retries."""

        @with_llm_retry
        async def my_llm_call(prompt: str) -> dict:
            raise APITimeoutError("timeout", service="llm")

        with pytest.raises(ExtractionError) as exc_info:
            await my_llm_call("test")

        assert exc_info.value.details["error_type"] == "timeout"
        assert exc_info.value.details["function"] == "my_llm_call"

    @pytest.mark.asyncio
    async def test_non_retryable_error_with_decorator(self):
        """Decorated function raises ExtractionError for non-retryable errors."""

        @with_llm_retry
        async def my_llm_call(prompt: str) -> dict:
            raise RuntimeError("unexpected failure")

        with pytest.raises(ExtractionError) as exc_info:
            await my_llm_call("test")

        assert exc_info.value.details["error_type"] == "unknown"
        assert exc_info.value.attempts == 1


# ─── Retry Configuration Tests ───────────────────────────────────────────────


class TestRetryConstants:
    """Verify retry configuration matches spec requirements."""

    def test_timeout_max_retries_is_3(self):
        assert TIMEOUT_MAX_RETRIES == 3

    def test_timeout_backoff_base_is_1_second(self):
        assert TIMEOUT_BACKOFF_BASE == 1.0

    def test_timeout_backoff_sequence(self):
        """Backoff: 1s, 2s, 4s."""
        expected = [1.0, 2.0, 4.0]
        actual = [
            TIMEOUT_BACKOFF_BASE * (2 ** i)
            for i in range(TIMEOUT_MAX_RETRIES)
        ]
        assert actual == expected

    def test_rate_limit_max_retries_is_5(self):
        assert RATE_LIMIT_MAX_RETRIES == 5

    def test_rate_limit_backoff_base_is_2_seconds(self):
        assert RATE_LIMIT_BACKOFF_BASE == 2.0

    def test_rate_limit_backoff_sequence(self):
        """Backoff: 2s, 4s, 8s, 16s, 32s."""
        expected = [2.0, 4.0, 8.0, 16.0, 32.0]
        actual = [
            RATE_LIMIT_BACKOFF_BASE * (2 ** i)
            for i in range(RATE_LIMIT_MAX_RETRIES)
        ]
        assert actual == expected
