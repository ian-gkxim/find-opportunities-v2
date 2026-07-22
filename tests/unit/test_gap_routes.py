"""Unit tests for Gap Analytics API routes.

Tests requirements 3.1, 3.3, 3.4:
- GET /gap-analysis/heatmap/{beneficiary_id} — 404 when not found
- POST /gap-analysis/on-demand — validation (must provide URL or ID, not both)
- GET /gap-analysis/recommendation/{capability_name} — 404 when unknown
- GET /gap-analysis/heatmap/{beneficiary_id}/history — returns list (possibly empty)
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.gap_routes import router


@pytest.fixture
def test_app() -> FastAPI:
    """Create a minimal FastAPI app with only the gap routes for isolated testing."""
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


@pytest.fixture
async def client(test_app: FastAPI):
    """Provide an httpx AsyncClient for the test app."""
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestGetHeatmap:
    """Tests for GET /api/gap-analysis/heatmap/{beneficiary_id}."""

    async def test_returns_404_when_no_heatmap_found(self, client: AsyncClient):
        """Should return 404 when no heatmap exists for the beneficiary."""
        response = await client.get("/api/gap-analysis/heatmap/nonexistent-consultant")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "nonexistent-consultant" in data["detail"]

    async def test_returns_404_with_opportunity_type_filter(self, client: AsyncClient):
        """Should return 404 even with opportunity_type query parameter."""
        response = await client.get(
            "/api/gap-analysis/heatmap/unknown-id",
            params={"opportunity_type": "contract"},
        )

        assert response.status_code == 404


class TestOnDemandAnalysis:
    """Tests for POST /api/gap-analysis/on-demand."""

    async def test_returns_422_when_neither_url_nor_id_provided(
        self, client: AsyncClient
    ):
        """Must provide at least one of opportunity_url or pipeline_record_id."""
        response = await client.post(
            "/api/gap-analysis/on-demand",
            json={"consultant_id": "consultant-1"},
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        assert "opportunity_url" in data["detail"] or "pipeline_record_id" in data["detail"]

    async def test_returns_422_when_both_url_and_id_provided(
        self, client: AsyncClient
    ):
        """Must provide only one of opportunity_url or pipeline_record_id, not both."""
        response = await client.post(
            "/api/gap-analysis/on-demand",
            json={
                "opportunity_url": "https://example.com/job/123",
                "pipeline_record_id": "record-abc",
                "consultant_id": "consultant-1",
            },
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        assert "not both" in data["detail"].lower() or "only one" in data["detail"].lower()

    async def test_valid_request_with_url_accepted(self, test_app: FastAPI, client: AsyncClient):
        """A valid request with only opportunity_url should pass validation.

        Uses FastAPI dependency_overrides to inject a mock GapAnalyzer,
        confirming the request passes input validation and reaches the
        business logic layer.
        """
        from app.api.gap_routes import get_gap_analyzer
        from app.core.gap_analyzer import OnDemandGapReport

        mock_report = OnDemandGapReport(
            opportunity_id=None,
            opportunity_url="https://example.com/job/456",
            consultant_id="consultant-1",
            required_gaps=[],
            preferred_gaps=[],
            total_required=5,
            total_matched=5,
            gap_percentage=0.0,
            generated_at=datetime.now(timezone.utc),
        )

        mock_analyzer = AsyncMock()
        mock_analyzer.load_opportunity_text_for_on_demand = AsyncMock(
            return_value="Some opportunity text for analysis"
        )
        mock_analyzer.analyze_on_demand = AsyncMock(return_value=mock_report)

        test_app.dependency_overrides[get_gap_analyzer] = lambda: mock_analyzer

        try:
            response = await client.post(
                "/api/gap-analysis/on-demand",
                json={
                    "opportunity_url": "https://example.com/job/456",
                    "consultant_id": "consultant-1",
                },
            )
        finally:
            test_app.dependency_overrides.clear()

        # Request passes validation and returns a successful response
        assert response.status_code == 200
        data = response.json()
        assert data["consultant_id"] == "consultant-1"
        assert data["opportunity_url"] == "https://example.com/job/456"
        assert data["gap_percentage"] == 0.0

    async def test_valid_request_with_pipeline_record_id_accepted(
        self, test_app: FastAPI, client: AsyncClient
    ):
        """A valid request with only pipeline_record_id should pass validation."""
        from app.api.gap_routes import get_gap_analyzer
        from app.core.gap_analyzer import OnDemandGapReport

        mock_report = OnDemandGapReport(
            opportunity_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            opportunity_url=None,
            consultant_id="consultant-2",
            required_gaps=[],
            preferred_gaps=[],
            total_required=3,
            total_matched=2,
            gap_percentage=33.33,
            generated_at=datetime.now(timezone.utc),
        )

        mock_analyzer = AsyncMock()
        mock_analyzer.load_opportunity_text_for_on_demand = AsyncMock(
            return_value="Another opportunity description"
        )
        mock_analyzer.analyze_on_demand = AsyncMock(return_value=mock_report)

        test_app.dependency_overrides[get_gap_analyzer] = lambda: mock_analyzer

        try:
            response = await client.post(
                "/api/gap-analysis/on-demand",
                json={
                    "pipeline_record_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "consultant_id": "consultant-2",
                },
            )
        finally:
            test_app.dependency_overrides.clear()

        # Request passes validation and returns a successful response
        assert response.status_code == 200
        data = response.json()
        assert data["consultant_id"] == "consultant-2"
        assert data["total_required"] == 3

    async def test_returns_422_when_consultant_id_missing(self, client: AsyncClient):
        """consultant_id is a required field — Pydantic should reject without it."""
        response = await client.post(
            "/api/gap-analysis/on-demand",
            json={"opportunity_url": "https://example.com/job/789"},
        )

        assert response.status_code == 422


class TestGetLearningRecommendation:
    """Tests for GET /api/gap-analysis/recommendation/{capability_name}."""

    async def test_returns_404_when_capability_unknown(self, client: AsyncClient):
        """Should return 404 when capability not in canonical registry."""
        response = await client.get(
            "/api/gap-analysis/recommendation/nonexistent-capability"
        )

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data
        assert "nonexistent-capability" in data["detail"]

    async def test_404_response_mentions_canonical_registry(self, client: AsyncClient):
        """Error message should reference the canonical registry."""
        response = await client.get(
            "/api/gap-analysis/recommendation/unknown-skill"
        )

        assert response.status_code == 404
        data = response.json()
        assert "canonical registry" in data["detail"].lower() or "not found" in data["detail"].lower()


class TestGetHeatmapHistory:
    """Tests for GET /api/gap-analysis/heatmap/{beneficiary_id}/history."""

    async def test_returns_empty_list_when_no_history(self, client: AsyncClient):
        """Should return an empty list when no historical heatmaps exist."""
        response = await client.get(
            "/api/gap-analysis/heatmap/consultant-1/history"
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert data == []

    async def test_respects_limit_query_parameter(self, client: AsyncClient):
        """Should accept limit query parameter without error."""
        response = await client.get(
            "/api/gap-analysis/heatmap/consultant-1/history",
            params={"limit": 5},
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_rejects_limit_below_minimum(self, client: AsyncClient):
        """limit must be >= 1 per the route definition."""
        response = await client.get(
            "/api/gap-analysis/heatmap/consultant-1/history",
            params={"limit": 0},
        )

        assert response.status_code == 422

    async def test_rejects_limit_above_maximum(self, client: AsyncClient):
        """limit must be <= 50 per the route definition."""
        response = await client.get(
            "/api/gap-analysis/heatmap/consultant-1/history",
            params={"limit": 100},
        )

        assert response.status_code == 422
