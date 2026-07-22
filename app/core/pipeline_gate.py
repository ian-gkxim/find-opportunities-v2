"""Pipeline Gate Service for enforcing grounding verification on state transitions.

Prevents pipeline records from advancing to gated states (Approve, Applied, Sent,
Proposal Submitted) when ungrounded claims exist. Also provides a warning badge
indicator for materials with only partially_grounded claims.

Requirements: 3.1, 3.4
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.core.grounding_verifier import (
    Claim,
    GroundingStatus,
    MaterialGroundingStatus,
)

if TYPE_CHECKING:
    from app.repositories.grounding_repository import GroundingRepository

logger = logging.getLogger(__name__)


class PipelineGateService:
    """Enforces grounding verification gate on pipeline state transitions.

    Requirements: 3.1, 3.4
    """

    GATED_STATES = {"Approve", "Applied", "Sent", "Proposal Submitted"}

    def __init__(self, db_repo: "GroundingRepository") -> None:
        self._db = db_repo

    async def can_transition(
        self,
        pipeline_record_id: str,
        target_state: str,
    ) -> tuple[bool, list[Claim] | None]:
        """Check if a pipeline record can transition to target_state.

        Returns:
        - (True, None) if target_state is not gated or grounding allows advancement
        - (False, []) if no grounding report exists (material hasn't been verified)
        - (False, ungrounded_claims) if transition is blocked by ungrounded claims

        This method is called by the pipeline state machine before
        any state transition to a gated state.

        Requirements: 3.1
        """
        if target_state not in self.GATED_STATES:
            return (True, None)

        report = await self._db.get_latest_grounding_report(pipeline_record_id)
        if report is None:
            # No grounding report exists — material hasn't been verified
            return (False, [])

        if report.material_grounding_status == MaterialGroundingStatus.GROUNDING_BLOCKED:
            ungrounded = [
                c for c in report.claims
                if c.grounding_status == GroundingStatus.UNGROUNDED
            ]
            return (False, ungrounded)

        return (True, None)

    async def get_warning_badge(
        self,
        pipeline_record_id: str,
    ) -> bool:
        """Check if pipeline record should display a warning badge.

        Returns True if material has partially_grounded claims
        but no ungrounded claims (pipeline can advance with warning).

        Requirements: 3.4
        """
        report = await self._db.get_latest_grounding_report(pipeline_record_id)
        if report is None:
            return False
        return (
            report.partially_grounded_count > 0
            and report.ungrounded_count == 0
        )
