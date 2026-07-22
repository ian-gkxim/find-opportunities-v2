"""Integration tests for on-demand gap analysis.

Tests the full flow: load text → extract capabilities → normalize → load
profile → diff → classify → produce OnDemandGapReport.

Requirements: 3.4
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.capability_normalizer import CapabilityNormalizer
from app.core.gap_analyzer import (
    GapAnalysisConfig,
    GapAnalyzer,
    GapClassification,
    OnDemandGapReport,
)
from app.core.gap_errors import GapAnalysisError, OnDemandTimeoutError


# ─── FIXTURES / HELPERS ───────────────────────────────────────────────────────


class FakeRedis:
    """Lightweight Redis mock for on-demand tests."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def publish(self, channel: str, message: str) -> int:
        return 0


def _make_llm_router_mock(
    required: list[str] | None = None,
    preferred: list[str] | None = None,
) -> MagicMock:
    """Create a mocked LLM_Router that returns specified capabilities."""
    if required is None:
        required = ["kubernetes", "python", "terraform"]
    if preferred is None:
        preferred = ["aws", "docker"]

    llm = MagicMock()
    llm.dispatch_extraction = AsyncMock(
        return_value={"required": required, "preferred": preferred}
    )
    return llm


def _make_db_session_with_profile(
    profile_capabilities: dict[str, str] | None = None,
) -> AsyncMock:
    """Create a mocked DB session that returns consultant profile data.

    Args:
        profile_capabilities: Dict of canonical_name -> proficiency_level.
            If None, returns an empty profile (consultant not found scenario).
    """
    db = AsyncMock()

    if profile_capabilities is None:
        profile_capabilities = {}

    # Mock the execute call for BeneficiaryCapability query
    mock_records = []
    for cap_name, level in profile_capabilities.items():
        record = MagicMock()
        record.canonical = MagicMock()
        record.canonical.canonical_name = cap_name
        record.proficiency_level = level
        record.beneficiary_id = "consultant-1"
        mock_records.append(record)

    # The DB session execute returns a result with scalars().all()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_records
    db.execute = AsyncMock(return_value=mock_result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()

    return db


def _make_normalizer(synonyms: dict[str, str] | None = None) -> CapabilityNormalizer:
    """Create a CapabilityNormalizer with optional synonym mappings."""
    if synonyms is None:
        synonyms = {"k8s": "kubernetes", "py": "python", "tf": "terraform"}
    return CapabilityNormalizer(synonyms)


def _build_analyzer(
    llm_router: MagicMock | None = None,
    db_session: AsyncMock | None = None,
    redis_client: FakeRedis | None = None,
    normalizer: CapabilityNormalizer | None = None,
    timeout_seconds: int = 120,
) -> GapAnalyzer:
    """Build a GapAnalyzer with mocked dependencies for integration testing."""
    config = GapAnalysisConfig(on_demand_timeout_seconds=timeout_seconds)
    return GapAnalyzer(
        config=config,
        llm_router=llm_router or _make_llm_router_mock(),
        schema_registry=None,
        db_session=db_session or _make_db_session_with_profile({}),
        redis_client=redis_client or FakeRedis(),
        ws_manager=None,
        normalizer=normalizer or _make_normalizer(),
    )


# ─── TEST 1: Happy path — full on-demand analysis ────────────────────────────


@pytest.mark.asyncio
async def test_on_demand_happy_path_generates_report():
    """Mock LLM returns capabilities, mock DB returns consultant profile.

    Verifies OnDemandGapReport is generated correctly with:
    - required_gaps for capabilities not in profile
    - preferred_gaps for preferred capabilities not in profile
    - correct gap_percentage calculation
    - correct total_required / total_matched counts

    Requirements: 3.4
    """
    # Arrange: LLM extracts [kubernetes, python, terraform] as required
    # Consultant profile has [python, kubernetes] at senior level
    # Expected gap: terraform (hard gap)
    llm = _make_llm_router_mock(
        required=["Kubernetes", "Python", "Terraform"],
        preferred=["AWS", "Docker"],
    )
    db = _make_db_session_with_profile({
        "kubernetes": "senior",
        "python": "senior",
    })
    normalizer = _make_normalizer()
    redis = FakeRedis()

    analyzer = _build_analyzer(
        llm_router=llm,
        db_session=db,
        redis_client=redis,
        normalizer=normalizer,
    )

    opportunity_text = (
        "We are looking for a DevOps Engineer with strong Kubernetes, "
        "Python, and Terraform experience. AWS and Docker preferred."
    )

    # Act
    report = await analyzer.analyze_on_demand(
        opportunity_text=opportunity_text,
        consultant_id="consultant-1",
        opportunity_url="https://example.com/job/devops-engineer",
    )

    # Assert: report structure
    assert isinstance(report, OnDemandGapReport)
    assert report.consultant_id == "consultant-1"
    assert report.opportunity_url == "https://example.com/job/devops-engineer"
    assert report.generated_at is not None

    # Assert: required gaps — terraform is missing
    assert report.total_required == 3
    assert report.total_matched == 2
    required_gap_names = {g.canonical_name for g in report.required_gaps}
    assert "terraform" in required_gap_names
    assert "kubernetes" not in required_gap_names
    assert "python" not in required_gap_names

    # Assert: gap percentage (1 gap out of 3 required = 33.33%)
    assert abs(report.gap_percentage - 33.33) < 0.5

    # Assert: preferred gaps — AWS and Docker are missing from profile
    preferred_gap_names = {g.canonical_name for g in report.preferred_gaps}
    assert "aws" in preferred_gap_names
    assert "docker" in preferred_gap_names

    # Assert: classification is HARD for missing capabilities
    for gap in report.required_gaps:
        if gap.canonical_name == "terraform":
            assert gap.classification == GapClassification.HARD

    # Assert: LLM was called exactly once for extraction
    llm.dispatch_extraction.assert_called_once()


# ─── TEST 2: URL fetch failure → 422 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_on_demand_url_fetch_failure_raises_error():
    """When httpx raises an error fetching the opportunity URL, verify
    GapAnalysisError is raised with appropriate message.

    Requirements: 3.4
    """
    import httpx

    analyzer = _build_analyzer()

    # Mock httpx.AsyncClient to raise on GET
    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_client_class.return_value.__aenter__ = AsyncMock(
            return_value=mock_client_instance
        )
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(GapAnalysisError, match="Failed to fetch"):
            await analyzer.load_opportunity_text_for_on_demand(
                opportunity_url="https://example.com/broken-url"
            )


# ─── TEST 3: Consultant not found → gaps = all demanded ──────────────────────


@pytest.mark.asyncio
async def test_on_demand_consultant_not_found_all_gaps():
    """When DB returns an empty profile (no BeneficiaryCapability records),
    all demanded capabilities become gaps.

    Requirements: 3.4
    """
    # Arrange: LLM returns capabilities, but profile is empty
    llm = _make_llm_router_mock(
        required=["Python", "Kubernetes", "Terraform"],
        preferred=["Docker"],
    )
    # Empty profile — no capabilities on file for this consultant
    db = _make_db_session_with_profile({})
    normalizer = _make_normalizer()

    analyzer = _build_analyzer(
        llm_router=llm,
        db_session=db,
        normalizer=normalizer,
    )

    opportunity_text = (
        "Senior DevOps role requiring Python, Kubernetes, and Terraform. "
        "Docker is preferred for container orchestration."
    )

    # Act
    report = await analyzer.analyze_on_demand(
        opportunity_text=opportunity_text,
        consultant_id="unknown-consultant",
    )

    # Assert: all required capabilities are gaps
    assert report.total_required == 3
    assert report.total_matched == 0
    assert len(report.required_gaps) == 3
    assert report.gap_percentage == 100.0

    required_gap_names = {g.canonical_name for g in report.required_gaps}
    assert "python" in required_gap_names
    assert "kubernetes" in required_gap_names
    assert "terraform" in required_gap_names

    # Assert: all preferred are gaps too
    assert len(report.preferred_gaps) == 1
    assert report.preferred_gaps[0].canonical_name == "docker"

    # Assert: all gaps classified as HARD (completely absent from profile)
    for gap in report.required_gaps:
        assert gap.classification == GapClassification.HARD


# ─── TEST 4: Text too short → GapAnalysisError ───────────────────────────────


@pytest.mark.asyncio
async def test_on_demand_text_too_short_raises_error():
    """When opportunity text is shorter than the minimum threshold,
    GapAnalysisError should be raised.

    Requirements: 3.4
    """
    analyzer = _build_analyzer()

    # Mock _load_opportunity_text to return very short text (< 20 chars)
    with patch.object(
        analyzer, "_load_opportunity_text", new=AsyncMock(return_value="Short")
    ):
        with pytest.raises(GapAnalysisError, match="too short"):
            await analyzer.load_opportunity_text_for_on_demand(
                pipeline_record_id="a1b2c3d4-e5f6-7890-abcd-ef1234567890"
            )


@pytest.mark.asyncio
async def test_on_demand_url_returns_short_text_raises_error():
    """When a URL is fetched but returns very short content,
    GapAnalysisError should be raised with 'too short' message.

    Requirements: 3.4
    """
    import httpx

    analyzer = _build_analyzer()

    # Mock httpx to return a very short response
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "Hi"  # Less than 20 chars
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client_class:
        mock_client_instance = AsyncMock()
        mock_client_instance.get = AsyncMock(return_value=mock_response)
        mock_client_class.return_value.__aenter__ = AsyncMock(
            return_value=mock_client_instance
        )
        mock_client_class.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(GapAnalysisError, match="too short"):
            await analyzer.load_opportunity_text_for_on_demand(
                opportunity_url="https://example.com/short-page"
            )


# ─── TEST 5: Timeout → OnDemandTimeoutError ──────────────────────────────────


@pytest.mark.asyncio
async def test_on_demand_timeout_raises_error():
    """When LLM hangs beyond the timeout budget, OnDemandTimeoutError
    should be raised within the configured timeout window.

    Requirements: 3.4
    """

    # Arrange: LLM that hangs forever
    async def hanging_extraction(*args, **kwargs):
        await asyncio.sleep(10)  # Will never complete within 1s timeout
        return {"required": [], "preferred": []}

    llm = MagicMock()
    llm.dispatch_extraction = AsyncMock(side_effect=hanging_extraction)

    # Use a very short timeout (1 second) so the test runs quickly
    analyzer = _build_analyzer(
        llm_router=llm,
        timeout_seconds=1,
    )

    opportunity_text = (
        "This is a sufficiently long opportunity description for a "
        "senior backend engineer role with Python and AWS."
    )

    # Act & Assert: should raise OnDemandTimeoutError within ~1 second
    with pytest.raises(OnDemandTimeoutError):
        await analyzer.analyze_on_demand(
            opportunity_text=opportunity_text,
            consultant_id="consultant-1",
            opportunity_url="https://example.com/job/hanging",
        )

    # Verify: the timeout did not hang the test for too long
    # (the test framework itself would fail if it took >5s)
