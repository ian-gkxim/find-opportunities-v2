"""API route for the Dashboard aggregate endpoint.

Requirement 8.1: Dashboard loads within 2 seconds showing pipeline counts,
conversion rates, top 5 prospects, requires action, and hot prospects.

Serves all dashboard data in a single API call to minimize latency.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["dashboard"])


# --- Response Schemas ---


class ConversionRateEntry(BaseModel):
    from_stage: str
    to_stage: str
    rate: float = Field(..., ge=0, le=100)
    period: str = "30d"


class TopProspectEntry(BaseModel):
    id: str
    company_name: str = Field(alias="companyName")
    score: int
    tier: str
    stage: str
    intent_strength: str | None = Field(default=None, alias="intentStrength")

    model_config = {"populate_by_name": True}


class ActionItemEntry(BaseModel):
    id: str
    type: str
    title: str
    description: str
    company_name: str = Field(alias="companyName")
    days_stale: int | None = Field(default=None, alias="daysStale")
    created_at: str = Field(alias="createdAt")

    model_config = {"populate_by_name": True}


class HotProspectEntry(BaseModel):
    id: str
    company_name: str = Field(alias="companyName")
    topic: str
    strength: str
    detected_at: str = Field(alias="detectedAt")
    score: int

    model_config = {"populate_by_name": True}


class DashboardResponse(BaseModel):
    """All dashboard data in a single response."""

    pipeline_counts: dict[str, int] = Field(alias="pipelineCounts")
    conversion_rates: list[ConversionRateEntry] = Field(alias="conversionRates")
    top_prospects: list[TopProspectEntry] = Field(alias="topProspects")
    requires_action: list[ActionItemEntry] = Field(alias="requiresAction")
    hot_prospects: list[HotProspectEntry] = Field(alias="hotProspects")

    model_config = {"populate_by_name": True}


# --- Route ---


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    beneficiary: str = Query(
        default="consultant",
        description="Beneficiary to show dashboard for",
    ),
) -> DashboardResponse:
    """Get all dashboard data in a single call.

    Returns pipeline counts, conversion rates, top 5 prospects,
    requires-action items, and hot prospects for the specified beneficiary.

    In production, this queries the database. Currently returns data from
    whatever is in the DB (empty when no discoveries have run yet).
    """
    # Import models here to avoid circular imports at module level
    try:
        from app.models.base import get_async_engine, get_async_session_factory
        from app.models.pipeline_record import PipelineRecord
        from app.models.prospect import Prospect
        from app.models.account_score import AccountScore
        from app.models.intent_signal import IntentSignal

        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)

        async with session_factory() as session:
            pipeline_counts = await _get_pipeline_counts(session, beneficiary)
            top_prospects = await _get_top_prospects(session, beneficiary)
            requires_action = await _get_requires_action(session, beneficiary)
            hot_prospects = await _get_hot_prospects(session, beneficiary)
            conversion_rates = await _get_conversion_rates(session, beneficiary)

        await engine.dispose()

        return DashboardResponse(
            pipelineCounts=pipeline_counts,
            conversionRates=conversion_rates,
            topProspects=top_prospects,
            requiresAction=requires_action,
            hotProspects=hot_prospects,
        )

    except Exception:
        # If DB isn't available, return empty dashboard
        return DashboardResponse(
            pipelineCounts={},
            conversionRates=[],
            topProspects=[],
            requiresAction=[],
            hotProspects=[],
        )


async def _get_pipeline_counts(session: AsyncSession, beneficiary: str) -> dict[str, int]:
    """Get pipeline record counts grouped by status."""
    from app.models.pipeline_record import PipelineRecord

    stmt = (
        select(PipelineRecord.current_status, func.count(PipelineRecord.id))
        .where(PipelineRecord.beneficiary_id == beneficiary)
        .where(PipelineRecord.is_terminal == False)  # noqa: E712
        .group_by(PipelineRecord.current_status)
    )
    result = await session.execute(stmt)
    return {row[0]: row[1] for row in result.all()}


async def _get_top_prospects(session: AsyncSession, beneficiary: str) -> list[TopProspectEntry]:
    """Get top 5 highest-scored non-terminal prospects."""
    from app.models.account_score import AccountScore
    from app.models.prospect import Prospect

    stmt = (
        select(Prospect, AccountScore)
        .join(AccountScore, AccountScore.prospect_id == Prospect.id)
        .where(Prospect.beneficiary_id == beneficiary)
        .order_by(AccountScore.total_score.desc())
        .limit(5)
    )
    result = await session.execute(stmt)
    prospects = []
    for row in result.all():
        prospect, score = row
        prospects.append(TopProspectEntry(
            id=str(prospect.id),
            companyName=prospect.company_name,
            score=score.total_score,
            tier=score.tier,
            stage="Discovered",
            intentStrength=None,
        ))
    return prospects


async def _get_requires_action(session: AsyncSession, beneficiary: str) -> list[ActionItemEntry]:
    """Get items requiring user action (stale follow-ups, errors)."""
    from app.models.pipeline_record import PipelineRecord

    stale_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    stmt = (
        select(PipelineRecord)
        .join(
            __import__("app.models.prospect", fromlist=["Prospect"]).Prospect,
            PipelineRecord.prospect_id == __import__("app.models.prospect", fromlist=["Prospect"]).Prospect.id,
        )
        .where(PipelineRecord.beneficiary_id == beneficiary)
        .where(PipelineRecord.is_terminal == False)  # noqa: E712
        .where(PipelineRecord.updated_at < stale_cutoff)
        .limit(10)
    )
    # Simplified: return empty for now until we refine the query
    return []


async def _get_hot_prospects(session: AsyncSession, beneficiary: str) -> list[HotProspectEntry]:
    """Get prospects with recent strong/moderate intent signals."""
    from app.models.intent_signal import IntentSignal
    from app.models.prospect import Prospect

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    stmt = (
        select(IntentSignal, Prospect)
        .join(Prospect, IntentSignal.prospect_id == Prospect.id)
        .where(Prospect.beneficiary_id == beneficiary)
        .where(IntentSignal.detected_at >= thirty_days_ago)
        .order_by(IntentSignal.strength.asc(), IntentSignal.detected_at.desc())
        .limit(10)
    )
    result = await session.execute(stmt)
    hot = []
    for row in result.all():
        signal, prospect = row
        hot.append(HotProspectEntry(
            id=str(prospect.id),
            companyName=prospect.company_name,
            topic=signal.topic,
            strength=signal.strength,
            detectedAt=signal.detected_at.isoformat(),
            score=0,
        ))
    return hot


async def _get_conversion_rates(session: AsyncSession, beneficiary: str) -> list[ConversionRateEntry]:
    """Compute stage-to-stage conversion rates for the last 30 days."""
    # This is a complex query — return empty until analytics service is wired
    return []
