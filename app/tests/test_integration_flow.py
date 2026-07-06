"""End-to-end integration tests for discovery → enrichment → scoring → pipeline → outreach flow.

Tests the complete flow using mocked external dependencies (Apollo, Lemlist APIs)
while wiring real service instances together.

Requirements: 1.1, 4.1, 5.4, 7.2, 10.2
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.analytics_service import (
    AnalyticsService,
    ChannelData,
    FunnelStage,
    PipelineRecord,
    StageTransition,
)
from app.core.discovery_pipeline import (
    DiscoveryConfig,
    DiscoveryPipeline,
    DiscoveryResult,
    RawProspect,
    SourceClient,
    SourceType,
)
from app.core.pipeline_manager import (
    PipelineManager,
    PipelineRecordData,
    PipelineTransitionResult,
    RequiresActionType,
)
from app.core.scoring_engine import ScoreResult, ScoreTier, ScoringEngine, ScoringWeights
from app.integrations.apollo_client import (
    ApolloClient,
    Contact,
    EmailVerificationStatus,
    EnrichmentRecord,
    EnrichmentStatus,
    IntentSignal,
    SignalStrength,
)
from app.integrations.lemlist_engine import (
    Channel,
    LemlistEngine,
    ProspectEnrollment,
    ProspectSequenceStatus,
    ResponseEvent,
    ResponseEventType,
    Sequence,
    SequenceStep,
    SequenceSyncStatus,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def scoring_engine():
    """Create a scoring engine with default weights."""
    return ScoringEngine(ScoringWeights())


@pytest.fixture
def mock_apollo_enrichment_response():
    """Mock Apollo enrichment API response."""
    return {
        "organization": {
            "name": "TechCorp Inc",
            "primary_domain": "techcorp.io",
            "estimated_num_employees": 250,
            "annual_revenue_printed": "$10M-$50M",
            "industry": "Software Development",
            "technology_names": ["Python", "React", "AWS", "PostgreSQL"],
            "latest_funding_stage": "Series B",
            "city": "London",
            "country": "United Kingdom",
        }
    }


@pytest.fixture
def mock_apollo_contacts_response():
    """Mock Apollo contacts API response."""
    return {
        "people": [
            {
                "first_name": "Jane",
                "last_name": "Smith",
                "title": "CTO",
                "email": "jane@techcorp.io",
                "email_status": "verified",
                "linkedin_url": "https://linkedin.com/in/janesmith",
                "phone_numbers": [{"number": "+44123456789"}],
            },
            {
                "first_name": "Bob",
                "last_name": "Johnson",
                "title": "VP Engineering",
                "email": "bob@techcorp.io",
                "email_status": "unverified",
                "linkedin_url": "https://linkedin.com/in/bobjohnson",
                "phone_numbers": [],
            },
        ]
    }


@pytest.fixture
def mock_apollo_intent_response():
    """Mock Apollo intent signals API response."""
    return {
        "intent_signals": [
            {
                "topic": "cloud migration",
                "strength": "strong",
                "detected_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "topic": "digital transformation",
                "strength": "moderate",
                "detected_at": (
                    datetime.now(timezone.utc) - timedelta(days=5)
                ).isoformat(),
            },
        ]
    }


@pytest.fixture
def mock_lemlist_campaign_response():
    """Mock Lemlist campaign creation API response."""
    return {"_id": "camp_12345", "name": "Test Outreach"}


@pytest.fixture
def mock_lemlist_activities_response():
    """Mock Lemlist activities/poll response."""
    return [
        {
            "type": "emailsReplied",
            "leadId": "prospect-001",
            "campaignId": "seq-001",
            "stepOrder": 1,
            "text": "Thanks for reaching out! Let's schedule a call.",
        }
    ]


class FakePipelineRepository:
    """In-memory pipeline repository for integration testing."""

    def __init__(self):
        self._records: dict[str, PipelineRecordData] = {}

    async def get_pipeline_record(self, record_id: str):
        return self._records.get(record_id)

    async def update_pipeline_record(
        self, record_id: str, new_status: str, previous_status: str, is_terminal: bool
    ):
        record = self._records.get(record_id)
        if record:
            record.previous_status = previous_status
            record.current_status = new_status
            record.is_terminal = is_terminal
            record.updated_at = datetime.now(timezone.utc)

    async def get_stale_records(self, days_threshold: int):
        now = datetime.now(timezone.utc)
        return [
            r for r in self._records.values()
            if not r.is_terminal
            and (now - r.updated_at).days >= days_threshold
        ]

    async def get_failed_sequence_records(self):
        return []

    async def get_enrichment_error_records(self):
        return []

    def add_record(self, record: PipelineRecordData):
        self._records[record.id] = record


class FakeLemlistRepository:
    """In-memory Lemlist repository for integration testing."""

    def __init__(self):
        self._sequences: dict[str, Sequence] = {}
        self._enrollments: dict[str, ProspectEnrollment] = {}

    async def get_sequence(self, sequence_id: str):
        return self._sequences.get(sequence_id)

    async def save_sequence(self, sequence: Sequence):
        self._sequences[sequence.id] = sequence

    async def get_enrollment(self, prospect_id: str, sequence_id: str):
        key = f"{prospect_id}:{sequence_id}"
        return self._enrollments.get(key)

    async def save_enrollment(self, enrollment: ProspectEnrollment):
        key = f"{enrollment.prospect_id}:{enrollment.sequence_id}"
        self._enrollments[key] = enrollment

    async def get_active_enrollments(self, sequence_id: str):
        return [
            e for e in self._enrollments.values()
            if e.sequence_id == sequence_id
            and e.status == ProspectSequenceStatus.ACTIVE
        ]

    async def get_prospects_by_filter(self, enrollment_filter):
        return list({e.prospect_id for e in self._enrollments.values()})

    async def get_touchpoints_for_enrollment(self, prospect_id, sequence_id):
        return []

    async def save_touchpoint(self, touchpoint):
        pass

    async def update_touchpoint_status(self, touchpoint_id, status):
        pass

    async def get_pending_touchpoints(self, prospect_id, sequence_id):
        return []


class FakeEventPublisher:
    """In-memory event publisher capturing broadcasts for testing."""

    def __init__(self):
        self.published: list[tuple[str, str]] = []

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1


class FakeSourceClient:
    """Fake discovery source client returning configured prospects."""

    def __init__(self, prospects: list[RawProspect]):
        self._prospects = prospects

    async def discover(self, beneficiary_id: str, **kwargs):
        return self._prospects


# ─── Test: Discovery Pipeline finds and deduplicates ──────────────────────────


class TestDiscoveryToScoringFlow:
    """Integration tests for discovery → deduplication → scoring flow."""

    async def test_discovery_finds_prospects_and_deduplicates(
        self, scoring_engine
    ):
        """Discovery pipeline finds prospects from a source, deduplicates
        matching records, and awards multi-source bonus."""
        now = datetime.now(timezone.utc)

        # Existing prospects in the system
        existing_prospects = [
            {
                "company_domain": "techcorp.io",
                "normalized_name": "techcorp",
                "company_name": "TechCorp Inc",
                "source_count": 1,
                "sources": ["adzuna"],
                "enrichment_data": {"industry": "Software"},
                "discovered_at": (now - timedelta(days=7)).isoformat(),
            }
        ]

        # New prospects discovered from Apollo source
        new_raw_prospects = [
            RawProspect(
                company_name="TechCorp Inc",
                company_domain="techcorp.io",
                source_type=SourceType.APOLLO,
                beneficiary_id="consultant",
                opportunity_type_id="cold_outreach_consultant",
                enrichment_data={"tech_stack": ["Python", "React"]},
                discovered_at=now,
            ),
            RawProspect(
                company_name="NewStartup Ltd",
                company_domain="newstartup.com",
                source_type=SourceType.APOLLO,
                beneficiary_id="consultant",
                opportunity_type_id="cold_outreach_consultant",
                enrichment_data={"industry": "FinTech"},
                discovered_at=now,
            ),
        ]

        fake_source = FakeSourceClient(new_raw_prospects)
        pipeline = DiscoveryPipeline(
            scoring_engine=scoring_engine,
            source_clients={SourceType.APOLLO: fake_source},
            existing_prospects=existing_prospects,
        )

        # Run deduplication
        results = await pipeline.deduplicate_and_merge(new_raw_prospects)

        # Should have 2 results: one merged, one new
        assert len(results) == 2

        # First result: TechCorp merged (matched by domain)
        merged = next(r for r in results if r.get("company_domain") == "techcorp.io")
        assert merged["source_count"] == 2
        assert "apollo" in merged["sources"]
        assert "adzuna" in merged["sources"]
        assert merged["is_new"] is False

        # Second result: NewStartup is new
        new = next(r for r in results if r.get("company_domain") == "newstartup.com")
        assert new["source_count"] == 1
        assert new["is_new"] is True

    async def test_multi_source_bonus_applied_in_scoring(self, scoring_engine):
        """Multi-source bonus is correctly applied to scores based on source count."""
        # Score with 1 source: no bonus
        result_1 = scoring_engine.compute_score(
            firmographic=60, technographic=70, intent=50,
            llm_relevance=80, historical=40, source_count=1
        )

        # Score with 3 sources: +20 bonus
        result_3 = scoring_engine.compute_score(
            firmographic=60, technographic=70, intent=50,
            llm_relevance=80, historical=40, source_count=3
        )

        assert result_3.multi_source_bonus == 20
        assert result_1.multi_source_bonus == 0
        # The 3-source score should be higher due to bonus
        assert result_3.total_score >= result_1.total_score

    async def test_score_threshold_filtering(self, scoring_engine):
        """Only prospects above the score threshold are surfaced."""
        pipeline = DiscoveryPipeline(scoring_engine=scoring_engine)

        prospects = [
            {"company_name": "HighScore Corp", "score": 80},
            {"company_name": "MidScore LLC", "score": 50},
            {"company_name": "LowScore Inc", "score": 10},
        ]

        filtered = pipeline.apply_score_threshold(prospects, threshold=25)
        assert len(filtered) == 2
        assert all(p["score"] >= 25 for p in filtered)

        # With default threshold
        filtered_default = pipeline.apply_score_threshold(prospects)
        assert len(filtered_default) == 2


    async def test_full_discovery_run_with_source_client(self, scoring_engine):
        """Run a full discovery cycle: discover → deduplicate → score → filter."""
        now = datetime.now(timezone.utc)
        raw_prospects = [
            RawProspect(
                company_name="Alpha Corp",
                company_domain="alpha.com",
                source_type=SourceType.APOLLO,
                beneficiary_id="consultant",
                opportunity_type_id="cold_outreach_consultant",
                enrichment_data={"industry": "Consulting"},
                discovered_at=now,
            ),
        ]

        fake_source = FakeSourceClient(raw_prospects)
        pipeline = DiscoveryPipeline(
            scoring_engine=scoring_engine,
            source_clients={SourceType.APOLLO: fake_source},
            existing_prospects=[],
        )

        result = await pipeline.run_discovery(
            source_type=SourceType.APOLLO,
            beneficiary_id="consultant",
        )

        assert isinstance(result, DiscoveryResult)
        assert result.source_type == SourceType.APOLLO
        assert result.prospects_found >= 0
        assert result.duration_seconds >= 0


# ─── Test: Enrichment through Apollo Client (mocked) ─────────────────────────


class TestEnrichmentFlow:
    """Integration tests for Apollo enrichment → storage."""

    async def test_apollo_enrichment_stores_data(
        self, mock_apollo_enrichment_response
    ):
        """Apollo client processes enrichment response and produces an EnrichmentRecord."""
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=mock_apollo_enrichment_response
            )
        )
        async with httpx.AsyncClient(transport=mock_transport) as client:
            apollo = ApolloClient(api_key="test-key", http_client=client)
            record = await apollo.enrich_company("techcorp.io")

        assert isinstance(record, EnrichmentRecord)
        assert record.status == EnrichmentStatus.COMPLETE
        assert record.employee_count == 250
        assert record.industry == "Software Development"
        assert "Python" in record.tech_stack
        assert "React" in record.tech_stack
        assert record.funding_stage == "Series B"
        assert record.headquarters_city == "London"
        assert record.headquarters_country == "United Kingdom"


    async def test_apollo_contact_discovery(
        self, mock_apollo_contacts_response
    ):
        """Apollo client finds contacts matching decision-maker titles."""
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=mock_apollo_contacts_response
            )
        )
        async with httpx.AsyncClient(transport=mock_transport) as client:
            apollo = ApolloClient(api_key="test-key", http_client=client)
            contacts, status = await apollo.find_contacts("company-123")

        assert len(contacts) <= 5
        assert all(isinstance(c, Contact) for c in contacts)
        # CTO should be prioritized over VP Engineering
        assert contacts[0].job_title == "CTO"
        assert contacts[0].email == "jane@techcorp.io"
        assert contacts[0].email_verification == EmailVerificationStatus.VERIFIED

    async def test_apollo_intent_signals(
        self, mock_apollo_intent_response
    ):
        """Apollo client retrieves and parses intent signals."""
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=mock_apollo_intent_response
            )
        )
        async with httpx.AsyncClient(transport=mock_transport) as client:
            apollo = ApolloClient(api_key="test-key", http_client=client)
            signals = await apollo.get_intent_signals(
                "company-123", topic_keywords=["cloud migration"]
            )

        assert len(signals) <= 20
        assert all(isinstance(s, IntentSignal) for s in signals)
        strong_signals = [s for s in signals if s.strength == SignalStrength.STRONG]
        assert len(strong_signals) >= 1


# ─── Test: Scoring Engine with enrichment data + multi-source bonus ───────────


class TestScoringWithEnrichment:
    """Integration tests for scoring engine using enrichment data."""

    async def test_scoring_with_complete_enrichment(self, scoring_engine):
        """Score computation with all factors available produces A/B tier result."""
        result = scoring_engine.compute_score(
            firmographic=85,
            technographic=90,
            intent=70,
            llm_relevance=80,
            historical=60,
            source_count=2,
            has_strong_intent=True,
        )

        assert isinstance(result, ScoreResult)
        assert 0 <= result.total_score <= 100
        assert result.is_partial is False
        assert result.multi_source_bonus == 10
        assert len(result.missing_factors) == 0
        # With high sub-scores + intent boost + multi-source, expect A tier
        assert result.tier == ScoreTier.A


    async def test_scoring_with_partial_enrichment(self, scoring_engine):
        """Score computation redistributes weights when factors are missing."""
        result = scoring_engine.compute_score(
            firmographic=70,
            technographic=None,
            intent=None,
            llm_relevance=60,
            historical=None,
            source_count=1,
            has_strong_intent=False,
        )

        assert isinstance(result, ScoreResult)
        assert result.is_partial is True
        assert "technographic" in result.missing_factors
        assert "intent" in result.missing_factors
        assert "historical" in result.missing_factors
        assert 0 <= result.total_score <= 100

    async def test_scoring_intent_boost_applied_once(self, scoring_engine):
        """Strong intent signal adds exactly 15 points regardless of count."""
        base = scoring_engine.compute_score(
            firmographic=50, technographic=50, intent=50,
            llm_relevance=50, historical=50,
            source_count=1, has_strong_intent=False,
        )
        boosted = scoring_engine.compute_score(
            firmographic=50, technographic=50, intent=50,
            llm_relevance=50, historical=50,
            source_count=1, has_strong_intent=True,
        )

        assert boosted.total_score == min(base.total_score + 15, 100)


# ─── Test: Pipeline Manager creates records and handles transitions ───────────


class TestPipelineTransitions:
    """Integration tests for pipeline state transitions."""

    async def test_pipeline_reply_advances_status(self):
        """Genuine reply advances pipeline from Sent to Replied."""
        repo = FakePipelineRepository()
        publisher = FakeEventPublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        record = PipelineRecordData(
            id="rec-001",
            prospect_id="prospect-001",
            opportunity_type_id="cold_outreach_consultant",
            beneficiary_id="consultant",
            current_status="Sent",
        )
        repo.add_record(record)

        transition = await manager.advance_on_reply(
            "rec-001", "Thanks for reaching out! I'd love to chat."
        )

        assert transition.result == PipelineTransitionResult.ADVANCED
        assert transition.new_status == "Replied"
        assert transition.previous_status == "Sent"

        # Verify event was published
        assert len(publisher.published) == 1
        channel, message = publisher.published[0]
        assert channel == "pipeline_updates"
        data = json.loads(message)
        assert data["new_status"] == "Replied"


    async def test_auto_reply_does_not_advance_pipeline(self):
        """Auto-reply (out of office) does NOT advance pipeline status."""
        repo = FakePipelineRepository()
        publisher = FakeEventPublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        record = PipelineRecordData(
            id="rec-002",
            prospect_id="prospect-002",
            opportunity_type_id="cold_outreach_consultant",
            beneficiary_id="consultant",
            current_status="Sent",
        )
        repo.add_record(record)

        transition = await manager.advance_on_reply(
            "rec-002", "I am currently out of office until next week."
        )

        assert transition.result == PipelineTransitionResult.NO_CHANGE
        # No event published
        assert len(publisher.published) == 0

    async def test_meeting_booked_advances_from_sent_or_replied(self):
        """Meeting signal advances pipeline to Meeting Booked from Sent or Replied."""
        repo = FakePipelineRepository()
        publisher = FakeEventPublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        # Test from Sent
        record_sent = PipelineRecordData(
            id="rec-003",
            prospect_id="prospect-003",
            opportunity_type_id="cold_outreach_consultant",
            beneficiary_id="consultant",
            current_status="Sent",
        )
        repo.add_record(record_sent)

        transition = await manager.advance_on_meeting("rec-003")
        assert transition.result == PipelineTransitionResult.ADVANCED
        assert transition.new_status == "Meeting Booked"

        # Test from Replied
        record_replied = PipelineRecordData(
            id="rec-004",
            prospect_id="prospect-004",
            opportunity_type_id="cold_outreach_consultant",
            beneficiary_id="consultant",
            current_status="Replied",
        )
        repo.add_record(record_replied)

        transition2 = await manager.advance_on_meeting("rec-004")
        assert transition2.result == PipelineTransitionResult.ADVANCED
        assert transition2.new_status == "Meeting Booked"


    async def test_proposal_request_advances_team_pipeline(self):
        """Proposal request keywords advance Team pipeline to Proposal Requested."""
        repo = FakePipelineRepository()
        publisher = FakeEventPublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        record = PipelineRecordData(
            id="rec-005",
            prospect_id="prospect-005",
            opportunity_type_id="cold_outreach_team",
            beneficiary_id="team",
            current_status="Replied",
        )
        repo.add_record(record)

        transition = await manager.advance_on_proposal_request(
            "rec-005", "Could you send a proposal for this project?"
        )

        assert transition.result == PipelineTransitionResult.ADVANCED
        assert transition.new_status == "Proposal Requested"

    async def test_terminal_state_blocks_transitions(self):
        """Pipeline records in terminal states cannot be advanced."""
        repo = FakePipelineRepository()
        publisher = FakeEventPublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        record = PipelineRecordData(
            id="rec-006",
            prospect_id="prospect-006",
            opportunity_type_id="cold_outreach_consultant",
            beneficiary_id="consultant",
            current_status="Converted",
            is_terminal=True,
        )
        repo.add_record(record)

        transition = await manager.advance_on_reply(
            "rec-006", "Sure let's connect again!"
        )
        assert transition.result == PipelineTransitionResult.ALREADY_TERMINAL


# ─── Test: Lemlist Engine enrolls prospects in sequences ──────────────────────


class TestLemlistEnrollmentFlow:
    """Integration tests for Lemlist sequence creation and enrollment."""

    async def test_sequence_creation_and_sync(
        self, mock_lemlist_campaign_response
    ):
        """Lemlist engine creates and syncs a sequence to the API."""
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(
                201, json=mock_lemlist_campaign_response
            )
        )
        async with httpx.AsyncClient(transport=mock_transport) as client:
            repo = FakeLemlistRepository()
            engine = LemlistEngine(
                api_key="test-key", http_client=client, db_repo=repo
            )

            sequence = Sequence(
                id="seq-001",
                name="Test Cold Outreach",
                beneficiary_id="consultant",
                steps=[
                    SequenceStep(
                        order=1,
                        channel=Channel.EMAIL,
                        delay_days=1,
                        content_template="Hi {{firstName}}, interested?",
                    ),
                    SequenceStep(
                        order=2,
                        channel=Channel.EMAIL,
                        delay_days=3,
                        content_template="Following up on my previous email.",
                    ),
                ],
                sync_status=SequenceSyncStatus.PENDING,
                created_at=datetime.now(timezone.utc),
            )

            status = await engine.create_sequence(sequence)

        assert status == SequenceSyncStatus.SYNCED
        # Sequence saved in repo
        saved = await repo.get_sequence("seq-001")
        assert saved is not None
        assert saved.sync_status == SequenceSyncStatus.SYNCED


    async def test_prospect_enrollment(self):
        """Lemlist engine enrolls prospects in a sequence."""
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True})
        )
        async with httpx.AsyncClient(transport=mock_transport) as client:
            repo = FakeLemlistRepository()
            engine = LemlistEngine(
                api_key="test-key", http_client=client, db_repo=repo
            )

            # Save sequence first
            sequence = Sequence(
                id="seq-001",
                name="Test Outreach",
                beneficiary_id="consultant",
                steps=[
                    SequenceStep(
                        order=1,
                        channel=Channel.EMAIL,
                        delay_days=1,
                        content_template="Hello!",
                    ),
                ],
                sync_status=SequenceSyncStatus.SYNCED,
                created_at=datetime.now(timezone.utc),
            )
            await repo.save_sequence(sequence)

            enrolled = await engine.enroll_prospects(
                "seq-001", ["prospect-001", "prospect-002", "prospect-003"]
            )

        assert enrolled == 3

        # Verify enrollments stored
        e1 = await repo.get_enrollment("prospect-001", "seq-001")
        assert e1 is not None
        assert e1.status == ProspectSequenceStatus.ACTIVE

    async def test_batch_enrollment_limit(self):
        """Enrollment rejects batches exceeding 200 prospects."""
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"ok": True})
        )
        async with httpx.AsyncClient(transport=mock_transport) as client:
            engine = LemlistEngine(api_key="test-key", http_client=client)

            prospect_ids = [f"prospect-{i}" for i in range(201)]
            with pytest.raises(ValueError, match="cannot exceed 200"):
                await engine.enroll_prospects("seq-001", prospect_ids)


# ─── Test: Response polling advances pipeline status ──────────────────────────


class TestResponsePollingFlow:
    """Integration tests for Lemlist response polling → pipeline advancement."""

    async def test_poll_responses_and_advance_pipeline(
        self, mock_lemlist_activities_response
    ):
        """Polling detects a reply and advances the pipeline record."""
        # Set up Lemlist engine with mock
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(
                200, json=mock_lemlist_activities_response
            )
        )
        async with httpx.AsyncClient(transport=mock_transport) as client:
            lemlist_repo = FakeLemlistRepository()
            engine = LemlistEngine(
                api_key="test-key", http_client=client, db_repo=lemlist_repo
            )

            # Poll for responses
            events = await engine.poll_responses()

        assert len(events) >= 1
        reply_event = events[0]
        assert reply_event.event_type == ResponseEventType.REPLY
        assert reply_event.prospect_id == "prospect-001"

        # Now use PipelineManager to advance based on the reply
        repo = FakePipelineRepository()
        publisher = FakeEventPublisher()
        manager = PipelineManager(repository=repo, publisher=publisher)

        record = PipelineRecordData(
            id="rec-001",
            prospect_id="prospect-001",
            opportunity_type_id="cold_outreach_consultant",
            beneficiary_id="consultant",
            current_status="Sent",
        )
        repo.add_record(record)

        # Advance on the detected reply
        transition = await manager.advance_on_reply(
            "rec-001", "Thanks for reaching out! Let's schedule a call."
        )

        assert transition.result == PipelineTransitionResult.ADVANCED
        assert transition.new_status == "Replied"


    async def test_poll_api_error_returns_empty_no_changes(self):
        """When Lemlist API is unreachable, polling returns empty without changes."""
        mock_transport = httpx.MockTransport(
            lambda request: httpx.Response(500, text="Internal Server Error")
        )
        async with httpx.AsyncClient(transport=mock_transport) as client:
            engine = LemlistEngine(api_key="test-key", http_client=client)
            events = await engine.poll_responses()

        assert events == []


# ─── Test: Analytics Service computes funnel metrics ──────────────────────────


class TestAnalyticsFunnelFlow:
    """Integration tests for analytics service computing funnel from flow data."""

    async def test_funnel_metrics_from_pipeline_data(self):
        """Analytics service computes correct funnel metrics from stage transitions."""
        service = AnalyticsService()
        now = datetime.now()  # naive datetime to match analytics_service cutoff

        stage_order = ["Drafted", "Sent", "Replied", "Meeting Booked", "Converted"]
        transitions = [
            # 10 entered Drafted, 8 exited to Sent
            *[
                StageTransition(
                    record_id=f"rec-{i}",
                    stage_name="Drafted",
                    entered_at=now - timedelta(days=20),
                    exited_at=now - timedelta(days=18),
                    exited_to_next=True,
                )
                for i in range(8)
            ],
            *[
                StageTransition(
                    record_id=f"rec-{i}",
                    stage_name="Drafted",
                    entered_at=now - timedelta(days=20),
                    exited_at=None,
                    exited_to_next=False,
                )
                for i in range(8, 10)
            ],
            # 8 entered Sent, 5 exited to Replied
            *[
                StageTransition(
                    record_id=f"rec-{i}",
                    stage_name="Sent",
                    entered_at=now - timedelta(days=18),
                    exited_at=now - timedelta(days=14),
                    exited_to_next=True,
                )
                for i in range(5)
            ],
            *[
                StageTransition(
                    record_id=f"rec-{i}",
                    stage_name="Sent",
                    entered_at=now - timedelta(days=18),
                    exited_at=None,
                    exited_to_next=False,
                )
                for i in range(5, 8)
            ],
            # 5 entered Replied, 2 exited to Meeting Booked
            *[
                StageTransition(
                    record_id=f"rec-{i}",
                    stage_name="Replied",
                    entered_at=now - timedelta(days=14),
                    exited_at=now - timedelta(days=10),
                    exited_to_next=True,
                )
                for i in range(2)
            ],
            *[
                StageTransition(
                    record_id=f"rec-{i}",
                    stage_name="Replied",
                    entered_at=now - timedelta(days=14),
                    exited_at=None,
                    exited_to_next=False,
                )
                for i in range(2, 5)
            ],
        ]

        funnel = service.compute_funnel(
            transitions=transitions,
            stage_order=stage_order,
            period_days=30,
        )

        assert len(funnel) == 5

        # Drafted: 10 entered, 8 exited → 80% conversion
        drafted = funnel[0]
        assert drafted.stage_name == "Drafted"
        assert drafted.entered_count == 10
        assert drafted.exited_count == 8
        assert drafted.conversion_rate == 80.0

        # Sent: 8 entered, 5 exited → 62.5%
        sent = funnel[1]
        assert sent.stage_name == "Sent"
        assert sent.entered_count == 8
        assert sent.exited_count == 5
        assert sent.conversion_rate == 62.5

        # Replied: 5 entered, 2 exited → 40%
        replied = funnel[2]
        assert replied.stage_name == "Replied"
        assert replied.entered_count == 5
        assert replied.exited_count == 2
        assert replied.conversion_rate == 40.0


    async def test_insufficient_data_indicator(self):
        """Stages with fewer than 5 records get insufficient data indicator."""
        service = AnalyticsService()
        now = datetime.now()  # naive datetime to match analytics_service cutoff

        transitions = [
            StageTransition(
                record_id=f"rec-{i}",
                stage_name="Drafted",
                entered_at=now - timedelta(days=10),
                exited_at=now - timedelta(days=8),
                exited_to_next=True,
            )
            for i in range(3)  # Only 3 records
        ]

        funnel = service.compute_funnel(
            transitions=transitions,
            stage_order=["Drafted", "Sent"],
            period_days=30,
        )

        drafted = funnel[0]
        assert drafted.has_insufficient_data is True

    async def test_channel_effectiveness_computation(self):
        """Analytics service computes channel effectiveness rates."""
        service = AnalyticsService()

        channel_data = [
            ChannelData(
                source="apollo",
                sequence_name="Cold Email v1",
                beneficiary="consultant",
                sends=100,
                replies=15,
                meetings=5,
                outcomes=2,
                total_entered=50,
            ),
            ChannelData(
                source="adzuna",
                sequence_name=None,
                beneficiary="consultant",
                sends=5,
                replies=1,
                meetings=0,
                outcomes=0,
                total_entered=5,
            ),
        ]

        results = service.compute_channel_effectiveness(channel_data=channel_data)

        assert len(results) == 2

        # Apollo channel: high confidence
        apollo_result = next(r for r in results if r.source == "apollo")
        assert apollo_result.response_rate == 0.15  # 15/100
        assert apollo_result.meeting_rate == 0.05  # 5/100
        assert apollo_result.conversion_rate == 0.04  # 2/50
        assert apollo_result.is_low_confidence is False

        # Adzuna channel: low confidence (< 10 prospects)
        adzuna_result = next(r for r in results if r.source == "adzuna")
        assert adzuna_result.is_low_confidence is True


# ─── Test: Full end-to-end flow ───────────────────────────────────────────────


class TestEndToEndFlow:
    """Full end-to-end integration: discovery → enrichment → scoring → pipeline → outreach → analytics."""

    async def test_complete_discovery_to_pipeline_flow(self, scoring_engine):
        """Test the complete flow from discovery through pipeline creation."""
        now = datetime.now(timezone.utc)

        # Step 1: Discovery finds a new prospect
        raw_prospects = [
            RawProspect(
                company_name="Acme Solutions",
                company_domain="acme.io",
                source_type=SourceType.APOLLO,
                beneficiary_id="consultant",
                opportunity_type_id="cold_outreach_consultant",
                enrichment_data={"industry": "Technology"},
                discovered_at=now,
            ),
        ]

        pipeline = DiscoveryPipeline(
            scoring_engine=scoring_engine,
            source_clients={},
            existing_prospects=[],
        )

        # Step 2: Deduplicate (new prospect)
        deduped = await pipeline.deduplicate_and_merge(raw_prospects)
        assert len(deduped) == 1
        assert deduped[0]["is_new"] is True

        # Step 3: Score the prospect
        score_result = scoring_engine.compute_score(
            firmographic=70,
            technographic=80,
            intent=60,
            llm_relevance=75,
            historical=None,
            source_count=1,
            has_strong_intent=True,
        )
        assert score_result.total_score > 25  # Above default threshold
        assert score_result.is_partial is True  # historical missing

        # Step 4: Create pipeline record
        repo = FakePipelineRepository()
        publisher = FakeEventPublisher()
        pipeline_mgr = PipelineManager(repository=repo, publisher=publisher)

        record = PipelineRecordData(
            id="rec-acme",
            prospect_id="prospect-acme",
            opportunity_type_id="cold_outreach_consultant",
            beneficiary_id="consultant",
            current_status="Drafted",
        )
        repo.add_record(record)

        # Step 5: After outreach sent, advance pipeline
        record.current_status = "Sent"

        # Step 6: Reply received → advance to Replied
        transition = await pipeline_mgr.advance_on_reply(
            "rec-acme", "Great to hear from you! When can we talk?"
        )
        assert transition.result == PipelineTransitionResult.ADVANCED
        assert transition.new_status == "Replied"

        # Step 7: Meeting booked → advance
        transition2 = await pipeline_mgr.advance_on_meeting("rec-acme")
        assert transition2.result == PipelineTransitionResult.ADVANCED
        assert transition2.new_status == "Meeting Booked"

        # Verify WebSocket broadcasts were published
        assert len(publisher.published) == 2
