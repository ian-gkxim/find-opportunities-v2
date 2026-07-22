"""Repository for review reasoning log persistence.

Handles insert and retrieval of review telemetry data (reasoning logs
and cycle details) using raw SQL via SQLAlchemy text() queries.

Requirements: 3.2, 3.4
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.review_models import (
    CritiqueCategory,
    CycleLog,
    EditOutcome,
    EditReason,
    EditSkipReason,
    ReasoningLog,
    ReviewStatus,
    StructuredEdit,
)

logger = logging.getLogger(__name__)


class ReviewRepository:
    """Persistence layer for review reasoning logs and cycle details.

    Uses raw SQL with text() queries following the same async session
    pattern as the project's workers.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def save_reasoning_log(self, log: ReasoningLog) -> str:
        """Persist a complete ReasoningLog with all cycle details.

        Inserts one row into review_reasoning_logs and one row per cycle
        into review_cycle_details within a single transaction.

        Args:
            log: Complete reasoning log from a review process.

        Returns:
            The UUID string of the inserted reasoning log row.
        """
        log_id = str(uuid.uuid4())

        async with self._session_factory() as session:
            # Insert the top-level reasoning log
            insert_log_stmt = text("""
                INSERT INTO review_reasoning_logs (
                    id, material_id, prepare_technique_id, review_technique_id,
                    total_cycles_executed, max_cycles_configured,
                    final_review_status, started_at, completed_at
                ) VALUES (
                    :id, :material_id, :prepare_technique_id, :review_technique_id,
                    :total_cycles_executed, :max_cycles_configured,
                    :final_review_status, :started_at, :completed_at
                )
            """)
            await session.execute(
                insert_log_stmt,
                {
                    "id": log_id,
                    "material_id": log.material_id,
                    "prepare_technique_id": log.prepare_technique_id,
                    "review_technique_id": log.review_technique_id,
                    "total_cycles_executed": log.total_cycles_executed,
                    "max_cycles_configured": log.max_cycles_configured,
                    "final_review_status": log.final_review_status.value,
                    "started_at": log.started_at,
                    "completed_at": log.completed_at,
                },
            )

            # Insert each cycle detail
            insert_cycle_stmt = text("""
                INSERT INTO review_cycle_details (
                    id, reasoning_log_id, cycle_number,
                    edits_applied, edits_skipped, edits_discarded,
                    narrative_findings, quality_score_before, quality_score_after,
                    duration_ms, skipped_edits_detail, discarded_edits_detail
                ) VALUES (
                    :id, :reasoning_log_id, :cycle_number,
                    :edits_applied, :edits_skipped, :edits_discarded,
                    :narrative_findings, :quality_score_before, :quality_score_after,
                    :duration_ms, :skipped_edits_detail, :discarded_edits_detail
                )
            """)
            for cycle in log.cycles:
                cycle_id = str(uuid.uuid4())
                await session.execute(
                    insert_cycle_stmt,
                    {
                        "id": cycle_id,
                        "reasoning_log_id": log_id,
                        "cycle_number": cycle.cycle_number,
                        "edits_applied": cycle.edits_applied,
                        "edits_skipped": cycle.edits_skipped,
                        "edits_discarded": cycle.edits_discarded,
                        "narrative_findings": json.dumps(
                            _serialize_narrative_findings(cycle.narrative_findings_by_category)
                        ),
                        "quality_score_before": cycle.quality_score_before,
                        "quality_score_after": cycle.quality_score_after,
                        "duration_ms": cycle.duration_ms,
                        "skipped_edits_detail": json.dumps(
                            _serialize_edit_outcomes(cycle.skipped_edits)
                        ),
                        "discarded_edits_detail": json.dumps(
                            _serialize_edit_outcomes(cycle.discarded_edits)
                        ),
                    },
                )

            await session.commit()

        logger.debug(
            "Saved reasoning log %s for material %s (%d cycles)",
            log_id,
            log.material_id,
            len(log.cycles),
        )
        return log_id

    async def get_reasoning_log(self, material_id: str) -> ReasoningLog | None:
        """Retrieve the reasoning log for a given material.

        Args:
            material_id: UUID of the material to look up.

        Returns:
            The ReasoningLog if found, or None if no review exists.
        """
        async with self._session_factory() as session:
            # Fetch the top-level log
            log_stmt = text("""
                SELECT id, material_id, prepare_technique_id, review_technique_id,
                       total_cycles_executed, max_cycles_configured,
                       final_review_status, started_at, completed_at
                FROM review_reasoning_logs
                WHERE material_id = :material_id
                ORDER BY created_at DESC
                LIMIT 1
            """)
            result = await session.execute(log_stmt, {"material_id": material_id})
            log_row = result.fetchone()

            if log_row is None:
                return None

            log_id = str(log_row[0])

            # Fetch all cycle details for this log
            cycles_stmt = text("""
                SELECT cycle_number, edits_applied, edits_skipped, edits_discarded,
                       narrative_findings, quality_score_before, quality_score_after,
                       duration_ms, skipped_edits_detail, discarded_edits_detail
                FROM review_cycle_details
                WHERE reasoning_log_id = :log_id
                ORDER BY cycle_number ASC
            """)
            cycles_result = await session.execute(cycles_stmt, {"log_id": log_id})
            cycle_rows = cycles_result.fetchall()

            cycles = [
                CycleLog(
                    cycle_number=row[0],
                    edits_applied=row[1],
                    edits_skipped=row[2],
                    edits_discarded=row[3],
                    narrative_findings_by_category=_deserialize_narrative_findings(row[4]),
                    quality_score_before=row[5],
                    quality_score_after=row[6],
                    duration_ms=row[7],
                    skipped_edits=_deserialize_edit_outcomes(row[8]),
                    discarded_edits=_deserialize_edit_outcomes(row[9]),
                )
                for row in cycle_rows
            ]

            return ReasoningLog(
                material_id=str(log_row[1]),
                prepare_technique_id=log_row[2],
                review_technique_id=log_row[3],
                cycles=cycles,
                total_cycles_executed=log_row[4],
                max_cycles_configured=log_row[5],
                final_review_status=ReviewStatus(log_row[6]),
                started_at=log_row[7],
                completed_at=log_row[8],
            )

    async def get_unreviewed_materials(self, limit: int = 50) -> list[dict]:
        """Fetch materials marked as unreviewed for Dashboard display.

        Returns a list of dicts with material_id, prepare_technique_id,
        review_technique_id, and completed_at for the "Requires Action" view.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of dicts representing unreviewed material summaries.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT material_id, prepare_technique_id, review_technique_id,
                       completed_at
                FROM review_reasoning_logs
                WHERE final_review_status = :status
                ORDER BY completed_at DESC
                LIMIT :limit
            """)
            result = await session.execute(
                stmt,
                {"status": ReviewStatus.UNREVIEWED.value, "limit": limit},
            )
            rows = result.fetchall()

            return [
                {
                    "material_id": str(row[0]),
                    "prepare_technique_id": row[1],
                    "review_technique_id": row[2],
                    "completed_at": row[3],
                }
                for row in rows
            ]

    async def mark_unreviewed(self, material_id: str) -> None:
        """Mark a material as unreviewed for graceful degradation.

        Called when the review process fails entirely (all retries exhausted).
        If a reasoning log already exists for this material, updates its status.
        Otherwise creates a minimal log entry recording the failure.

        Args:
            material_id: UUID of the material that could not be reviewed.
        """
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            # Try to update existing log first
            update_stmt = text("""
                UPDATE review_reasoning_logs
                SET final_review_status = :status, completed_at = :completed_at
                WHERE material_id = :material_id
                  AND final_review_status != :status
            """)
            result = await session.execute(
                update_stmt,
                {
                    "status": ReviewStatus.UNREVIEWED.value,
                    "completed_at": now,
                    "material_id": material_id,
                },
            )

            if result.rowcount == 0:
                # No existing log found — insert a minimal record
                insert_stmt = text("""
                    INSERT INTO review_reasoning_logs (
                        id, material_id, prepare_technique_id, review_technique_id,
                        total_cycles_executed, max_cycles_configured,
                        final_review_status, started_at, completed_at
                    ) VALUES (
                        :id, :material_id, :prepare_technique_id, :review_technique_id,
                        :total_cycles_executed, :max_cycles_configured,
                        :final_review_status, :started_at, :completed_at
                    )
                    ON CONFLICT DO NOTHING
                """)
                await session.execute(
                    insert_stmt,
                    {
                        "id": str(uuid.uuid4()),
                        "material_id": material_id,
                        "prepare_technique_id": "unknown",
                        "review_technique_id": "unknown",
                        "total_cycles_executed": 0,
                        "max_cycles_configured": 0,
                        "final_review_status": ReviewStatus.UNREVIEWED.value,
                        "started_at": now,
                        "completed_at": now,
                    },
                )

            await session.commit()

        logger.info("Marked material %s as unreviewed", material_id)


# ─── Serialization helpers ────────────────────────────────────────────────────


def _serialize_narrative_findings(findings: dict[CritiqueCategory, int]) -> dict[str, int]:
    """Convert CritiqueCategory keys to string for JSON storage."""
    return {category.value: count for category, count in findings.items()}


def _deserialize_narrative_findings(data: dict | str | None) -> dict[CritiqueCategory, int]:
    """Reconstruct CritiqueCategory-keyed dict from JSON storage."""
    if data is None:
        return {}
    if isinstance(data, str):
        data = json.loads(data)
    return {CritiqueCategory(key): value for key, value in data.items()}


def _serialize_edit_outcomes(outcomes: list[EditOutcome]) -> list[dict]:
    """Serialize EditOutcome list to JSON-compatible dicts."""
    return [
        {
            "old_string": outcome.edit.old_string,
            "new_string": outcome.edit.new_string,
            "target_material_id": outcome.edit.target_material_id,
            "reason": outcome.edit.reason.value,
            "category": outcome.edit.category.value,
            "applied": outcome.applied,
            "skip_reason": outcome.skip_reason.value if outcome.skip_reason else None,
        }
        for outcome in outcomes
    ]


def _deserialize_edit_outcomes(data: list | str | None) -> list[EditOutcome]:
    """Reconstruct EditOutcome list from JSON storage."""
    if data is None:
        return []
    if isinstance(data, str):
        data = json.loads(data)
    return [
        EditOutcome(
            edit=StructuredEdit(
                target_material_id=item.get("target_material_id", ""),
                old_string=item.get("old_string", ""),
                new_string=item.get("new_string", ""),
                reason=EditReason(item["reason"]),
                category=CritiqueCategory(item["category"]),
            ),
            applied=item.get("applied", False),
            skip_reason=EditSkipReason(item["skip_reason"]) if item.get("skip_reason") else None,
        )
        for item in data
    ]
