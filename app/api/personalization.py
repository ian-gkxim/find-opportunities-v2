"""API routes for personalization and outreach material generation.

Requirements 11.1, 13.4:
- POST /personalize/generate — generate personalized outreach material
"""

from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["personalization"])


# --- Request/Response Schemas ---


class GeneratePersonalizedRequest(BaseModel):
    """Request to generate personalized outreach material."""

    prospect_id: UUID = Field(..., description="Prospect to generate material for")
    beneficiary_id: str = Field(..., description="Beneficiary context for generation")
    material_type: str = Field(
        ...,
        description="Type of material: cv, cover_letter, proposal, email",
    )
    contact_id: UUID | None = Field(
        default=None,
        description="Optional target contact for tone adaptation",
    )


class PersonalizedMaterialResponse(BaseModel):
    """Response with generated personalized material."""

    prospect_id: UUID
    material_type: str
    content: str
    quality_score: int = Field(..., ge=0, le=100, description="Personalization quality score")
    fields_used: list[str] = Field(
        default_factory=list, description="Enrichment fields referenced in content"
    )
    fields_available_unused: list[str] = Field(
        default_factory=list, description="Available fields not incorporated"
    )
    tone_applied: str = Field(
        ..., description="Seniority-based tone: c_suite, director, manager, other"
    )
    hooks_referenced: list[str] = Field(
        default_factory=list, description="Hooks referenced in the content"
    )
    is_low_quality: bool = Field(
        default=False, description="True if quality_score < 40"
    )
    flags: list[str] = Field(
        default_factory=list,
        description="Flags: low_personalization, seniority_unknown",
    )


# --- Routes ---


@router.post("/personalize/generate", response_model=PersonalizedMaterialResponse)
async def generate_personalized_material(
    request: GeneratePersonalizedRequest,
) -> PersonalizedMaterialResponse:
    """Generate personalized outreach material for a prospect.

    Uses Apollo enrichment data combined with LLM generation to produce
    tailored materials. Tone is adapted based on target contact seniority:
    - C-suite: company-vision and ROI-focused
    - Director: implementation-focused and team-impact
    - Manager/Other: hands-on and collaboration-focused

    If seniority is unknown, defaults to director-level tone and flags
    the material with 'seniority_unknown'.
    """
    # Stub: In production, delegates to PersonalizationEngine.generate_materials()
    return PersonalizedMaterialResponse(
        prospect_id=request.prospect_id,
        material_type=request.material_type,
        content="[Placeholder: Generated personalized content]",
        quality_score=0,
        tone_applied="director",
        is_low_quality=True,
        flags=["low_personalization"],
    )
