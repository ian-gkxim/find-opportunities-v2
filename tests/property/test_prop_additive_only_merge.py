# Feature: internal-profile-enrichment, Property 7: Additive-Only Merge Invariant
"""Property-based tests for additive-only merge invariant.

Tests the ProposalReviewService's core safety guarantee: when a proposal
is accepted, the profile section contains all previous content unchanged
plus the new content appended. No existing content is modified, reordered,
or deleted.

**Validates: Requirements 3.2**
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
    ProfileAssetRow,
    ProposalRecord,
    ProposalReviewService,
)


# ─── In-Memory Repository ────────────────────────────────────────────────────


@dataclass
class InMemoryProposalReviewRepository:
    """In-memory implementation of ProposalReviewRepository for testing.

    Tracks profile asset rows to verify the additive-only invariant:
    - insert_profile_asset only adds rows (never modifies/deletes)
    - Existing rows remain unchanged after any operation
    """

    proposals: dict[str, ProposalRecord] = field(default_factory=dict)
    profile_assets: list[ProfileAssetRow] = field(default_factory=list)
    audit_entries: list[dict] = field(default_factory=list)

    async def get_proposal(self, proposal_id: str) -> ProposalRecord | None:
        return self.proposals.get(proposal_id)

    async def update_proposal_status(
        self,
        proposal_id: str,
        status: str,
        merged_content: str | None = None,
        reviewed_at: datetime | None = None,
    ) -> None:
        if proposal_id in self.proposals:
            proposal = self.proposals[proposal_id]
            self.proposals[proposal_id] = ProposalRecord(
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
        """INSERT a new row — never modifies or deletes existing rows."""
        asset_id = str(uuid.uuid4())
        row = ProfileAssetRow(
            id=asset_id,
            consultant_id=consultant_id,
            section=section,
            content=content,
            source_url=source_url,
            created_at=datetime.now(timezone.utc),
        )
        self.profile_assets.append(row)
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
            {
                "id": entry_id,
                "consultant_id": consultant_id,
                "proposal_id": proposal_id,
                "action": action,
                "added_content": added_content,
                "evidence_source_url": evidence_source_url,
                "profile_section": profile_section,
                "edited": edited,
            }
        )
        return entry_id


# ─── Strategies ───────────────────────────────────────────────────────────────

# Categories used for profile sections
CATEGORIES = [
    "technology",
    "publication",
    "certification",
    "course",
    "project",
    "community_role",
]

category_st = st.sampled_from(CATEGORIES)

# Strategy for profile content rows: non-empty printable strings
content_st = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "P", "Zs"),
        min_codepoint=32,
        max_codepoint=126,
    ),
    min_size=1,
    max_size=100,
).filter(lambda s: s.strip())

# Strategy for generating existing profile asset rows
profile_row_st = st.builds(
    lambda content, section: {
        "content": content,
        "section": section,
    },
    content=content_st,
    section=category_st,
)

# Strategy for proposal content (what the accepted proposal will add)
proposal_content_st = content_st

# Strategy for source URLs
source_url_st = st.from_regex(
    r"https://[a-z]{3,10}\.[a-z]{2,5}/[a-z0-9]{1,20}",
    fullmatch=True,
)


# ─── Helper ───────────────────────────────────────────────────────────────────


def run_async(coro):
    """Helper to run async code in tests."""
    return asyncio.run(coro)


# ─── Property 7: Additive-Only Merge Invariant ───────────────────────────────


class TestProperty7AdditiveOnlyMergeInvariant:
    """Property 7: Additive-Only Merge Invariant.

    **Validates: Requirements 3.2**

    Key invariants:
    - After accept_proposal, all pre-existing profile rows remain unchanged
    - After accept_proposal, exactly one new row is appended
    - No existing content is modified, reordered, or deleted
    - set(profile_after) ⊇ set(profile_before) and len(profile_after) == len(profile_before) + 1
    """

    @given(
        existing_rows=st.lists(profile_row_st, min_size=0, max_size=20),
        proposal_content=proposal_content_st,
        proposal_category=category_st,
        source_url=source_url_st,
    )
    @settings(max_examples=200)
    def test_all_existing_rows_preserved_after_accept(
        self,
        existing_rows: list[dict],
        proposal_content: str,
        proposal_category: str,
        source_url: str,
    ) -> None:
        """FOR ANY profile state and accepted proposal, all pre-existing rows
        remain in the profile unchanged after merge.

        set(profile_after) ⊇ set(profile_before)

        **Validates: Requirements 3.2**
        """
        consultant_id = "consultant-test-123"

        # Set up repository with existing profile rows
        repo = InMemoryProposalReviewRepository()
        for row in existing_rows:
            run_async(
                repo.insert_profile_asset(
                    consultant_id=consultant_id,
                    section=row["section"],
                    content=row["content"],
                    source_url=None,
                )
            )

        # Capture state before merge
        rows_before = [
            (r.content, r.section, r.id) for r in repo.profile_assets
        ]

        # Create a pending proposal
        proposal_id = str(uuid.uuid4())
        repo.proposals[proposal_id] = ProposalRecord(
            id=proposal_id,
            consultant_id=consultant_id,
            category=proposal_category,
            name=f"Test Competency {proposal_id[:8]}",
            evidence_summary=proposal_content,
            raw_evidence=proposal_content,
            confidence="strong",
            source_url=source_url,
            status="pending",
            merged_content=None,
            reviewed_at=None,
        )

        # Accept the proposal
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)
        run_async(
            service.accept_proposal(
                proposal_id=proposal_id,
                consultant_id=consultant_id,
            )
        )

        # Verify all pre-existing rows are still present and unchanged
        rows_after = repo.profile_assets
        for content, section, row_id in rows_before:
            matching = [r for r in rows_after if r.id == row_id]
            assert len(matching) == 1, (
                f"Pre-existing row (id={row_id}) disappeared after merge."
            )
            assert matching[0].content == content, (
                f"Pre-existing row (id={row_id}) content was modified: "
                f"'{content}' → '{matching[0].content}'"
            )
            assert matching[0].section == section, (
                f"Pre-existing row (id={row_id}) section was modified: "
                f"'{section}' → '{matching[0].section}'"
            )

    @given(
        existing_rows=st.lists(profile_row_st, min_size=0, max_size=20),
        proposal_content=proposal_content_st,
        proposal_category=category_st,
        source_url=source_url_st,
    )
    @settings(max_examples=200)
    def test_profile_grows_by_exactly_one_after_accept(
        self,
        existing_rows: list[dict],
        proposal_content: str,
        proposal_category: str,
        source_url: str,
    ) -> None:
        """FOR ANY profile state and accepted proposal, the profile section
        grows by exactly one row.

        len(profile_after) == len(profile_before) + 1

        **Validates: Requirements 3.2**
        """
        consultant_id = "consultant-test-456"

        # Set up repository with existing profile rows
        repo = InMemoryProposalReviewRepository()
        for row in existing_rows:
            run_async(
                repo.insert_profile_asset(
                    consultant_id=consultant_id,
                    section=row["section"],
                    content=row["content"],
                    source_url=None,
                )
            )

        count_before = len(repo.profile_assets)

        # Create a pending proposal
        proposal_id = str(uuid.uuid4())
        repo.proposals[proposal_id] = ProposalRecord(
            id=proposal_id,
            consultant_id=consultant_id,
            category=proposal_category,
            name=f"Test Competency {proposal_id[:8]}",
            evidence_summary=proposal_content,
            raw_evidence=proposal_content,
            confidence="inferred",
            source_url=source_url,
            status="pending",
            merged_content=None,
            reviewed_at=None,
        )

        # Accept the proposal
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)
        run_async(
            service.accept_proposal(
                proposal_id=proposal_id,
                consultant_id=consultant_id,
            )
        )

        count_after = len(repo.profile_assets)
        assert count_after == count_before + 1, (
            f"Expected profile to grow by 1 row "
            f"(before={count_before}, after={count_after})"
        )

    @given(
        existing_rows=st.lists(profile_row_st, min_size=0, max_size=20),
        proposal_content=proposal_content_st,
        proposal_category=category_st,
        source_url=source_url_st,
    )
    @settings(max_examples=200)
    def test_new_row_contains_proposal_content(
        self,
        existing_rows: list[dict],
        proposal_content: str,
        proposal_category: str,
        source_url: str,
    ) -> None:
        """FOR ANY accepted proposal, the newly appended row contains the
        proposal's evidence_summary as its content and uses the proposal's
        category as the section.

        **Validates: Requirements 3.2**
        """
        consultant_id = "consultant-test-789"

        # Set up repository with existing profile rows
        repo = InMemoryProposalReviewRepository()
        for row in existing_rows:
            run_async(
                repo.insert_profile_asset(
                    consultant_id=consultant_id,
                    section=row["section"],
                    content=row["content"],
                    source_url=None,
                )
            )

        existing_ids = {r.id for r in repo.profile_assets}

        # Create a pending proposal
        proposal_id = str(uuid.uuid4())
        repo.proposals[proposal_id] = ProposalRecord(
            id=proposal_id,
            consultant_id=consultant_id,
            category=proposal_category,
            name=f"Test Competency {proposal_id[:8]}",
            evidence_summary=proposal_content,
            raw_evidence=proposal_content,
            confidence="strong",
            source_url=source_url,
            status="pending",
            merged_content=None,
            reviewed_at=None,
        )

        # Accept the proposal
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)
        run_async(
            service.accept_proposal(
                proposal_id=proposal_id,
                consultant_id=consultant_id,
            )
        )

        # Find the newly added row (not in existing_ids)
        new_rows = [r for r in repo.profile_assets if r.id not in existing_ids]
        assert len(new_rows) == 1, (
            f"Expected exactly 1 new row, got {len(new_rows)}"
        )

        new_row = new_rows[0]
        assert new_row.content == proposal_content, (
            f"New row content mismatch: expected '{proposal_content}', "
            f"got '{new_row.content}'"
        )
        assert new_row.section == proposal_category, (
            f"New row section mismatch: expected '{proposal_category}', "
            f"got '{new_row.section}'"
        )

    @given(
        existing_rows=st.lists(profile_row_st, min_size=1, max_size=20),
        proposal_content=proposal_content_st,
        proposal_category=category_st,
        source_url=source_url_st,
    )
    @settings(max_examples=200)
    def test_existing_row_order_preserved_after_accept(
        self,
        existing_rows: list[dict],
        proposal_content: str,
        proposal_category: str,
        source_url: str,
    ) -> None:
        """FOR ANY profile state with existing rows, the order of pre-existing
        rows is preserved after merge. No reordering occurs.

        **Validates: Requirements 3.2**
        """
        consultant_id = "consultant-test-order"

        # Set up repository with existing profile rows
        repo = InMemoryProposalReviewRepository()
        for row in existing_rows:
            run_async(
                repo.insert_profile_asset(
                    consultant_id=consultant_id,
                    section=row["section"],
                    content=row["content"],
                    source_url=None,
                )
            )

        # Capture ordered IDs before merge
        ids_before = [r.id for r in repo.profile_assets]

        # Create a pending proposal
        proposal_id = str(uuid.uuid4())
        repo.proposals[proposal_id] = ProposalRecord(
            id=proposal_id,
            consultant_id=consultant_id,
            category=proposal_category,
            name=f"Test Competency {proposal_id[:8]}",
            evidence_summary=proposal_content,
            raw_evidence=proposal_content,
            confidence="strong",
            source_url=source_url,
            status="pending",
            merged_content=None,
            reviewed_at=None,
        )

        # Accept the proposal
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)
        run_async(
            service.accept_proposal(
                proposal_id=proposal_id,
                consultant_id=consultant_id,
            )
        )

        # Verify order of pre-existing rows is unchanged
        ids_after = [r.id for r in repo.profile_assets]
        # Pre-existing IDs should appear in the same order
        preserved_ids = [rid for rid in ids_after if rid in set(ids_before)]
        assert preserved_ids == ids_before, (
            f"Order of pre-existing rows was modified after merge. "
            f"Before: {ids_before}, After (filtered): {preserved_ids}"
        )

    @given(
        existing_rows=st.lists(profile_row_st, min_size=0, max_size=15),
        proposal_content=proposal_content_st,
        edited_content=proposal_content_st,
        proposal_category=category_st,
        source_url=source_url_st,
    )
    @settings(max_examples=200)
    def test_edit_then_accept_preserves_existing_rows(
        self,
        existing_rows: list[dict],
        proposal_content: str,
        edited_content: str,
        proposal_category: str,
        source_url: str,
    ) -> None:
        """FOR ANY profile state and edited acceptance, all pre-existing rows
        remain unchanged and the edited content (not original) is appended.

        **Validates: Requirements 3.2**
        """
        consultant_id = "consultant-test-edit"

        # Set up repository with existing profile rows
        repo = InMemoryProposalReviewRepository()
        for row in existing_rows:
            run_async(
                repo.insert_profile_asset(
                    consultant_id=consultant_id,
                    section=row["section"],
                    content=row["content"],
                    source_url=None,
                )
            )

        # Capture state before merge
        rows_before = [
            (r.content, r.section, r.id) for r in repo.profile_assets
        ]
        count_before = len(repo.profile_assets)
        existing_ids = {r.id for r in repo.profile_assets}

        # Create a pending proposal
        proposal_id = str(uuid.uuid4())
        repo.proposals[proposal_id] = ProposalRecord(
            id=proposal_id,
            consultant_id=consultant_id,
            category=proposal_category,
            name=f"Test Competency {proposal_id[:8]}",
            evidence_summary=proposal_content,
            raw_evidence=proposal_content,
            confidence="strong",
            source_url=source_url,
            status="pending",
            merged_content=None,
            reviewed_at=None,
        )

        # Accept the proposal with edited content
        service = ProposalReviewService(db_repo=repo, websocket_manager=None)
        run_async(
            service.accept_proposal(
                proposal_id=proposal_id,
                consultant_id=consultant_id,
                edited_content=edited_content,
            )
        )

        # Verify all pre-existing rows are unchanged
        for content, section, row_id in rows_before:
            matching = [r for r in repo.profile_assets if r.id == row_id]
            assert len(matching) == 1, (
                f"Pre-existing row (id={row_id}) disappeared after edit+accept."
            )
            assert matching[0].content == content, (
                f"Pre-existing row content modified after edit+accept."
            )

        # Verify exactly one new row added with the EDITED content
        count_after = len(repo.profile_assets)
        assert count_after == count_before + 1, (
            f"Expected profile to grow by 1 after edit+accept "
            f"(before={count_before}, after={count_after})"
        )

        new_rows = [r for r in repo.profile_assets if r.id not in existing_ids]
        assert len(new_rows) == 1
        assert new_rows[0].content == edited_content, (
            f"Edited content not used: expected '{edited_content}', "
            f"got '{new_rows[0].content}'"
        )
