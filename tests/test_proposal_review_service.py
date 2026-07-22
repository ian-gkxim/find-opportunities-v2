"""Unit tests for ProposalReviewService.

Tests accept/reject/bulk workflows, audit logging, authorization,
and status validation.

Requirements: 3.1, 3.2, 3.3, 3.4
"""

import pytest
from datetime import datetime, timezone

from app.core.proposal_review_service import (
    MergeAction,
    MergeResult,
    ProposalRecord,
    ProposalReviewService,
)


# ─── Mock Repository ──────────────────────────────────────────────────────────


class MockProposalReviewRepository:
    """In-memory implementation of ProposalReviewRepository for testing."""

    def __init__(self, proposals: list[ProposalRecord] | None = None):
        self._proposals: dict[str, ProposalRecord] = {}
        if proposals:
            for p in proposals:
                self._proposals[p.id] = p

        # Track calls for verification
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
        self.status_updates.append(
            {
                "proposal_id": proposal_id,
                "status": status,
                "merged_content": merged_content,
                "reviewed_at": reviewed_at,
            }
        )
        # Also update the in-memory record
        if proposal_id in self._proposals:
            proposal = self._proposals[proposal_id]
            self._proposals[proposal_id] = ProposalRecord(
                id=proposal.id,
                consultant_id=proposal.consultant_id,
                category=proposal.category,
                name=proposal.name,
                evidence_summary=proposal.evidence_summary,
                raw_evidence=proposal.raw_evidence,
                confidence=proposal.confidence,
                source_url=proposal.source_url,
                status=status,
                merged_content=merged_content or proposal.merged_content,
                reviewed_at=reviewed_at or proposal.reviewed_at,
            )

    async def insert_profile_asset(
        self,
        consultant_id: str,
        section: str,
        content: str,
        source_url: str | None = None,
    ) -> str:
        asset_id = f"asset-{len(self.inserted_assets) + 1}"
        self.inserted_assets.append(
            {
                "id": asset_id,
                "consultant_id": consultant_id,
                "section": section,
                "content": content,
                "source_url": source_url,
            }
        )
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
        self.audit_entries.append(
            {
                "id": audit_id,
                "consultant_id": consultant_id,
                "proposal_id": proposal_id,
                "action": action,
                "added_content": added_content,
                "evidence_source_url": evidence_source_url,
                "profile_section": profile_section,
                "edited": edited,
            }
        )
        return audit_id


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_pending_proposal(
    proposal_id: str = "proposal-001",
    consultant_id: str = "consultant-001",
    category: str = "technology",
    name: str = "Kubernetes",
    evidence_summary: str = "Owner of k8s-operator repo (142 stars)",
    source_url: str = "https://github.com/user/k8s-operator",
) -> ProposalRecord:
    """Create a pending ProposalRecord with sensible defaults."""
    return ProposalRecord(
        id=proposal_id,
        consultant_id=consultant_id,
        category=category,
        name=name,
        evidence_summary=evidence_summary,
        raw_evidence="raw snippet",
        confidence="strong",
        source_url=source_url,
        status="pending",
        merged_content=None,
        reviewed_at=None,
    )


# ─── Accept Proposal Tests ────────────────────────────────────────────────────


class TestAcceptProposal:
    """Tests for accept_proposal: audit entry creation and profile append."""

    async def test_accept_creates_audit_entry_and_appends_to_profile(self):
        """Accepting a proposal creates an audit entry and inserts a profile asset.

        Validates: Requirements 3.2, 3.4
        """
        proposal = _make_pending_proposal()
        repo = MockProposalReviewRepository(proposals=[proposal])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        result = await service.accept_proposal("proposal-001", "consultant-001")

        # Verify profile asset was inserted (additive-only append)
        assert len(repo.inserted_assets) == 1
        asset = repo.inserted_assets[0]
        assert asset["consultant_id"] == "consultant-001"
        assert asset["section"] == "technology"
        assert asset["content"] == proposal.evidence_summary
        assert asset["source_url"] == proposal.source_url

        # Verify audit entry was created
        assert len(repo.audit_entries) == 1
        audit = repo.audit_entries[0]
        assert audit["consultant_id"] == "consultant-001"
        assert audit["proposal_id"] == "proposal-001"
        assert audit["action"] == "accept"
        assert audit["added_content"] == proposal.evidence_summary
        assert audit["evidence_source_url"] == proposal.source_url
        assert audit["profile_section"] == "technology"
        assert audit["edited"] is False

        # Verify MergeResult
        assert result.proposal_id == "proposal-001"
        assert result.action == MergeAction.ACCEPT
        assert result.merged_content == proposal.evidence_summary
        assert result.profile_section == "technology"
        assert result.audit_log_id == "audit-1"

    async def test_accept_updates_status_to_accepted(self):
        """Accepting updates the proposal status to 'accepted'."""
        proposal = _make_pending_proposal()
        repo = MockProposalReviewRepository(proposals=[proposal])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        await service.accept_proposal("proposal-001", "consultant-001")

        assert len(repo.status_updates) == 1
        update = repo.status_updates[0]
        assert update["proposal_id"] == "proposal-001"
        assert update["status"] == "accepted"
        assert update["merged_content"] == proposal.evidence_summary
        assert update["reviewed_at"] is not None


# ─── Reject Proposal Tests ────────────────────────────────────────────────────


class TestRejectProposal:
    """Tests for reject_proposal: status update to 'rejected'."""

    async def test_reject_marks_proposal_as_rejected(self):
        """Rejecting a proposal sets its status to 'rejected'.

        Validates: Requirement 3.3
        """
        proposal = _make_pending_proposal()
        repo = MockProposalReviewRepository(proposals=[proposal])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        await service.reject_proposal("proposal-001", "consultant-001")

        assert len(repo.status_updates) == 1
        update = repo.status_updates[0]
        assert update["proposal_id"] == "proposal-001"
        assert update["status"] == "rejected"
        assert update["reviewed_at"] is not None

    async def test_reject_does_not_create_audit_or_asset(self):
        """Rejecting a proposal does not insert profile assets or audit entries."""
        proposal = _make_pending_proposal()
        repo = MockProposalReviewRepository(proposals=[proposal])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        await service.reject_proposal("proposal-001", "consultant-001")

        assert len(repo.inserted_assets) == 0
        assert len(repo.audit_entries) == 0


# ─── Edit-Then-Accept Tests ───────────────────────────────────────────────────


class TestEditThenAccept:
    """Tests for accept_proposal with edited_content."""

    async def test_edit_then_accept_stores_edited_content(self):
        """Accepting with edited content stores the edited text instead of original.

        Validates: Requirement 3.1
        """
        proposal = _make_pending_proposal()
        repo = MockProposalReviewRepository(proposals=[proposal])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        edited = "Expert in Kubernetes orchestration and Helm charts"
        result = await service.accept_proposal(
            "proposal-001", "consultant-001", edited_content=edited
        )

        # Verify edited content was stored in profile asset
        assert len(repo.inserted_assets) == 1
        assert repo.inserted_assets[0]["content"] == edited

        # Verify action is ACCEPT_WITH_EDIT
        assert result.action == MergeAction.ACCEPT_WITH_EDIT
        assert result.merged_content == edited

        # Verify audit records the edit flag
        assert len(repo.audit_entries) == 1
        assert repo.audit_entries[0]["edited"] is True
        assert repo.audit_entries[0]["added_content"] == edited

    async def test_edit_then_accept_status_stores_merged_content(self):
        """Status update stores the edited content as merged_content."""
        proposal = _make_pending_proposal()
        repo = MockProposalReviewRepository(proposals=[proposal])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        edited = "Refined: Kubernetes expert"
        await service.accept_proposal(
            "proposal-001", "consultant-001", edited_content=edited
        )

        assert repo.status_updates[0]["merged_content"] == edited


# ─── Bulk Action Tests ────────────────────────────────────────────────────────


class TestBulkAction:
    """Tests for bulk_action: batch processing up to 50 proposals."""

    async def test_bulk_accept_processes_multiple_proposals(self):
        """Bulk accept processes all provided proposals.

        Validates: Requirement 3.1
        """
        proposals = [
            _make_pending_proposal(proposal_id=f"proposal-{i:03d}")
            for i in range(5)
        ]
        repo = MockProposalReviewRepository(proposals=proposals)
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        ids = [f"proposal-{i:03d}" for i in range(5)]
        results = await service.bulk_action(ids, MergeAction.ACCEPT, "consultant-001")

        assert len(results) == 5
        assert all(r.action == MergeAction.ACCEPT for r in results)
        assert len(repo.inserted_assets) == 5
        assert len(repo.audit_entries) == 5

    async def test_bulk_reject_processes_multiple_proposals(self):
        """Bulk reject processes all provided proposals."""
        proposals = [
            _make_pending_proposal(proposal_id=f"proposal-{i:03d}")
            for i in range(5)
        ]
        repo = MockProposalReviewRepository(proposals=proposals)
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        ids = [f"proposal-{i:03d}" for i in range(5)]
        results = await service.bulk_action(ids, MergeAction.REJECT, "consultant-001")

        assert len(results) == 5
        assert all(r.action == MergeAction.REJECT for r in results)
        assert len(repo.inserted_assets) == 0
        assert len(repo.audit_entries) == 0

    async def test_bulk_action_at_max_50_succeeds(self):
        """Bulk action with exactly 50 proposals succeeds."""
        proposals = [
            _make_pending_proposal(proposal_id=f"proposal-{i:03d}")
            for i in range(50)
        ]
        repo = MockProposalReviewRepository(proposals=proposals)
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        ids = [f"proposal-{i:03d}" for i in range(50)]
        results = await service.bulk_action(ids, MergeAction.REJECT, "consultant-001")

        assert len(results) == 50

    async def test_bulk_action_over_50_raises_value_error(self):
        """Bulk action with >50 proposals raises ValueError."""
        proposals = [
            _make_pending_proposal(proposal_id=f"proposal-{i:03d}")
            for i in range(51)
        ]
        repo = MockProposalReviewRepository(proposals=proposals)
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        ids = [f"proposal-{i:03d}" for i in range(51)]
        with pytest.raises(ValueError, match="limited to 50"):
            await service.bulk_action(ids, MergeAction.ACCEPT, "consultant-001")


# ─── Non-Pending Proposal Tests ──────────────────────────────────────────────


class TestNonPendingProposal:
    """Tests that actions on non-pending proposals raise ValueError (409)."""

    async def test_accept_already_accepted_raises_value_error(self):
        """Accepting an already-accepted proposal raises ValueError."""
        proposal = ProposalRecord(
            id="proposal-001",
            consultant_id="consultant-001",
            category="technology",
            name="Kubernetes",
            evidence_summary="K8s evidence",
            raw_evidence="raw",
            confidence="strong",
            source_url="https://github.com/user/repo",
            status="accepted",
            merged_content="merged",
            reviewed_at=datetime.now(timezone.utc),
        )
        repo = MockProposalReviewRepository(proposals=[proposal])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        with pytest.raises(ValueError, match="not in 'pending' status"):
            await service.accept_proposal("proposal-001", "consultant-001")

    async def test_accept_already_rejected_raises_value_error(self):
        """Accepting an already-rejected proposal raises ValueError."""
        proposal = ProposalRecord(
            id="proposal-001",
            consultant_id="consultant-001",
            category="technology",
            name="Kubernetes",
            evidence_summary="K8s evidence",
            raw_evidence="raw",
            confidence="strong",
            source_url="https://github.com/user/repo",
            status="rejected",
            merged_content=None,
            reviewed_at=datetime.now(timezone.utc),
        )
        repo = MockProposalReviewRepository(proposals=[proposal])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        with pytest.raises(ValueError, match="not in 'pending' status"):
            await service.accept_proposal("proposal-001", "consultant-001")

    async def test_reject_already_accepted_raises_value_error(self):
        """Rejecting an already-accepted proposal raises ValueError."""
        proposal = ProposalRecord(
            id="proposal-001",
            consultant_id="consultant-001",
            category="technology",
            name="Kubernetes",
            evidence_summary="K8s evidence",
            raw_evidence="raw",
            confidence="strong",
            source_url="https://github.com/user/repo",
            status="accepted",
            merged_content="merged",
            reviewed_at=datetime.now(timezone.utc),
        )
        repo = MockProposalReviewRepository(proposals=[proposal])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        with pytest.raises(ValueError, match="not in 'pending' status"):
            await service.reject_proposal("proposal-001", "consultant-001")


# ─── Authorization Tests ──────────────────────────────────────────────────────


class TestUnauthorizedAccess:
    """Tests that wrong consultant_id raises PermissionError (403)."""

    async def test_accept_wrong_consultant_raises_permission_error(self):
        """Accepting a proposal owned by another consultant raises PermissionError."""
        proposal = _make_pending_proposal(consultant_id="consultant-001")
        repo = MockProposalReviewRepository(proposals=[proposal])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        with pytest.raises(PermissionError, match="does not own"):
            await service.accept_proposal("proposal-001", "consultant-999")

    async def test_reject_wrong_consultant_raises_permission_error(self):
        """Rejecting a proposal owned by another consultant raises PermissionError."""
        proposal = _make_pending_proposal(consultant_id="consultant-001")
        repo = MockProposalReviewRepository(proposals=[proposal])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        with pytest.raises(PermissionError, match="does not own"):
            await service.reject_proposal("proposal-001", "consultant-999")

    async def test_accept_nonexistent_proposal_raises_value_error(self):
        """Accepting a non-existent proposal raises ValueError."""
        repo = MockProposalReviewRepository(proposals=[])
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)

        with pytest.raises(ValueError, match="not found"):
            await service.accept_proposal("nonexistent-id", "consultant-001")
