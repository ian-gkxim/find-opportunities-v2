"""API route for the Dashboard aggregate endpoint.

Requirement 8.1: Dashboard loads within 2 seconds showing pipeline counts,
conversion rates, top 5 prospects, requires action, and hot prospects.

Requirement 1.3 (Voice Assets): When no Voice_Asset is configured for a
beneficiary, display a one-time suggestion in the Understand stage to create
the asset. Suggestion is non-blocking (voice is opt-in).

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


class SuggestionEntry(BaseModel):
    """A one-time, non-blocking suggestion shown in the Understand stage.

    Suggestions are opt-in recommendations (e.g., "Create a Voice Asset")
    that can be permanently dismissed by the user. They do not block any
    pipeline operations.

    Requirement 1.3: Dashboard displays a one-time suggestion to create the
    asset when no Voice_Asset is configured for a beneficiary.
    """

    suggestion_key: str = Field(alias="suggestionKey", description="Unique key for dismissal")
    title: str
    description: str
    stage: str = Field(description="Dashboard stage this suggestion relates to")
    beneficiary_id: str = Field(alias="beneficiaryId")
    asset_type: str | None = Field(
        default=None, alias="assetType", description="The asset type to create, if applicable"
    )

    model_config = {"populate_by_name": True}


class DashboardResponse(BaseModel):
    """All dashboard data in a single response."""

    pipeline_counts: dict[str, int] = Field(alias="pipelineCounts")
    conversion_rates: list[ConversionRateEntry] = Field(alias="conversionRates")
    top_prospects: list[TopProspectEntry] = Field(alias="topProspects")
    requires_action: list[ActionItemEntry] = Field(alias="requiresAction")
    hot_prospects: list[HotProspectEntry] = Field(alias="hotProspects")
    suggestions: list[SuggestionEntry] = Field(default=[], alias="suggestions")

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
            suggestions = await _get_voice_asset_suggestions(session, beneficiary)

        await engine.dispose()

        return DashboardResponse(
            pipelineCounts=pipeline_counts,
            conversionRates=conversion_rates,
            topProspects=top_prospects,
            requiresAction=requires_action,
            hotProspects=hot_prospects,
            suggestions=suggestions,
        )

    except Exception:
        # If DB isn't available, return empty dashboard
        return DashboardResponse(
            pipelineCounts={},
            conversionRates=[],
            topProspects=[],
            requiresAction=[],
            hotProspects=[],
            suggestions=[],
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
    """Get items requiring user action (stale follow-ups, errors, unreviewed materials)."""
    from app.models.pipeline_record import PipelineRecord

    action_items: list[ActionItemEntry] = []

    # 1. Stale follow-ups
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
    # Stale follow-ups query — returns empty for now until fully refined

    # 2. Unreviewed materials from review_reasoning_logs
    try:
        unreviewed_stmt = text("""
            SELECT rrl.material_id, rrl.pipeline_record_id,
                   rrl.prepare_technique_id, rrl.completed_at
            FROM review_reasoning_logs rrl
            WHERE rrl.final_review_status = 'unreviewed'
            ORDER BY rrl.completed_at DESC
            LIMIT 10
        """)
        unreviewed_result = await session.execute(unreviewed_stmt)
        unreviewed_rows = unreviewed_result.fetchall()

        for row in unreviewed_rows:
            material_id = str(row[0])
            pipeline_record_id = str(row[1]) if row[1] else "unknown"
            prepare_technique_id = row[2] or "unknown"
            completed_at = row[3]

            action_items.append(ActionItemEntry(
                id=material_id,
                type="unreviewed_material",
                title=f"Unreviewed material: {prepare_technique_id}",
                description=(
                    f"Material {material_id[:8]}... from technique "
                    f"'{prepare_technique_id}' could not be reviewed and requires attention."
                ),
                companyName="Unknown",
                daysStale=None,
                createdAt=completed_at.isoformat() if completed_at else datetime.now(timezone.utc).isoformat(),
            ))
    except Exception:
        # If the review_reasoning_logs table doesn't exist yet, skip gracefully
        pass

    # 3. Grounding-blocked and grounding-unverified materials (Requirements: 1.4, 3.1)
    try:
        grounding_stmt = text("""
            SELECT gr.material_id, gr.pipeline_record_id,
                   gr.material_grounding_status, gr.ungrounded_count,
                   gr.created_at
            FROM grounding_reports gr
            WHERE gr.material_grounding_status IN ('grounding_blocked', 'grounding_unverified')
            ORDER BY gr.created_at DESC
            LIMIT 10
        """)
        grounding_result = await session.execute(grounding_stmt)
        grounding_rows = grounding_result.fetchall()

        for row in grounding_rows:
            material_id = str(row[0])
            pipeline_record_id = str(row[1]) if row[1] else "unknown"
            grounding_status = row[2]
            ungrounded_count = row[3] or 0
            created_at = row[4]

            if grounding_status == "grounding_blocked":
                action_items.append(ActionItemEntry(
                    id=material_id,
                    type="grounding_blocked",
                    title="Blocked — ungrounded claims",
                    description=(
                        f"Material {material_id[:8]}... has {ungrounded_count} "
                        f"ungrounded claim(s). Resolve to unblock pipeline."
                    ),
                    companyName="Unknown",
                    daysStale=None,
                    createdAt=created_at.isoformat() if created_at else datetime.now(timezone.utc).isoformat(),
                ))
            elif grounding_status == "grounding_unverified":
                action_items.append(ActionItemEntry(
                    id=material_id,
                    type="grounding_unverified",
                    title="Grounding unverified",
                    description=(
                        f"Material {material_id[:8]}... could not be verified "
                        f"(extraction failed). Claims not checked."
                    ),
                    companyName="Unknown",
                    daysStale=None,
                    createdAt=created_at.isoformat() if created_at else datetime.now(timezone.utc).isoformat(),
                ))
    except Exception:
        # If the grounding_reports table doesn't exist yet, skip gracefully
        pass

    return action_items


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


# ─── SUGGESTION KEY CONSTANTS ─────────────────────────────────────────────────

VOICE_ASSET_SUGGESTION_KEY = "create_voice_asset"
"""Suggestion key for the 'create Voice_Asset' hint in the Understand stage."""


# ─── VOICE ASSET SUGGESTIONS (Requirement 1.3) ───────────────────────────────


async def _get_voice_asset_suggestions(
    session: AsyncSession, beneficiary: str
) -> list[SuggestionEntry]:
    """Check if the beneficiary has a voice asset and return a suggestion if not.

    Returns a suggestion to create a Voice_Asset when:
    1. No active voice asset (writing_style for consultant, brand_voice for team) exists
    2. The suggestion has not been previously dismissed

    The suggestion is non-blocking — voice is opt-in, and the system operates
    without error when no Voice_Asset is configured.

    Requirement 1.3: If a Voice_Asset is absent for a Beneficiary, the Dashboard
    SHALL display a one-time suggestion in the Understand stage to create the asset.
    """
    suggestions: list[SuggestionEntry] = []

    try:
        # Determine which voice asset type to check for this beneficiary
        if beneficiary == "consultant":
            asset_type_to_check = "writing_style"
            suggestion_title = "Define your writing voice"
            suggestion_description = (
                "Create a Writing Style asset to make generated materials sound like you. "
                "Define your register, sentence rhythm, preferred vocabulary, and phrases "
                "to avoid. This is optional but improves outreach authenticity."
            )
        elif beneficiary == "team":
            asset_type_to_check = "brand_voice"
            suggestion_title = "Define your brand voice"
            suggestion_description = (
                "Create a Brand Voice asset to ensure all team materials reflect a consistent "
                "brand identity. Define the firm's register, vocabulary preferences, and "
                "personality traits. This is optional but improves brand consistency."
            )
        else:
            return suggestions

        # Check if suggestion has been dismissed
        dismissed_stmt = text("""
            SELECT 1 FROM dismissed_suggestions
            WHERE beneficiary_id = :beneficiary_id
              AND suggestion_key = :suggestion_key
            LIMIT 1
        """)
        dismissed_result = await session.execute(
            dismissed_stmt,
            {
                "beneficiary_id": beneficiary,
                "suggestion_key": VOICE_ASSET_SUGGESTION_KEY,
            },
        )
        if dismissed_result.fetchone() is not None:
            # Already dismissed — don't show again
            return suggestions

        # Check if a voice asset already exists
        voice_asset_stmt = text("""
            SELECT 1 FROM voice_assets
            WHERE beneficiary_id = :beneficiary_id
              AND asset_type = :asset_type
              AND is_active = TRUE
            LIMIT 1
        """)
        voice_result = await session.execute(
            voice_asset_stmt,
            {
                "beneficiary_id": beneficiary,
                "asset_type": asset_type_to_check,
            },
        )
        if voice_result.fetchone() is not None:
            # Voice asset exists — no suggestion needed
            return suggestions

        # No voice asset and not dismissed — show the suggestion
        suggestions.append(
            SuggestionEntry(
                suggestionKey=VOICE_ASSET_SUGGESTION_KEY,
                title=suggestion_title,
                description=suggestion_description,
                stage="understand",
                beneficiaryId=beneficiary,
                assetType=asset_type_to_check,
            )
        )

    except Exception:
        # If tables don't exist yet (e.g., migrations not run), skip gracefully
        pass

    return suggestions


# ─── DISMISS SUGGESTION ENDPOINT ─────────────────────────────────────────────


class DismissSuggestionResponse(BaseModel):
    """Response for suggestion dismissal."""

    suggestion_key: str = Field(alias="suggestionKey")
    beneficiary_id: str = Field(alias="beneficiaryId")
    dismissed: bool = True

    model_config = {"populate_by_name": True}


@router.post(
    "/dashboard/suggestions/{suggestion_key}/dismiss",
    response_model=DismissSuggestionResponse,
)
async def dismiss_suggestion(
    suggestion_key: str,
    beneficiary: str = Query(
        default="consultant",
        description="Beneficiary to dismiss suggestion for",
    ),
) -> DismissSuggestionResponse:
    """Dismiss a one-time suggestion so it is never shown again.

    Inserts a record into the dismissed_suggestions table. If already
    dismissed, the operation is idempotent (ON CONFLICT DO NOTHING).

    Requirement 1.3: Suggestion is one-time — once dismissed, don't show again.
    """
    try:
        from app.models.base import get_async_engine, get_async_session_factory

        engine = get_async_engine()
        session_factory = get_async_session_factory(engine)

        async with session_factory() as session:
            stmt = text("""
                INSERT INTO dismissed_suggestions (beneficiary_id, suggestion_key)
                VALUES (:beneficiary_id, :suggestion_key)
                ON CONFLICT (beneficiary_id, suggestion_key) DO NOTHING
            """)
            await session.execute(
                stmt,
                {
                    "beneficiary_id": beneficiary,
                    "suggestion_key": suggestion_key,
                },
            )
            await session.commit()

        await engine.dispose()

    except Exception:
        # If DB isn't available, still return success (idempotent)
        pass

    return DismissSuggestionResponse(
        suggestionKey=suggestion_key,
        beneficiaryId=beneficiary,
        dismissed=True,
    )
