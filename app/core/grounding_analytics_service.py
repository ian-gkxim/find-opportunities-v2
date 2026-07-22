"""Grounding Analytics Service — computes and stores ungrounded-claim rates.

Tracks the ungrounded-claim rate per prepare technique per ISO week,
stores results in the grounding_analytics_weekly table, and provides
trailing trend data for the Dashboard Reports stage.

Requirements: 4.2
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


@dataclass
class UngroundedClaimRate:
    """Weekly ungrounded-claim rate per prepare technique.

    Attributes:
        prepare_technique_id: The prepare technique this rate applies to.
        week_start: ISO week start (Monday).
        week_end: ISO week end (Sunday).
        total_claims_extracted: Total claims across all reports in this week.
        ungrounded_claims: Count of ungrounded claims in this week.
        partially_grounded_claims: Count of partially grounded claims.
        ungrounded_rate: ungrounded_claims / total_claims_extracted (0 if total is 0).
        partially_grounded_rate: partially_grounded_claims / total_claims_extracted.
    """

    prepare_technique_id: str
    week_start: date
    week_end: date
    total_claims_extracted: int
    ungrounded_claims: int
    partially_grounded_claims: int
    ungrounded_rate: float
    partially_grounded_rate: float


class GroundingAnalyticsService:
    """Computes and persists weekly ungrounded-claim rates per prepare technique.

    Queries grounding_reports grouped by prepare_technique_id and ISO week,
    computes the ungrounded_rate, and upserts results into
    grounding_analytics_weekly for efficient read access.

    Requirements: 4.2
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def compute_ungrounded_claim_rates(
        self,
        period_weeks: int = 4,
    ) -> list[UngroundedClaimRate]:
        """Compute ungrounded-claim rate per prepare technique per week.

        Groups grounding reports by prepare_technique_id and ISO week,
        then computes ungrounded/total ratio for each group. Results are
        upserted into grounding_analytics_weekly.

        Args:
            period_weeks: Number of trailing weeks to compute (default 4).

        Returns:
            List of UngroundedClaimRate objects for the computed period.
        """
        today = date.today()
        # Compute the start of the trailing period (N weeks ago, aligned to Monday)
        # ISO weekday: Monday=1, Sunday=7
        days_since_monday = today.weekday()  # Monday=0 in Python
        current_week_start = today - timedelta(days=days_since_monday)
        period_start = current_week_start - timedelta(weeks=period_weeks - 1)

        async with self._session_factory() as session:
            # Query grounding_reports grouped by technique and ISO week
            stmt = text("""
                SELECT
                    prepare_technique_id,
                    DATE_TRUNC('week', created_at)::date AS week_start,
                    SUM(total_claims) AS total_claims_extracted,
                    SUM(grounded_count) AS grounded_claims,
                    SUM(partially_grounded_count) AS partially_grounded_claims,
                    SUM(ungrounded_count) AS ungrounded_claims,
                    COUNT(*) FILTER (WHERE material_grounding_status = 'grounding_verified') AS materials_verified,
                    COUNT(*) FILTER (WHERE material_grounding_status = 'grounding_blocked') AS materials_blocked
                FROM grounding_reports
                WHERE created_at >= :period_start
                GROUP BY prepare_technique_id, DATE_TRUNC('week', created_at)::date
                ORDER BY prepare_technique_id, week_start
            """)
            result = await session.execute(
                stmt,
                {
                    "period_start": datetime.combine(
                        period_start, datetime.min.time(), tzinfo=timezone.utc
                    ),
                },
            )
            rows = result.fetchall()

        rates: list[UngroundedClaimRate] = []
        for row in rows:
            technique_id = row[0]
            week_start = row[1]
            week_end = week_start + timedelta(days=6)
            total_claims = row[2] or 0
            grounded = row[3] or 0
            partially_grounded = row[4] or 0
            ungrounded = row[5] or 0
            materials_verified = row[6] or 0
            materials_blocked = row[7] or 0

            ungrounded_rate = (
                ungrounded / total_claims if total_claims > 0 else 0.0
            )
            partially_grounded_rate = (
                partially_grounded / total_claims if total_claims > 0 else 0.0
            )

            rate = UngroundedClaimRate(
                prepare_technique_id=technique_id,
                week_start=week_start,
                week_end=week_end,
                total_claims_extracted=total_claims,
                ungrounded_claims=ungrounded,
                partially_grounded_claims=partially_grounded,
                ungrounded_rate=round(ungrounded_rate, 4),
                partially_grounded_rate=round(partially_grounded_rate, 4),
            )
            rates.append(rate)

            # Upsert into grounding_analytics_weekly
            await self._upsert_weekly_rate(
                technique_id=technique_id,
                week_start=week_start,
                week_end=week_end,
                total_claims=total_claims,
                grounded=grounded,
                partially_grounded=partially_grounded,
                ungrounded=ungrounded,
                ungrounded_rate=ungrounded_rate,
                materials_verified=materials_verified,
                materials_blocked=materials_blocked,
            )

        return rates

    async def get_grounding_trend(
        self,
        prepare_technique_id: str,
        weeks: int = 12,
    ) -> list[UngroundedClaimRate]:
        """Get weekly ungrounded rate trend for a specific technique.

        Returns one entry per week for the trailing N weeks,
        zero-filling weeks with no data.

        Args:
            prepare_technique_id: The technique to get trend for.
            weeks: Number of trailing weeks to include (default 12).

        Returns:
            List of UngroundedClaimRate, one per week, ordered chronologically.
            Weeks with no data are zero-filled.
        """
        today = date.today()
        days_since_monday = today.weekday()
        current_week_start = today - timedelta(days=days_since_monday)
        period_start = current_week_start - timedelta(weeks=weeks - 1)

        async with self._session_factory() as session:
            stmt = text("""
                SELECT
                    week_start, week_end,
                    total_claims_extracted,
                    grounded_claims,
                    partially_grounded_claims,
                    ungrounded_claims,
                    ungrounded_rate
                FROM grounding_analytics_weekly
                WHERE prepare_technique_id = :technique_id
                  AND week_start >= :period_start
                ORDER BY week_start ASC
            """)
            result = await session.execute(
                stmt,
                {
                    "technique_id": prepare_technique_id,
                    "period_start": period_start,
                },
            )
            rows = result.fetchall()

        # Build lookup from existing data
        existing: dict[date, tuple] = {}
        for row in rows:
            existing[row[0]] = row

        # Generate all weeks and zero-fill missing ones
        trend: list[UngroundedClaimRate] = []
        for i in range(weeks):
            week_start = period_start + timedelta(weeks=i)
            week_end = week_start + timedelta(days=6)

            if week_start in existing:
                row = existing[week_start]
                total_claims = row[2] or 0
                partially_grounded = row[4] or 0
                ungrounded = row[5] or 0
                rate_value = float(row[6]) if row[6] else 0.0
                partially_grounded_rate = (
                    partially_grounded / total_claims if total_claims > 0 else 0.0
                )

                trend.append(UngroundedClaimRate(
                    prepare_technique_id=prepare_technique_id,
                    week_start=week_start,
                    week_end=week_end,
                    total_claims_extracted=total_claims,
                    ungrounded_claims=ungrounded,
                    partially_grounded_claims=partially_grounded,
                    ungrounded_rate=round(rate_value, 4),
                    partially_grounded_rate=round(partially_grounded_rate, 4),
                ))
            else:
                # Zero-fill for weeks with no data
                trend.append(UngroundedClaimRate(
                    prepare_technique_id=prepare_technique_id,
                    week_start=week_start,
                    week_end=week_end,
                    total_claims_extracted=0,
                    ungrounded_claims=0,
                    partially_grounded_claims=0,
                    ungrounded_rate=0.0,
                    partially_grounded_rate=0.0,
                ))

        return trend

    async def _upsert_weekly_rate(
        self,
        technique_id: str,
        week_start: date,
        week_end: date,
        total_claims: int,
        grounded: int,
        partially_grounded: int,
        ungrounded: int,
        ungrounded_rate: float,
        materials_verified: int,
        materials_blocked: int,
    ) -> None:
        """Upsert a weekly analytics row using the unique constraint.

        Uses INSERT ... ON CONFLICT (prepare_technique_id, week_start)
        DO UPDATE to either insert a new row or update existing data.
        """
        async with self._session_factory() as session:
            stmt = text("""
                INSERT INTO grounding_analytics_weekly (
                    id, prepare_technique_id, week_start, week_end,
                    total_claims_extracted, grounded_claims,
                    partially_grounded_claims, ungrounded_claims,
                    ungrounded_rate, materials_verified, materials_blocked,
                    created_at
                ) VALUES (
                    :id, :technique_id, :week_start, :week_end,
                    :total_claims, :grounded_claims,
                    :partially_grounded_claims, :ungrounded_claims,
                    :ungrounded_rate, :materials_verified, :materials_blocked,
                    :created_at
                )
                ON CONFLICT (prepare_technique_id, week_start)
                DO UPDATE SET
                    total_claims_extracted = EXCLUDED.total_claims_extracted,
                    grounded_claims = EXCLUDED.grounded_claims,
                    partially_grounded_claims = EXCLUDED.partially_grounded_claims,
                    ungrounded_claims = EXCLUDED.ungrounded_claims,
                    ungrounded_rate = EXCLUDED.ungrounded_rate,
                    materials_verified = EXCLUDED.materials_verified,
                    materials_blocked = EXCLUDED.materials_blocked
            """)
            await session.execute(
                stmt,
                {
                    "id": str(uuid.uuid4()),
                    "technique_id": technique_id,
                    "week_start": week_start,
                    "week_end": week_end,
                    "total_claims": total_claims,
                    "grounded_claims": grounded,
                    "partially_grounded_claims": partially_grounded,
                    "ungrounded_claims": ungrounded,
                    "ungrounded_rate": round(ungrounded_rate, 4),
                    "materials_verified": materials_verified,
                    "materials_blocked": materials_blocked,
                    "created_at": datetime.now(timezone.utc),
                },
            )
            await session.commit()

        logger.debug(
            "Upserted grounding analytics for technique=%s week=%s "
            "(total=%d, ungrounded=%d, rate=%.4f)",
            technique_id,
            week_start,
            total_claims,
            ungrounded,
            ungrounded_rate,
        )
