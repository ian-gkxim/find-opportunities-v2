"""Personalization Engine — generates tailored outreach materials using enrichment + LLM.

Requirements 11.1–11.7: Enhanced personalization using Apollo enrichment data,
seniority-based tone adaptation, quality scoring, hook incorporation, and
graceful sparse enrichment handling.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


# ─── Protocols (for testability) ──────────────────────────────────────────────


class LLMContentGenerator(Protocol):
    """Protocol matching LLMRouter.generate_content signature."""

    async def generate_content(
        self,
        prompt: str,
        context: dict,
        material_type: str,
    ) -> str:
        """Generate outreach material content.

        Args:
            prompt: The generation prompt with tone and instructions.
            context: Context dict with enrichment data, profile info, hooks.
            material_type: One of "cv", "cover_letter", "proposal", "email".

        Returns:
            Generated content string.
        """
        ...


# ─── Enums ────────────────────────────────────────────────────────────────────


class SeniorityLevel(str, Enum):
    """Contact seniority levels for tone determination."""

    C_SUITE = "c_suite"
    DIRECTOR = "director"
    MANAGER = "manager"
    OTHER = "other"


class MaterialType(str, Enum):
    """Supported outreach material types."""

    CV = "cv"
    COVER_LETTER = "cover_letter"
    PROPOSAL = "proposal"
    EMAIL = "email"


# ─── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class PersonalizationResult:
    """Result of a personalization generation request.

    Attributes:
        content: The generated material content.
        quality_score: Personalization quality 0–100 (% of available fields referenced).
        fields_used: Enrichment fields that were referenced in the content.
        fields_available_unused: Available fields NOT referenced (up to 3 listed when low quality).
        tone_applied: The seniority-based tone used for generation.
        hooks_referenced: Hooks (news, job postings, tech adoption) referenced in content.
        is_low_quality: True if quality_score < 40.
        flags: Additional flags (e.g., "seniority_unknown", "low personalization").
    """

    content: str
    quality_score: int
    fields_used: list[str]
    fields_available_unused: list[str]
    tone_applied: str
    hooks_referenced: list[str]
    is_low_quality: bool
    flags: list[str] = field(default_factory=list)


@dataclass
class EnrichmentData:
    """Enrichment data relevant to personalization.

    A simplified view of the enrichment record fields used by the
    personalization engine for quality scoring and context building.
    """

    industry: str | None = None
    tech_stack: list[str] = field(default_factory=list)
    company_size: int | None = None
    recent_funding: str | None = None
    intent_signals: list[str] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)


# ─── Personalization Engine ───────────────────────────────────────────────────


class PersonalizationEngine:
    """Generates personalized outreach materials using enrichment + LLM.

    Combines Apollo enrichment data with LLM generation, adapting tone
    based on contact seniority, incorporating hooks, computing quality
    scores, and handling sparse data gracefully.

    Requirements:
        11.1: Incorporate enrichment into LLM context, return within 30s
        11.2: Reference at least one hook when available
        11.3: Handle < 3 fields gracefully with reduced quality score
        11.4: Adapt tone based on seniority (C-suite/director/manager)
        11.5: Quality score = (referenced / available) × 100
        11.6: Flag low quality (< 40) with up to 3 unused fields
        11.7: Default to director tone when seniority unknown, flag "seniority_unknown"
    """

    LOW_QUALITY_THRESHOLD = 40
    MIN_DATA_FIELDS = 3
    GENERATION_TIMEOUT = 30.0  # seconds (configurable)

    TONE_MAP: dict[SeniorityLevel, str] = {
        SeniorityLevel.C_SUITE: "company-vision and ROI-focused",
        SeniorityLevel.DIRECTOR: "implementation-focused and team-impact",
        SeniorityLevel.MANAGER: "hands-on and collaboration-focused",
        SeniorityLevel.OTHER: "hands-on and collaboration-focused",
    }

    ENRICHMENT_FIELDS: list[str] = [
        "industry",
        "tech_stack",
        "company_size",
        "recent_funding",
        "intent_signals",
        "hooks",
    ]

    VALID_MATERIAL_TYPES: set[str] = {"cv", "cover_letter", "proposal", "email"}

    def __init__(
        self,
        llm_router: LLMContentGenerator,
        schema_registry=None,
        generation_timeout: float | None = None,
    ) -> None:
        """Initialize the PersonalizationEngine.

        Args:
            llm_router: LLM router implementing the generate_content protocol.
            schema_registry: Schema registry for beneficiary/opportunity config.
            generation_timeout: Override default 30s generation timeout.
        """
        self._llm = llm_router
        self._schema = schema_registry
        self._timeout = generation_timeout or self.GENERATION_TIMEOUT

    async def generate_materials(
        self,
        enrichment: EnrichmentData,
        beneficiary_id: str,
        material_type: str,
        contact_seniority: str | None = None,
        beneficiary_context: dict | None = None,
    ) -> PersonalizationResult:
        """Generate personalized outreach material.

        Orchestrates the full personalization pipeline: tone determination,
        context building, LLM generation, quality scoring, and flagging.

        Args:
            enrichment: Enrichment data for the prospect.
            beneficiary_id: The beneficiary generating outreach (e.g., "consultant").
            material_type: Type of material to generate ("cv", "cover_letter", "proposal", "email").
            contact_seniority: Seniority of the target contact (e.g., "c_suite", "director").
            beneficiary_context: Additional context (baseline assets, offerings, etc.).

        Returns:
            PersonalizationResult with content, quality score, and flags.

        Raises:
            ValueError: If material_type is not one of the supported types.
            asyncio.TimeoutError: If generation exceeds the configured timeout.
        """
        if material_type not in self.VALID_MATERIAL_TYPES:
            raise ValueError(
                f"Invalid material_type '{material_type}'. "
                f"Must be one of: {', '.join(sorted(self.VALID_MATERIAL_TYPES))}"
            )

        # Determine tone from contact seniority
        seniority_level = self._determine_tone(contact_seniority)
        tone_description = self.TONE_MAP[seniority_level]

        # Build flags
        flags: list[str] = []
        if contact_seniority is None:
            flags.append("seniority_unknown")

        # Identify available fields
        available_fields = self._get_available_fields(enrichment)

        # Build LLM context
        context = self._build_context(
            enrichment=enrichment,
            beneficiary_id=beneficiary_id,
            tone=tone_description,
            hooks=enrichment.hooks,
            beneficiary_context=beneficiary_context or {},
        )

        # Build generation prompt
        prompt = self._build_prompt(
            material_type=material_type,
            tone=tone_description,
            available_fields=available_fields,
            hooks=enrichment.hooks,
            is_sparse=len(available_fields) < self.MIN_DATA_FIELDS,
        )

        # Generate content with timeout
        content = await asyncio.wait_for(
            self._llm.generate_content(
                prompt=prompt,
                context=context,
                material_type=material_type,
            ),
            timeout=self._timeout,
        )

        # Compute quality score
        quality_score, fields_used, fields_unused = self._compute_quality_score(
            content, enrichment
        )

        # Determine hooks referenced
        hooks_referenced = self._find_hooks_referenced(content, enrichment.hooks)

        # Check low quality
        is_low_quality = quality_score < self.LOW_QUALITY_THRESHOLD
        if is_low_quality:
            flags.append("low personalization")

        # Limit unused fields list to 3 for the result
        fields_available_unused = fields_unused[:3] if is_low_quality else fields_unused

        return PersonalizationResult(
            content=content,
            quality_score=quality_score,
            fields_used=fields_used,
            fields_available_unused=fields_available_unused,
            tone_applied=tone_description,
            hooks_referenced=hooks_referenced,
            is_low_quality=is_low_quality,
            flags=flags,
        )

    def _determine_tone(self, contact_seniority: str | None) -> SeniorityLevel:
        """Determine tone from contact seniority level.

        Requirement 11.4: Adapt tone based on seniority.
        Requirement 11.7: Default to director when seniority unknown.

        Args:
            contact_seniority: Seniority string from Contact (e.g., "c_suite", "director").

        Returns:
            SeniorityLevel enum value for tone mapping.
        """
        if contact_seniority is None:
            return SeniorityLevel.DIRECTOR

        # Map string to enum, defaulting to DIRECTOR for unknown values
        seniority_map = {
            "c_suite": SeniorityLevel.C_SUITE,
            "director": SeniorityLevel.DIRECTOR,
            "manager": SeniorityLevel.MANAGER,
            "other": SeniorityLevel.OTHER,
        }
        return seniority_map.get(contact_seniority.lower(), SeniorityLevel.DIRECTOR)

    def _compute_quality_score(
        self, content: str, enrichment: EnrichmentData
    ) -> tuple[int, list[str], list[str]]:
        """Compute personalization quality as % of available fields referenced.

        Requirement 11.5: Score = (referenced_fields / available_fields) × 100.
        Requirement 11.6: List up to 3 unused available fields when low quality.

        Args:
            content: The generated material content.
            enrichment: The enrichment data used for generation.

        Returns:
            Tuple of (quality_score, fields_used, fields_unused).
        """
        content_lower = content.lower()

        available_fields = self._get_available_fields(enrichment)
        if not available_fields:
            return (0, [], [])

        fields_used: list[str] = []
        fields_unused: list[str] = []

        for field_name in available_fields:
            if self._is_field_referenced(field_name, content_lower, enrichment):
                fields_used.append(field_name)
            else:
                fields_unused.append(field_name)

        # Score = (referenced / available) × 100
        score = int((len(fields_used) / len(available_fields)) * 100)

        return (score, fields_used, fields_unused)

    def _get_available_fields(self, enrichment: EnrichmentData) -> list[str]:
        """Get list of enrichment fields that have data available.

        A field is "available" if it has a non-None, non-empty value.

        Args:
            enrichment: The enrichment data to inspect.

        Returns:
            List of field names that contain data.
        """
        available: list[str] = []

        if enrichment.industry:
            available.append("industry")
        if enrichment.tech_stack:
            available.append("tech_stack")
        if enrichment.company_size is not None:
            available.append("company_size")
        if enrichment.recent_funding:
            available.append("recent_funding")
        if enrichment.intent_signals:
            available.append("intent_signals")
        if enrichment.hooks:
            available.append("hooks")

        return available

    def _is_field_referenced(
        self, field_name: str, content_lower: str, enrichment: EnrichmentData
    ) -> bool:
        """Check if a specific enrichment field is referenced in the content.

        Uses heuristic matching — checks for field values or related terms
        appearing in the generated content.

        Args:
            field_name: Name of the enrichment field.
            content_lower: Lowercased content string for matching.
            enrichment: The enrichment data with actual values.

        Returns:
            True if the field appears to be referenced in the content.
        """
        if field_name == "industry":
            return enrichment.industry is not None and enrichment.industry.lower() in content_lower

        if field_name == "tech_stack":
            # Check if any tech in the stack is mentioned
            return any(
                tech.lower() in content_lower for tech in enrichment.tech_stack
            )

        if field_name == "company_size":
            # Check for employee count reference
            if enrichment.company_size is not None:
                return str(enrichment.company_size) in content_lower or "employee" in content_lower

        if field_name == "recent_funding":
            return (
                enrichment.recent_funding is not None
                and enrichment.recent_funding.lower() in content_lower
            )

        if field_name == "intent_signals":
            # Check if any intent signal topic is mentioned
            return any(
                signal.lower() in content_lower for signal in enrichment.intent_signals
            )

        if field_name == "hooks":
            # Check if any hook content is referenced
            return any(
                self._hook_referenced(hook, content_lower) for hook in enrichment.hooks
            )

        return False

    def _hook_referenced(self, hook: dict, content_lower: str) -> bool:
        """Check if a specific hook is referenced in the content.

        Args:
            hook: Hook dict with type and content/topic fields.
            content_lower: Lowercased content for matching.

        Returns:
            True if the hook appears referenced.
        """
        # Check hook topic/title/content fields
        for key in ("topic", "title", "content", "name"):
            value = hook.get(key)
            if value and isinstance(value, str) and value.lower() in content_lower:
                return True
        return False

    def _find_hooks_referenced(
        self, content: str, hooks: list[dict]
    ) -> list[str]:
        """Find which hooks are referenced in the generated content.

        Requirement 11.2: Reference at least one hook when available.

        Args:
            content: Generated content.
            hooks: Available hooks from enrichment.

        Returns:
            List of hook identifiers/topics that were referenced.
        """
        content_lower = content.lower()
        referenced: list[str] = []

        for hook in hooks:
            hook_type = hook.get("type", "unknown")
            hook_topic = hook.get("topic") or hook.get("title") or hook.get("name", "")
            if self._hook_referenced(hook, content_lower):
                referenced.append(f"{hook_type}:{hook_topic}")

        return referenced

    def _build_context(
        self,
        enrichment: EnrichmentData,
        beneficiary_id: str,
        tone: str,
        hooks: list[dict],
        beneficiary_context: dict,
    ) -> dict:
        """Build the context dict passed to the LLM for generation.

        Incorporates all available enrichment data, hooks, tone instructions,
        and beneficiary information into a structured context.

        Args:
            enrichment: Prospect enrichment data.
            beneficiary_id: The beneficiary ID.
            tone: Tone description string.
            hooks: Available hooks for the prospect.
            beneficiary_context: Additional beneficiary assets/info.

        Returns:
            Context dictionary for LLM generation.
        """
        context: dict = {
            "beneficiary_id": beneficiary_id,
            "tone": tone,
            "beneficiary_assets": beneficiary_context,
        }

        # Add available enrichment data
        if enrichment.industry:
            context["industry"] = enrichment.industry
        if enrichment.tech_stack:
            context["tech_stack"] = enrichment.tech_stack
        if enrichment.company_size is not None:
            context["company_size"] = enrichment.company_size
        if enrichment.recent_funding:
            context["recent_funding"] = enrichment.recent_funding
        if enrichment.intent_signals:
            context["intent_signals"] = enrichment.intent_signals
        if hooks:
            context["hooks"] = hooks

        return context

    def _build_prompt(
        self,
        material_type: str,
        tone: str,
        available_fields: list[str],
        hooks: list[dict],
        is_sparse: bool,
    ) -> str:
        """Build the generation prompt with tone and context instructions.

        Args:
            material_type: Type of material to generate.
            tone: Tone description for the content.
            available_fields: Fields available for personalization.
            hooks: Available hooks to reference.
            is_sparse: Whether enrichment has < 3 fields (sparse data).

        Returns:
            Prompt string for LLM generation.
        """
        parts: list[str] = [
            f"Generate a personalized {material_type.replace('_', ' ')} for outreach.",
            "",
            f"TONE: Use a {tone} tone throughout the content.",
            "",
            "PERSONALIZATION REQUIREMENTS:",
            f"- Reference as many of these available data fields as naturally possible: {', '.join(available_fields)}",
        ]

        if hooks:
            hook_descriptions = []
            for hook in hooks:
                hook_type = hook.get("type", "signal")
                hook_topic = hook.get("topic") or hook.get("title") or hook.get("name", "")
                hook_descriptions.append(f"{hook_type}: {hook_topic}")
            parts.append(
                f"- IMPORTANT: Reference at least one of these hooks: {'; '.join(hook_descriptions)}"
            )

        if is_sparse:
            parts.extend([
                "",
                "NOTE: Limited enrichment data is available. Maximize the use of what is provided",
                "while maintaining a natural, professional tone. Do not invent details.",
            ])

        parts.extend([
            "",
            "GUIDELINES:",
            "- Keep the content professional and tailored to the prospect",
            "- Naturally weave enrichment data into the narrative",
            "- Do not explicitly mention that you are referencing enrichment data",
            "- Maintain the specified tone consistently",
        ])

        return "\n".join(parts)
