"""Tests for app.core.errors module."""

import pytest

from app.core.errors import (
    APIAuthError,
    APITimeoutError,
    BaseServiceError,
    QuotaExhaustedError,
    RateLimitError,
    SchemaValidationError,
)


class TestBaseServiceError:
    """Tests for BaseServiceError base class."""

    def test_basic_instantiation(self):
        err = BaseServiceError("something went wrong")
        assert str(err) == "something went wrong"
        assert err.message == "something went wrong"
        assert err.service is None
        assert err.entity_id is None
        assert err.details == {}

    def test_with_service_and_entity(self):
        err = BaseServiceError(
            "failure", service="apollo", entity_id="company-123"
        )
        assert "failure" in str(err)
        assert "[service=apollo]" in str(err)
        assert "[entity_id=company-123]" in str(err)

    def test_with_details(self):
        err = BaseServiceError("oops", details={"retry_count": 3})
        assert err.details == {"retry_count": 3}

    def test_is_exception(self):
        err = BaseServiceError("test")
        assert isinstance(err, Exception)

    def test_repr(self):
        err = BaseServiceError("msg", service="svc", entity_id="eid")
        r = repr(err)
        assert "BaseServiceError" in r
        assert "msg" in r
        assert "svc" in r
        assert "eid" in r


class TestAPITimeoutError:
    """Tests for APITimeoutError."""

    def test_default_message(self):
        err = APITimeoutError()
        assert err.message == "API request timed out"

    def test_custom_message_and_timeout(self):
        err = APITimeoutError(
            "Apollo enrichment timed out",
            service="apollo",
            timeout_seconds=15.0,
        )
        assert err.timeout_seconds == 15.0
        assert err.service == "apollo"

    def test_inherits_base(self):
        err = APITimeoutError()
        assert isinstance(err, BaseServiceError)
        assert isinstance(err, Exception)

    def test_entity_id_propagation(self):
        err = APITimeoutError(entity_id="prospect-456", timeout_seconds=10.0)
        assert err.entity_id == "prospect-456"


class TestAPIAuthError:
    """Tests for APIAuthError."""

    def test_default_message(self):
        err = APIAuthError()
        assert err.message == "API authentication failed"

    def test_custom_message(self):
        err = APIAuthError("Invalid Apollo API key", service="apollo")
        assert err.message == "Invalid Apollo API key"
        assert err.service == "apollo"

    def test_inherits_base(self):
        assert isinstance(APIAuthError(), BaseServiceError)


class TestRateLimitError:
    """Tests for RateLimitError."""

    def test_default_message(self):
        err = RateLimitError()
        assert err.message == "API rate limit exceeded"

    def test_retry_after(self):
        err = RateLimitError(
            service="apollo",
            retry_after_seconds=60.0,
        )
        assert err.retry_after_seconds == 60.0
        assert err.service == "apollo"

    def test_inherits_base(self):
        assert isinstance(RateLimitError(), BaseServiceError)


class TestQuotaExhaustedError:
    """Tests for QuotaExhaustedError."""

    def test_default_message(self):
        err = QuotaExhaustedError()
        assert err.message == "Integration quota exhausted"

    def test_usage_tracking(self):
        err = QuotaExhaustedError(
            service="apollo",
            usage_current=10000,
            usage_limit=10000,
        )
        assert err.usage_current == 10000
        assert err.usage_limit == 10000
        assert err.service == "apollo"

    def test_inherits_base(self):
        assert isinstance(QuotaExhaustedError(), BaseServiceError)


class TestSchemaValidationError:
    """Tests for SchemaValidationError."""

    def test_service_is_always_schema_registry(self):
        err = SchemaValidationError("Missing key: stages")
        assert err.service == "schema_registry"

    def test_entity_id(self):
        err = SchemaValidationError(
            "OpportunityType 'cold_outreach' references unknown beneficiary 'unknown'",
            entity_id="cold_outreach",
        )
        assert err.entity_id == "cold_outreach"
        assert "cold_outreach" in str(err)

    def test_inherits_base(self):
        assert isinstance(SchemaValidationError("x"), BaseServiceError)

    def test_with_details(self):
        err = SchemaValidationError(
            "Invalid cross-reference",
            entity_id="opp-type-1",
            details={"missing_ref": "beneficiary_x"},
        )
        assert err.details == {"missing_ref": "beneficiary_x"}


class TestErrorHierarchy:
    """Verify that all errors are catchable via BaseServiceError."""

    @pytest.mark.parametrize(
        "error_class",
        [
            APITimeoutError,
            APIAuthError,
            RateLimitError,
            QuotaExhaustedError,
            SchemaValidationError,
        ],
    )
    def test_all_catchable_as_base(self, error_class):
        if error_class == SchemaValidationError:
            err = error_class("test")
        else:
            err = error_class()
        with pytest.raises(BaseServiceError):
            raise err
