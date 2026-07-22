"""Unit tests for grounding dashboard integration.

Tests:
- GroundingNotificationService WebSocket push logic (Task 15.1)
- PipelineGateService.get_warning_badge() display integration (Task 15.2)
- build_grounding_action_items() for dashboard display (Task 15.1)

Requirements: 1.4, 3.1, 3.4
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.grounding_verifier import (
    Claim,
    ClaimCategory,
    GroundingReport,
    GroundingResult,
    GroundingStatus,
    MaterialGroundingStatus,
)
from app.core.grounding_notifications import (
    GroundingNotificationService,
    build_grounding_action_items,
)
from app.core.pipeline_gate import PipelineGateService


# ─── FIXTURES ─────────────────────────────────────────────────────────────────


def _make_claim(
    *,
    claim_id: str = "claim-1",
    grounding_status: GroundingStatus = GroundingStatus.UNGROUNDED,
    claim_text: str = "Expert in Kubernetes",
    source_span: str = "Expert in Kubernetes",
) -> Claim:
    return Claim(
        id=claim_id,
        material_id="mat-001",
        category=ClaimCategory.SKILL_TECHNOLOGY,
        claim_text=claim_text,
        source_span=source_span,
        source_span_start=0,
        source_span_end=len(source_span),
        grounding_status=grounding_status,
    )


def _make_report(
    *,
    material_grounding_status: MaterialGroundingStatus,
    grounded_count: int = 2,
    partially_grounded_count: int = 0,
    ungrounded_count: int = 0,
    claims: list[Claim] | None = None,
    material_id: str = "mat-001",
    pipeline_record_id: str = "pr-001",
) -> GroundingReport:
    now = datetime.now(timezone.utc)
    total = grounded_count + partially_grounded_count + ungrounded_count
    return GroundingReport(
        id="rpt-001",
        material_id=material_id,
        pipeline_record_id=pipeline_record_id,
        claims=claims or [],
        total_claims=total,
        grounded_count=grounded_count,
        partially_grounded_count=partially_grounded_count,
        ungrounded_count=ungrounded_count,
        material_grounding_status=material_grounding_status,
        extraction_duration_ms=100,
        verification_duration_ms=50,
        created_at=now,
        updated_at=now,
    )


def _make_result(
    *,
    material_grounding_status: MaterialGroundingStatus,
    requires_action: bool = True,
    blocked_states: list[str] | None = None,
    report: GroundingReport | None = None,
) -> GroundingResult:
    if report is None:
        report = _make_report(
            material_grounding_status=material_grounding_status
        )
    return GroundingResult(
        material_id=report.material_id,
        material_grounding_status=material_grounding_status,
        grounding_report=report,
        blocked_states=blocked_states or [],
        requires_action=requires_action,
    )


# ─── Task 15.1: WebSocket notifications ──────────────────────────────────────


class TestGroundingNotificationService:
    """Tests for GroundingNotificationService (Task 15.1, Requirements 1.4, 3.1)."""

    @pytest.fixture
    def mock_ws_manager(self):
        manager = MagicMock()
        manager.broadcast_notification = AsyncMock()
        return manager

    @pytest.fixture
    def notification_service(self, mock_ws_manager):
        return GroundingNotificationService(ws_manager=mock_ws_manager)

    @pytest.mark.asyncio
    async def test_blocked_material_sends_notification(
        self, notification_service, mock_ws_manager
    ):
        """Blocked materials push a grounding_blocked notification via WebSocket."""
        ungrounded_claims = [
            _make_claim(claim_id="c-1", grounding_status=GroundingStatus.UNGROUNDED),
            _make_claim(
                claim_id="c-2",
                grounding_status=GroundingStatus.UNGROUNDED,
                claim_text="10 years Python experience",
                source_span="10 years Python experience",
            ),
        ]
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            ungrounded_count=2,
            claims=ungrounded_claims,
        )
        result = _make_result(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            requires_action=True,
            blocked_states=["Approve", "Applied", "Sent", "Proposal Submitted"],
            report=report,
        )

        await notification_service.notify_requires_action(result)

        mock_ws_manager.broadcast_notification.assert_called_once()
        notification = mock_ws_manager.broadcast_notification.call_args[0][0]

        assert notification["category"] == "grounding_blocked"
        assert notification["severity"] == "error"
        assert notification["material_id"] == "mat-001"
        assert notification["pipeline_record_id"] == "pr-001"
        assert notification["ungrounded_count"] == 2
        assert len(notification["ungrounded_claims"]) == 2
        # Verify claim details include source spans
        assert notification["ungrounded_claims"][0]["source_span"] == "Expert in Kubernetes"
        assert notification["ungrounded_claims"][1]["claim_text"] == "10 years Python experience"

    @pytest.mark.asyncio
    async def test_unverified_material_sends_info_notification(
        self, notification_service, mock_ws_manager
    ):
        """Unverified materials push a grounding_unverified notification (info severity)."""
        result = _make_result(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_UNVERIFIED,
            requires_action=True,
        )

        await notification_service.notify_requires_action(result)

        mock_ws_manager.broadcast_notification.assert_called_once()
        notification = mock_ws_manager.broadcast_notification.call_args[0][0]

        assert notification["category"] == "grounding_unverified"
        assert notification["severity"] == "info"
        assert notification["material_id"] == "mat-001"

    @pytest.mark.asyncio
    async def test_verified_material_no_notification(
        self, notification_service, mock_ws_manager
    ):
        """Verified materials do not trigger any notification."""
        result = _make_result(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            requires_action=False,
        )

        await notification_service.notify_requires_action(result)

        mock_ws_manager.broadcast_notification.assert_not_called()

    @pytest.mark.asyncio
    async def test_blocked_notification_includes_blocked_states(
        self, notification_service, mock_ws_manager
    ):
        """Blocked notification includes the list of states that are blocked."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            ungrounded_count=1,
            claims=[_make_claim()],
        )
        result = _make_result(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            requires_action=True,
            blocked_states=["Approve", "Applied", "Sent", "Proposal Submitted"],
            report=report,
        )

        await notification_service.notify_requires_action(result)

        notification = mock_ws_manager.broadcast_notification.call_args[0][0]
        assert "Approve" in notification["blocked_states"]
        assert "Applied" in notification["blocked_states"]
        assert "Sent" in notification["blocked_states"]
        assert "Proposal Submitted" in notification["blocked_states"]


class TestBuildGroundingActionItems:
    """Tests for build_grounding_action_items() dashboard helper (Task 15.1)."""

    def test_blocked_report_creates_error_action_item(self):
        """Blocked reports produce an error-severity action item with claims."""
        claims = [_make_claim(claim_id="c-1")]
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            ungrounded_count=1,
            claims=claims,
        )

        items = build_grounding_action_items([report])

        assert len(items) == 1
        assert items[0]["type"] == "grounding_blocked"
        assert items[0]["severity"] == "error"
        assert len(items[0]["ungrounded_claims"]) == 1
        assert items[0]["ungrounded_claims"][0]["claim_text"] == "Expert in Kubernetes"

    def test_unverified_report_creates_info_action_item(self):
        """Unverified reports produce an info-severity action item."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_UNVERIFIED,
        )

        items = build_grounding_action_items([report])

        assert len(items) == 1
        assert items[0]["type"] == "grounding_unverified"
        assert items[0]["severity"] == "info"
        assert items[0]["ungrounded_claims"] == []

    def test_verified_report_creates_no_action_item(self):
        """Verified reports do not produce action items."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
        )

        items = build_grounding_action_items([report])

        assert len(items) == 0

    def test_multiple_reports_produces_multiple_items(self):
        """Multiple blocked/unverified reports produce one item each."""
        reports = [
            _make_report(
                material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
                ungrounded_count=1,
                claims=[_make_claim(claim_id="c-1")],
                material_id="mat-001",
            ),
            _make_report(
                material_grounding_status=MaterialGroundingStatus.GROUNDING_UNVERIFIED,
                material_id="mat-002",
            ),
            _make_report(
                material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
                material_id="mat-003",
            ),
        ]

        items = build_grounding_action_items(reports)

        assert len(items) == 2
        assert items[0]["id"] == "mat-001"
        assert items[1]["id"] == "mat-002"


# ─── Task 15.2: Warning badge via PipelineGateService.get_warning_badge() ────


class TestWarningBadgeIntegration:
    """Tests for warning badge display logic (Task 15.2, Requirement 3.4)."""

    @pytest.fixture
    def mock_db_repo(self):
        repo = MagicMock()
        repo.get_latest_grounding_report = AsyncMock(return_value=None)
        return repo

    @pytest.fixture
    def gate_service(self, mock_db_repo):
        return PipelineGateService(db_repo=mock_db_repo)

    @pytest.mark.asyncio
    async def test_warning_badge_shown_for_partially_grounded_only(
        self, gate_service, mock_db_repo
    ):
        """Badge shown when partially_grounded > 0 and ungrounded == 0."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            grounded_count=3,
            partially_grounded_count=2,
            ungrounded_count=0,
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        result = await gate_service.get_warning_badge("pr-001")

        assert result is True

    @pytest.mark.asyncio
    async def test_warning_badge_hidden_when_all_grounded(
        self, gate_service, mock_db_repo
    ):
        """No badge when all claims are fully grounded."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_VERIFIED,
            grounded_count=5,
            partially_grounded_count=0,
            ungrounded_count=0,
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        result = await gate_service.get_warning_badge("pr-001")

        assert result is False

    @pytest.mark.asyncio
    async def test_warning_badge_hidden_when_ungrounded_exists(
        self, gate_service, mock_db_repo
    ):
        """No badge when ungrounded claims exist (material is blocked, not warned)."""
        report = _make_report(
            material_grounding_status=MaterialGroundingStatus.GROUNDING_BLOCKED,
            grounded_count=1,
            partially_grounded_count=2,
            ungrounded_count=1,
        )
        mock_db_repo.get_latest_grounding_report.return_value = report

        result = await gate_service.get_warning_badge("pr-001")

        assert result is False

    @pytest.mark.asyncio
    async def test_warning_badge_hidden_when_no_report(
        self, gate_service, mock_db_repo
    ):
        """No badge when no grounding report exists."""
        mock_db_repo.get_latest_grounding_report.return_value = None

        result = await gate_service.get_warning_badge("pr-001")

        assert result is False
