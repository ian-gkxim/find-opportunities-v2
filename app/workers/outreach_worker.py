"""Outreach background workers for Lemlist enrollment and Gmail sending.

Implements the ARQ task functions for outbound material delivery:
- run_outreach_send: Unified entry point that dispatches to Gmail or Lemlist
- run_lemlist_outreach: Enroll prospects in Lemlist sequences via LemlistEngine
- run_gmail_outreach: Send emails directly via Gmail API

Both paths are intercepted by the OutboundValidator.validate_and_send() gate,
which validates materials against configured rules before allowing submission
to the external Send_Channel.

Interception pattern:
    [ARQ Worker] → OutboundValidator.validate_and_send() → [Send Channel]
                         ↓ (on blocking failure)
                  PipelineManager.transition("validation_failed")

Requirements: 1.1, 1.2
"""

import logging
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.core.outbound_validator import (
    Material,
    OutboundValidator,
    ValidationContext,
    ValidationGateResult,
)
from app.core.pipeline_manager import PipelineManager
from app.core.schema_registry import SchemaRegistry
from app.integrations.gmail_client import EmailMessage, GmailClient
from app.integrations.lemlist_engine import LemlistEngine
from app.models.base import get_async_engine, get_async_session_factory
from app.repositories.validation_repository import ValidationRepository

logger = logging.getLogger(__name__)


# ─── Data Structures ──────────────────────────────────────────────────────────


@dataclass
class OutreachRequest:
    """Parameters for an outreach send request.

    Constructed by the pipeline when a material is ready for delivery.
    Contains all info needed to build Material and ValidationContext.
    """

    pipeline_record_id: str
    contact_email: str
    contact_first_name: str
    contact_last_name: str
    outreach_technique: str
    subject: str
    body: str
    signature: str | None = None
    personalization_fields: dict[str, str] | None = None
    sequence_id: str | None = None  # For Lemlist enrollment
    prospect_id: str | None = None  # For Lemlist enrollment


# ─── Helper Functions ─────────────────────────────────────────────────────────


def _build_material(request: OutreachRequest) -> Material:
    """Construct a Material from outreach request parameters.

    Maps the outreach request fields to the Material dataclass
    used by the OutboundValidator for rule execution.
    """
    return Material(
        subject=request.subject,
        body=request.body,
        signature=request.signature,
        personalization_fields=request.personalization_fields or {},
    )


def _build_validation_context(request: OutreachRequest) -> ValidationContext:
    """Construct a ValidationContext from outreach request parameters.

    Maps pipeline/contact info to the ValidationContext dataclass
    used by the OutboundValidator for rule execution.
    """
    return ValidationContext(
        pipeline_record_id=request.pipeline_record_id,
        contact_first_name=request.contact_first_name,
        contact_last_name=request.contact_last_name,
        outreach_technique=request.outreach_technique,
        material_type="email",
        required_fields=list(
            (request.personalization_fields or {}).keys()
        ),
    )


def _build_outbound_validator(
    schema_registry: SchemaRegistry,
    pipeline_manager: PipelineManager,
    validation_repo: ValidationRepository,
) -> OutboundValidator:
    """Build an OutboundValidator with the required dependencies."""
    return OutboundValidator(
        schema_registry=schema_registry,
        pipeline_manager=pipeline_manager,
        db_repo=validation_repo,
    )


# ─── Gmail Outreach Worker ────────────────────────────────────────────────────


async def run_gmail_outreach(ctx: dict, request: OutreachRequest) -> dict:
    """Send an email via Gmail API with OutboundValidator interception.

    Constructs Material and ValidationContext from the request parameters,
    wraps the Gmail send call in a lambda, and passes everything through
    OutboundValidator.validate_and_send().

    If validation blocks the send (blocking rule failure), logs the failure
    and returns a blocked result. The PipelineManager transitions the record
    to validation_failed state automatically within the validator.

    Args:
        ctx: ARQ worker context containing shared resources:
            - 'schema_registry': SchemaRegistry instance
            - 'pipeline_manager': PipelineManager instance
            - 'validation_repo': ValidationRepository instance
        request: OutreachRequest with email content and recipient info.

    Returns:
        Summary dict with send status, message_id (if sent), or blocked info.

    Requirements: 1.1, 1.2
    """
    logger.info(
        "Starting Gmail outreach for pipeline record %s (to: %s)",
        request.pipeline_record_id,
        request.contact_email,
    )

    settings = get_settings()

    # Extract shared resources from ARQ context
    schema_registry = ctx.get("schema_registry") if isinstance(ctx, dict) else None
    pipeline_manager = ctx.get("pipeline_manager") if isinstance(ctx, dict) else None
    validation_repo = ctx.get("validation_repo") if isinstance(ctx, dict) else None

    if not schema_registry or not pipeline_manager or not validation_repo:
        logger.error(
            "Missing required ARQ context resources for Gmail outreach "
            "(schema_registry, pipeline_manager, validation_repo)"
        )
        return {
            "status": "error",
            "error": "Missing required worker context resources",
            "pipeline_record_id": request.pipeline_record_id,
        }

    # Build Material and ValidationContext from request
    material = _build_material(request)
    context = _build_validation_context(request)

    # Build the OutboundValidator
    validator = _build_outbound_validator(
        schema_registry=schema_registry,
        pipeline_manager=pipeline_manager,
        validation_repo=validation_repo,
    )

    # Create the Gmail client
    gmail_client = GmailClient(
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        refresh_token=settings.google_refresh_token,
    )

    # Build the email message for Gmail
    email_message = EmailMessage(
        to=request.contact_email,
        subject=request.subject or "",
        body_html=request.body + (f"\n{request.signature}" if request.signature else ""),
    )

    # Wrap the Gmail send call as an async callable (send_fn)
    async def send_fn():
        return await gmail_client.send_email(email_message)

    # Pass through the OutboundValidator gate
    result: ValidationGateResult = await validator.validate_and_send(
        material=material,
        context=context,
        send_fn=send_fn,
    )

    # Handle blocked path (same pattern as Lemlist integration)
    if result.blocked:
        blocking_rules = [r.rule_id for r in result.report.blocking_failures]
        logger.warning(
            "Gmail outreach BLOCKED for pipeline record %s: "
            "blocking rules=%s",
            request.pipeline_record_id,
            blocking_rules,
        )
        return {
            "status": "blocked",
            "pipeline_record_id": request.pipeline_record_id,
            "blocking_rules": blocking_rules,
            "report_id": result.report.id,
        }

    # Send succeeded
    send_result = result.send_result
    logger.info(
        "Gmail outreach completed for pipeline record %s: message_id=%s",
        request.pipeline_record_id,
        getattr(send_result, "message_id", None),
    )
    return {
        "status": "sent",
        "pipeline_record_id": request.pipeline_record_id,
        "message_id": getattr(send_result, "message_id", ""),
        "thread_id": getattr(send_result, "thread_id", ""),
        "report_id": result.report.id,
    }


# ─── Lemlist Outreach Worker ─────────────────────────────────────────────────


async def run_lemlist_outreach(ctx: dict, request: OutreachRequest) -> dict:
    """Enroll a prospect in a Lemlist sequence with OutboundValidator interception.

    Constructs Material and ValidationContext from the request parameters,
    wraps the LemlistEngine.enroll_prospects() call in a lambda, and passes
    everything through OutboundValidator.validate_and_send().

    If validation blocks the send (blocking rule failure), logs the failure
    and returns a blocked result. The PipelineManager transitions the record
    to validation_failed state automatically within the validator.

    Args:
        ctx: ARQ worker context containing shared resources:
            - 'schema_registry': SchemaRegistry instance
            - 'pipeline_manager': PipelineManager instance
            - 'validation_repo': ValidationRepository instance
        request: OutreachRequest with material content and prospect info.

    Returns:
        Summary dict with enrollment status or blocked info.

    Requirements: 1.1, 1.2
    """
    logger.info(
        "Starting Lemlist outreach for pipeline record %s (prospect: %s)",
        request.pipeline_record_id,
        request.prospect_id,
    )

    settings = get_settings()

    # Extract shared resources from ARQ context
    schema_registry = ctx.get("schema_registry") if isinstance(ctx, dict) else None
    pipeline_manager = ctx.get("pipeline_manager") if isinstance(ctx, dict) else None
    validation_repo = ctx.get("validation_repo") if isinstance(ctx, dict) else None

    if not schema_registry or not pipeline_manager or not validation_repo:
        logger.error(
            "Missing required ARQ context resources for Lemlist outreach "
            "(schema_registry, pipeline_manager, validation_repo)"
        )
        return {
            "status": "error",
            "error": "Missing required worker context resources",
            "pipeline_record_id": request.pipeline_record_id,
        }

    # Build Material and ValidationContext from request
    material = _build_material(request)
    context = _build_validation_context(request)

    # Build the OutboundValidator
    validator = _build_outbound_validator(
        schema_registry=schema_registry,
        pipeline_manager=pipeline_manager,
        validation_repo=validation_repo,
    )

    # Create the Lemlist engine
    async with httpx.AsyncClient() as http_client:
        lemlist = LemlistEngine(
            api_key=settings.lemlist_api_key,
            http_client=http_client,
        )

        # Wrap the Lemlist enrollment call as an async callable (send_fn)
        async def send_fn():
            if not request.sequence_id or not request.prospect_id:
                raise ValueError(
                    "sequence_id and prospect_id are required for Lemlist enrollment"
                )
            enrolled = await lemlist.enroll_prospects(
                request.sequence_id, [request.prospect_id]
            )
            return {"enrolled_count": enrolled}

        # Pass through the OutboundValidator gate
        result: ValidationGateResult = await validator.validate_and_send(
            material=material,
            context=context,
            send_fn=send_fn,
        )

    # Handle blocked path (same pattern as Gmail integration)
    if result.blocked:
        blocking_rules = [r.rule_id for r in result.report.blocking_failures]
        logger.warning(
            "Lemlist outreach BLOCKED for pipeline record %s: "
            "blocking rules=%s",
            request.pipeline_record_id,
            blocking_rules,
        )
        return {
            "status": "blocked",
            "pipeline_record_id": request.pipeline_record_id,
            "blocking_rules": blocking_rules,
            "report_id": result.report.id,
        }

    # Enrollment succeeded
    send_result = result.send_result
    logger.info(
        "Lemlist outreach completed for pipeline record %s: enrolled=%s",
        request.pipeline_record_id,
        send_result,
    )
    return {
        "status": "enrolled",
        "pipeline_record_id": request.pipeline_record_id,
        "enrolled_count": send_result.get("enrolled_count", 0) if send_result else 0,
        "report_id": result.report.id,
    }


# ─── Unified Entry Point ──────────────────────────────────────────────────────

# Outreach techniques that use Lemlist sequence enrollment
LEMLIST_TECHNIQUES = {"lemlist_sequence"}

# Outreach techniques that use direct Gmail send
GMAIL_TECHNIQUES = {"manual_apply", "tender_submission"}


async def run_outreach_send(ctx: dict, request: OutreachRequest) -> dict:
    """Unified ARQ task: dispatch outreach to Gmail or Lemlist based on technique.

    This is the single entry point registered with the ARQ worker. It inspects
    the outreach_technique on the request and delegates to the appropriate
    send path (Gmail or Lemlist), both of which are gated by OutboundValidator.

    Args:
        ctx: ARQ worker context containing shared resources.
        request: OutreachRequest with material content and delivery info.

    Returns:
        Summary dict from the appropriate send path.

    Requirements: 1.1, 1.2
    """
    technique = request.outreach_technique

    if technique in LEMLIST_TECHNIQUES:
        return await run_lemlist_outreach(ctx, request)
    else:
        # Default to Gmail for all non-Lemlist outreach techniques
        return await run_gmail_outreach(ctx, request)
