"""Apollo.io integration client for B2B enrichment, contact discovery, and intent signals.

Requirements 1.1-1.7: Account enrichment with retry logic and rate limiting.
Requirements 2.1-2.6: Contact discovery with title prioritization and broadened search.
Requirements 3.1-3.6: Intent signal querying with topic keyword matching.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

import httpx

from app.core.errors import APITimeoutError, RateLimitError

logger = logging.getLogger(__name__)


# --- Enums ---


class EnrichmentStatus(str, Enum):
    """Status of a company enrichment record."""

    COMPLETE = "complete"
    PENDING_RETRY = "pending_retry"
    ENRICHMENT_FAILED = "enrichment_failed"
    NOT_FOUND = "not_found"


class ContactSearchStatus(str, Enum):
    """Status of a contact search operation."""

    COMPLETE = "complete"
    BROADENED_SEARCH = "broadened_search"
    CONTACTS_UNAVAILABLE = "contacts_unavailable"
    PENDING_RETRY = "pending_retry"


class EmailVerificationStatus(str, Enum):
    """Email verification status as returned by Apollo.io."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    CATCH_ALL = "catch_all"


class SignalStrength(str, Enum):
    """Strength of an intent signal."""

    STRONG = "strong"
    MODERATE = "moderate"
    WEAK = "weak"


# --- Data Models ---


@dataclass
class EnrichmentRecord:
    """Firmographic and technographic enrichment data for a prospect company.

    Requirement 1.2: Contains company size, revenue range, industry,
    tech stack, funding stage, and HQ location.
    Requirement 1.7: Records older than 30 days are flagged for refresh.
    """

    company_id: str
    company_domain: str
    employee_count: int | None = None
    revenue_range: str | None = None
    industry: str | None = None
    tech_stack: list[str] = field(default_factory=list)
    funding_stage: str | None = None
    headquarters_city: str | None = None
    headquarters_country: str | None = None
    status: EnrichmentStatus = EnrichmentStatus.COMPLETE
    retry_count: int = 0
    enriched_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc) + timedelta(days=30)
    )

    @property
    def is_stale(self) -> bool:
        """Check if the record is older than 30 days and needs refresh."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def needs_refresh(self) -> bool:
        """Requirement 1.7: Flag records > 30 days old for refresh."""
        return self.is_stale and self.status == EnrichmentStatus.COMPLETE


@dataclass
class Contact:
    """A decision-maker contact at a prospect company.

    Requirement 2.2: Must have at least email or LinkedIn URL.
    Each contact has full name and job title as required fields.
    """

    full_name: str
    job_title: str
    email: str | None = None
    linkedin_url: str | None = None
    phone: str | None = None
    email_verification: EmailVerificationStatus | None = None
    seniority_level: str | None = None  # c_suite, director, manager, other

    @property
    def has_contact_method(self) -> bool:
        """Requirement 2.2: Contact must have email OR LinkedIn URL."""
        return bool(self.email) or bool(self.linkedin_url)


@dataclass
class IntentSignal:
    """An intent signal indicating active buying interest.

    Requirement 3.2: Each signal has topic, strength, and detection date.
    """

    topic: str
    strength: SignalStrength
    detected_at: datetime

    @property
    def is_stale(self) -> bool:
        """Requirement 3.5: Signals older than 30 days need refresh."""
        age = datetime.now(timezone.utc) - self.detected_at
        return age > timedelta(days=30)


# --- Client ---


class ApolloClient:
    """Integration layer for Apollo.io API.

    Handles enrichment, contact discovery, and intent signal queries
    with timeout, retry, and rate limiting logic.
    """

    BASE_URL = "https://api.apollo.io/v1"
    TIMEOUT = 15.0  # seconds (Requirement 1.3)
    MAX_RETRIES = 3  # (Requirement 1.3)
    RETRY_DELAY = 300  # 5 minutes (Requirement 1.3)
    RATE_LIMIT = 5  # requests per second for batch operations (Requirement 1.6)
    BATCH_THRESHOLD = 20  # Rate limiting applies when batch > 20 (Requirement 1.6)

    DECISION_MAKER_TITLES = [
        "CEO",
        "CTO",
        "VP Engineering",
        "Founder",
        "Head of Delivery",
    ]
    BROADENED_TITLES = [
        "Director of Engineering",
        "Director of Technology",
        "Director of Operations",
        "Director of Sales",
        "Director of Delivery",
    ]

    # Priority order for sorting contacts by seniority
    _TITLE_PRIORITY = {
        "CEO": 1,
        "Founder": 2,
        "CTO": 3,
        "VP Engineering": 4,
        "Head of Delivery": 5,
        "Director of Engineering": 6,
        "Director of Technology": 7,
        "Director of Operations": 8,
        "Director of Sales": 9,
        "Director of Delivery": 10,
    }

    def __init__(self, api_key: str, http_client: httpx.AsyncClient | None = None):
        """Initialize the Apollo client.

        Args:
            api_key: Apollo.io API key for authentication.
            http_client: Optional httpx.AsyncClient for dependency injection/testing.
        """
        self._api_key = api_key
        self._client = http_client or httpx.AsyncClient(timeout=self.TIMEOUT)
        self._batch_timestamps: list[float] = []

    @property
    def headers(self) -> dict[str, str]:
        """Standard headers for Apollo.io API requests."""
        return {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self._api_key,
        }

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    # --- Enrichment ---

    async def enrich_company(self, company_domain: str) -> EnrichmentRecord:
        """Enrich a company via Apollo.io.

        Requirement 1.1: Request enrichment within 30 seconds of discovery.
        Requirement 1.3: 15s timeout, 3 retries with 5-min delay.
        Requirement 1.4: Mark as enrichment_failed after all retries exhausted.
        Requirement 1.5: Mark as not_found if no matching company.

        Args:
            company_domain: The company's domain name for lookup.

        Returns:
            EnrichmentRecord with status reflecting the outcome.
        """
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self._client.post(
                    f"{self.BASE_URL}/organizations/enrich",
                    headers=self.headers,
                    json={"domain": company_domain},
                    timeout=self.TIMEOUT,
                )

                if response.status_code == 200:
                    data = response.json()
                    organization = data.get("organization")

                    if not organization:
                        # Requirement 1.5: No matching company
                        logger.info(
                            "Apollo.io returned no matching company for domain: %s",
                            company_domain,
                        )
                        return EnrichmentRecord(
                            company_id="",
                            company_domain=company_domain,
                            status=EnrichmentStatus.NOT_FOUND,
                        )

                    return self._parse_enrichment(organization, company_domain)

                if response.status_code == 404:
                    # Requirement 1.5: Not found
                    logger.info(
                        "Apollo.io company not found for domain: %s", company_domain
                    )
                    return EnrichmentRecord(
                        company_id="",
                        company_domain=company_domain,
                        status=EnrichmentStatus.NOT_FOUND,
                    )

                if response.status_code == 429:
                    raise RateLimitError(
                        "Apollo.io rate limit exceeded",
                        service="apollo",
                        entity_id=company_domain,
                        retry_after_seconds=self.RETRY_DELAY,
                    )

                # Other error status codes
                last_error = Exception(
                    f"Apollo API returned status {response.status_code}: "
                    f"{response.text}"
                )

            except httpx.TimeoutException as e:
                last_error = APITimeoutError(
                    f"Apollo.io enrichment timed out for {company_domain}",
                    service="apollo",
                    entity_id=company_domain,
                    timeout_seconds=self.TIMEOUT,
                )
                logger.warning(
                    "Apollo.io timeout on attempt %d/%d for %s: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    company_domain,
                    str(e),
                )

            except httpx.HTTPError as e:
                last_error = e
                logger.warning(
                    "Apollo.io HTTP error on attempt %d/%d for %s: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    company_domain,
                    str(e),
                )

            # Requirement 1.3: Schedule retry with 5-min delay
            if attempt < self.MAX_RETRIES - 1:
                # Mark as pending_retry during wait
                logger.info(
                    "Scheduling retry %d/%d for %s in %d seconds",
                    attempt + 2,
                    self.MAX_RETRIES,
                    company_domain,
                    self.RETRY_DELAY,
                )
                await asyncio.sleep(self.RETRY_DELAY)

        # Requirement 1.4: All retries exhausted
        logger.error(
            "All %d retry attempts exhausted for %s. Last error: %s",
            self.MAX_RETRIES,
            company_domain,
            str(last_error),
        )
        return EnrichmentRecord(
            company_id="",
            company_domain=company_domain,
            status=EnrichmentStatus.ENRICHMENT_FAILED,
            retry_count=self.MAX_RETRIES,
        )

    def _parse_enrichment(
        self, organization: dict, company_domain: str
    ) -> EnrichmentRecord:
        """Parse Apollo.io organization response into an EnrichmentRecord."""
        now = datetime.now(timezone.utc)
        return EnrichmentRecord(
            company_id=organization.get("id", ""),
            company_domain=company_domain,
            employee_count=organization.get("estimated_num_employees"),
            revenue_range=organization.get("annual_revenue_printed"),
            industry=organization.get("industry"),
            tech_stack=organization.get("technology_names", []) or [],
            funding_stage=organization.get("latest_funding_stage"),
            headquarters_city=organization.get("city"),
            headquarters_country=organization.get("country"),
            status=EnrichmentStatus.COMPLETE,
            enriched_at=now,
            expires_at=now + timedelta(days=30),
        )

    # --- Contact Discovery ---

    async def find_contacts(
        self, company_id: str, max_contacts: int = 5
    ) -> tuple[list[Contact], ContactSearchStatus]:
        """Find decision-maker contacts at a company.

        Requirement 2.1: Search for configured decision-maker titles.
        Requirement 2.2: Up to 5 contacts, prioritized by seniority, each with email or LinkedIn.
        Requirement 2.3: Broaden to director-level if no decision-makers found.
        Requirement 2.4: Mark as contacts_unavailable if none found after broadening.
        Requirement 2.6: Retry logic on error/timeout.

        Args:
            company_id: The Apollo.io company ID.
            max_contacts: Maximum contacts to return (default 5).

        Returns:
            Tuple of (contacts list, search status).
        """
        # First try: decision-maker titles
        contacts, status = await self._search_contacts(
            company_id, self.DECISION_MAKER_TITLES, max_contacts
        )

        if contacts:
            return contacts, ContactSearchStatus.COMPLETE

        if status == ContactSearchStatus.PENDING_RETRY:
            return [], ContactSearchStatus.PENDING_RETRY

        # Requirement 2.3: Broaden search to director-level titles
        logger.info(
            "No decision-maker contacts found for company %s, broadening search",
            company_id,
        )
        contacts, status = await self._search_contacts(
            company_id, self.BROADENED_TITLES, max_contacts
        )

        if contacts:
            return contacts, ContactSearchStatus.BROADENED_SEARCH

        if status == ContactSearchStatus.PENDING_RETRY:
            return [], ContactSearchStatus.PENDING_RETRY

        # Requirement 2.4: No contacts after broadening
        logger.warning(
            "No contacts found for company %s after broadened search", company_id
        )
        return [], ContactSearchStatus.CONTACTS_UNAVAILABLE

    async def _search_contacts(
        self,
        company_id: str,
        titles: list[str],
        max_contacts: int,
    ) -> tuple[list[Contact], ContactSearchStatus]:
        """Search for contacts with given titles, with retry logic.

        Requirement 2.6: 15s timeout, 3 retries, 5-min delay.
        """
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self._client.post(
                    f"{self.BASE_URL}/mixed_people/search",
                    headers=self.headers,
                    json={
                        "organization_ids": [company_id],
                        "person_titles": titles,
                        "per_page": max_contacts * 2,  # Fetch extra to filter
                    },
                    timeout=self.TIMEOUT,
                )

                if response.status_code == 200:
                    data = response.json()
                    people = data.get("people", [])
                    contacts = self._parse_and_filter_contacts(people, max_contacts)
                    return contacts, ContactSearchStatus.COMPLETE

                if response.status_code == 429:
                    raise RateLimitError(
                        "Apollo.io rate limit exceeded during contact search",
                        service="apollo",
                        entity_id=company_id,
                        retry_after_seconds=self.RETRY_DELAY,
                    )

                last_error = Exception(
                    f"Apollo API returned status {response.status_code}"
                )

            except httpx.TimeoutException as e:
                last_error = APITimeoutError(
                    f"Apollo.io contact search timed out for company {company_id}",
                    service="apollo",
                    entity_id=company_id,
                    timeout_seconds=self.TIMEOUT,
                )
                logger.warning(
                    "Contact search timeout attempt %d/%d for %s: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    company_id,
                    str(e),
                )

            except httpx.HTTPError as e:
                last_error = e
                logger.warning(
                    "Contact search HTTP error attempt %d/%d for %s: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    company_id,
                    str(e),
                )

            if attempt < self.MAX_RETRIES - 1:
                await asyncio.sleep(self.RETRY_DELAY)

        # All retries exhausted
        logger.error(
            "Contact search retries exhausted for company %s: %s",
            company_id,
            str(last_error),
        )
        return [], ContactSearchStatus.PENDING_RETRY

    def _parse_and_filter_contacts(
        self, people: list[dict], max_contacts: int
    ) -> list[Contact]:
        """Parse and filter contacts from Apollo.io response.

        Requirement 2.2: Prioritize by title seniority and email verification status.
        Only include contacts that have at least an email or LinkedIn URL.
        """
        contacts: list[Contact] = []

        for person in people:
            contact = self._parse_contact(person)
            if contact.has_contact_method:
                contacts.append(contact)

        # Sort by seniority priority (lower number = higher priority)
        contacts.sort(key=lambda c: self._get_title_priority(c.job_title))

        # Secondary sort: verified emails first
        contacts.sort(
            key=lambda c: (
                self._get_title_priority(c.job_title),
                0 if c.email_verification == EmailVerificationStatus.VERIFIED else 1,
            )
        )

        return contacts[:max_contacts]

    def _parse_contact(self, person: dict) -> Contact:
        """Parse a single contact from Apollo.io person data."""
        email = person.get("email")
        linkedin_url = person.get("linkedin_url")

        # Requirement 2.5: Map verification status
        email_status_raw = person.get("email_status")
        email_verification = None
        if email and email_status_raw:
            verification_map = {
                "verified": EmailVerificationStatus.VERIFIED,
                "valid": EmailVerificationStatus.VERIFIED,
                "unverified": EmailVerificationStatus.UNVERIFIED,
                "guessed": EmailVerificationStatus.UNVERIFIED,
                "catch_all": EmailVerificationStatus.CATCH_ALL,
                "catch-all": EmailVerificationStatus.CATCH_ALL,
            }
            email_verification = verification_map.get(
                email_status_raw.lower(), EmailVerificationStatus.UNVERIFIED
            )

        # Determine seniority level
        title = person.get("title", "")
        seniority = self._classify_seniority(title)

        return Contact(
            full_name=person.get("name", ""),
            job_title=title,
            email=email,
            linkedin_url=linkedin_url,
            phone=person.get("phone_number"),
            email_verification=email_verification,
            seniority_level=seniority,
        )

    def _get_title_priority(self, title: str) -> int:
        """Get priority score for a job title. Lower = higher priority."""
        # Check exact match first
        if title in self._TITLE_PRIORITY:
            return self._TITLE_PRIORITY[title]

        # Check partial match (case-insensitive)
        title_lower = title.lower()
        for known_title, priority in self._TITLE_PRIORITY.items():
            if known_title.lower() in title_lower:
                return priority

        return 99  # Unknown titles get lowest priority

    @staticmethod
    def _classify_seniority(title: str) -> str:
        """Classify a job title into a seniority level."""
        title_lower = title.lower()

        c_suite_indicators = ["ceo", "cto", "cfo", "coo", "chief", "founder", "co-founder"]
        director_indicators = ["director", "vp", "vice president", "head of"]
        manager_indicators = ["manager", "lead", "senior"]

        if any(ind in title_lower for ind in c_suite_indicators):
            return "c_suite"
        if any(ind in title_lower for ind in director_indicators):
            return "director"
        if any(ind in title_lower for ind in manager_indicators):
            return "manager"
        return "other"

    # --- Intent Signals ---

    async def get_intent_signals(
        self, company_id: str, topic_keywords: list[str], max_signals: int = 20
    ) -> list[IntentSignal]:
        """Query intent signals for configured topic keywords.

        Requirement 3.1: Query matching configured topic keywords, up to 20 per company.
        Requirement 3.6: 15s timeout, retry with 5-min delay on error.

        Args:
            company_id: The Apollo.io company ID.
            topic_keywords: List of topic keywords to match.
            max_signals: Maximum signals to return (default 20).

        Returns:
            List of IntentSignal objects.
        """
        last_error: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = await self._client.post(
                    f"{self.BASE_URL}/organizations/{company_id}/intent_signals",
                    headers=self.headers,
                    json={"topics": topic_keywords},
                    timeout=self.TIMEOUT,
                )

                if response.status_code == 200:
                    data = response.json()
                    signals = self._parse_intent_signals(
                        data.get("intent_signals", []),
                        topic_keywords,
                        max_signals,
                    )
                    return signals

                if response.status_code == 429:
                    raise RateLimitError(
                        "Apollo.io rate limit exceeded during intent signal query",
                        service="apollo",
                        entity_id=company_id,
                        retry_after_seconds=self.RETRY_DELAY,
                    )

                last_error = Exception(
                    f"Apollo API returned status {response.status_code}"
                )

            except httpx.TimeoutException as e:
                last_error = APITimeoutError(
                    f"Apollo.io intent signal query timed out for {company_id}",
                    service="apollo",
                    entity_id=company_id,
                    timeout_seconds=self.TIMEOUT,
                )
                logger.warning(
                    "Intent signal timeout attempt %d/%d for %s: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    company_id,
                    str(e),
                )

            except httpx.HTTPError as e:
                last_error = e
                logger.warning(
                    "Intent signal HTTP error attempt %d/%d for %s: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    company_id,
                    str(e),
                )

            if attempt < self.MAX_RETRIES - 1:
                await asyncio.sleep(self.RETRY_DELAY)

        # All retries exhausted - return empty (caller handles pending_retry status)
        logger.error(
            "Intent signal retries exhausted for company %s: %s",
            company_id,
            str(last_error),
        )
        return []

    def _parse_intent_signals(
        self,
        raw_signals: list[dict],
        topic_keywords: list[str],
        max_signals: int,
    ) -> list[IntentSignal]:
        """Parse intent signals, filtering by topic keywords.

        Requirement 3.1: Only include signals matching configured keywords.
        """
        signals: list[IntentSignal] = []
        keywords_lower = [kw.lower() for kw in topic_keywords]

        for raw in raw_signals:
            topic = raw.get("topic", "")
            # Match if topic contains any of the configured keywords
            if not any(kw in topic.lower() for kw in keywords_lower):
                continue

            strength_raw = raw.get("strength", "weak").lower()
            strength_map = {
                "strong": SignalStrength.STRONG,
                "high": SignalStrength.STRONG,
                "moderate": SignalStrength.MODERATE,
                "medium": SignalStrength.MODERATE,
                "weak": SignalStrength.WEAK,
                "low": SignalStrength.WEAK,
            }
            strength = strength_map.get(strength_raw, SignalStrength.WEAK)

            detected_at_raw = raw.get("detected_at")
            if detected_at_raw:
                try:
                    detected_at = datetime.fromisoformat(detected_at_raw)
                    if detected_at.tzinfo is None:
                        detected_at = detected_at.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    detected_at = datetime.now(timezone.utc)
            else:
                detected_at = datetime.now(timezone.utc)

            signals.append(
                IntentSignal(
                    topic=topic,
                    strength=strength,
                    detected_at=detected_at,
                )
            )

            if len(signals) >= max_signals:
                break

        return signals

    # --- Batch Enrichment ---

    async def enrich_batch(
        self, company_domains: list[str]
    ) -> list[EnrichmentRecord]:
        """Batch enrichment with rate limiting for large batches.

        Requirement 1.6: Max 5 requests per second when batch > 20 companies.

        Args:
            company_domains: List of company domains to enrich.

        Returns:
            List of EnrichmentRecord results.
        """
        results: list[EnrichmentRecord] = []
        apply_rate_limit = len(company_domains) > self.BATCH_THRESHOLD

        for domain in company_domains:
            if apply_rate_limit:
                await self._enforce_rate_limit()

            record = await self.enrich_company(domain)
            results.append(record)

        return results

    async def _enforce_rate_limit(self) -> None:
        """Enforce rate limiting: max 5 requests per second.

        Requirement 1.6: Throttle to maximum 5 requests/sec for batches > 20.
        Uses a sliding window approach to track request timestamps.
        """
        now = time.monotonic()

        # Remove timestamps older than 1 second
        self._batch_timestamps = [
            ts for ts in self._batch_timestamps if now - ts < 1.0
        ]

        # If at capacity, wait until the oldest request falls outside the window
        if len(self._batch_timestamps) >= self.RATE_LIMIT:
            oldest = self._batch_timestamps[0]
            sleep_time = 1.0 - (now - oldest)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            # Clean up again after sleeping
            now = time.monotonic()
            self._batch_timestamps = [
                ts for ts in self._batch_timestamps if now - ts < 1.0
            ]

        self._batch_timestamps.append(time.monotonic())
