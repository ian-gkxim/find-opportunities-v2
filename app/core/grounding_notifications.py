"""Grounding Notification Service — pushes WebSocket notifications for grounding events.

When materials are blocked (grounding_blocked) or unverified (grounding_unverified),
pushes real-time notifications via the WebSocket manager so the Dashboard
"Requires Action" section can display them immediately.

Requirements: 1.4, 3.1
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.core.grounding_verifier import (
    Claim,
    GroundingReport,
    GroundingResult,
    GroundingStatus,
    MaterialGroundingStatus,
)

if TYPE_CHECKING:
    from app.core.websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)


class GroundingNotificationService:
    """Pushes WebSocket notifications for grounding-related events.

    Integrates with the existing WebSocketManager to broadcast notifications
    when materials are blocked or marked unverified by the Grounding_Verifier.

    Requirements: 1.4, 3.1
    """

    # Notification categories used in the WebSocket message
    CATEGORY_GROUNDING_BLOCKED = "grounding_blocked"
    CATEGORY_GROUNDING_UNVERIFIED = "grounding_unverified"

    def __init__(self, ws_manager: "WebSocketManager") -> None:
        self._ws = ws_manager

    async def notify_requires_action(self, result: GroundingResult) -> None:
        """Push a notification based on the grounding result status.

        - If material is blocked: sends a "grounding_blocked" notification
          listing each ungrounded claim with its source text span.
        - If material is unverified: sends a "grounding_unverified" notification
          as an informational notice (not blocking).
        - If material is verified: no notification is sent.

        Requirements: 1.4, 3.1
        """
        if not result.requires_action:
            return

        status = result.material_grounding_status

        if status == MaterialGroundingStatus.GROUNDING_BLOCKED:
            await self._notify_blocked(result)
        elif status == MaterialGroundingStatus.GROUNDING_UNVERIFIED:
            await self._notify_unverified(result)

    async def _notify_blocked(self, result: GroundingResult) -> None:
        """Send notification for a blocked material with ungrounded claims.

        Includes each ungrounded claim's text and source span for
        display in the Dashboard "Requires Action" section.

        Requirements: 3.1
        """
        report = result.grounding_report
        ungrounded_claims = [
            c for c in report.claims
            if c.grounding_status == GroundingStatus.UNGROUNDED
        ]

        claims_summary = [
            {
                "claim_id": c.id,
                "claim_text": c.claim_text,
                "source_span": c.source_span,
                "source_span_start": c.source_span_start,
                "source_span_end": c.source_span_end,
                "category": c.category.value if hasattr(c.category, "value") else c.category,
            }
            for c in ungrounded_claims
        ]

        notification: dict[str, Any] = {
            "category": self.CATEGORY_GROUNDING_BLOCKED,
            "title": "Material blocked — ungrounded claims detected",
            "message": (
                f"Material {report.material_id[:8]}... has "
                f"{len(ungrounded_claims)} ungrounded claim(s) that must be "
                f"resolved before pipeline advancement."
            ),
            "material_id": report.material_id,
            "pipeline_record_id": report.pipeline_record_id,
            "ungrounded_count": len(ungrounded_claims),
            "ungrounded_claims": claims_summary,
            "blocked_states": result.blocked_states,
            "severity": "error",
        }

        await self._ws.broadcast_notification(notification)

        logger.info(
            "Sent grounding_blocked notification: material=%s, "
            "ungrounded_claims=%d",
            report.material_id,
            len(ungrounded_claims),
        )

    async def _notify_unverified(self, result: GroundingResult) -> None:
        """Send informational notification for an unverified material.

        The material is NOT blocked, but extraction failed so grounding
        could not be confirmed. Surfaces as informational notice.

        Requirements: 1.4
        """
        report = result.grounding_report

        notification: dict[str, Any] = {
            "category": self.CATEGORY_GROUNDING_UNVERIFIED,
            "title": "Material grounding unverified",
            "message": (
                f"Material {report.material_id[:8]}... could not be verified "
                f"(extraction failed after retries). Pipeline can advance, "
                f"but claims have not been checked."
            ),
            "material_id": report.material_id,
            "pipeline_record_id": report.pipeline_record_id,
            "severity": "info",
        }

        await self._ws.broadcast_notification(notification)

        logger.info(
            "Sent grounding_unverified notification: material=%s",
            report.material_id,
        )


def build_grounding_action_items(
    reports: list[GroundingReport],
) -> list[dict[str, Any]]:
    """Build Dashboard 'Requires Action' entries from grounding reports.

    Returns action items for:
    - Blocked materials (grounding_blocked): listed with ungrounded claims
    - Unverified materials (grounding_unverified): listed with informational notice

    Used by the Dashboard API to include grounding-related items in the
    'Requires Action' section alongside stale follow-ups and other items.

    Requirements: 1.4, 3.1
    """
    action_items: list[dict[str, Any]] = []

    for report in reports:
        if report.material_grounding_status == MaterialGroundingStatus.GROUNDING_BLOCKED:
            ungrounded_claims = [
                c for c in report.claims
                if c.grounding_status == GroundingStatus.UNGROUNDED
            ]
            action_items.append({
                "id": report.material_id,
                "type": "grounding_blocked",
                "title": "Blocked — ungrounded claims",
                "description": (
                    f"{len(ungrounded_claims)} ungrounded claim(s) detected. "
                    f"Resolve to unblock pipeline advancement."
                ),
                "pipeline_record_id": report.pipeline_record_id,
                "ungrounded_claims": [
                    {
                        "claim_id": c.id,
                        "claim_text": c.claim_text,
                        "source_span": c.source_span,
                    }
                    for c in ungrounded_claims
                ],
                "severity": "error",
                "created_at": report.created_at.isoformat(),
            })

        elif report.material_grounding_status == MaterialGroundingStatus.GROUNDING_UNVERIFIED:
            action_items.append({
                "id": report.material_id,
                "type": "grounding_unverified",
                "title": "Grounding unverified",
                "description": (
                    "Claim extraction failed after retries. Pipeline can advance "
                    "but factual claims have not been checked."
                ),
                "pipeline_record_id": report.pipeline_record_id,
                "ungrounded_claims": [],
                "severity": "info",
                "created_at": report.created_at.isoformat(),
            })

    return action_items
