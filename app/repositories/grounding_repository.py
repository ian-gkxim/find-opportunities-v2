"""Repository for grounding verification persistence.

Handles insert, retrieval, and update of grounding reports, claims,
resolutions, and analytics queries using raw SQL via SQLAlchemy text() queries.

Requirements: 2.4, 3.3
"""

import json
import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.grounding_verifier import (
    Claim,
    ClaimCategory,
    GroundingReport,
    GroundingStatus,
    MaterialGroundingStatus,
    SourcePointer,
)

logger = logging.getLogger(__name__)


class GroundingRepository:
    """Persistence layer for grounding reports, claims, and resolutions.

    Uses raw SQL with text() queries following the same async session
    pattern as ReviewRepository.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def store_grounding_report(self, report: GroundingReport) -> str:
        """Persist a complete GroundingReport with all claims in a single transaction.

        Inserts one row into grounding_reports and one row per claim
        into grounding_claims within a single transaction.

        Args:
            report: Complete grounding report from a verification process.

        Returns:
            The UUID string of the inserted grounding report row.
        """
        async with self._session_factory() as session:
            # Insert the top-level grounding report
            insert_report_stmt = text("""
                INSERT INTO grounding_reports (
                    id, material_id, pipeline_record_id,
                    prepare_technique_id, grounding_technique_id,
                    total_claims, grounded_count, partially_grounded_count,
                    ungrounded_count, material_grounding_status,
                    extraction_duration_ms, verification_duration_ms,
                    created_at, updated_at
                ) VALUES (
                    :id, :material_id, :pipeline_record_id,
                    :prepare_technique_id, :grounding_technique_id,
                    :total_claims, :grounded_count, :partially_grounded_count,
                    :ungrounded_count, :material_grounding_status,
                    :extraction_duration_ms, :verification_duration_ms,
                    :created_at, :updated_at
                )
            """)
            await session.execute(
                insert_report_stmt,
                {
                    "id": report.id,
                    "material_id": report.material_id,
                    "pipeline_record_id": report.pipeline_record_id,
                    "prepare_technique_id": getattr(report, "prepare_technique_id", "unknown"),
                    "grounding_technique_id": getattr(report, "grounding_technique_id", "standard_grounding"),
                    "total_claims": report.total_claims,
                    "grounded_count": report.grounded_count,
                    "partially_grounded_count": report.partially_grounded_count,
                    "ungrounded_count": report.ungrounded_count,
                    "material_grounding_status": report.material_grounding_status.value,
                    "extraction_duration_ms": report.extraction_duration_ms,
                    "verification_duration_ms": report.verification_duration_ms,
                    "created_at": report.created_at,
                    "updated_at": report.updated_at,
                },
            )

            # Insert each claim
            insert_claim_stmt = text("""
                INSERT INTO grounding_claims (
                    id, grounding_report_id, category, claim_text,
                    source_span, source_span_start, source_span_end,
                    grounding_status, is_prospect_side,
                    source_asset_type, source_asset_id, source_passage,
                    discrepancy, created_at, updated_at
                ) VALUES (
                    :id, :grounding_report_id, :category, :claim_text,
                    :source_span, :source_span_start, :source_span_end,
                    :grounding_status, :is_prospect_side,
                    :source_asset_type, :source_asset_id, :source_passage,
                    :discrepancy, :created_at, :updated_at
                )
            """)
            now = datetime.now(timezone.utc)
            for claim in report.claims:
                await session.execute(
                    insert_claim_stmt,
                    {
                        "id": claim.id,
                        "grounding_report_id": report.id,
                        "category": claim.category.value,
                        "claim_text": claim.claim_text,
                        "source_span": claim.source_span,
                        "source_span_start": claim.source_span_start,
                        "source_span_end": claim.source_span_end,
                        "grounding_status": claim.grounding_status.value if claim.grounding_status else "ungrounded",
                        "is_prospect_side": claim.is_prospect_side,
                        "source_asset_type": claim.source_pointer.asset_type if claim.source_pointer else None,
                        "source_asset_id": claim.source_pointer.asset_id if claim.source_pointer else None,
                        "source_passage": claim.source_pointer.passage if claim.source_pointer else None,
                        "discrepancy": claim.discrepancy,
                        "created_at": now,
                        "updated_at": now,
                    },
                )

            await session.commit()

        logger.debug(
            "Stored grounding report %s for pipeline_record %s (%d claims)",
            report.id,
            report.pipeline_record_id,
            len(report.claims),
        )
        return report.id

    async def get_latest_grounding_report(self, pipeline_record_id: str) -> GroundingReport | None:
        """Retrieve the most recent grounding report for a pipeline record.

        Fetches the latest report (by created_at) and JOINs with its claims.

        Args:
            pipeline_record_id: UUID of the pipeline record to look up.

        Returns:
            The GroundingReport if found, or None if no report exists.
        """
        async with self._session_factory() as session:
            # Fetch the latest report for this pipeline_record_id
            report_stmt = text("""
                SELECT id, material_id, pipeline_record_id,
                       prepare_technique_id, grounding_technique_id,
                       total_claims, grounded_count, partially_grounded_count,
                       ungrounded_count, material_grounding_status,
                       extraction_duration_ms, verification_duration_ms,
                       created_at, updated_at
                FROM grounding_reports
                WHERE pipeline_record_id = :pipeline_record_id
                ORDER BY created_at DESC
                LIMIT 1
            """)
            result = await session.execute(
                report_stmt, {"pipeline_record_id": pipeline_record_id}
            )
            report_row = result.fetchone()

            if report_row is None:
                return None

            report_id = str(report_row[0])

            # Fetch all claims for this report
            claims_stmt = text("""
                SELECT id, category, claim_text, source_span,
                       source_span_start, source_span_end,
                       grounding_status, is_prospect_side,
                       source_asset_type, source_asset_id, source_passage,
                       discrepancy
                FROM grounding_claims
                WHERE grounding_report_id = :report_id
                ORDER BY source_span_start ASC
            """)
            claims_result = await session.execute(claims_stmt, {"report_id": report_id})
            claim_rows = claims_result.fetchall()

            claims = [
                _row_to_claim(row, material_id=str(report_row[1]))
                for row in claim_rows
            ]

            return GroundingReport(
                id=report_id,
                material_id=str(report_row[1]),
                pipeline_record_id=str(report_row[2]),
                claims=claims,
                total_claims=report_row[5],
                grounded_count=report_row[6],
                partially_grounded_count=report_row[7],
                ungrounded_count=report_row[8],
                material_grounding_status=MaterialGroundingStatus(report_row[9]),
                extraction_duration_ms=report_row[10],
                verification_duration_ms=report_row[11],
                created_at=report_row[12],
                updated_at=report_row[13],
            )

    async def get_latest_grounding_report_by_material(self, material_id: str) -> GroundingReport | None:
        """Retrieve the most recent grounding report for a material.

        Fetches the latest report (by created_at) for a given material_id
        and JOINs with its claims.

        Args:
            material_id: UUID of the material to look up.

        Returns:
            The GroundingReport if found, or None if no report exists.
        """
        async with self._session_factory() as session:
            report_stmt = text("""
                SELECT id, material_id, pipeline_record_id,
                       prepare_technique_id, grounding_technique_id,
                       total_claims, grounded_count, partially_grounded_count,
                       ungrounded_count, material_grounding_status,
                       extraction_duration_ms, verification_duration_ms,
                       created_at, updated_at
                FROM grounding_reports
                WHERE material_id = :material_id
                ORDER BY created_at DESC
                LIMIT 1
            """)
            result = await session.execute(
                report_stmt, {"material_id": material_id}
            )
            report_row = result.fetchone()

            if report_row is None:
                return None

            report_id = str(report_row[0])

            # Fetch all claims for this report
            claims_stmt = text("""
                SELECT id, category, claim_text, source_span,
                       source_span_start, source_span_end,
                       grounding_status, is_prospect_side,
                       source_asset_type, source_asset_id, source_passage,
                       discrepancy
                FROM grounding_claims
                WHERE grounding_report_id = :report_id
                ORDER BY source_span_start ASC
            """)
            claims_result = await session.execute(claims_stmt, {"report_id": report_id})
            claim_rows = claims_result.fetchall()

            claims = [
                _row_to_claim(row, material_id=str(report_row[1]))
                for row in claim_rows
            ]

            return GroundingReport(
                id=report_id,
                material_id=str(report_row[1]),
                pipeline_record_id=str(report_row[2]),
                claims=claims,
                total_claims=report_row[5],
                grounded_count=report_row[6],
                partially_grounded_count=report_row[7],
                ungrounded_count=report_row[8],
                material_grounding_status=MaterialGroundingStatus(report_row[9]),
                extraction_duration_ms=report_row[10],
                verification_duration_ms=report_row[11],
                created_at=report_row[12],
                updated_at=report_row[13],
            )

    async def update_grounding_report(self, report: GroundingReport) -> None:
        """Update an existing grounding report's counts and claim statuses.

        Updates the report-level aggregate counts and each claim's
        grounding_status, source pointer, and discrepancy fields.

        Args:
            report: The updated GroundingReport with new counts and claim statuses.
        """
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            # Update the report-level fields
            update_report_stmt = text("""
                UPDATE grounding_reports
                SET total_claims = :total_claims,
                    grounded_count = :grounded_count,
                    partially_grounded_count = :partially_grounded_count,
                    ungrounded_count = :ungrounded_count,
                    material_grounding_status = :material_grounding_status,
                    verification_duration_ms = :verification_duration_ms,
                    updated_at = :updated_at
                WHERE id = :id
            """)
            await session.execute(
                update_report_stmt,
                {
                    "id": report.id,
                    "total_claims": report.total_claims,
                    "grounded_count": report.grounded_count,
                    "partially_grounded_count": report.partially_grounded_count,
                    "ungrounded_count": report.ungrounded_count,
                    "material_grounding_status": report.material_grounding_status.value,
                    "verification_duration_ms": report.verification_duration_ms,
                    "updated_at": now,
                },
            )

            # Update each claim's status and source information
            update_claim_stmt = text("""
                UPDATE grounding_claims
                SET grounding_status = :grounding_status,
                    source_asset_type = :source_asset_type,
                    source_asset_id = :source_asset_id,
                    source_passage = :source_passage,
                    discrepancy = :discrepancy,
                    updated_at = :updated_at
                WHERE id = :id
            """)
            for claim in report.claims:
                await session.execute(
                    update_claim_stmt,
                    {
                        "id": claim.id,
                        "grounding_status": claim.grounding_status.value if claim.grounding_status else "ungrounded",
                        "source_asset_type": claim.source_pointer.asset_type if claim.source_pointer else None,
                        "source_asset_id": claim.source_pointer.asset_id if claim.source_pointer else None,
                        "source_passage": claim.source_pointer.passage if claim.source_pointer else None,
                        "discrepancy": claim.discrepancy,
                        "updated_at": now,
                    },
                )

            await session.commit()

        logger.debug(
            "Updated grounding report %s (grounded=%d, partial=%d, ungrounded=%d)",
            report.id,
            report.grounded_count,
            report.partially_grounded_count,
            report.ungrounded_count,
        )

    async def store_resolution(self, resolution: dict) -> str:
        """Persist a resolution record for a blocked claim.

        Args:
            resolution: Dict with keys: grounding_report_id, claim_id,
                resolution_path, resolved_by, resolution_detail,
                re_verification_status, re_verification_duration_ms, resolved_at.

        Returns:
            The UUID string of the inserted resolution row.
        """
        resolution_id = str(uuid.uuid4())

        async with self._session_factory() as session:
            insert_stmt = text("""
                INSERT INTO grounding_resolutions (
                    id, grounding_report_id, claim_id, resolution_path,
                    resolved_by, resolution_detail,
                    re_verification_status, re_verification_duration_ms,
                    resolved_at
                ) VALUES (
                    :id, :grounding_report_id, :claim_id, :resolution_path,
                    :resolved_by, :resolution_detail,
                    :re_verification_status, :re_verification_duration_ms,
                    :resolved_at
                )
            """)
            await session.execute(
                insert_stmt,
                {
                    "id": resolution_id,
                    "grounding_report_id": resolution["grounding_report_id"],
                    "claim_id": resolution["claim_id"],
                    "resolution_path": resolution["resolution_path"],
                    "resolved_by": resolution["resolved_by"],
                    "resolution_detail": json.dumps(resolution.get("resolution_detail", {})),
                    "re_verification_status": resolution.get("re_verification_status"),
                    "re_verification_duration_ms": resolution.get("re_verification_duration_ms"),
                    "resolved_at": resolution.get("resolved_at", datetime.now(timezone.utc)),
                },
            )
            await session.commit()

        logger.debug(
            "Stored resolution %s for claim %s (path=%s)",
            resolution_id,
            resolution["claim_id"],
            resolution["resolution_path"],
        )
        return resolution_id

    async def get_pending_verifications(self, limit: int = 10) -> list[dict]:
        """Fetch materials that haven't been grounding-verified yet.

        Finds pipeline records with material_grounding_status = 'grounding_unverified'
        or materials that have no grounding report at all but have completed review.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of dicts with pipeline_record_id, material_id, and metadata
            for the batch worker to process.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT gr.id, gr.material_id, gr.pipeline_record_id,
                       gr.prepare_technique_id, gr.created_at
                FROM grounding_reports gr
                WHERE gr.material_grounding_status = :status
                ORDER BY gr.created_at ASC
                LIMIT :limit
            """)
            result = await session.execute(
                stmt,
                {
                    "status": MaterialGroundingStatus.GROUNDING_UNVERIFIED.value,
                    "limit": limit,
                },
            )
            rows = result.fetchall()

            return [
                {
                    "report_id": str(row[0]),
                    "material_id": str(row[1]),
                    "pipeline_record_id": str(row[2]),
                    "prepare_technique_id": row[3],
                    "created_at": row[4],
                }
                for row in rows
            ]

    async def get_reports_for_analytics(
        self, technique_id: str, week_start: date, week_end: date
    ) -> list[GroundingReport]:
        """Fetch grounding reports for analytics aggregation.

        Queries reports within the date range for a given prepare technique,
        used to compute ungrounded-claim rate per technique per week.

        Args:
            technique_id: The prepare_technique_id to filter by.
            week_start: Start of the week (inclusive).
            week_end: End of the week (inclusive).

        Returns:
            List of GroundingReport objects (without claims loaded for performance).
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, material_id, pipeline_record_id,
                       prepare_technique_id, grounding_technique_id,
                       total_claims, grounded_count, partially_grounded_count,
                       ungrounded_count, material_grounding_status,
                       extraction_duration_ms, verification_duration_ms,
                       created_at, updated_at
                FROM grounding_reports
                WHERE prepare_technique_id = :technique_id
                  AND created_at >= :week_start
                  AND created_at < :week_end
                ORDER BY created_at ASC
            """)
            result = await session.execute(
                stmt,
                {
                    "technique_id": technique_id,
                    "week_start": datetime.combine(week_start, datetime.min.time(), tzinfo=timezone.utc),
                    "week_end": datetime.combine(week_end, datetime.min.time(), tzinfo=timezone.utc),
                },
            )
            rows = result.fetchall()

            return [
                GroundingReport(
                    id=str(row[0]),
                    material_id=str(row[1]),
                    pipeline_record_id=str(row[2]),
                    claims=[],  # Not loaded for analytics performance
                    total_claims=row[5],
                    grounded_count=row[6],
                    partially_grounded_count=row[7],
                    ungrounded_count=row[8],
                    material_grounding_status=MaterialGroundingStatus(row[9]),
                    extraction_duration_ms=row[10],
                    verification_duration_ms=row[11],
                    created_at=row[12],
                    updated_at=row[13],
                )
                for row in rows
            ]


# ─── Helper functions ─────────────────────────────────────────────────────────


def _row_to_claim(row, material_id: str) -> Claim:
    """Convert a database row tuple to a Claim dataclass instance."""
    source_pointer = None
    if row[8] is not None:  # source_asset_type
        source_pointer = SourcePointer(
            asset_type=row[8],
            asset_id=row[9] or "",
            passage=row[10] or "",
            confidence=1.0,  # stored claims have already been verified
        )

    return Claim(
        id=str(row[0]),
        material_id=material_id,
        category=ClaimCategory(row[1]),
        claim_text=row[2],
        source_span=row[3],
        source_span_start=row[4],
        source_span_end=row[5],
        grounding_status=GroundingStatus(row[6]) if row[6] else None,
        source_pointer=source_pointer,
        is_prospect_side=row[7],
        discrepancy=row[11],
    )
