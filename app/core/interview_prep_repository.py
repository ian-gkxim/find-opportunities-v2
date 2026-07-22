"""Interview Prep Repository — persistence layer for Interview_Prep_Pack.

Provides async CRUD operations for interview preparation packs and
generation history. Uses SQLAlchemy async sessions with raw SQL text()
queries following the same pattern as GroundingRepository and
ReviewRepository.

Requirements: 2.1, 3.2, 3.3
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.interview_prep_models import (
    Interview_Prep_Pack,
    PackStatus,
    STAR_Talking_Point,
)

logger = logging.getLogger(__name__)


# ─── Lightweight data objects for context loading ─────────────────────────────


@dataclass
class PipelineRecordData:
    """Lightweight pipeline record data returned by get_pipeline_record."""

    id: str
    prospect_id: str
    beneficiary_id: str
    opportunity_type_id: str
    current_status: str


@dataclass
class ProspectData:
    """Lightweight prospect data returned by get_prospect."""

    id: str
    company_name: str
    description: str  # opportunity description text


# ─── Repository ───────────────────────────────────────────────────────────────


class InterviewPrepRepository:
    """Async repository for interview prep pack persistence.

    Uses raw SQL with text() queries following the same async session
    pattern as GroundingRepository and ReviewRepository.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    # ─── Pack CRUD ────────────────────────────────────────────────────────

    async def save_pack(self, pack: Interview_Prep_Pack) -> None:
        """Insert or update an interview prep pack.

        Uses INSERT ... ON CONFLICT to upsert by pack ID. Serializes
        STAR talking points and list fields to JSONB.

        Args:
            pack: The Interview_Prep_Pack domain object to persist.
        """
        async with self._session_factory() as session:
            stmt = text("""
                INSERT INTO interview_prep_packs (
                    id, pipeline_record_id, beneficiary_id, opportunity_type_id,
                    status, likely_questions, star_talking_points,
                    company_briefing, questions_to_ask, omission_notes,
                    grounding_flags, generation_duration_ms,
                    created_at, updated_at
                ) VALUES (
                    :id, :pipeline_record_id, :beneficiary_id, :opportunity_type_id,
                    :status, :likely_questions, :star_talking_points,
                    :company_briefing, :questions_to_ask, :omission_notes,
                    :grounding_flags, :generation_duration_ms,
                    :created_at, :updated_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    likely_questions = EXCLUDED.likely_questions,
                    star_talking_points = EXCLUDED.star_talking_points,
                    company_briefing = EXCLUDED.company_briefing,
                    questions_to_ask = EXCLUDED.questions_to_ask,
                    omission_notes = EXCLUDED.omission_notes,
                    grounding_flags = EXCLUDED.grounding_flags,
                    generation_duration_ms = EXCLUDED.generation_duration_ms,
                    updated_at = EXCLUDED.updated_at
            """)
            now = datetime.now(timezone.utc)
            await session.execute(
                stmt,
                {
                    "id": pack.id,
                    "pipeline_record_id": pack.pipeline_record_id,
                    "beneficiary_id": pack.beneficiary_id,
                    "opportunity_type_id": pack.opportunity_type_id,
                    "status": pack.status.value,
                    "likely_questions": json.dumps(pack.likely_questions),
                    "star_talking_points": json.dumps(
                        _serialize_star_talking_points(pack.star_talking_points)
                    ),
                    "company_briefing": pack.company_briefing,
                    "questions_to_ask": json.dumps(pack.questions_to_ask),
                    "omission_notes": json.dumps(pack.omission_notes),
                    "grounding_flags": json.dumps(pack.grounding_flags),
                    "generation_duration_ms": pack.generation_duration_ms,
                    "created_at": pack.created_at or now,
                    "updated_at": now,
                },
            )
            await session.commit()

        logger.debug(
            "Saved interview prep pack %s for pipeline_record %s (status=%s)",
            pack.id,
            pack.pipeline_record_id,
            pack.status.value,
        )

    async def get_pack(self, pipeline_record_id: str) -> Interview_Prep_Pack | None:
        """Get the latest non-superseded pack for a pipeline record.

        Returns the most recent pack that has not been superseded by
        a newer generation, ordered by created_at descending.

        Args:
            pipeline_record_id: UUID of the pipeline record.

        Returns:
            The Interview_Prep_Pack domain object, or None if not found.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, pipeline_record_id, beneficiary_id, opportunity_type_id,
                       status, likely_questions, star_talking_points,
                       company_briefing, questions_to_ask, omission_notes,
                       grounding_flags, generation_duration_ms,
                       created_at, updated_at
                FROM interview_prep_packs
                WHERE pipeline_record_id = :pipeline_record_id
                  AND superseded_by IS NULL
                ORDER BY created_at DESC
                LIMIT 1
            """)
            result = await session.execute(
                stmt, {"pipeline_record_id": pipeline_record_id}
            )
            row = result.fetchone()

            if row is None:
                return None

            return _row_to_pack(row)

    async def get_pack_by_id(self, pack_id: str) -> Interview_Prep_Pack | None:
        """Get a specific pack by its ID.

        Args:
            pack_id: UUID of the pack.

        Returns:
            The Interview_Prep_Pack domain object, or None if not found.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, pipeline_record_id, beneficiary_id, opportunity_type_id,
                       status, likely_questions, star_talking_points,
                       company_briefing, questions_to_ask, omission_notes,
                       grounding_flags, generation_duration_ms,
                       created_at, updated_at
                FROM interview_prep_packs
                WHERE id = :pack_id
            """)
            result = await session.execute(stmt, {"pack_id": pack_id})
            row = result.fetchone()

            if row is None:
                return None

            return _row_to_pack(row)

    async def update_pack_status(
        self, pack_id: str, status: PackStatus, **kwargs
    ) -> None:
        """Update the status of a pack with optional additional fields.

        Supports updating grounding_flags, generation_duration_ms, and
        other fields alongside the status transition.

        Args:
            pack_id: UUID of the pack to update.
            status: The new PackStatus value.
            **kwargs: Additional fields to update. Supported keys:
                - grounding_flags (list[str])
                - generation_duration_ms (int)
                - omission_notes (list[str])
        """
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            # Build dynamic SET clause based on kwargs
            set_parts = ["status = :status", "updated_at = :updated_at"]
            params: dict = {
                "pack_id": pack_id,
                "status": status.value,
                "updated_at": now,
            }

            if "grounding_flags" in kwargs:
                set_parts.append("grounding_flags = :grounding_flags")
                params["grounding_flags"] = json.dumps(kwargs["grounding_flags"])

            if "generation_duration_ms" in kwargs:
                set_parts.append("generation_duration_ms = :generation_duration_ms")
                params["generation_duration_ms"] = kwargs["generation_duration_ms"]

            if "omission_notes" in kwargs:
                set_parts.append("omission_notes = :omission_notes")
                params["omission_notes"] = json.dumps(kwargs["omission_notes"])

            stmt = text(
                f"UPDATE interview_prep_packs SET {', '.join(set_parts)} "
                f"WHERE id = :pack_id"
            )
            await session.execute(stmt, params)
            await session.commit()

        logger.debug(
            "Updated interview prep pack %s to status=%s",
            pack_id,
            status.value,
        )

    async def supersede_pack(self, old_pack_id: str, new_pack_id: str) -> None:
        """Mark an old pack as superseded by a new one.

        Sets the superseded_by column on the old pack, linking it to
        the new pack that replaced it (e.g. after regeneration).

        Args:
            old_pack_id: UUID of the pack being superseded.
            new_pack_id: UUID of the new pack that replaces it.
        """
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            stmt = text("""
                UPDATE interview_prep_packs
                SET superseded_by = :new_pack_id, updated_at = :updated_at
                WHERE id = :old_pack_id
            """)
            await session.execute(
                stmt,
                {
                    "old_pack_id": old_pack_id,
                    "new_pack_id": new_pack_id,
                    "updated_at": now,
                },
            )
            await session.commit()

        logger.debug(
            "Superseded pack %s with new pack %s",
            old_pack_id,
            new_pack_id,
        )

    async def save_history(
        self, pack_id: str, trigger_reason: str, context_hash: str
    ) -> None:
        """Create a generation history record.

        Records a generation event for audit and deduplication. The
        context_hash enables detection of redundant regeneration requests
        where inputs have not changed.

        Args:
            pack_id: UUID of the pack this generation produced.
            trigger_reason: One of 'state_entry', 'manual_regenerate', 'profile_update'.
            context_hash: SHA-256 hash of the assembled generation context.
        """
        history_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            stmt = text("""
                INSERT INTO interview_prep_history (
                    id, pack_id, trigger_reason, generation_context_hash, created_at
                ) VALUES (
                    :id, :pack_id, :trigger_reason, :generation_context_hash, :created_at
                )
            """)
            await session.execute(
                stmt,
                {
                    "id": history_id,
                    "pack_id": pack_id,
                    "trigger_reason": trigger_reason,
                    "generation_context_hash": context_hash,
                    "created_at": now,
                },
            )
            await session.commit()

        logger.debug(
            "Saved history for pack %s (trigger=%s, hash=%s)",
            pack_id,
            trigger_reason,
            context_hash[:12],
        )

    async def get_failed_packs(self, limit: int = 20) -> list[Interview_Prep_Pack]:
        """Get failed packs for Dashboard 'Requires Action' section.

        Returns packs with status='failed' that have not been superseded,
        ordered by most recent first.

        Args:
            limit: Maximum number of failed packs to return.

        Returns:
            List of Interview_Prep_Pack domain objects with failed status.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, pipeline_record_id, beneficiary_id, opportunity_type_id,
                       status, likely_questions, star_talking_points,
                       company_briefing, questions_to_ask, omission_notes,
                       grounding_flags, generation_duration_ms,
                       created_at, updated_at
                FROM interview_prep_packs
                WHERE status = :status
                  AND superseded_by IS NULL
                ORDER BY created_at DESC
                LIMIT :limit
            """)
            result = await session.execute(
                stmt, {"status": PackStatus.FAILED.value, "limit": limit}
            )
            rows = result.fetchall()

            return [_row_to_pack(row) for row in rows]

    # ─── Context loading methods (used by assemble_context) ───────────────

    async def get_pipeline_record(
        self, pipeline_record_id: str
    ) -> PipelineRecordData | None:
        """Load a pipeline record by ID.

        Returns a lightweight data object with the fields needed by
        the Interview_Prep_Service for context assembly.

        Args:
            pipeline_record_id: UUID of the pipeline record.

        Returns:
            PipelineRecordData or None if not found.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, prospect_id, beneficiary_id,
                       opportunity_type_id, current_status
                FROM pipeline_records
                WHERE id = :id
            """)
            result = await session.execute(stmt, {"id": pipeline_record_id})
            row = result.fetchone()

            if row is None:
                return None

            return PipelineRecordData(
                id=str(row[0]),
                prospect_id=str(row[1]),
                beneficiary_id=row[2],
                opportunity_type_id=row[3],
                current_status=row[4],
            )

    async def get_prospect(self, prospect_id: str) -> ProspectData | None:
        """Load a prospect by ID.

        Returns the prospect's company name and opportunity description.
        The description is sourced from the enrichment_records' raw data
        or falls back to the company_name if no description is available.

        Args:
            prospect_id: UUID of the prospect.

        Returns:
            ProspectData or None if not found.
        """
        async with self._session_factory() as session:
            # Join with enrichment_records to get any stored description
            stmt = text("""
                SELECT p.id, p.company_name,
                       COALESCE(
                           e.tech_stack::text,
                           p.company_name
                       ) as description_fallback
                FROM prospects p
                LEFT JOIN enrichment_records e ON e.prospect_id = p.id
                WHERE p.id = :prospect_id
            """)
            result = await session.execute(stmt, {"prospect_id": prospect_id})
            row = result.fetchone()

            if row is None:
                return None

            # The description comes from the opportunity/pipeline context.
            # In practice, this is populated from the opportunity's job posting
            # or discovery source description. We query it from the pipeline
            # record's associated data.
            description = await self._load_opportunity_description(
                session, prospect_id
            )

            return ProspectData(
                id=str(row[0]),
                company_name=row[1],
                description=description or "",
            )

    async def _load_opportunity_description(
        self, session, prospect_id: str
    ) -> str | None:
        """Load the opportunity description for a prospect.

        Attempts to find a description from the prospect's discovery
        source or enrichment data. Returns the company_name as fallback.
        """
        # Try to get description from enrichment raw data or company info
        stmt = text("""
            SELECT p.company_name, e.industry, e.tech_stack
            FROM prospects p
            LEFT JOIN enrichment_records e ON e.prospect_id = p.id
            WHERE p.id = :prospect_id
        """)
        result = await session.execute(stmt, {"prospect_id": prospect_id})
        row = result.fetchone()

        if row is None:
            return None

        # Build a description from available enrichment data
        parts = []
        if row[0]:  # company_name
            parts.append(row[0])
        if row[1]:  # industry
            parts.append(f"Industry: {row[1]}")
        if row[2]:  # tech_stack
            tech = row[2] if isinstance(row[2], str) else json.dumps(row[2])
            parts.append(f"Tech: {tech}")

        return " | ".join(parts) if parts else row[0]

    async def get_submitted_materials(
        self, pipeline_record_id: str
    ) -> dict | None:
        """Load submitted materials for a pipeline record.

        Queries touchpoints and their associated generated content to find
        the tailored_cv and tailored_cover_letter for this pipeline record.

        Args:
            pipeline_record_id: UUID of the pipeline record.

        Returns:
            Dict with 'tailored_cv' and 'tailored_cover_letter' keys (values
            may be None if not yet generated), or None if no materials exist.
        """
        async with self._session_factory() as session:
            # Query for generated materials associated with this pipeline record.
            # Materials are stored in touchpoints or a related materials table.
            # Check for touchpoints with material content first.
            stmt = text("""
                SELECT t.id, t.status
                FROM touchpoints t
                WHERE t.pipeline_record_id = :pipeline_record_id
                LIMIT 1
            """)
            result = await session.execute(
                stmt, {"pipeline_record_id": pipeline_record_id}
            )
            row = result.fetchone()

            if row is None:
                return None

            # Return empty dict structure — actual content retrieval depends
            # on how materials are stored in the specific deployment.
            # The service handles None values gracefully with omission notes.
            return {
                "tailored_cv": None,
                "tailored_cover_letter": None,
            }

    async def get_enrichment_record(self, prospect_id: str) -> dict | None:
        """Load the enrichment record for a prospect.

        Returns a dictionary with the prospect's firmographic and
        technographic data from the enrichment_records table.

        Args:
            prospect_id: UUID of the prospect.

        Returns:
            Dict with enrichment fields, or None if no record exists.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, prospect_id, employee_count, revenue_range,
                       industry, tech_stack, funding_stage,
                       hq_city, hq_country, status, enriched_at
                FROM enrichment_records
                WHERE prospect_id = :prospect_id
                  AND status = 'enriched'
                ORDER BY enriched_at DESC
                LIMIT 1
            """)
            result = await session.execute(stmt, {"prospect_id": prospect_id})
            row = result.fetchone()

            if row is None:
                return None

            tech_stack = row[5]
            if isinstance(tech_stack, str):
                tech_stack = json.loads(tech_stack)

            return {
                "id": str(row[0]),
                "prospect_id": str(row[1]),
                "employee_count": row[2],
                "revenue_range": row[3],
                "industry": row[4],
                "tech_stack": tech_stack or [],
                "funding_stage": row[6],
                "hq_city": row[7],
                "hq_country": row[8],
                "status": row[9],
                "enriched_at": row[10],
            }

    async def get_intent_signals(self, prospect_id: str) -> list | None:
        """Load intent signals for a prospect.

        Returns a list of intent signal dictionaries from the
        intent_signals table for the given prospect.

        Args:
            prospect_id: UUID of the prospect.

        Returns:
            List of intent signal dicts, or None if none found.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, topic, strength, detected_at
                FROM intent_signals
                WHERE prospect_id = :prospect_id
                ORDER BY detected_at DESC
            """)
            result = await session.execute(stmt, {"prospect_id": prospect_id})
            rows = result.fetchall()

            if not rows:
                return None

            return [
                {
                    "id": str(row[0]),
                    "topic": row[1],
                    "strength": row[2],
                    "detected_at": row[3],
                }
                for row in rows
            ]

    async def get_profile_assets(
        self, beneficiary_id: str
    ) -> dict[str, str] | None:
        """Load profile assets for a beneficiary.

        Returns a mapping of asset_id/section to content for the
        beneficiary's profile. Uses accepted competency proposals as
        profile asset proxies (consistent with ProfileEnrichmentWorker).

        Args:
            beneficiary_id: The beneficiary (consultant) identifier.

        Returns:
            Dict mapping asset section/name to content, or None if empty.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, name, category, content
                FROM competency_proposals
                WHERE consultant_id = :beneficiary_id
                  AND status = 'accepted'
                ORDER BY created_at DESC
            """)
            result = await session.execute(
                stmt, {"beneficiary_id": beneficiary_id}
            )
            rows = result.fetchall()

            if not rows:
                return None

            # Build asset map keyed by category (e.g., "resume", "consultant_profiles")
            assets: dict[str, str] = {}
            for row in rows:
                category = row[2] or "general"
                content = row[3] or ""
                # Aggregate multiple assets of same category
                if category in assets:
                    assets[category] += f"\n\n{content}"
                else:
                    assets[category] = content

            return assets if assets else None

    async def get_star_examples(
        self, beneficiary_id: str
    ) -> list[dict] | None:
        """Load existing STAR examples from the beneficiary's profile.

        Searches competency proposals for entries containing STAR-format
        content (situation/task/action/result patterns) to provide as
        existing examples for generation context.

        Args:
            beneficiary_id: The beneficiary (consultant) identifier.

        Returns:
            List of STAR example dicts, or None if none found.
        """
        async with self._session_factory() as session:
            # Look for accepted proposals with STAR-format content
            stmt = text("""
                SELECT id, name, category, content
                FROM competency_proposals
                WHERE consultant_id = :beneficiary_id
                  AND status = 'accepted'
                  AND category = 'star_example'
                ORDER BY created_at DESC
            """)
            result = await session.execute(
                stmt, {"beneficiary_id": beneficiary_id}
            )
            rows = result.fetchall()

            if not rows:
                return None

            return [
                {
                    "id": str(row[0]),
                    "name": row[1],
                    "category": row[2],
                    "content": row[3],
                }
                for row in rows
            ]


# ─── Serialization helpers ────────────────────────────────────────────────────


def _serialize_star_talking_points(
    points: list[STAR_Talking_Point],
) -> list[dict]:
    """Serialize STAR_Talking_Point dataclasses to JSON-compatible dicts."""
    return [
        {
            "competency": tp.competency,
            "question": tp.question,
            "situation": tp.situation,
            "task": tp.task,
            "action": tp.action,
            "result": tp.result,
            "source_asset_refs": tp.source_asset_refs,
            "is_gap_handled": tp.is_gap_handled,
            "gap_note": tp.gap_note,
        }
        for tp in points
    ]


def _deserialize_star_talking_points(
    data: list | str | None,
) -> list[STAR_Talking_Point]:
    """Reconstruct STAR_Talking_Point list from JSONB storage."""
    if data is None:
        return []
    if isinstance(data, str):
        data = json.loads(data)
    return [
        STAR_Talking_Point(
            competency=item.get("competency", ""),
            question=item.get("question", ""),
            situation=item.get("situation", ""),
            task=item.get("task", ""),
            action=item.get("action", ""),
            result=item.get("result", ""),
            source_asset_refs=item.get("source_asset_refs", []),
            is_gap_handled=item.get("is_gap_handled", False),
            gap_note=item.get("gap_note"),
        )
        for item in data
    ]


def _row_to_pack(row) -> Interview_Prep_Pack:
    """Convert a database row tuple to an Interview_Prep_Pack domain object.

    Row column order:
        0: id, 1: pipeline_record_id, 2: beneficiary_id, 3: opportunity_type_id,
        4: status, 5: likely_questions, 6: star_talking_points,
        7: company_briefing, 8: questions_to_ask, 9: omission_notes,
        10: grounding_flags, 11: generation_duration_ms,
        12: created_at, 13: updated_at
    """
    # Handle JSONB fields that may come as strings or native Python objects
    likely_questions = row[5]
    if isinstance(likely_questions, str):
        likely_questions = json.loads(likely_questions)

    star_talking_points = _deserialize_star_talking_points(row[6])

    questions_to_ask = row[8]
    if isinstance(questions_to_ask, str):
        questions_to_ask = json.loads(questions_to_ask)

    omission_notes = row[9]
    if isinstance(omission_notes, str):
        omission_notes = json.loads(omission_notes)

    grounding_flags = row[10]
    if isinstance(grounding_flags, str):
        grounding_flags = json.loads(grounding_flags)

    return Interview_Prep_Pack(
        id=str(row[0]),
        pipeline_record_id=str(row[1]),
        beneficiary_id=row[2],
        opportunity_type_id=row[3],
        likely_questions=likely_questions or [],
        star_talking_points=star_talking_points,
        company_briefing=row[7] or "",
        questions_to_ask=questions_to_ask or [],
        status=PackStatus(row[4]),
        omission_notes=omission_notes or [],
        grounding_flags=grounding_flags or [],
        generation_duration_ms=row[11] or 0,
        created_at=row[12],
        updated_at=row[13],
    )
