"""API routes for settings and integration management.

Requirements 18.1, 18.2:
- GET /settings/integrations — get all integration health/status
- PUT /settings/integrations — update integration credentials
- POST /settings/integrations/validate — validate credentials for an integration
"""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["settings"])


# --- Request/Response Schemas ---


class IntegrationHealthEntry(BaseModel):
    """Health and status for a single integration."""

    name: str = Field(
        ..., description="Integration name: apollo, lemlist, adzuna, gmail, llm_provider"
    )
    status: str = Field(..., description="Status: connected, disconnected, error")
    usage_current: int = 0
    usage_limit: int | None = None
    usage_percentage: float = Field(default=0.0, ge=0, le=100)
    warning_triggered: bool = Field(
        default=False, description="True if usage >= 80%"
    )
    critical_triggered: bool = Field(
        default=False, description="True if usage >= 100%"
    )
    last_validated: datetime | None = None
    last_error: str | None = None


class IntegrationsListResponse(BaseModel):
    """All integration health statuses."""

    integrations: list[IntegrationHealthEntry]


class UpdateIntegrationCredentialsRequest(BaseModel):
    """Request to update credentials for an integration."""

    integration_name: str = Field(
        ..., description="Integration to update: apollo, lemlist, adzuna, gmail, llm_provider"
    )
    credentials: dict[str, str] = Field(
        ..., description="Key-value pairs of credential fields (e.g., {'api_key': '...'})"
    )


class UpdateIntegrationCredentialsResponse(BaseModel):
    """Response from credential update."""

    integration_name: str
    status: str = "updated"
    validated: bool = False


class ValidateCredentialsRequest(BaseModel):
    """Request to validate credentials for an integration."""

    integration_name: str = Field(
        ..., description="Integration to validate: apollo, lemlist, adzuna, gmail, llm_provider"
    )
    credentials: dict[str, str] = Field(
        ..., description="Credentials to validate"
    )


class ValidateCredentialsResponse(BaseModel):
    """Response from credential validation."""

    integration_name: str
    status: str = Field(..., description="Validation result: connected, disconnected, error")
    error: str | None = Field(default=None, description="Error message if validation failed")


# --- Routes ---


@router.get("/settings/integrations", response_model=IntegrationsListResponse)
async def get_integrations() -> IntegrationsListResponse:
    """Get health and status for all configured integrations.

    Returns usage metrics, connection status, and warning/critical flags.
    """
    # Stub: In production, delegates to ConfigManager.get_health() for each integration
    return IntegrationsListResponse(integrations=[])


@router.put("/settings/integrations", response_model=UpdateIntegrationCredentialsResponse)
async def update_integration_credentials(
    request: UpdateIntegrationCredentialsRequest,
) -> UpdateIntegrationCredentialsResponse:
    """Update credentials for a specific integration.

    Stores credentials securely and optionally triggers validation.
    """
    # Stub: In production, stores credentials securely
    return UpdateIntegrationCredentialsResponse(
        integration_name=request.integration_name,
        status="updated",
        validated=False,
    )


@router.post("/settings/integrations/validate", response_model=ValidateCredentialsResponse)
async def validate_integration_credentials(
    request: ValidateCredentialsRequest,
) -> ValidateCredentialsResponse:
    """Validate credentials for an integration by making a test API call.

    Returns the connection status and any error details. Timeout is 10 seconds.
    """
    # Stub: In production, delegates to ConfigManager.validate_credentials()
    return ValidateCredentialsResponse(
        integration_name=request.integration_name,
        status="disconnected",
        error="Validation not yet implemented",
    )
