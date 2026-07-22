"""Proposal Review Service — accept, reject, bulk operations, merge.

Enforces the additive-only constraint: accepted proposals APPEND to
profile asset sections. No existing content is ever modified or deleted.
All merges are recorded in the audit log.

Requirements: 3.1, 3.2, 3.3, 3.4
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol

logger = logging.getLogger(__name__)


# ─── Data Models ──────────────────────────────────────────────────────────────


class MergeAction(str, Enum):
    """Action taken on a proposal during review."""

    ACCEPT = "accept"
    ACCEPT_WITH_EDIT = "accept_with_edit"
    REJECT = "reject"


@dataclass
class MergeResult:
    """Result of merging an accepted proposal into the profile."""

    proposal_id: str
    action: MergeAction
    merged_content: str | None  # The content appended (None for reject)
    profile_section: str  # Which profile asset section was modified
    audit_log_id: str  # Reference to the audit log entry


@dataclass
class ProfileAssetRow:
    """Represents a single row in the profile assets table."""

    id: str
    consultant_id: str
    section: str
    content: str
    source_url: str | None
    created_at: datetime


@dataclass
class ProposalRecord:
    """A competency proposal as retrieved from the database."""

    id: str
    consultant_id: str
    category: str
    name: str
    evidence_summary: str
    raw_evidence: str | None
    confidence: str
    source_url: str
    status: str
    merged_content: str | None
    reviewed_at: datetime | None


# ─── Repository Protocol ─────────────────────────────────────────────────────


class ProposalReviewRepository(Protocol):
    """Protocol for the data access layer used by ProposalReviewService.

    Implementations must provide methods to query and update proposals,
    append to profile assets, and create audit entries.
    """

    async def get_proposal(self, proposal_id: str) -> ProposalRecord | None:
        """Retrieve a proposal by ID."""
        ...

    async def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        merged_content: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> None:
        """Update a proposal's status and optional merge metadata."""
        ...

    async def insert_profile_asset(
        self,
        consultant_id: str,
        section: str,
        content: str,
        source_url: str | None = None,
    ) -> str:
        """INSERT a new row into the profile assets table.

        Returns the ID of the newly created row.
        CRITICAL: This must only INSERT, never UPDATE or DELETE existing rows.
        """
        ...

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
        """Create an immutable audit log entry. Returns the audit entry ID."""
        ...


# ─── Service ─────────────────────────────────────────────────────────────────


class ProposalReviewService:
    """Manages the Consultant review workflow for competency proposals.

    Enforces the additive-only constraint: accepted proposals APPEND to
    profile asset sections. No existing content is ever modified or deleted.

    Dependencies:
        db_repo: ProposalReviewRepository for data access.
        websocket_manager: WebSocketManager for real-time notifications.
    """

    MAX_BULK_SIZE = 50  # max proposals per bulk operation

    def __init__(self, db_repo: ProposalReviewRepository, websocket_manager=None):
        self._db = db_repo
        self._ws = websocket_manager

    async def accept_proposal(
        self,
        proposal_id: str,
        consultant_id: str,
        edited_content: str | None = None,
    ) -> MergeResult:
        """Accept a proposal and merge into the profile (additive-only).

        Steps:
            1. Verify proposal exists and belongs to consultant
            2. Verify proposal is in 'pending' status
            3. Determine content to merge (edited_content or evidence_summary)
            4. Append content to profile asset section (INSERT only)
            5. Update proposal status to 'accepted'
            6. Create immutable audit log entry

        Args:
            proposal_id: The proposal to accept.
            consultant_id: The owning Consultant (authorization check).
            edited_content: If provided, use this instead of the proposal content.

        Returns:
            MergeResult with details of what was appended.

        Raises:
            PermissionError: If consultant_id doesn't own the proposal.
            ValueError: If proposal is not in 'pending' status.
        """
        # 1. Fetch and verify ownership
        proposal = await self._get_and_authorize(proposal_id, consultant_id)

        # 2. Verify pending status
        if proposal.status != "pending":
            raise ValueError(
                f"Proposal {proposal_id} is not in 'pending' status "
                f"(current: '{proposal.status}')"
            )

        # 3. Determine content to merge
        is_edited = edited_content is not None
        content_to_merge = edited_content if is_edited else proposal.evidence_summary
        action = MergeAction.ACCEPT_WITH_EDIT if is_edited else MergeAction.ACCEPT
        profile_section = proposal.category

        # 4. Append to profile (INSERT only, never UPDATE/DELETE)
        await self._append_to_profile(
            consultant_id=consultant_id,
            content=content_to_merge,
            section=profile_section,
            source_url=proposal.source_url,
        )

        # 5. Update proposal status
        now = datetime.now(timezone.utc)
        await self._db.update_proposal_status(
            proposal_id=proposal_id,
            status="accepted",
            merged_content=content_to_merge,
            reviewed_at=now,
        )

        # 6. Create audit entry
        audit_log_id = await self._create_audit_entry(
            consultant_id=consultant_id,
            proposal_id=proposal_id,
            action=action,
            content=content_to_merge,
            source_url=proposal.source_url,
            section=profile_section,
            edited=is_edited,
        )

        logger.info(
            "Proposal accepted: proposal=%s, consultant=%s, edited=%s",
            proposal_id,
            consultant_id,
            is_edited,
        )

        return MergeResult(
            proposal_id=proposal_id,
            action=action,
            merged_content=content_to_merge,
            profile_section=profile_section,
            audit_log_id=audit_log_id,
        )

    async def reject_proposal(
        self, proposal_id: str, consultant_id: str
    ) -> None:
        """Reject a proposal. Records rejection to prevent re-proposal.

        The rejection status is used by the deduplicator to prevent
        re-proposing the same item in future scan cycles.

        Args:
            proposal_id: The proposal to reject.
            consultant_id: The owning Consultant (authorization check).

        Raises:
            PermissionError: If consultant_id doesn't own the proposal.
            ValueError: If proposal is not in 'pending' status.
        """
        # Verify ownership and status
        proposal = await self._get_and_authorize(proposal_id, consultant_id)

        if proposal.status != "pending":
            raise ValueError(
                f"Proposal {proposal_id} is not in 'pending' status "
                f"(current: '{proposal.status}')"
            )

        # Update proposal status to rejected
        now = datetime.now(timezone.utc)
        await self._db.update_proposal_status(
            proposal_id=proposal_id,
            status="rejected",
            reviewed_at=now,
        )

        logger.info(
            "Proposal rejected: proposal=%s, consultant=%s",
            proposal_id,
            consultant_id,
        )

    async def bulk_action(
        self,
        proposal_ids: list[str],
        action: MergeAction,
        consultant_id: str,
    ) -> list[MergeResult]:
        """Process up to MAX_BULK_SIZE proposals in a single operation.

        Enforces the bulk size limit. Each proposal is processed individually
        to maintain proper authorization and status checks.

        Args:
            proposal_ids: List of proposal IDs to process.
            action: The action to apply (ACCEPT or REJECT).
            consultant_id: The owning Consultant (authorization check).

        Returns:
            List of MergeResult for accepted proposals (empty for rejects).

        Raises:
            ValueError: If proposal_ids exceeds MAX_BULK_SIZE.
        """
        if len(proposal_ids) > self.MAX_BULK_SIZE:
            raise ValueError(
                f"Bulk action limited to {self.MAX_BULK_SIZE} proposals, "
                f"got {len(proposal_ids)}"
            )

        results: list[MergeResult] = []

        for pid in proposal_ids:
            if action == MergeAction.REJECT:
                await self.reject_proposal(pid, consultant_id)
                results.append(
                    MergeResult(
                        proposal_id=pid,
                        action=MergeAction.REJECT,
                        merged_content=None,
                        profile_section="",
                        audit_log_id="",
                    )
                )
            else:
                # ACCEPT or ACCEPT_WITH_EDIT (bulk doesn't support editing)
                result = await self.accept_proposal(pid, consultant_id)
                results.append(result)

        logger.info(
            "Bulk action completed: action=%s, count=%d, consultant=%s",
            action.value,
            len(proposal_ids),
            consultant_id,
        )

        return results

    # ─── PRIVATE METHODS ──────────────────────────────────────────────────────

    async def _get_and_authorize(
        self, proposal_id: str, consultant_id: str
    ) -> ProposalRecord:
        """Fetch a proposal and verify the consultant owns it.

        Args:
            proposal_id: The proposal to retrieve.
            consultant_id: The consultant claiming ownership.

        Returns:
            The ProposalRecord if authorized.

        Raises:
            ValueError: If proposal does not exist.
            PermissionError: If consultant does not own the proposal.
        """
        proposal = await self._db.get_proposal(proposal_id)

        if proposal is None:
            raise ValueError(f"Proposal {proposal_id} not found")

        if proposal.consultant_id != consultant_id:
            raise PermissionError(
                f"Consultant {consultant_id} does not own proposal {proposal_id}"
            )

        return proposal

    async def _append_to_profile(
        self,
        consultant_id: str,
        content: str,
        section: str,
        source_url: str | None = None,
    ) -> None:
        """Append content to the specified profile asset section.

        CRITICAL: This method only ever appends (INSERT). It never modifies
        or deletes existing content. The implementation uses an INSERT into
        the profile_assets table, preserving all existing rows unchanged.

        Args:
            consultant_id: The consultant whose profile to append to.
            content: The content to append.
            section: The profile asset section (e.g., 'technology', 'publication').
            source_url: The evidence source URL for attribution.
        """
        await self._db.insert_profile_asset(
            consultant_id=consultant_id,
            section=section,
            content=content,
            source_url=source_url,
        )

    async def _create_audit_entry(
        self,
        consultant_id: str,
        proposal_id: str,
        action: MergeAction,
        content: str,
        source_url: str,
        section: str,
        edited: bool,
    ) -> str:
        """Create an immutable audit log entry for the profile change.

        Records all required fields for traceability: who, what, when,
        where (section), and whether the content was edited before acceptance.

        Args:
            consultant_id: The consultant who approved the change.
            proposal_id: The proposal being merged.
            action: The merge action taken.
            content: The content that was appended.
            source_url: The evidence source URL.
            section: The profile section that was modified.
            edited: Whether the content was edited before acceptance.

        Returns:
            The audit log entry ID.
        """
        audit_id = await self._db.create_audit_entry(
            consultant_id=consultant_id,
            proposal_id=proposal_id,
            action=action.value,
            added_content=content,
            evidence_source_url=source_url,
            profile_section=section,
            edited=edited,
        )

        logger.debug(
            "Audit entry created: audit_id=%s, proposal=%s, action=%s",
            audit_id,
            proposal_id,
            action.value,
        )

        return audit_id
