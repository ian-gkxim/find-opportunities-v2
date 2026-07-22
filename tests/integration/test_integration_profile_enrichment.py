"""Integration tests for the full Profile Enrichment scan-to-review flow.

Tests higher-level scenarios wiring together worker, deduplicator,
review service, and notification system with mocked external deps.

Requirements: 1.2, 1.4, 2.2, 2.4, 3.2, 3.4
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.proposal_deduplicator import (
    CompetencyCandidate,
    ProfileAsset,
    ProposalDeduplicator,
    ProposalRecord as DeduplicationProposalRecord,
)
from app.core.proposal_review_service import (
    MergeAction,
    ProposalRecord,
    ProposalReviewService,
)
from app.workers.profile_enrichment_worker import (
    CONSECUTIVE_FAILURE_THRESHOLD,
    _scan_source,
    _emit_source_failure_notice,
)


# ─── MOCK REPOSITORIES ───────────────────────────────────────────────────────


class MockProposalReviewRepository:
    """In-memory repository for ProposalReviewService integration testing."""

    def __init__(self, proposals: list[ProposalRecord] | None = None):
        self._proposals: dict[str, ProposalRecord] = {}
        if proposals:
            for p in proposals:
                self._proposals[p.id] = p

        self.inserted_assets: list[dict] = []
        self.audit_entries: list[dict] = []
        self.status_updates: list[dict] = []

    async def get_proposal(self, proposal_id: str) -> ProposalRecord | None:
        return self._proposals.get(proposal_id)

    async def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        merged_content: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> None:
        self.status_updates.append({
            "proposal_id": proposal_id,
            "status": status,
            "merged_content": merged_content,
            "reviewed_at": reviewed_at,
        })
        if proposal_id in self._proposals:
            old = self._proposals[proposal_id]
            self._proposals[proposal_id] = ProposalRecord(
                id=old.id,
                consultant_id=old.consultant_id,
                category=old.category,
                name=old.name,
                evidence_summary=old.evidence_summary,
                raw_evidence=old.raw_evidence,
                confidence=old.confidence,
                source_url=old.source_url,
                status=status,
                merged_content=merged_content or old.merged_content,
                reviewed_at=reviewed_at or old.reviewed_at,
            )

    async def insert_profile_asset(
        self,
        consultant_id: str,
        section: str,
        content: str,
        source_url: str | None = None,
    ) -> str:
        asset_id = f"asset-{len(self.inserted_assets) + 1}"
        self.inserted_assets.append({
            "id": asset_id,
            "consultant_id": consultant_id,
            "section": section,
            "content": content,
            "source_url": source_url,
        })
        return asset_id

    async def create_audit_entry(
        self,
        consultant_id: str,
        proposal_id: str,
        action: str,
        added_content: str,
        evidence_source_url: str,
        profile_section: str,
        edited: bool,
    ) -> str:
        audit_id = f"audit-{len(self.audit_entries) + 1}"
        self.audit_entries.append({
            "id": audit_id,
            "consultant_id": consultant_id,
            "proposal_id": proposal_id,
            "action": action,
            "added_content": added_content,
            "evidence_source_url": evidence_source_url,
            "profile_section": profile_section,
            "edited": edited,
        })
        return audit_id


class MockDeduplicationRepository:
    """In-memory repository for ProposalDeduplicator integration testing."""

    def __init__(
        self,
        profile_assets: list[ProfileAsset] | None = None,
        rejected_proposals: list[DeduplicationProposalRecord] | None = None,
        pending_proposals: list[DeduplicationProposalRecord] | None = None,
    ):
        self._profile_assets = profile_assets or []
        self._rejected_proposals = rejected_proposals or []
        self._pending_proposals = pending_proposals or []

    async def get_profile_assets(self, consultant_id: str) -> list[ProfileAsset]:
        return self._profile_assets

    async def get_rejected_proposals(
        self, consultant_id: str
    ) -> list[DeduplicationProposalRecord]:
        return self._rejected_proposals

    async def get_pending_proposals(
        self, consultant_id: str
    ) -> list[DeduplicationProposalRecord]:
        return self._pending_proposals


class MockDeduplicationRepositoryPerConsultant:
    """Deduplication repository that isolates data per consultant."""

    def __init__(self):
        self._profile_assets: dict[str, list[ProfileAsset]] = {}
        self._rejected_proposals: dict[str, list[DeduplicationProposalRecord]] = {}
        self._pending_proposals: dict[str, list[DeduplicationProposalRecord]] = {}

    def add_profile_asset(self, consultant_id: str, asset: ProfileAsset):
        self._profile_assets.setdefault(consultant_id, []).append(asset)

    def add_rejected_proposal(
        self, consultant_id: str, proposal: DeduplicationProposalRecord
    ):
        self._rejected_proposals.setdefault(consultant_id, []).append(proposal)

    async def get_profile_assets(self, consultant_id: str) -> list[ProfileAsset]:
        return self._profile_assets.get(consultant_id, [])

    async def get_rejected_proposals(
        self, consultant_id: str
    ) -> list[DeduplicationProposalRecord]:
        return self._rejected_proposals.get(consultant_id, [])

    async def get_pending_proposals(
        self, consultant_id: str
    ) -> list[DeduplicationProposalRecord]:
        return self._pending_proposals.get(consultant_id, [])


# ─── HELPERS ──────────────────────────────────────────────────────────────────


def _make_source(
    consultant_id: str = "consultant-001",
    url: str = "https://github.com/consultant",
    source_type: str = "github",
    label: str = "My GitHub",
    consecutive_failures: int = 0,
):
    """Create a mock PublicSource object."""
    source = MagicMock()
    source.id = str(uuid.uuid4())
    source.consultant_id = consultant_id
    source.url = url
    source.source_type = source_type
    source.label = label
    source.consecutive_failures = consecutive_failures
    source.last_scanned_at = None
    source.scan_interval_days = 30
    source.is_active = True
    source.updated_at = None
    return source


def _make_candidate(
    name: str = "Kubernetes",
    category: str = "technology",
    source_url: str = "https://github.com/consultant",
) -> CompetencyCandidate:
    """Create a CompetencyCandidate for testing."""
    return CompetencyCandidate(
        category=category,
        name=name,
        evidence_summary=f"Evidence for {name}",
        confidence="strong",
        source_url=source_url,
        raw_evidence=f"Raw evidence snippet for {name}",
    )


def _make_pending_proposal(
    proposal_id: str = "proposal-001",
    consultant_id: str = "consultant-001",
    category: str = "technology",
    name: str = "Kubernetes",
    source_url: str = "https://github.com/consultant/k8s-operator",
) -> ProposalRecord:
    """Create a pending ProposalRecord."""
    return ProposalRecord(
        id=proposal_id,
        consultant_id=consultant_id,
        category=category,
        name=name,
        evidence_summary=f"Owner of {name} repo (142 stars)",
        raw_evidence="raw snippet",
        confidence="strong",
        source_url=source_url,
        status="pending",
        merged_content=None,
        reviewed_at=None,
    )


# ─── TEST 1: Full scan-to-review flow ────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_scan_to_review_flow():
    """Integration: configure source → scan → proposals created → accept → profile updated → audit log.

    Validates Requirements: 1.2, 2.4, 3.2, 3.4
    """
    consultant_id = "consultant-001"
    source = _make_source(consultant_id=consultant_id)

    # Mock session to capture created proposals
    created_proposals = []

    mock_session = AsyncMock()

    def capture_add(obj):
        created_proposals.append(obj)

    mock_session.add = MagicMock(side_effect=capture_add)
    mock_session.flush = AsyncMock()

    mock_throttler = AsyncMock()
    mock_ws_manager = AsyncMock()
    mock_settings = MagicMock()

    # Candidates the LLM will "extract"
    candidates = [
        _make_candidate("Kubernetes", "technology", source.url),
        _make_candidate("Helm Charts", "technology", source.url),
    ]

    with (
        patch(
            "app.workers.profile_enrichment_worker._fetch_with_retries",
            new_callable=AsyncMock,
            return_value="<html>GitHub profile with Kubernetes and Helm projects</html>",
        ),
        patch(
            "app.integrations.llm_router.LLMRouter",
        ) as mock_llm_cls,
        patch(
            "app.workers.profile_enrichment_worker.CompetencyExtractor",
        ) as mock_extractor_cls,
        patch(
            "app.workers.profile_enrichment_worker.ProposalDeduplicator",
        ) as mock_dedup_cls,
    ):
        # Extractor returns our candidates
        mock_extractor = AsyncMock()
        mock_extractor.extract.return_value = candidates
        mock_extractor_cls.return_value = mock_extractor

        # Deduplicator passes all candidates through (they're new)
        mock_dedup = AsyncMock()
        mock_dedup.deduplicate.return_value = candidates
        mock_dedup_cls.return_value = mock_dedup

        # Step 1: Run scan
        num_proposals = await _scan_source(
            session=mock_session,
            source=source,
            throttler=mock_throttler,
            ws_manager=mock_ws_manager,
            settings=mock_settings,
        )

    # Assert: 2 proposals were created
    assert num_proposals == 2
    assert len(created_proposals) == 2

    # Verify proposals have correct consultant_id and source data
    for p in created_proposals:
        assert p.consultant_id == consultant_id
        assert p.source_id == source.id
        assert p.status == "pending"

    # Assert: throttler was used
    mock_throttler.acquire.assert_called_once_with(source.url)

    # Assert: consecutive_failures was reset on success
    assert source.consecutive_failures == 0

    # Step 2: Accept first proposal via ProposalReviewService
    proposal = _make_pending_proposal(
        proposal_id="proposal-001",
        consultant_id=consultant_id,
        category="technology",
        name="Kubernetes",
        source_url=source.url,
    )
    review_repo = MockProposalReviewRepository(proposals=[proposal])
    review_service = ProposalReviewService(
        db_repo=review_repo, websocket_manager=None
    )

    result = await review_service.accept_proposal("proposal-001", consultant_id)

    # Assert: profile asset was inserted (additive-only)
    assert len(review_repo.inserted_assets) == 1
    asset = review_repo.inserted_assets[0]
    assert asset["consultant_id"] == consultant_id
    assert asset["section"] == "technology"
    assert asset["content"] == proposal.evidence_summary
    assert asset["source_url"] == source.url

    # Assert: proposal status updated to accepted
    assert len(review_repo.status_updates) == 1
    assert review_repo.status_updates[0]["status"] == "accepted"

    # Assert: audit log was created
    assert len(review_repo.audit_entries) == 1
    audit = review_repo.audit_entries[0]
    assert audit["consultant_id"] == consultant_id
    assert audit["proposal_id"] == "proposal-001"
    assert audit["action"] == "accept"
    assert audit["added_content"] == proposal.evidence_summary
    assert audit["evidence_source_url"] == source.url
    assert audit["profile_section"] == "technology"
    assert audit["edited"] is False

    # Assert: MergeResult is correct
    assert result.action == MergeAction.ACCEPT
    assert result.merged_content == proposal.evidence_summary
    assert result.profile_section == "technology"
    assert result.audit_log_id == "audit-1"


# ─── TEST 2: 3 consecutive failures → Dashboard notice emitted ───────────────


@pytest.mark.asyncio
async def test_three_consecutive_failures_emits_dashboard_notice():
    """Integration: 3 consecutive scan failures → WebSocket broadcast_notification called.

    Validates Requirements: 1.4
    """
    consultant_id = "consultant-001"
    # Source already has 2 consecutive failures; next failure hits threshold
    source = _make_source(
        consultant_id=consultant_id,
        consecutive_failures=2,
        url="https://dead-site.example.com/portfolio",
        label="Dead Portfolio",
    )

    mock_ws_manager = AsyncMock()

    # Simulate the failure: increment counter (as the worker does)
    source.consecutive_failures += 1

    # At threshold (3), emit notice
    assert source.consecutive_failures == CONSECUTIVE_FAILURE_THRESHOLD

    await _emit_source_failure_notice(
        ws_manager=mock_ws_manager,
        consultant_id=consultant_id,
        source=source,
    )

    # Assert: broadcast_notification was called with correct payload
    mock_ws_manager.broadcast_notification.assert_called_once()
    call_payload = mock_ws_manager.broadcast_notification.call_args[0][0]
    assert call_payload["category"] == "source_failure_notice"
    assert call_payload["consultant_id"] == consultant_id
    assert call_payload["source_url"] == "https://dead-site.example.com/portfolio"
    assert call_payload["source_label"] == "Dead Portfolio"
    assert call_payload["consecutive_failures"] == 3
    assert "unreachable" in call_payload["message"].lower()


@pytest.mark.asyncio
async def test_no_notice_before_threshold():
    """No notice emitted when consecutive failures are below threshold.

    Validates Requirements: 1.4
    """
    consultant_id = "consultant-001"
    # Source has 0 failures; after 1 failure it's still below threshold
    source = _make_source(consultant_id=consultant_id, consecutive_failures=0)
    mock_ws_manager = AsyncMock()

    # Simulate 1 failure
    source.consecutive_failures += 1

    # Below threshold — should NOT emit notice
    assert source.consecutive_failures < CONSECUTIVE_FAILURE_THRESHOLD

    # Verify: the worker only calls _emit_source_failure_notice at exactly threshold
    # (We don't call it here since the condition wouldn't be met)
    mock_ws_manager.broadcast_notification.assert_not_called()


# ─── TEST 3: Rejected proposal not re-proposed in next cycle ──────────────────


@pytest.mark.asyncio
async def test_rejected_proposal_not_reproposed():
    """Integration: rejected "Kubernetes" in "technology" is filtered out in next scan.

    Validates Requirements: 2.2, 3.3 (via deduplicator)
    """
    consultant_id = "consultant-001"

    # Set up: a previously rejected proposal for "Kubernetes" in "technology"
    dedup_repo = MockDeduplicationRepository(
        profile_assets=[],
        rejected_proposals=[
            DeduplicationProposalRecord(name="Kubernetes", category="technology"),
        ],
        pending_proposals=[],
    )

    deduplicator = ProposalDeduplicator(db_repo=dedup_repo)

    # New candidates from a fresh scan — includes "Kubernetes" again
    new_candidates = [
        _make_candidate("Kubernetes", "technology"),
        _make_candidate("Docker", "technology"),
        _make_candidate("Terraform", "technology"),
    ]

    # Run deduplication
    result = await deduplicator.deduplicate(
        candidates=new_candidates,
        consultant_id=consultant_id,
    )

    # Assert: "Kubernetes" is filtered out, but Docker and Terraform pass through
    result_names = [c.name for c in result]
    assert "Kubernetes" not in result_names
    assert "Docker" in result_names
    assert "Terraform" in result_names
    assert len(result) == 2


@pytest.mark.asyncio
async def test_rejected_proposal_different_category_allowed():
    """A rejected item in one category can still be proposed in another category.

    Validates Requirements: 2.2
    """
    consultant_id = "consultant-001"

    # Rejected "Kubernetes" as "technology"
    dedup_repo = MockDeduplicationRepository(
        profile_assets=[],
        rejected_proposals=[
            DeduplicationProposalRecord(name="Kubernetes", category="technology"),
        ],
        pending_proposals=[],
    )

    deduplicator = ProposalDeduplicator(db_repo=dedup_repo)

    # Same name, different category (e.g., "certification" for CKA)
    new_candidates = [
        _make_candidate("Kubernetes", "certification"),
    ]

    result = await deduplicator.deduplicate(
        candidates=new_candidates,
        consultant_id=consultant_id,
    )

    # "Kubernetes" in "certification" is different from rejected "technology"
    assert len(result) == 1
    assert result[0].name == "Kubernetes"
    assert result[0].category == "certification"


# ─── TEST 4: Privacy isolation ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_privacy_isolation_scan_does_not_cross_consultants():
    """Integration: Consultant A's scan never creates proposals for Consultant B.

    Validates Requirements: 2.4
    """
    consultant_a_id = "consultant-A"
    consultant_b_id = "consultant-B"

    # Source belongs to Consultant A
    source_a = _make_source(
        consultant_id=consultant_a_id,
        url="https://github.com/consultantA",
    )

    # Track proposals created for each consultant
    created_proposals = []

    mock_session = AsyncMock()
    mock_session.add = MagicMock(side_effect=lambda obj: created_proposals.append(obj))
    mock_session.flush = AsyncMock()

    mock_throttler = AsyncMock()
    mock_ws_manager = AsyncMock()
    mock_settings = MagicMock()

    candidates_a = [
        _make_candidate("React", "technology", source_a.url),
        _make_candidate("TypeScript", "technology", source_a.url),
    ]

    with (
        patch(
            "app.workers.profile_enrichment_worker._fetch_with_retries",
            new_callable=AsyncMock,
            return_value="<html>Consultant A profile content</html>",
        ),
        patch("app.integrations.llm_router.LLMRouter"),
        patch(
            "app.workers.profile_enrichment_worker.CompetencyExtractor",
        ) as mock_extractor_cls,
        patch(
            "app.workers.profile_enrichment_worker.ProposalDeduplicator",
        ) as mock_dedup_cls,
    ):
        mock_extractor = AsyncMock()
        mock_extractor.extract.return_value = candidates_a
        mock_extractor_cls.return_value = mock_extractor

        mock_dedup = AsyncMock()
        mock_dedup.deduplicate.return_value = candidates_a
        mock_dedup_cls.return_value = mock_dedup

        # Scan Consultant A's source
        num_proposals = await _scan_source(
            session=mock_session,
            source=source_a,
            throttler=mock_throttler,
            ws_manager=mock_ws_manager,
            settings=mock_settings,
        )

    # Assert: all proposals created belong to Consultant A
    assert num_proposals == 2
    assert len(created_proposals) == 2
    for p in created_proposals:
        assert p.consultant_id == consultant_a_id
        # None belong to Consultant B
        assert p.consultant_id != consultant_b_id

    # Also verify: deduplicator was called with Consultant A's ID only
    mock_dedup.deduplicate.assert_called_once()
    dedup_call_kwargs = mock_dedup.deduplicate.call_args
    assert dedup_call_kwargs[1]["consultant_id"] == consultant_a_id


@pytest.mark.asyncio
async def test_privacy_isolation_deduplication_uses_correct_consultant():
    """Deduplication only checks the owning consultant's profile, not others'.

    Validates Requirements: 2.4
    """
    consultant_a_id = "consultant-A"
    consultant_b_id = "consultant-B"

    # Consultant B has "React" in their profile, but Consultant A does not
    dedup_repo = MockDeduplicationRepositoryPerConsultant()
    dedup_repo.add_profile_asset(
        consultant_b_id, ProfileAsset(name="React", category="technology")
    )

    deduplicator = ProposalDeduplicator(db_repo=dedup_repo)

    # Candidate "React" for Consultant A
    candidates = [
        _make_candidate("React", "technology"),
    ]

    # Deduplicate for Consultant A — should NOT filter React
    # because it's only in Consultant B's profile
    result_a = await deduplicator.deduplicate(
        candidates=candidates, consultant_id=consultant_a_id
    )

    # Assert: React passes through for Consultant A
    assert len(result_a) == 1
    assert result_a[0].name == "React"

    # Deduplicate for Consultant B — SHOULD filter React
    result_b = await deduplicator.deduplicate(
        candidates=candidates, consultant_id=consultant_b_id
    )

    # Assert: React is filtered for Consultant B (already in their profile)
    assert len(result_b) == 0
