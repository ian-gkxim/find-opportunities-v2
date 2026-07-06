"""Unit tests for Apollo.io client integration.

Tests cover enrichment, contact discovery, intent signals, batch processing,
and error handling with mock httpx responses.
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.integrations.apollo_client import (
    ApolloClient,
    Contact,
    ContactSearchStatus,
    EmailVerificationStatus,
    EnrichmentRecord,
    EnrichmentStatus,
    IntentSignal,
    SignalStrength,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_http_client():
    """Create a mock httpx.AsyncClient for testing."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def apollo_client(mock_http_client):
    """Create an ApolloClient with mock HTTP client."""
    return ApolloClient(api_key="test-key", http_client=mock_http_client)


def _make_response(status_code: int, json_data: dict) -> httpx.Response:
    """Helper to create a mock httpx.Response."""
    response = httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("POST", "https://api.apollo.io/v1/test"),
    )
    return response


# ---------------------------------------------------------------------------
# Enrichment Tests
# ---------------------------------------------------------------------------


class TestEnrichCompany:
    """Tests for ApolloClient.enrich_company()."""

    async def test_successful_enrichment(self, apollo_client, mock_http_client):
        """Successful enrichment returns a complete EnrichmentRecord."""
        mock_http_client.post.return_value = _make_response(
            200,
            {
                "organization": {
                    "id": "org_123",
                    "estimated_num_employees": 150,
                    "annual_revenue_printed": "$10M-$50M",
                    "industry": "Information Technology",
                    "technology_names": ["Python", "React", "AWS"],
                    "latest_funding_stage": "Series B",
                    "city": "London",
                    "country": "United Kingdom",
                }
            },
        )

        record = await apollo_client.enrich_company("example.com")

        assert record.status == EnrichmentStatus.COMPLETE
        assert record.company_id == "org_123"
        assert record.company_domain == "example.com"
        assert record.employee_count == 150
        assert record.revenue_range == "$10M-$50M"
        assert record.industry == "Information Technology"
        assert record.tech_stack == ["Python", "React", "AWS"]
        assert record.funding_stage == "Series B"
        assert record.headquarters_city == "London"
        assert record.headquarters_country == "United Kingdom"

    async def test_not_found_empty_organization(self, apollo_client, mock_http_client):
        """Returns NOT_FOUND when API returns empty organization."""
        mock_http_client.post.return_value = _make_response(
            200, {"organization": None}
        )

        record = await apollo_client.enrich_company("nonexistent.com")

        assert record.status == EnrichmentStatus.NOT_FOUND
        assert record.company_domain == "nonexistent.com"

    async def test_not_found_404(self, apollo_client, mock_http_client):
        """Returns NOT_FOUND on 404 response."""
        mock_http_client.post.return_value = _make_response(404, {})

        record = await apollo_client.enrich_company("missing.com")

        assert record.status == EnrichmentStatus.NOT_FOUND

    async def test_timeout_retries_and_fails(self, apollo_client, mock_http_client):
        """Returns ENRICHMENT_FAILED after all retries exhausted on timeout."""
        mock_http_client.post.side_effect = httpx.ReadTimeout("timeout")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            record = await apollo_client.enrich_company("slow.com")

        assert record.status == EnrichmentStatus.ENRICHMENT_FAILED
        assert record.retry_count == 3
        assert mock_http_client.post.call_count == 3

    async def test_server_error_retries(self, apollo_client, mock_http_client):
        """Retries on 500 errors, returns ENRICHMENT_FAILED if all fail."""
        mock_http_client.post.return_value = _make_response(
            500, {"error": "Internal Server Error"}
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            record = await apollo_client.enrich_company("broken.com")

        assert record.status == EnrichmentStatus.ENRICHMENT_FAILED
        assert mock_http_client.post.call_count == 3

    async def test_retry_succeeds_on_second_attempt(
        self, apollo_client, mock_http_client
    ):
        """Succeeds on second attempt after first timeout."""
        mock_http_client.post.side_effect = [
            httpx.ReadTimeout("timeout"),
            _make_response(
                200,
                {
                    "organization": {
                        "id": "org_456",
                        "estimated_num_employees": 50,
                        "industry": "SaaS",
                        "technology_names": ["Node.js"],
                    }
                },
            ),
        ]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            record = await apollo_client.enrich_company("retry.com")

        assert record.status == EnrichmentStatus.COMPLETE
        assert record.company_id == "org_456"
        assert mock_http_client.post.call_count == 2

    async def test_enrichment_record_expiry(self, apollo_client, mock_http_client):
        """EnrichmentRecord expires_at is set to 30 days from enrichment."""
        mock_http_client.post.return_value = _make_response(
            200,
            {
                "organization": {
                    "id": "org_789",
                    "estimated_num_employees": 10,
                }
            },
        )

        record = await apollo_client.enrich_company("fresh.com")

        assert record.enriched_at is not None
        assert record.expires_at is not None
        delta = record.expires_at - record.enriched_at
        assert delta == timedelta(days=30)


# ---------------------------------------------------------------------------
# Contact Discovery Tests
# ---------------------------------------------------------------------------


class TestFindContacts:
    """Tests for ApolloClient.find_contacts()."""

    async def test_finds_decision_makers(self, apollo_client, mock_http_client):
        """Returns contacts when decision-maker titles are found."""
        mock_http_client.post.return_value = _make_response(
            200,
            {
                "people": [
                    {
                        "name": "Jane Doe",
                        "title": "CEO",
                        "email": "jane@example.com",
                        "email_status": "verified",
                        "linkedin_url": "https://linkedin.com/in/janedoe",
                    },
                    {
                        "name": "John Smith",
                        "title": "CTO",
                        "email": "john@example.com",
                        "email_status": "unverified",
                        "linkedin_url": None,
                    },
                ]
            },
        )

        contacts, status = await apollo_client.find_contacts("org_123")

        assert status == ContactSearchStatus.COMPLETE
        assert len(contacts) == 2
        assert contacts[0].full_name == "Jane Doe"
        assert contacts[0].email_verification == EmailVerificationStatus.VERIFIED
        assert contacts[0].seniority_level == "c_suite"

    async def test_broadens_search_when_no_decision_makers(
        self, apollo_client, mock_http_client
    ):
        """Broadens to director-level when no decision-maker titles found."""
        # First call returns no people, second returns directors
        mock_http_client.post.side_effect = [
            _make_response(200, {"people": []}),
            _make_response(
                200,
                {
                    "people": [
                        {
                            "name": "Alice Director",
                            "title": "Director of Engineering",
                            "email": "alice@example.com",
                            "email_status": "verified",
                        }
                    ]
                },
            ),
        ]

        contacts, status = await apollo_client.find_contacts("org_456")

        assert status == ContactSearchStatus.BROADENED_SEARCH
        assert len(contacts) == 1
        assert contacts[0].full_name == "Alice Director"

    async def test_contacts_unavailable_after_broadening(
        self, apollo_client, mock_http_client
    ):
        """Returns CONTACTS_UNAVAILABLE when no contacts found after broadening."""
        mock_http_client.post.return_value = _make_response(200, {"people": []})

        contacts, status = await apollo_client.find_contacts("org_789")

        assert status == ContactSearchStatus.CONTACTS_UNAVAILABLE
        assert contacts == []

    async def test_max_5_contacts_returned(self, apollo_client, mock_http_client):
        """Returns at most 5 contacts even if more available."""
        people = [
            {
                "name": f"Person {i}",
                "title": "CTO",
                "email": f"person{i}@example.com",
                "email_status": "verified",
            }
            for i in range(10)
        ]
        mock_http_client.post.return_value = _make_response(200, {"people": people})

        contacts, status = await apollo_client.find_contacts("org_many")

        assert len(contacts) <= 5

    async def test_filters_contacts_without_contact_method(
        self, apollo_client, mock_http_client
    ):
        """Excludes contacts without email or LinkedIn URL."""
        mock_http_client.post.return_value = _make_response(
            200,
            {
                "people": [
                    {
                        "name": "Has Email",
                        "title": "CEO",
                        "email": "ceo@example.com",
                        "email_status": "verified",
                    },
                    {
                        "name": "No Contact Info",
                        "title": "CTO",
                        "email": None,
                        "linkedin_url": None,
                    },
                    {
                        "name": "Has LinkedIn",
                        "title": "Founder",
                        "email": None,
                        "linkedin_url": "https://linkedin.com/in/founder",
                    },
                ]
            },
        )

        contacts, status = await apollo_client.find_contacts("org_filter")

        assert len(contacts) == 2
        names = [c.full_name for c in contacts]
        assert "Has Email" in names
        assert "Has LinkedIn" in names
        assert "No Contact Info" not in names

    async def test_prioritizes_by_title_seniority(
        self, apollo_client, mock_http_client
    ):
        """Contacts are sorted by title seniority (CEO > CTO > VP)."""
        mock_http_client.post.return_value = _make_response(
            200,
            {
                "people": [
                    {
                        "name": "VP Person",
                        "title": "VP Engineering",
                        "email": "vp@example.com",
                        "email_status": "verified",
                    },
                    {
                        "name": "CEO Person",
                        "title": "CEO",
                        "email": "ceo@example.com",
                        "email_status": "verified",
                    },
                    {
                        "name": "CTO Person",
                        "title": "CTO",
                        "email": "cto@example.com",
                        "email_status": "verified",
                    },
                ]
            },
        )

        contacts, status = await apollo_client.find_contacts("org_priority")

        assert contacts[0].full_name == "CEO Person"
        assert contacts[1].full_name == "CTO Person"
        assert contacts[2].full_name == "VP Person"

    async def test_timeout_returns_pending_retry(
        self, apollo_client, mock_http_client
    ):
        """Returns PENDING_RETRY when all retries exhausted on timeout."""
        mock_http_client.post.side_effect = httpx.ReadTimeout("timeout")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            contacts, status = await apollo_client.find_contacts("org_slow")

        assert status == ContactSearchStatus.PENDING_RETRY
        assert contacts == []


# ---------------------------------------------------------------------------
# Intent Signal Tests
# ---------------------------------------------------------------------------


class TestGetIntentSignals:
    """Tests for ApolloClient.get_intent_signals()."""

    async def test_returns_matching_signals(self, apollo_client, mock_http_client):
        """Returns intent signals matching topic keywords."""
        mock_http_client.post.return_value = _make_response(
            200,
            {
                "intent_signals": [
                    {
                        "topic": "Cloud Migration Services",
                        "strength": "strong",
                        "detected_at": "2024-01-15T10:00:00Z",
                    },
                    {
                        "topic": "DevOps Consulting",
                        "strength": "moderate",
                        "detected_at": "2024-01-10T08:00:00Z",
                    },
                    {
                        "topic": "Unrelated Topic",
                        "strength": "weak",
                        "detected_at": "2024-01-05T06:00:00Z",
                    },
                ]
            },
        )

        signals = await apollo_client.get_intent_signals(
            "org_123", ["cloud", "devops"]
        )

        assert len(signals) == 2
        assert signals[0].topic == "Cloud Migration Services"
        assert signals[0].strength == SignalStrength.STRONG
        assert signals[1].topic == "DevOps Consulting"
        assert signals[1].strength == SignalStrength.MODERATE

    async def test_max_20_signals(self, apollo_client, mock_http_client):
        """Returns at most 20 signals."""
        raw_signals = [
            {
                "topic": f"Python topic {i}",
                "strength": "weak",
                "detected_at": "2024-01-01T00:00:00Z",
            }
            for i in range(30)
        ]
        mock_http_client.post.return_value = _make_response(
            200, {"intent_signals": raw_signals}
        )

        signals = await apollo_client.get_intent_signals("org_many", ["python"])

        assert len(signals) == 20

    async def test_filters_by_topic_keywords(self, apollo_client, mock_http_client):
        """Only returns signals matching provided keywords."""
        mock_http_client.post.return_value = _make_response(
            200,
            {
                "intent_signals": [
                    {
                        "topic": "Python Development",
                        "strength": "strong",
                        "detected_at": "2024-01-15T00:00:00Z",
                    },
                    {
                        "topic": "Marketing Automation",
                        "strength": "moderate",
                        "detected_at": "2024-01-10T00:00:00Z",
                    },
                ]
            },
        )

        signals = await apollo_client.get_intent_signals("org_filter", ["python"])

        assert len(signals) == 1
        assert signals[0].topic == "Python Development"

    async def test_timeout_returns_empty_list(self, apollo_client, mock_http_client):
        """Returns empty list when all retries exhausted."""
        mock_http_client.post.side_effect = httpx.ReadTimeout("timeout")

        with patch("asyncio.sleep", new_callable=AsyncMock):
            signals = await apollo_client.get_intent_signals(
                "org_slow", ["cloud"]
            )

        assert signals == []

    async def test_signal_strength_mapping(self, apollo_client, mock_http_client):
        """Maps various strength values to SignalStrength enum."""
        mock_http_client.post.return_value = _make_response(
            200,
            {
                "intent_signals": [
                    {
                        "topic": "Cloud high",
                        "strength": "high",
                        "detected_at": "2024-01-15T00:00:00Z",
                    },
                    {
                        "topic": "Cloud medium",
                        "strength": "medium",
                        "detected_at": "2024-01-14T00:00:00Z",
                    },
                    {
                        "topic": "Cloud low",
                        "strength": "low",
                        "detected_at": "2024-01-13T00:00:00Z",
                    },
                ]
            },
        )

        signals = await apollo_client.get_intent_signals("org_map", ["cloud"])

        assert signals[0].strength == SignalStrength.STRONG
        assert signals[1].strength == SignalStrength.MODERATE
        assert signals[2].strength == SignalStrength.WEAK


# ---------------------------------------------------------------------------
# Batch Enrichment Tests
# ---------------------------------------------------------------------------


class TestEnrichBatch:
    """Tests for ApolloClient.enrich_batch()."""

    async def test_small_batch_no_rate_limiting(self, apollo_client, mock_http_client):
        """Batches <= 20 don't trigger rate limiting."""
        mock_http_client.post.return_value = _make_response(
            200,
            {"organization": {"id": "org_1", "estimated_num_employees": 10}},
        )

        domains = [f"company{i}.com" for i in range(5)]
        results = await apollo_client.enrich_batch(domains)

        assert len(results) == 5
        assert all(r.status == EnrichmentStatus.COMPLETE for r in results)

    async def test_large_batch_applies_rate_limiting(
        self, apollo_client, mock_http_client
    ):
        """Batches > 20 trigger rate limiting logic."""
        mock_http_client.post.return_value = _make_response(
            200,
            {"organization": {"id": "org_1", "estimated_num_employees": 10}},
        )

        domains = [f"company{i}.com" for i in range(25)]

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            results = await apollo_client.enrich_batch(domains)

        assert len(results) == 25
        assert all(r.status == EnrichmentStatus.COMPLETE for r in results)


# ---------------------------------------------------------------------------
# Data Model Tests
# ---------------------------------------------------------------------------


class TestEnrichmentRecord:
    """Tests for EnrichmentRecord dataclass."""

    def test_is_stale_when_expired(self):
        """Record is stale when current time is past expires_at."""
        record = EnrichmentRecord(
            company_id="org_1",
            company_domain="old.com",
            status=EnrichmentStatus.COMPLETE,
            enriched_at=datetime.now(timezone.utc) - timedelta(days=31),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert record.is_stale is True

    def test_not_stale_when_fresh(self):
        """Record is not stale when within 30-day window."""
        record = EnrichmentRecord(
            company_id="org_2",
            company_domain="fresh.com",
            status=EnrichmentStatus.COMPLETE,
        )
        assert record.is_stale is False

    def test_needs_refresh_when_stale_and_complete(self):
        """needs_refresh is True only when stale AND status is COMPLETE."""
        stale_complete = EnrichmentRecord(
            company_id="org_3",
            company_domain="stale.com",
            status=EnrichmentStatus.COMPLETE,
            enriched_at=datetime.now(timezone.utc) - timedelta(days=31),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert stale_complete.needs_refresh is True

        stale_failed = EnrichmentRecord(
            company_id="org_4",
            company_domain="failed.com",
            status=EnrichmentStatus.ENRICHMENT_FAILED,
            enriched_at=datetime.now(timezone.utc) - timedelta(days=31),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        assert stale_failed.needs_refresh is False


class TestContact:
    """Tests for Contact dataclass."""

    def test_has_contact_method_with_email(self):
        """Contact with email has a valid contact method."""
        contact = Contact(
            full_name="Test User",
            job_title="CEO",
            email="test@example.com",
        )
        assert contact.has_contact_method is True

    def test_has_contact_method_with_linkedin(self):
        """Contact with LinkedIn has a valid contact method."""
        contact = Contact(
            full_name="Test User",
            job_title="CTO",
            linkedin_url="https://linkedin.com/in/test",
        )
        assert contact.has_contact_method is True

    def test_no_contact_method(self):
        """Contact without email or LinkedIn lacks a contact method."""
        contact = Contact(
            full_name="No Contact",
            job_title="CEO",
        )
        assert contact.has_contact_method is False


class TestIntentSignal:
    """Tests for IntentSignal dataclass."""

    def test_is_stale_when_old(self):
        """Signal older than 30 days is stale."""
        signal = IntentSignal(
            topic="Old Topic",
            strength=SignalStrength.STRONG,
            detected_at=datetime.now(timezone.utc) - timedelta(days=31),
        )
        assert signal.is_stale is True

    def test_not_stale_when_recent(self):
        """Signal within 30 days is not stale."""
        signal = IntentSignal(
            topic="Recent Topic",
            strength=SignalStrength.MODERATE,
            detected_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        assert signal.is_stale is False
