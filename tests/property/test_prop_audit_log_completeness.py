# Feature: internal-profile-enrichment, Property 8: Audit Log Completeness
"""Property-based tests for audit log completeness.

Tests that for any accepted and merged proposal, exactly one audit log entry
is created containing: non-null timestamp, added_content matching merged content,
evidence_source_url from proposal, and target profile_section.

**Validates: Requirements 3.4**
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.core.proposal_review_service import (
    MergeAction,
    MergeResult,
    ProposalRecord,
    ProposalReviewRepository,
    ProposalReviewService,
)


# ─── Audit Entry Record ──────────────────────────────────────────────────────


@dataclass
class AuditEntry:
    """Recorded audit entry for verification."""

    id: str
    consultant_id: str
    proposal_id: str
    action: str
    added_content: str
    evidence_source_url: str
    profile_section: str
    edited: bool
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ─── Mock Repository ─────────────────────────────────────────────────────────


class AuditTrackingRepository:
    """In-memory repository that records all audit entries created.

    Tracks every call to create_audit_entry so we can verify
    exactly one entry is created per accept with correct fields.
    """

    def __init__(self, proposals: dict[str, ProposalRecord]):
        self._proposals = proposals
        self.audit_entries: list[AuditEntry] = []
        self.profile_assets: list[dict] = []
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
        # Update the in-memory proposal status
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
                merged_content=merged_content,
                reviewed_at=reviewed_at,
            )

    async def insert_profile_asset(
        self,
        consultant_id: str,
        section: str,
        content: str,
        source_url: str | None = None,
    ) -> str:
        asset_id = str(uuid.uuid4())
        self.profile_assets.append(
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
        entry_id = str(uuid.uuid4())
        self.audit_entries.append(
            AuditEntry(
                id=entry_id,
                consultant_id=consultant_id,
                proposal_id=proposal_id,
                action=action,
                added_content=added_content,
                evidence_source_url=evidence_source_url,
                profile_section=profile_section,
                edited=edited,
            )
        )
        return entry_id


# ─── Strategies ───────────────────────────────────────────────────────────────

CATEGORIES = [
    "technology",
    "publication",
    "certification",
    "course",
    "project",
    "community_role",
]

category_st = st.sampled_from(CATEGORIES)

# Non-empty text for proposal content fields
content_st = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs"), min_codepoint=32, max_codepoint=122),
    min_size=1,
    max_size=100,
).filter(lambda s: len(s.strip()) >= 1)

# Strategy for source URLs
source_url_st = st.builds(
    lambda domain, path: f"https://{domain}.com/{path}",
    domain=st.text(
        alphabet=st.characters(whitelist_categories=("Ll",), min_codepoint=97, max_codepoint=122),
        min_size=3,
        max_size=10,
    ),
    path=st.text(
        alphabet=st.characters(whitelist_categories=("Ll", "Nd"), min_codepoint=48, max_codepoint=122),
        min_size=1,
        max_size=20,
    ),
)

# Strategy for generating proposal data
proposal_data_st = st.fixed_dictionaries(
    {
        "category": category_st,
        "name": content_st,
        "evidence_summary": content_st,
        "source_url": source_url_st,
    }
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def run_async(coro):
    """Helper to run async code in tests."""
    return asyncio.run(coro)


def make_proposal(
    proposal_id: str,
    consultant_id: str,
    category: str,
    name: str,
    evidence_summary: str,
    source_url: str,
) -> ProposalRecord:
    """Create a pending ProposalRecord for testing."""
    return ProposalRecord(
        id=proposal_id,
        consultant_id=consultant_id,
        category=category,
        name=name,
        evidence_summary=evidence_summary,
        raw_evidence=None,
        confidence="strong",
        source_url=source_url,
        status="pending",
        merged_content=None,
        reviewed_at=None,
    )


# ─── Property 8: Audit Log Completeness ──────────────────────────────────────


class TestProperty8AuditLogCompleteness:
    """Property 8: Audit Log Completeness.

    **Validates: Requirements 3.4**

    Key invariants:
    - For any accepted proposal, exactly one audit log entry is created
    - The audit entry has non-null/non-empty added_content matching merged content
    - The audit entry has evidence_source_url matching the proposal's source_url
    - The audit entry has profile_section matching the proposal's category
    - The audit entry action is 'accept' or 'accept_with_edit'
    """

    @given(data=proposal_data_st)
    @settings(max_examples=200)
    def test_accept_creates_exactly_one_audit_entry(
        self,
        data: dict,
    ) -> None:
        """FOR ANY accepted proposal, exactly one audit log entry is created.

        **Validates: Requirements 3.4**
        """
        proposal_id = str(uuid.uuid4())
        consultant_id = str(uuid.uuid4())

        proposal = make_proposal(
            proposal_id=proposal_id,
            consultant_id=consultant_id,
            category=data["category"],
            name=data["name"],
            evidence_summary=data["evidence_summary"],
            source_url=data["source_url"],
        )

        repo = AuditTrackingRepository(proposals={proposal_id: proposal})
        service = ProposalReviewService(db_repo=repo)

        run_async(service.accept_proposal(proposal_id, consultant_id))

        # Exactly one audit entry must be created
        assert len(repo.audit_entries) == 1, (
            f"Expected exactly 1 audit entry, got {len(repo.audit_entries)}"
        )

    @given(data=proposal_data_st)
    @settings(max_examples=200)
    def test_audit_entry_added_content_matches_merged_content(
        self,
        data: dict,
    ) -> None:
        """FOR ANY accepted proposal (without edit), the audit entry's
        added_content matches the proposal's evidence_summary (the merged content).

        **Validates: Requirements 3.4**
        """
        proposal_id = str(uuid.uuid4())
        consultant_id = str(uuid.uuid4())

        proposal = make_proposal(
            proposal_id=proposal_id,
            consultant_id=consultant_id,
            category=data["category"],
            name=data["name"],
            evidence_summary=data["evidence_summary"],
            source_url=data["source_url"],
        )

        repo = AuditTrackingRepository(proposals={proposal_id: proposal})
        service = ProposalReviewService(db_repo=repo)

        result = run_async(service.accept_proposal(proposal_id, consultant_id))

        audit_entry = repo.audit_entries[0]

        # added_content must be non-null and non-empty
        assert audit_entry.added_content is not None, (
            "Audit entry added_content must not be None"
        )
        assert len(audit_entry.added_content) > 0, (
            "Audit entry added_content must not be empty"
        )

        # added_content must match the merged content
        assert audit_entry.added_content == result.merged_content, (
            f"Audit added_content '{audit_entry.added_content}' does not match "
            f"merged content '{result.merged_content}'"
        )

        # For non-edited accept, merged content is evidence_summary
        assert audit_entry.added_content == data["evidence_summary"], (
            f"Audit added_content '{audit_entry.added_content}' does not match "
            f"proposal evidence_summary '{data['evidence_summary']}'"
        )

    @given(data=proposal_data_st)
    @settings(max_examples=200)
    def test_audit_entry_evidence_source_url_matches_proposal(
        self,
        data: dict,
    ) -> None:
        """FOR ANY accepted proposal, the audit entry's evidence_source_url
        matches the proposal's source_url.

        **Validates: Requirements 3.4**
        """
        proposal_id = str(uuid.uuid4())
        consultant_id = str(uuid.uuid4())

        proposal = make_proposal(
            proposal_id=proposal_id,
            consultant_id=consultant_id,
            category=data["category"],
            name=data["name"],
            evidence_summary=data["evidence_summary"],
            source_url=data["source_url"],
        )

        repo = AuditTrackingRepository(proposals={proposal_id: proposal})
        service = ProposalReviewService(db_repo=repo)

        run_async(service.accept_proposal(proposal_id, consultant_id))

        audit_entry = repo.audit_entries[0]

        # evidence_source_url must match proposal's source_url
        assert audit_entry.evidence_source_url == data["source_url"], (
            f"Audit evidence_source_url '{audit_entry.evidence_source_url}' "
            f"does not match proposal source_url '{data['source_url']}'"
        )

    @given(data=proposal_data_st)
    @settings(max_examples=200)
    def test_audit_entry_profile_section_matches_proposal_category(
        self,
        data: dict,
    ) -> None:
        """FOR ANY accepted proposal, the audit entry's profile_section
        matches the proposal's category.

        **Validates: Requirements 3.4**
        """
        proposal_id = str(uuid.uuid4())
        consultant_id = str(uuid.uuid4())

        proposal = make_proposal(
            proposal_id=proposal_id,
            consultant_id=consultant_id,
            category=data["category"],
            name=data["name"],
            evidence_summary=data["evidence_summary"],
            source_url=data["source_url"],
        )

        repo = AuditTrackingRepository(proposals={proposal_id: proposal})
        service = ProposalReviewService(db_repo=repo)

        run_async(service.accept_proposal(proposal_id, consultant_id))

        audit_entry = repo.audit_entries[0]

        # profile_section must match proposal's category
        assert audit_entry.profile_section == data["category"], (
            f"Audit profile_section '{audit_entry.profile_section}' "
            f"does not match proposal category '{data['category']}'"
        )

    @given(data=proposal_data_st)
    @settings(max_examples=200)
    def test_audit_entry_action_is_accept_without_edit(
        self,
        data: dict,
    ) -> None:
        """FOR ANY accepted proposal (without edit), the audit entry's action
        is 'accept'.

        **Validates: Requirements 3.4**
        """
        proposal_id = str(uuid.uuid4())
        consultant_id = str(uuid.uuid4())

        proposal = make_proposal(
            proposal_id=proposal_id,
            consultant_id=consultant_id,
            category=data["category"],
            name=data["name"],
            evidence_summary=data["evidence_summary"],
            source_url=data["source_url"],
        )

        repo = AuditTrackingRepository(proposals={proposal_id: proposal})
        service = ProposalReviewService(db_repo=repo)

        run_async(service.accept_proposal(proposal_id, consultant_id))

        audit_entry = repo.audit_entries[0]

        assert audit_entry.action == "accept", (
            f"Audit action '{audit_entry.action}' should be 'accept' "
            f"for non-edited proposal"
        )

    @given(
        data=proposal_data_st,
        edited_content=content_st,
    )
    @settings(max_examples=200)
    def test_edit_case_audit_entry_matches_edited_content(
        self,
        data: dict,
        edited_content: str,
    ) -> None:
        """FOR ANY accepted proposal with edited_content, the audit entry's
        added_content matches the edited_content (not the original evidence_summary),
        and the action is 'accept_with_edit'.

        **Validates: Requirements 3.4**
        """
        proposal_id = str(uuid.uuid4())
        consultant_id = str(uuid.uuid4())

        proposal = make_proposal(
            proposal_id=proposal_id,
            consultant_id=consultant_id,
            category=data["category"],
            name=data["name"],
            evidence_summary=data["evidence_summary"],
            source_url=data["source_url"],
        )

        repo = AuditTrackingRepository(proposals={proposal_id: proposal})
        service = ProposalReviewService(db_repo=repo)

        result = run_async(
            service.accept_proposal(proposal_id, consultant_id, edited_content=edited_content)
        )

        # Exactly one audit entry
        assert len(repo.audit_entries) == 1, (
            f"Expected exactly 1 audit entry, got {len(repo.audit_entries)}"
        )

        audit_entry = repo.audit_entries[0]

        # added_content must match the edited_content (not evidence_summary)
        assert audit_entry.added_content == edited_content, (
            f"Audit added_content '{audit_entry.added_content}' does not match "
            f"edited_content '{edited_content}'"
        )

        # merged content in result must also match edited_content
        assert result.merged_content == edited_content, (
            f"MergeResult merged_content '{result.merged_content}' does not "
            f"match edited_content '{edited_content}'"
        )

        # Action must be 'accept_with_edit'
        assert audit_entry.action == "accept_with_edit", (
            f"Audit action '{audit_entry.action}' should be 'accept_with_edit' "
            f"for edited proposal"
        )

        # evidence_source_url still matches the proposal's source_url
        assert audit_entry.evidence_source_url == data["source_url"], (
            f"Audit evidence_source_url '{audit_entry.evidence_source_url}' "
            f"does not match proposal source_url '{data['source_url']}'"
        )

        # profile_section still matches the proposal's category
        assert audit_entry.profile_section == data["category"], (
            f"Audit profile_section '{audit_entry.profile_section}' "
            f"does not match proposal category '{data['category']}'"
        )
