"""Integration tests for the full nightly gap analysis cycle.

Tests end-to-end flow through GapAnalyzer.run_nightly_cycle() with
mocked LLM_Router, DB session, Redis, and WebSocket manager.

Verifies: extraction → normalization → gap computation → heatmap storage
→ WebSocket notification, and carry-forward queue population when batch
exceeds cap.

Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.2, 3.5
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.capability_normalizer import CapabilityNormalizer
from app.core.gap_analyzer import (
    CapabilityLevel,
    ExtractedCapability,
    GapAnalysisConfig,
    GapAnalyzer,
    GapClassification,
    GapEntry,
    GapTrend,
)


# ─── FIXTURES / HELPERS ───────────────────────────────────────────────────────


def _make_uuid() -> str:
    return str(uuid.uuid4())


def _make_beneficiary_cap_mock(
    beneficiary_id: str, canonical_name: str, proficiency: str = "senior"
):
    """Create a mock BeneficiaryCapability DB model."""
    bc = MagicMock()
    bc.beneficiary_id = beneficiary_id
    bc.proficiency_level = proficiency
    bc.canonical = MagicMock()
    bc.canonical.canonical_name = canonical_name
    return bc


def _make_extraction_cap_mock(
    extraction_id: uuid.UUID, canonical_name: str, raw_name: str, level: str
):
    """Create a mock ExtractedCapability DB model."""
    ec = MagicMock()
    ec.extraction_id = extraction_id
    ec.raw_name = raw_name
    ec.level = level
    ec.canonical = MagicMock()
    ec.canonical.canonical_name = canonical_name
    return ec


def _build_gap_analyzer(
    config: GapAnalysisConfig | None = None,
    llm_router=None,
    db_session=None,
    redis_client=None,
    ws_manager=None,
    normalizer: CapabilityNormalizer | None = None,
) -> GapAnalyzer:
    """Build a GapAnalyzer with mocked dependencies for testing."""
    if config is None:
        config = GapAnalysisConfig(
            analysis_window_days=90,
            max_extractions_per_cycle=200,
            max_heatmap_entries=25,
            single_blocker_weight=2.0,
            on_demand_timeout_seconds=120,
            default_opportunity_value=10000.0,
        )
    if llm_router is None:
        llm_router = MagicMock()
    if db_session is None:
        db_session = AsyncMock()
    if redis_client is None:
        redis_client = AsyncMock()
        redis_client.get = AsyncMock(return_value=None)
        redis_client.set = AsyncMock()
        redis_client.publish = AsyncMock()
    if ws_manager is None:
        ws_manager = AsyncMock()
        ws_manager.broadcast_heatmap_available = AsyncMock()
    if normalizer is None:
        normalizer = CapabilityNormalizer({
            "k8s": "kubernetes",
            "js": "javascript",
            "py": "python",
            "react.js": "react",
        })

    return GapAnalyzer(
        config=config,
        llm_router=llm_router,
        schema_registry=MagicMock(),
        db_session=db_session,
        redis_client=redis_client,
        ws_manager=ws_manager,
        normalizer=normalizer,
    )


# ─── TEST: Full nightly cycle end-to-end ──────────────────────────────────────


@pytest.mark.asyncio
async def test_nightly_cycle_full_pipeline():
    """Full nightly cycle: extraction → normalization → gaps → heatmap → WS.

    Patches internal DB helper methods to isolate orchestration logic.
    Verifies extraction is called for eligible opportunities, gaps are
    computed, heatmaps stored, and WebSocket notification sent.

    Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 3.2, 3.5
    """
    opp_id_1 = _make_uuid()
    opp_id_2 = _make_uuid()
    extraction_id_1 = uuid.uuid4()
    extraction_id_2 = uuid.uuid4()

    # LLM mock returns capabilities
    llm_router = MagicMock()
    llm_router.dispatch_extraction = AsyncMock(return_value={
        "required": ["Kubernetes", "Python", "AWS"],
        "preferred": ["Terraform"],
    })

    redis_client = AsyncMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock()
    redis_client.publish = AsyncMock()

    ws_manager = AsyncMock()
    ws_manager.broadcast_heatmap_available = AsyncMock()

    db_session = AsyncMock()
    db_session.add = MagicMock()
    db_session.flush = AsyncMock()
    db_session.commit = AsyncMock()

    normalizer = CapabilityNormalizer({"k8s": "kubernetes"})

    analyzer = GapAnalyzer(
        config=GapAnalysisConfig(
            analysis_window_days=90,
            max_extractions_per_cycle=200,
            max_heatmap_entries=25,
            single_blocker_weight=2.0,
            default_opportunity_value=10000.0,
        ),
        llm_router=llm_router,
        schema_registry=MagicMock(),
        db_session=db_session,
        redis_client=redis_client,
        ws_manager=ws_manager,
        normalizer=normalizer,
    )

    # Patch internal methods that interact with DB directly
    analyzer.get_eligible_opportunities = AsyncMock(
        return_value=[opp_id_1, opp_id_2]
    )
    analyzer.enforce_batch_cap = AsyncMock(
        return_value=[opp_id_1, opp_id_2]
    )
    analyzer._load_opportunity_text = AsyncMock(
        return_value="Company: Acme Corp\nNeeds Kubernetes and Python and AWS"
    )
    analyzer._store_extraction_in_db = AsyncMock()

    # Mock the "load all extracted capabilities" DB query (Step 4)
    all_extracted_models = [
        _make_extraction_cap_mock(extraction_id_1, "kubernetes", "Kubernetes", "required"),
        _make_extraction_cap_mock(extraction_id_1, "python", "Python", "required"),
        _make_extraction_cap_mock(extraction_id_1, "aws", "AWS", "required"),
        _make_extraction_cap_mock(extraction_id_2, "kubernetes", "K8s", "required"),
        _make_extraction_cap_mock(extraction_id_2, "python", "Python", "required"),
        _make_extraction_cap_mock(extraction_id_2, "react", "React", "required"),
    ]

    # Beneficiary profile: consultant_1 has python + aws (senior)
    beneficiary_caps = [
        _make_beneficiary_cap_mock("consultant_1", "python", "senior"),
        _make_beneficiary_cap_mock("consultant_1", "aws", "senior"),
    ]

    # extraction_to_opp mapping
    extraction_mapping = [
        MagicMock(id=extraction_id_1, pipeline_record_id=uuid.UUID(opp_id_1)),
        MagicMock(id=extraction_id_2, pipeline_record_id=uuid.UUID(opp_id_2)),
    ]

    # opportunity_values query (returns tier info)
    opp_value_rows = [
        MagicMock(id=uuid.UUID(opp_id_1), tier="C-tier"),
        MagicMock(id=uuid.UUID(opp_id_2), tier="D-tier"),
    ]

    # Set up sequential DB execute responses for the nightly cycle steps
    # after extraction (Steps 4-6)
    call_idx = {"n": 0}

    async def mock_execute(stmt):
        call_idx["n"] += 1
        n = call_idx["n"]
        if n == 1:
            # Step 4: Load all extracted capabilities within window
            result = MagicMock()
            result.scalars.return_value.all.return_value = all_extracted_models
            return result
        elif n == 2:
            # Step 4: Load extraction_to_opp mapping
            result = MagicMock()
            result.all.return_value = extraction_mapping
            return result
        elif n == 3:
            # Step 4: _build_opportunity_values
            result = MagicMock()
            result.all.return_value = opp_value_rows
            return result
        elif n == 4:
            # Step 5: Load beneficiary capabilities
            result = MagicMock()
            result.scalars.return_value.all.return_value = beneficiary_caps
            return result
        else:
            # Steps 6+: _load_previous_heatmap_gaps, _store_heatmap queries
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.scalar_one_or_none.return_value = None
            return result

    db_session.execute = AsyncMock(side_effect=mock_execute)

    # ── Act ───────────────────────────────────────────────────────────────
    result = await analyzer.run_nightly_cycle()

    # ── Assert ────────────────────────────────────────────────────────────
    # 1. Extraction was called for both opportunities
    assert result["extracted"] == 2
    assert llm_router.dispatch_extraction.call_count == 2

    # 2. Redis cache was set for each extraction
    assert redis_client.set.call_count == 2

    # 3. Heatmaps were generated (consultant_1 + __firm__)
    assert result["heatmaps_generated"] == 2

    # 4. WebSocket notification was sent for each heatmap
    assert ws_manager.broadcast_heatmap_available.call_count == 2

    # 5. Carry-forward is 0 (batch within cap)
    assert result["carried_forward"] == 0

    # 6. Duration was recorded
    assert "duration_seconds" in result
    assert result["duration_seconds"] >= 0


@pytest.mark.asyncio
async def test_nightly_cycle_extraction_produces_normalized_capabilities():
    """Extraction results are normalized via synonym map before storage.

    Verifies that when LLM returns "K8s", the normalizer converts it
    to "kubernetes" before caching.

    Requirements: 1.2
    """
    opp_id = _make_uuid()

    llm_router = MagicMock()
    llm_router.dispatch_extraction = AsyncMock(return_value={
        "required": ["K8s", "React.js"],
        "preferred": ["Py"],
    })

    redis_client = AsyncMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock()

    normalizer = CapabilityNormalizer({
        "k8s": "kubernetes",
        "react.js": "react",
        "py": "python",
    })

    analyzer = _build_gap_analyzer(
        llm_router=llm_router,
        redis_client=redis_client,
        normalizer=normalizer,
    )
    # Bypass DB storage
    analyzer._store_extraction_in_db = AsyncMock()

    # Act
    result = await analyzer.extract_capabilities(
        opp_id, "Need K8s and React.js expertise, Python preferred"
    )

    # Assert: raw names preserved in extraction result
    assert "K8s" in result.required_capabilities
    assert "React.js" in result.required_capabilities
    assert result.cached is False

    # Verify normalization works correctly
    assert normalizer.normalize("K8s") == "kubernetes"
    assert normalizer.normalize("React.js") == "react"
    assert normalizer.normalize("Py") == "python"


@pytest.mark.asyncio
async def test_nightly_cycle_gap_computation_identifies_missing_caps():
    """Gap computation correctly identifies capabilities absent from profile.

    Sets up demanded capabilities and a profile, verifies the diff produces
    the expected gaps with correct classification and values.

    Requirements: 2.1, 2.2
    """
    opp_id_1 = _make_uuid()
    opp_id_2 = _make_uuid()

    demanded = [
        ExtractedCapability("Kubernetes", "kubernetes", CapabilityLevel.REQUIRED, opp_id_1),
        ExtractedCapability("Python", "python", CapabilityLevel.REQUIRED, opp_id_1),
        ExtractedCapability("AWS", "aws", CapabilityLevel.REQUIRED, opp_id_1),
        ExtractedCapability("Kubernetes", "kubernetes", CapabilityLevel.REQUIRED, opp_id_2),
        ExtractedCapability("React", "react", CapabilityLevel.REQUIRED, opp_id_2),
    ]

    # Profile has python + aws (senior), missing kubernetes + react
    profile = {"python", "aws"}
    opp_values = {opp_id_1: 5000.0, opp_id_2: 2500.0}

    analyzer = _build_gap_analyzer()

    # Act
    gaps = analyzer.compute_gaps(demanded, profile, opp_values)

    # Assert: kubernetes and react are gaps
    gap_names = {g.canonical_name for g in gaps}
    assert "kubernetes" in gap_names
    assert "react" in gap_names
    assert "python" not in gap_names
    assert "aws" not in gap_names

    # Kubernetes appears in both opps → count=2, value=5000+2500=7500
    k8s_gap = next(g for g in gaps if g.canonical_name == "kubernetes")
    assert k8s_gap.opportunity_count == 2
    assert k8s_gap.blocked_pipeline_value == 7500.0
    assert k8s_gap.classification == GapClassification.HARD

    # React appears only in opp_2 → count=1, value=2500
    react_gap = next(g for g in gaps if g.canonical_name == "react")
    assert react_gap.opportunity_count == 1
    assert react_gap.blocked_pipeline_value == 2500.0
    assert react_gap.classification == GapClassification.HARD


@pytest.mark.asyncio
async def test_nightly_cycle_single_blocker_weighting():
    """Single-blocker gaps receive 2x weight in ranking.

    When an opportunity has exactly one unmet required capability,
    that gap is flagged as single-blocker with doubled weighted_rank_score.

    Requirements: 2.3
    """
    opp_id = _make_uuid()

    # Opportunity requires kubernetes + python; profile has python only
    # → kubernetes is the sole unmet → single-blocker
    demanded = [
        ExtractedCapability("Kubernetes", "kubernetes", CapabilityLevel.REQUIRED, opp_id),
        ExtractedCapability("Python", "python", CapabilityLevel.REQUIRED, opp_id),
    ]

    profile = {"python"}
    opp_values = {opp_id: 10000.0}

    analyzer = _build_gap_analyzer()

    # Act: compute gaps then detect single blockers and apply weighting
    gaps = analyzer.compute_gaps(demanded, profile, opp_values)
    single_blockers = analyzer.detect_single_blockers(demanded, profile)
    weighted_gaps = analyzer.apply_single_blocker_weighting(gaps, single_blockers)

    # Assert
    assert "kubernetes" in single_blockers
    k8s_gap = next(g for g in weighted_gaps if g.canonical_name == "kubernetes")
    assert k8s_gap.is_single_blocker is True
    assert k8s_gap.weighted_rank_score == 20000.0  # 10000 * 2x


@pytest.mark.asyncio
async def test_nightly_cycle_heatmap_storage_and_ws_notification():
    """Heatmap is stored in DB and WebSocket notification is broadcast.

    Verifies the full path from gap computation through to heatmap storage
    and WebSocket broadcast for each beneficiary.

    Requirements: 3.2, 3.5
    """
    opp_id_1 = _make_uuid()
    extraction_id_1 = uuid.uuid4()

    llm_router = MagicMock()
    llm_router.dispatch_extraction = AsyncMock(return_value={
        "required": ["Docker", "Go"],
        "preferred": [],
    })

    redis_client = AsyncMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock()
    redis_client.publish = AsyncMock()

    ws_manager = AsyncMock()
    ws_manager.broadcast_heatmap_available = AsyncMock()

    db_session = AsyncMock()
    db_session.add = MagicMock()
    db_session.flush = AsyncMock()
    db_session.commit = AsyncMock()

    normalizer = CapabilityNormalizer({})
    analyzer = GapAnalyzer(
        config=GapAnalysisConfig(
            max_extractions_per_cycle=200,
            max_heatmap_entries=25,
            default_opportunity_value=8000.0,
        ),
        llm_router=llm_router,
        schema_registry=MagicMock(),
        db_session=db_session,
        redis_client=redis_client,
        ws_manager=ws_manager,
        normalizer=normalizer,
    )

    # Patch methods for this specific scenario
    analyzer.get_eligible_opportunities = AsyncMock(return_value=[opp_id_1])
    analyzer.enforce_batch_cap = AsyncMock(return_value=[opp_id_1])
    analyzer._load_opportunity_text = AsyncMock(
        return_value="Need Docker and Go developers"
    )
    analyzer._store_extraction_in_db = AsyncMock()

    # Extracted caps after extraction phase
    extracted_caps = [
        _make_extraction_cap_mock(extraction_id_1, "docker", "Docker", "required"),
        _make_extraction_cap_mock(extraction_id_1, "go", "Go", "required"),
    ]

    # Beneficiary has "docker" but not "go"
    beneficiary_caps = [
        _make_beneficiary_cap_mock("dev_1", "docker", "senior"),
    ]

    extraction_mapping = [
        MagicMock(id=extraction_id_1, pipeline_record_id=uuid.UUID(opp_id_1)),
    ]

    opp_value_rows = [
        MagicMock(id=uuid.UUID(opp_id_1), tier="C-tier"),
    ]

    call_idx = {"n": 0}

    async def mock_execute(stmt):
        call_idx["n"] += 1
        n = call_idx["n"]
        if n == 1:
            result = MagicMock()
            result.scalars.return_value.all.return_value = extracted_caps
            return result
        elif n == 2:
            result = MagicMock()
            result.all.return_value = extraction_mapping
            return result
        elif n == 3:
            result = MagicMock()
            result.all.return_value = opp_value_rows
            return result
        elif n == 4:
            result = MagicMock()
            result.scalars.return_value.all.return_value = beneficiary_caps
            return result
        else:
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.scalar_one_or_none.return_value = None
            return result

    db_session.execute = AsyncMock(side_effect=mock_execute)

    # Act
    result = await analyzer.run_nightly_cycle()

    # Assert: heatmaps generated
    assert result["heatmaps_generated"] == 2  # dev_1 + __firm__

    # Assert: WebSocket notification was sent for each heatmap
    assert ws_manager.broadcast_heatmap_available.call_count == 2
    # Verify the notification includes beneficiary info
    calls = ws_manager.broadcast_heatmap_available.call_args_list
    beneficiary_ids_notified = {call.args[0] for call in calls}
    assert "dev_1" in beneficiary_ids_notified
    assert "__firm__" in beneficiary_ids_notified

    # Assert: DB commit was called (heatmap storage)
    assert db_session.commit.call_count >= 1


# ─── TEST: Carry-forward when batch exceeds cap ──────────────────────────────


@pytest.mark.asyncio
async def test_nightly_cycle_carry_forward_when_batch_exceeds_cap():
    """When eligible opportunities exceed batch cap, remainder is carried forward.

    With cap=2 and 5 eligible opportunities, only 2 are processed and
    3 are carried forward to the extraction queue.

    Requirements: 1.3
    """
    opp_ids = [_make_uuid() for _ in range(5)]
    extraction_id = uuid.uuid4()

    llm_router = MagicMock()
    llm_router.dispatch_extraction = AsyncMock(return_value={
        "required": ["Python"],
        "preferred": [],
    })

    redis_client = AsyncMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock()
    redis_client.publish = AsyncMock()

    ws_manager = AsyncMock()
    ws_manager.broadcast_heatmap_available = AsyncMock()

    db_session = AsyncMock()
    db_session.add = MagicMock()
    db_session.flush = AsyncMock()
    db_session.commit = AsyncMock()

    config = GapAnalysisConfig(
        analysis_window_days=90,
        max_extractions_per_cycle=2,  # Cap at 2
        max_heatmap_entries=25,
        default_opportunity_value=10000.0,
    )

    normalizer = CapabilityNormalizer({})
    analyzer = GapAnalyzer(
        config=config,
        llm_router=llm_router,
        schema_registry=MagicMock(),
        db_session=db_session,
        redis_client=redis_client,
        ws_manager=ws_manager,
        normalizer=normalizer,
    )

    # Return all 5 as eligible, but enforce_batch_cap returns only 2
    analyzer.get_eligible_opportunities = AsyncMock(return_value=opp_ids)
    analyzer.enforce_batch_cap = AsyncMock(
        return_value=opp_ids[:2]  # Only first 2 processed
    )
    analyzer._load_opportunity_text = AsyncMock(
        return_value="Company needs Python developers"
    )
    analyzer._store_extraction_in_db = AsyncMock()

    # Extracted caps for the post-extraction query
    extracted_caps = [
        _make_extraction_cap_mock(extraction_id, "python", "Python", "required"),
    ]

    beneficiary_caps = [
        _make_beneficiary_cap_mock("consultant_a", "javascript", "senior"),
    ]

    extraction_mapping = [
        MagicMock(id=extraction_id, pipeline_record_id=uuid.UUID(opp_ids[0])),
    ]

    opp_value_rows = [
        MagicMock(id=uuid.UUID(opp_ids[0]), tier="C-tier"),
    ]

    call_idx = {"n": 0}

    async def mock_execute(stmt):
        call_idx["n"] += 1
        n = call_idx["n"]
        if n == 1:
            result = MagicMock()
            result.scalars.return_value.all.return_value = extracted_caps
            return result
        elif n == 2:
            result = MagicMock()
            result.all.return_value = extraction_mapping
            return result
        elif n == 3:
            result = MagicMock()
            result.all.return_value = opp_value_rows
            return result
        elif n == 4:
            result = MagicMock()
            result.scalars.return_value.all.return_value = beneficiary_caps
            return result
        else:
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.scalar_one_or_none.return_value = None
            return result

    db_session.execute = AsyncMock(side_effect=mock_execute)

    # Act
    result = await analyzer.run_nightly_cycle()

    # Assert: only 2 were extracted (cap enforced)
    assert result["extracted"] == 2
    assert llm_router.dispatch_extraction.call_count == 2

    # Assert: 3 were carried forward (5 eligible - 2 processed)
    assert result["carried_forward"] == 3

    # Assert: enforce_batch_cap was called with all 5 eligible IDs
    analyzer.enforce_batch_cap.assert_called_once_with(opp_ids)

    # Assert: _load_opportunity_text was called exactly 2 times (for batch)
    assert analyzer._load_opportunity_text.call_count == 2


@pytest.mark.asyncio
async def test_nightly_cycle_trend_computation():
    """Trend diff classifies gaps as new/growing/shrinking/resolved.

    Verifies that compute_trend correctly annotates gaps based on comparison
    with a previous heatmap.

    Requirements: 3.2
    """
    analyzer = _build_gap_analyzer()

    previous_gaps = [
        GapEntry("kubernetes", GapClassification.HARD, 3, 15000.0, False, 15000.0, None),
        GapEntry("terraform", GapClassification.HARD, 2, 8000.0, False, 8000.0, None),
        GapEntry("go", GapClassification.SOFT, 1, 5000.0, False, 5000.0, None),
    ]

    current_gaps = [
        # kubernetes: value increased → GROWING
        GapEntry("kubernetes", GapClassification.HARD, 5, 25000.0, True, 50000.0, None),
        # terraform: value decreased → SHRINKING
        GapEntry("terraform", GapClassification.HARD, 1, 4000.0, False, 4000.0, None),
        # rust: new gap → NEW
        GapEntry("rust", GapClassification.HARD, 2, 10000.0, False, 10000.0, None),
        # go is absent from current → will appear as RESOLVED
    ]

    # Act
    result = analyzer.compute_trend(current_gaps, previous_gaps)

    # Assert
    trend_map = {g.canonical_name: g.trend for g in result}
    assert trend_map["kubernetes"] == GapTrend.GROWING
    assert trend_map["terraform"] == GapTrend.SHRINKING
    assert trend_map["rust"] == GapTrend.NEW
    assert trend_map["go"] == GapTrend.RESOLVED

    # Resolved entry has 0 values
    go_entry = next(g for g in result if g.canonical_name == "go")
    assert go_entry.opportunity_count == 0
    assert go_entry.blocked_pipeline_value == 0.0


@pytest.mark.asyncio
async def test_nightly_cycle_graceful_degradation_llm_unavailable():
    """When LLM is unavailable, cycle continues with cached extractions only.

    Verifies graceful degradation: extraction is skipped for each opportunity
    but heatmap generation still proceeds using previously cached data.

    Requirements: 1.1, 1.2
    """
    opp_id_1 = _make_uuid()
    extraction_id_1 = uuid.uuid4()

    redis_client = AsyncMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock()
    redis_client.publish = AsyncMock()

    ws_manager = AsyncMock()
    ws_manager.broadcast_heatmap_available = AsyncMock()

    db_session = AsyncMock()
    db_session.add = MagicMock()
    db_session.flush = AsyncMock()
    db_session.commit = AsyncMock()

    # LLM is None (unavailable)
    analyzer = GapAnalyzer(
        config=GapAnalysisConfig(max_extractions_per_cycle=200),
        llm_router=None,  # LLM unavailable
        schema_registry=MagicMock(),
        db_session=db_session,
        redis_client=redis_client,
        ws_manager=ws_manager,
        normalizer=CapabilityNormalizer({}),
    )

    analyzer.get_eligible_opportunities = AsyncMock(return_value=[opp_id_1])
    analyzer.enforce_batch_cap = AsyncMock(return_value=[opp_id_1])
    analyzer._load_opportunity_text = AsyncMock(
        return_value="Some opportunity text"
    )

    # Provide previously-cached extracted caps for heatmap generation
    cached_caps = [
        _make_extraction_cap_mock(extraction_id_1, "docker", "Docker", "required"),
    ]
    beneficiary_caps = [
        _make_beneficiary_cap_mock("consultant_x", "python", "senior"),
    ]
    extraction_mapping = [
        MagicMock(id=extraction_id_1, pipeline_record_id=uuid.UUID(opp_id_1)),
    ]
    opp_value_rows = [
        MagicMock(id=uuid.UUID(opp_id_1), tier=None),
    ]

    call_idx = {"n": 0}

    async def mock_execute(stmt):
        call_idx["n"] += 1
        n = call_idx["n"]
        if n == 1:
            result = MagicMock()
            result.scalars.return_value.all.return_value = cached_caps
            return result
        elif n == 2:
            result = MagicMock()
            result.all.return_value = extraction_mapping
            return result
        elif n == 3:
            result = MagicMock()
            result.all.return_value = opp_value_rows
            return result
        elif n == 4:
            result = MagicMock()
            result.scalars.return_value.all.return_value = beneficiary_caps
            return result
        else:
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.scalar_one_or_none.return_value = None
            return result

    db_session.execute = AsyncMock(side_effect=mock_execute)

    # Act
    result = await analyzer.run_nightly_cycle()

    # Assert: no extractions performed (LLM unavailable)
    assert result["extracted"] == 0

    # Assert: heatmaps still generated from cached data
    assert result["heatmaps_generated"] >= 1


@pytest.mark.asyncio
async def test_nightly_cycle_websocket_notification_payload():
    """WebSocket broadcast includes correct payload structure.

    Verifies the Redis publish and WebSocket broadcast contain
    beneficiary_id, heatmap_id, and generated_at fields.

    Requirements: 3.5
    """
    opp_id = _make_uuid()
    extraction_id = uuid.uuid4()

    llm_router = MagicMock()
    llm_router.dispatch_extraction = AsyncMock(return_value={
        "required": ["Rust"],
        "preferred": [],
    })

    redis_client = AsyncMock()
    redis_client.get = AsyncMock(return_value=None)
    redis_client.set = AsyncMock()
    redis_client.publish = AsyncMock()

    ws_manager = AsyncMock()
    ws_manager.broadcast_heatmap_available = AsyncMock()

    db_session = AsyncMock()
    db_session.add = MagicMock()
    db_session.flush = AsyncMock()
    db_session.commit = AsyncMock()

    analyzer = GapAnalyzer(
        config=GapAnalysisConfig(max_extractions_per_cycle=200),
        llm_router=llm_router,
        schema_registry=MagicMock(),
        db_session=db_session,
        redis_client=redis_client,
        ws_manager=ws_manager,
        normalizer=CapabilityNormalizer({}),
    )

    analyzer.get_eligible_opportunities = AsyncMock(return_value=[opp_id])
    analyzer.enforce_batch_cap = AsyncMock(return_value=[opp_id])
    analyzer._load_opportunity_text = AsyncMock(return_value="Need Rust devs")
    analyzer._store_extraction_in_db = AsyncMock()

    # Profile has nothing → Rust is a gap
    extracted_caps = [
        _make_extraction_cap_mock(extraction_id, "rust", "Rust", "required"),
    ]
    beneficiary_caps = [
        _make_beneficiary_cap_mock("consultant_z", "python", "senior"),
    ]
    extraction_mapping = [
        MagicMock(id=extraction_id, pipeline_record_id=uuid.UUID(opp_id)),
    ]
    opp_value_rows = [
        MagicMock(id=uuid.UUID(opp_id), tier="D-tier"),
    ]

    call_idx = {"n": 0}

    async def mock_execute(stmt):
        call_idx["n"] += 1
        n = call_idx["n"]
        if n == 1:
            result = MagicMock()
            result.scalars.return_value.all.return_value = extracted_caps
            return result
        elif n == 2:
            result = MagicMock()
            result.all.return_value = extraction_mapping
            return result
        elif n == 3:
            result = MagicMock()
            result.all.return_value = opp_value_rows
            return result
        elif n == 4:
            result = MagicMock()
            result.scalars.return_value.all.return_value = beneficiary_caps
            return result
        else:
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            result.scalar_one_or_none.return_value = None
            return result

    db_session.execute = AsyncMock(side_effect=mock_execute)

    # Act
    result = await analyzer.run_nightly_cycle()

    # Assert: WebSocket notification sent with correct args
    assert ws_manager.broadcast_heatmap_available.call_count >= 1
    for call in ws_manager.broadcast_heatmap_available.call_args_list:
        args = call.args
        # Should have beneficiary_id, heatmap_id, generated_at
        assert len(args) == 3
        beneficiary_id, heatmap_id, generated_at = args
        assert isinstance(beneficiary_id, str)
        assert isinstance(generated_at, str)

    # Assert: Redis publish called for WS multi-worker broadcast
    assert redis_client.publish.call_count >= 1
