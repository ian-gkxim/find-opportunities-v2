"""Unit tests for Profile Enrichment API routes.

Tests requirements 1.1, 3.1:
- POST /profile-enrichment/sources — add source succeeds (201)
- POST /profile-enrichment/sources — add 11th source fails (422)
- GET /profile-enrichment/proposals — list proposals with status filter
- POST /profile-enrichment/proposals/{id}/accept — valid proposal succeeds
- POST /profile-enrichment/proposals/{id}/reject — valid proposal succeeds
- POST /profile-enrichment/proposals/{id}/accept — non-existent proposal returns 409
- POST /profile-enrichment/proposals/{id}/accept — wrong consultant returns 403
- POST /profile-enrichment/proposals/bulk — >50 proposals returns 422
- DELETE /profile-enrichment/sources/{id} — wrong consultant returns 404
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.profile_enrichment import router


# ─── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def test_app() -> FastAPI:
    """Create a minimal FastAPI app with only the profile enrichment routes."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
async def client(test_app: FastAPI):
    """Provide an httpx AsyncClient for the test app."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ─── Mock Helpers ─────────────────────────────────────────────────────────────


def _make_mock_source(
    source_id: str | None = None,
    consultant_id: str = "consultant-001",
    source_type: str = "github",
    url: str = "https://github.com/testuser",
    label: str = "My GitHub",
) -> MagicMock:
    """Create a mock PublicSource ORM object."""
    source = MagicMock()
    source.id = uuid.UUID(source_id) if source_id else uuid.uuid4()
    source.consultant_id = consultant_id
    source.source_type = source_type
    source.url = url
    source.label = label
    source.last_scanned_at = None
    source.consecutive_failures = 0
    source.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    source.scan_interval_days = 30
    source.is_active = True
    return source


def _create_mock_session_factory(session):
    """Create a mock session factory that returns our mock session as async context manager."""
    mock_factory = MagicMock()

    async_ctx = AsyncMock()
    async_ctx.__aenter__ = AsyncMock(return_value=session)
    async_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_factory.return_value = async_ctx

    return mock_factory


# Patch target: these are imported inside route functions from app.models.base
PATCH_ENGINE = "app.models.base.get_async_engine"
PATCH_SESSION_FACTORY = "app.models.base.get_async_session_factory"


# ─── Source Configuration Tests ───────────────────────────────────────────────


class TestAddSource:
    """Tests for POST /profile-enrichment/sources."""

    async def test_add_source_succeeds_with_201(self, client: AsyncClient):
        """POST /sources with valid data and <10 existing sources returns 201.

        Validates: Requirement 1.1
        """
        session = AsyncMock()

        # First execute: count query returning 5 (under the limit)
        count_result = MagicMock()
        count_result.scalar_one.return_value = 5

        call_count = [0]

        async def execute_side_effect(stmt):
            call_count[0] += 1
            if call_count[0] == 1:
                return count_result
            return MagicMock()

        session.execute = AsyncMock(side_effect=execute_side_effect)
        session.add = MagicMock()
        session.commit = AsyncMock()

        # Simulate refresh populating the new source object
        async def refresh_side_effect(obj):
            obj.id = uuid.uuid4()
            obj.source_type = "github"
            obj.url = "https://github.com/testuser"
            obj.label = "My GitHub"
            obj.last_scanned_at = None
            obj.consecutive_failures = 0
            obj.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
            obj.scan_interval_days = 30
            obj.is_active = True

        session.refresh = AsyncMock(side_effect=refresh_side_effect)

        mock_engine = MagicMock()
        mock_session_factory = _create_mock_session_factory(session)

        with (
            patch(PATCH_ENGINE, return_value=mock_engine),
            patch(PATCH_SESSION_FACTORY, return_value=mock_session_factory),
        ):
            response = await client.post(
                "/profile-enrichment/sources",
                params={"consultant_id": "consultant-001"},
                json={
                    "source_type": "github",
                    "url": "https://github.com/testuser",
                    "label": "My GitHub",
                },
            )

        assert response.status_code == 201
        data = response.json()
        assert data["source_type"] == "github"
        assert data["url"] == "https://github.com/testuser"
        assert data["label"] == "My GitHub"
        assert data["is_active"] is True

    async def test_add_11th_source_fails_with_422(self, client: AsyncClient):
        """POST /sources when consultant already has 10 sources returns 422.

        Validates: Requirement 1.1 (max 10 sources per Consultant)
        """
        session = AsyncMock()

        # Count query returns 10 (at the limit)
        count_result = MagicMock()
        count_result.scalar_one.return_value = 10
        session.execute = AsyncMock(return_value=count_result)
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        mock_engine = MagicMock()
        mock_session_factory = _create_mock_session_factory(session)

        with (
            patch(PATCH_ENGINE, return_value=mock_engine),
            patch(PATCH_SESSION_FACTORY, return_value=mock_session_factory),
        ):
            response = await client.post(
                "/profile-enrichment/sources",
                params={"consultant_id": "consultant-001"},
                json={
                    "source_type": "github",
                    "url": "https://github.com/newrepo",
                    "label": "Overflow Source",
                },
            )

        assert response.status_code == 422
        data = response.json()
        assert "Maximum of 10" in data["detail"]


class TestDeleteSource:
    """Tests for DELETE /profile-enrichment/sources/{source_id}."""

    async def test_delete_wrong_consultant_returns_404(self, client: AsyncClient):
        """DELETE /sources/{id} with a source_id not belonging to the consultant returns 404.

        Validates: Requirement 1.1 (authorization — Consultant A cannot access Consultant B resources)
        """
        session = AsyncMock()

        # The query returns None (source not found for this consultant)
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=result_mock)
        session.commit = AsyncMock()

        mock_engine = MagicMock()
        mock_session_factory = _create_mock_session_factory(session)

        source_id = str(uuid.uuid4())

        with (
            patch(PATCH_ENGINE, return_value=mock_engine),
            patch(PATCH_SESSION_FACTORY, return_value=mock_session_factory),
        ):
            response = await client.delete(
                f"/profile-enrichment/sources/{source_id}",
                params={"consultant_id": "consultant-999"},
            )

        assert response.status_code == 404
        data = response.json()
        assert "not found" in data["detail"].lower()


# ─── Proposal List Tests ──────────────────────────────────────────────────────


class TestListProposals:
    """Tests for GET /profile-enrichment/proposals."""

    async def test_list_proposals_returns_filtered_results(self, client: AsyncClient):
        """GET /proposals with status filter returns correctly filtered proposals.

        Validates: Requirement 3.1
        """
        session = AsyncMock()

        # Create mock proposal (simulating what the join query returns)
        mock_proposal = MagicMock()
        mock_proposal.id = uuid.uuid4()
        mock_proposal.category = "technology"
        mock_proposal.name = "Kubernetes"
        mock_proposal.evidence_summary = "Owner of k8s-operator repo"
        mock_proposal.confidence = "strong"
        mock_proposal.source_url = "https://github.com/user/k8s-operator"
        mock_proposal.status = "pending"
        mock_proposal.created_at = datetime(2024, 1, 15, tzinfo=timezone.utc)

        # The query returns tuples of (proposal, source_label)
        result_mock = MagicMock()
        result_mock.all.return_value = [(mock_proposal, "GitHub Profile")]
        session.execute = AsyncMock(return_value=result_mock)

        mock_engine = MagicMock()
        mock_session_factory = _create_mock_session_factory(session)

        with (
            patch(PATCH_ENGINE, return_value=mock_engine),
            patch(PATCH_SESSION_FACTORY, return_value=mock_session_factory),
        ):
            response = await client.get(
                "/profile-enrichment/proposals",
                params={"consultant_id": "consultant-001", "status": "pending"},
            )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "Kubernetes"
        assert data[0]["confidence"] == "strong"
        assert data[0]["source_label"] == "GitHub Profile"
        assert data[0]["status"] == "pending"

    async def test_list_proposals_empty_when_no_results(self, client: AsyncClient):
        """GET /proposals returns empty list when no proposals match filter.

        Validates: Requirement 3.1
        """
        session = AsyncMock()

        result_mock = MagicMock()
        result_mock.all.return_value = []
        session.execute = AsyncMock(return_value=result_mock)

        mock_engine = MagicMock()
        mock_session_factory = _create_mock_session_factory(session)

        with (
            patch(PATCH_ENGINE, return_value=mock_engine),
            patch(PATCH_SESSION_FACTORY, return_value=mock_session_factory),
        ):
            response = await client.get(
                "/profile-enrichment/proposals",
                params={"consultant_id": "consultant-001", "status": "accepted"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data == []


# ─── Accept/Reject Proposal Tests ────────────────────────────────────────────


class TestAcceptProposal:
    """Tests for POST /profile-enrichment/proposals/{id}/accept."""

    async def test_accept_valid_proposal_succeeds(self, client: AsyncClient):
        """POST /proposals/{id}/accept with valid pending proposal returns 200.

        Validates: Requirement 3.1
        """
        from app.core.proposal_review_service import MergeAction, MergeResult

        mock_merge_result = MergeResult(
            proposal_id="proposal-001",
            action=MergeAction.ACCEPT,
            merged_content="Owner of k8s-operator repo",
            profile_section="technology",
            audit_log_id="audit-001",
        )

        session = AsyncMock()
        session.commit = AsyncMock()

        mock_engine = MagicMock()
        mock_session_factory = _create_mock_session_factory(session)

        with (
            patch(PATCH_ENGINE, return_value=mock_engine),
            patch(PATCH_SESSION_FACTORY, return_value=mock_session_factory),
            patch(
                "app.core.proposal_review_service.ProposalReviewService.accept_proposal",
                new=AsyncMock(return_value=mock_merge_result),
            ),
        ):
            response = await client.post(
                "/profile-enrichment/proposals/proposal-001/accept",
                params={"consultant_id": "consultant-001"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["proposal_id"] == "proposal-001"
        assert data["action"] == "accept"
        assert data["merged_content"] == "Owner of k8s-operator repo"
        assert data["profile_section"] == "technology"
        assert data["audit_log_id"] == "audit-001"

    async def test_accept_nonexistent_proposal_returns_409(self, client: AsyncClient):
        """POST /proposals/{id}/accept with non-existent proposal returns 409.

        The service raises ValueError when proposal not found, mapped to 409.
        Validates: Requirement 3.1
        """
        session = AsyncMock()
        session.commit = AsyncMock()

        mock_engine = MagicMock()
        mock_session_factory = _create_mock_session_factory(session)

        with (
            patch(PATCH_ENGINE, return_value=mock_engine),
            patch(PATCH_SESSION_FACTORY, return_value=mock_session_factory),
            patch(
                "app.core.proposal_review_service.ProposalReviewService.accept_proposal",
                new=AsyncMock(side_effect=ValueError("Proposal nonexistent-id not found")),
            ),
        ):
            response = await client.post(
                "/profile-enrichment/proposals/nonexistent-id/accept",
                params={"consultant_id": "consultant-001"},
            )

        assert response.status_code == 409
        data = response.json()
        assert "not found" in data["detail"].lower()

    async def test_accept_wrong_consultant_returns_403(self, client: AsyncClient):
        """POST /proposals/{id}/accept with wrong consultant returns 403.

        The service raises PermissionError when consultant doesn't own proposal.
        Validates: Requirement 3.1 (authorization)
        """
        session = AsyncMock()
        session.commit = AsyncMock()

        mock_engine = MagicMock()
        mock_session_factory = _create_mock_session_factory(session)

        with (
            patch(PATCH_ENGINE, return_value=mock_engine),
            patch(PATCH_SESSION_FACTORY, return_value=mock_session_factory),
            patch(
                "app.core.proposal_review_service.ProposalReviewService.accept_proposal",
                new=AsyncMock(
                    side_effect=PermissionError(
                        "Consultant consultant-999 does not own proposal proposal-001"
                    )
                ),
            ),
        ):
            response = await client.post(
                "/profile-enrichment/proposals/proposal-001/accept",
                params={"consultant_id": "consultant-999"},
            )

        assert response.status_code == 403
        data = response.json()
        assert "does not own" in data["detail"].lower()


class TestRejectProposal:
    """Tests for POST /profile-enrichment/proposals/{id}/reject."""

    async def test_reject_valid_proposal_succeeds(self, client: AsyncClient):
        """POST /proposals/{id}/reject with valid pending proposal returns 200.

        Validates: Requirement 3.1
        """
        session = AsyncMock()
        session.commit = AsyncMock()

        mock_engine = MagicMock()
        mock_session_factory = _create_mock_session_factory(session)

        with (
            patch(PATCH_ENGINE, return_value=mock_engine),
            patch(PATCH_SESSION_FACTORY, return_value=mock_session_factory),
            patch(
                "app.core.proposal_review_service.ProposalReviewService.reject_proposal",
                new=AsyncMock(return_value=None),
            ),
        ):
            response = await client.post(
                "/profile-enrichment/proposals/proposal-001/reject",
                params={"consultant_id": "consultant-001"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["proposal_id"] == "proposal-001"
        assert data["status"] == "rejected"

    async def test_reject_nonexistent_proposal_returns_409(self, client: AsyncClient):
        """POST /proposals/{id}/reject with non-existent proposal returns 409.

        Validates: Requirement 3.1
        """
        session = AsyncMock()
        session.commit = AsyncMock()

        mock_engine = MagicMock()
        mock_session_factory = _create_mock_session_factory(session)

        with (
            patch(PATCH_ENGINE, return_value=mock_engine),
            patch(PATCH_SESSION_FACTORY, return_value=mock_session_factory),
            patch(
                "app.core.proposal_review_service.ProposalReviewService.reject_proposal",
                new=AsyncMock(side_effect=ValueError("Proposal bad-id not found")),
            ),
        ):
            response = await client.post(
                "/profile-enrichment/proposals/bad-id/reject",
                params={"consultant_id": "consultant-001"},
            )

        assert response.status_code == 409


# ─── Bulk Action Tests ────────────────────────────────────────────────────────


class TestBulkAction:
    """Tests for POST /profile-enrichment/proposals/bulk."""

    async def test_bulk_action_over_50_returns_422(self, client: AsyncClient):
        """POST /proposals/bulk with >50 proposal IDs returns 422.

        The Pydantic validator on BulkActionRequest rejects >50 proposals.
        Validates: Requirement 3.1
        """
        proposal_ids = [f"proposal-{i:03d}" for i in range(51)]

        response = await client.post(
            "/profile-enrichment/proposals/bulk",
            params={"consultant_id": "consultant-001"},
            json={
                "proposal_ids": proposal_ids,
                "action": "accept",
            },
        )

        assert response.status_code == 422

    async def test_bulk_action_at_50_succeeds(self, client: AsyncClient):
        """POST /proposals/bulk with exactly 50 proposal IDs succeeds.

        Validates: Requirement 3.1
        """
        from app.core.proposal_review_service import MergeAction, MergeResult

        mock_results = [
            MergeResult(
                proposal_id=f"proposal-{i:03d}",
                action=MergeAction.REJECT,
                merged_content=None,
                profile_section="",
                audit_log_id="",
            )
            for i in range(50)
        ]

        session = AsyncMock()
        session.commit = AsyncMock()

        mock_engine = MagicMock()
        mock_session_factory = _create_mock_session_factory(session)

        with (
            patch(PATCH_ENGINE, return_value=mock_engine),
            patch(PATCH_SESSION_FACTORY, return_value=mock_session_factory),
            patch(
                "app.core.proposal_review_service.ProposalReviewService.bulk_action",
                new=AsyncMock(return_value=mock_results),
            ),
        ):
            proposal_ids = [f"proposal-{i:03d}" for i in range(50)]
            response = await client.post(
                "/profile-enrichment/proposals/bulk",
                params={"consultant_id": "consultant-001"},
                json={
                    "proposal_ids": proposal_ids,
                    "action": "reject",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["processed"] == 50
        assert data["action"] == "reject"
