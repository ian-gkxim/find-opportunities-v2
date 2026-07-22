"""Repository for validation report persistence.

Handles insert and retrieval of validation reports produced by the
Outbound_Validator service, using raw SQL via SQLAlchemy text() queries.

Requirements: 1.4
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.outbound_validator import (
    RuleResult,
    RuleSeverity,
    TextSpan,
    ValidationReport,
)

# ValidationReportModel (app.models.validation_report) defines the ORM schema
# but this repository uses raw SQL text() queries for consistency with the rest
# of the persistence layer.

logger = logging.getLogger(__name__)


class ValidationRepository:
    """Persistence layer for validation reports.

    Uses raw SQL with text() queries following the same async session
    pattern as ReviewRepository and GroundingRepository.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def save_validation_report(self, report: ValidationReport) -> str:
        """Persist a ValidationReport to PostgreSQL.

        Serializes the list of RuleResult objects to JSONB and inserts
        a single row into the validation_reports table.

        Args:
            report: Complete validation report from an Outbound_Validator run.

        Returns:
            The UUID string of the inserted validation report row.
        """
        results_json = _serialize_results(report.results)

        async with self._session_factory() as session:
            insert_stmt = text("""
                INSERT INTO validation_reports (
                    id, pipeline_record_id, outreach_technique,
                    passed, has_warnings, total_execution_ms,
                    results, created_at
                ) VALUES (
                    :id, :pipeline_record_id, :outreach_technique,
                    :passed, :has_warnings, :total_execution_ms,
                    :results, :created_at
                )
            """)
            await session.execute(
                insert_stmt,
                {
                    "id": report.id,
                    "pipeline_record_id": report.pipeline_record_id,
                    "outreach_technique": report.outreach_technique,
                    "passed": report.passed,
                    "has_warnings": report.has_warnings,
                    "total_execution_ms": report.total_execution_ms,
                    "results": json.dumps(results_json),
                    "created_at": report.created_at,
                },
            )
            await session.commit()

        logger.debug(
            "Saved validation report %s for pipeline_record %s (passed=%s)",
            report.id,
            report.pipeline_record_id,
            report.passed,
        )
        return report.id

    async def get_report_by_id(self, report_id: str) -> ValidationReport | None:
        """Retrieve a validation report by its UUID.

        Args:
            report_id: UUID of the validation report to look up.

        Returns:
            The ValidationReport if found, or None if not found.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, pipeline_record_id, outreach_technique,
                       passed, has_warnings, total_execution_ms,
                       results, created_at
                FROM validation_reports
                WHERE id = :report_id
            """)
            result = await session.execute(stmt, {"report_id": report_id})
            row = result.fetchone()

            if row is None:
                return None

            return _row_to_report(row)

    async def get_reports_for_pipeline_record(
        self, pipeline_record_id: str
    ) -> list[ValidationReport]:
        """Retrieve all validation reports for a given pipeline record.

        Returns reports ordered by creation time (most recent first).

        Args:
            pipeline_record_id: UUID of the pipeline record to query.

        Returns:
            List of ValidationReport objects for the pipeline record.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, pipeline_record_id, outreach_technique,
                       passed, has_warnings, total_execution_ms,
                       results, created_at
                FROM validation_reports
                WHERE pipeline_record_id = :pipeline_record_id
                ORDER BY created_at DESC
            """)
            result = await session.execute(
                stmt, {"pipeline_record_id": pipeline_record_id}
            )
            rows = result.fetchall()

            return [_row_to_report(row) for row in rows]


# ─── Serialization helpers ────────────────────────────────────────────────────


def _serialize_results(results: list[RuleResult]) -> list[dict]:
    """Serialize a list of RuleResult objects to JSON-compatible dicts.

    Each dict includes: rule_id, passed, severity (as string), message,
    offending_spans (list of span dicts), execution_ms.
    """
    return [
        {
            "rule_id": r.rule_id,
            "passed": r.passed,
            "severity": r.severity.value,
            "message": r.message,
            "offending_spans": [
                {
                    "start": span.start,
                    "end": span.end,
                    "field_name": span.field_name,
                    "text": span.text,
                }
                for span in r.offending_spans
            ],
            "execution_ms": r.execution_ms,
        }
        for r in results
    ]


def _deserialize_results(data: list | str | None) -> list[RuleResult]:
    """Reconstruct RuleResult list from JSON storage.

    Handles both raw list (already parsed by JSONB) and string forms.
    """
    if data is None:
        return []
    if isinstance(data, str):
        data = json.loads(data)
    return [
        RuleResult(
            rule_id=item["rule_id"],
            passed=item["passed"],
            severity=RuleSeverity(item["severity"]),
            message=item.get("message", ""),
            offending_spans=[
                TextSpan(
                    start=span["start"],
                    end=span["end"],
                    field_name=span["field_name"],
                    text=span["text"],
                )
                for span in item.get("offending_spans", [])
            ],
            execution_ms=item.get("execution_ms", 0.0),
        )
        for item in data
    ]


def _row_to_report(row) -> ValidationReport:
    """Convert a database row tuple to a ValidationReport dataclass."""
    return ValidationReport(
        id=str(row[0]),
        pipeline_record_id=str(row[1]),
        outreach_technique=row[2],
        results=_deserialize_results(row[6]),
        passed=row[3],
        has_warnings=row[4],
        total_execution_ms=row[5],
        created_at=row[7] if row[7] else datetime.now(timezone.utc),
    )
