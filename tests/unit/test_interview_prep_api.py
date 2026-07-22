"""Unit tests for Interview Prep API routes.

Tests requirements 3.2:
- GET /interview-prep/{pipeline_record_id} — returns pack when ready (200)
- GET /interview-prep/{pipeline_record_id} — returns 404 when no pack exists
- POST /interview-prep/{pipeline_record_id}/regenerate — returns 202 and enqueues job
- GET /interview-prep/{pipeline_record_id}/status — returns correct PackStatus values
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.interview_prep import router, get_interview_prep_repository, get_redis_pool
from app.core.interview_prep_models import Interview_Prep_Pack, PackStatus, STAR_Talking_Point


# ─── Fixtures ─────────────────────────────────────────────────────────────────


def _make_sample_pack(
    pipeline_record_id: str = "pipeline-001",
    status: PackStatus = PackStatus.READY,
) -> Interview_Prep_Pack:
    """Create a sample Interview_Prep_Pack for testing."""
    return Interview_Prep_Pack(
        id="pack-001",
        pipeline_record_id=pipeline_record_id,
        beneficiary_id="beneficiary-001",
        opportunity_type_id="job_site",
        likely_questions=[
            "Tell me about your experience with Python",
            "Describe a challenging project",
            "How do you handle tight deadlines?",
            "What is your approach to testing?",
            "How do you stay current with technology?",
            "Describe your teamwork style",
            "What motivates you?",
            "How do you handle disagreements?",
        ],
        star_talking_points=[
            STAR_Talking_Point(
                competency="Python development",
                question="Tell me about your experience with Python",
                situation="Led backend migration at previous company",
                task="Migrate legacy PHP service to Python FastAPI",
                action="Designed async architecture, wrote migration tooling",
                result="50% latency reduction, 3x throughput improvement",
                source_asset_refs=["asset-001", "asset-002"],
                is_gap_handled=False,
                gap_note=None,
            ),
        ],
        company_briefing="A technology company focused on AI solutions.",
        questions_to_ask=[
            "What does your CI/CD pipeline look like?",
            "How is the team structured?",
            "What are the main technical challenges?",
        ],
        status=status,
        omission_notes=[],
        grounding_flags=[],
        generation_duration_ms=4500,
        created_at=datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2024, 6, 1, 12, 0, 5, tzinfo=timezone.utc),
    )


@pytest.fixture
def mock_repo():
    """Create a mock interview prep repository."""
    repo = AsyncMock()
    return repo


@pytest.fixture
def mock_redis():
    """Create a mock Redis pool with enqueue_job."""
    redis = AsyncMock()
    redis.enqueue_job = AsyncMock()
    return redis


@pytest.fixture
def test_app(mock_repo, mock_redis) -> FastAPI:
    """Create a minimal FastAPI app with dependency overrides."""
    app = FastAPI()
    app.include_router(router)

    async def override_repo():
        return mock_repo

    async def override_redis():
        return mock_redis

    app.dependency_overrides[get_interview_prep_repository] = override_repo
    app.dependency_overrides[get_redis_pool] = override_redis
    return app


@pytest.fixture
async def client(test_app: FastAPI):
    """Provide an httpx AsyncClient for the test app."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ─── GET Pack Tests ───────────────────────────────────────────────────────────


class TestGetPack:
    """Tests for GET /interview-prep/{pipeline_record_id}."""

    async def test_get_pack_returns_200_when_ready(
        self, client: AsyncClient, mock_repo
    ):
        """GET /interview-prep/{id} returns 200 with pack data when pack exists.

        Validates: Requirements 3.2
        """
        pack = _make_sample_pack()
        mock_repo.get_pack = AsyncMock(return_value=pack)

        response = await client.get("/interview-prep/pipeline-001")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == "pack-001"
        assert data["pipeline_record_id"] == "pipeline-001"
        assert data["beneficiary_id"] == "beneficiary-001"
        assert data["status"] == "ready"
        assert len(data["likely_questions"]) == 8
        assert len(data["star_talking_points"]) == 1
        assert data["star_talking_points"][0]["competency"] == "Python development"
        assert data["company_briefing"] == "A technology company focused on AI solutions."
        assert len(data["questions_to_ask"]) == 3
        assert data["generation_duration_ms"] == 4500

    async def test_get_pack_returns_404_when_no_pack(
        self, client: AsyncClient, mock_repo
    ):
        """GET /interview-prep/{id} returns 404 when no pack exists for the pipeline record.

        Validates: Requirements 3.2
        """
        mock_repo.get_pack = AsyncMock(return_value=None)

        response = await client.get("/interview-prep/pipeline-nonexistent")

        assert response.status_code == 404
        data = response.json()
        assert "no interview prep pack found" in data["detail"].lower()


# ─── GET Status Tests ─────────────────────────────────────────────────────────


class TestGetStatus:
    """Tests for GET /interview-prep/{pipeline_record_id}/status."""

    async def test_get_status_returns_not_started_when_no_pack(
        self, client: AsyncClient, mock_repo
    ):
        """GET /status returns 'not_started' when no pack exists.

        Validates: Requirements 3.2
        """
        mock_repo.get_pack = AsyncMock(return_value=None)

        response = await client.get("/interview-prep/pipeline-001/status")

        assert response.status_code == 200
        data = response.json()
        assert data["pipeline_record_id"] == "pipeline-001"
        assert data["status"] == "not_started"
        assert data["pack_id"] is None

    async def test_get_status_returns_current_status(
        self, client: AsyncClient, mock_repo
    ):
        """GET /status returns the current pack status when pack exists.

        Validates: Requirements 3.2
        """
        pack = _make_sample_pack(status=PackStatus.GENERATING)
        mock_repo.get_pack = AsyncMock(return_value=pack)

        response = await client.get("/interview-prep/pipeline-001/status")

        assert response.status_code == 200
        data = response.json()
        assert data["pipeline_record_id"] == "pipeline-001"
        assert data["status"] == "generating"
        assert data["pack_id"] == "pack-001"


# ─── POST Regenerate Tests ────────────────────────────────────────────────────


class TestPostRegenerate:
    """Tests for POST /interview-prep/{pipeline_record_id}/regenerate."""

    async def test_post_regenerate_returns_202(
        self, client: AsyncClient, mock_redis
    ):
        """POST /regenerate returns 202 Accepted.

        Validates: Requirements 3.2
        """
        response = await client.post("/interview-prep/pipeline-001/regenerate")

        assert response.status_code == 202
        data = response.json()
        assert data["message"] == "Regeneration job enqueued"
        assert data["pipeline_record_id"] == "pipeline-001"

    async def test_post_regenerate_enqueues_job(
        self, client: AsyncClient, mock_redis
    ):
        """POST /regenerate enqueues a regeneration job via redis pool.

        Validates: Requirements 3.2
        """
        response = await client.post("/interview-prep/pipeline-001/regenerate")

        assert response.status_code == 202
        mock_redis.enqueue_job.assert_called_once_with(
            "regenerate_interview_prep", "pipeline-001"
        )
