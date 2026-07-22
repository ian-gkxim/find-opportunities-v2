"""LLM Router for provider routing, caching, and retry logic.

Requirements 17.1-17.7: LLM evaluation retention and enhancement.
- 17.1: Relevance score (0-100) and reasoning (max 500 chars)
- 17.2: Provide LLM with prospect description and enrichment context
- 17.3: Proceed with partial context when enrichment unavailable, flag as "partial_context"
- 17.4: Configurable provider per evaluation type (matching, generation, research)
- 17.5: 7-day cache with hash-based invalidation
- 17.6: Retry logic (3 attempts, 5-min intervals) on provider unavailability
- 17.7: Queue "evaluation_pending" when all retries exhausted and no cache exists
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from app.core.errors import APITimeoutError, BaseServiceError
from app.core.utils import compute_content_hash, truncate_string

logger = logging.getLogger(__name__)


# --- Enums ---


class LLMProvider(str, Enum):
    """Supported LLM providers."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class EvaluationType(str, Enum):
    """Types of LLM evaluation, each can be routed to a different provider."""

    MATCHING = "matching"
    GENERATION = "generation"
    RESEARCH = "research"
    CRITIQUE = "critique"      # Fresh-context review
    REVISION = "revision"      # Narrative finding revision
    EXTRACTION = "extraction"  # P2: claim extraction from materials


class EvaluationStatus(str, Enum):
    """Status of an LLM evaluation result."""

    COMPLETE = "complete"
    PARTIAL_CONTEXT = "partial_context"
    EVALUATION_PENDING = "evaluation_pending"


# --- Protocols for testability ---


class LLMProviderClient(Protocol):
    """Protocol for LLM provider implementations (Anthropic, OpenAI)."""

    async def complete(self, prompt: str, model: str, timeout: int) -> str:
        """Send a completion request to the provider.

        Args:
            prompt: The full prompt to send.
            model: Model identifier (e.g., "claude-3-sonnet-20240229").
            timeout: Request timeout in seconds.

        Returns:
            The raw text response from the provider.

        Raises:
            APITimeoutError: If the request exceeds the timeout.
            BaseServiceError: For other provider errors.
        """
        ...


class LLMCache(Protocol):
    """Protocol for LLM cache implementations (Redis, in-memory, etc.)."""

    async def get(self, key: str) -> str | None:
        """Retrieve a cached value by key.

        Returns:
            The cached JSON string, or None if not found or expired.
        """
        ...

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        """Store a value in the cache with optional TTL.

        Args:
            key: Cache key.
            value: JSON string to store.
            ex: Time-to-live in seconds, or None for no expiration.
        """
        ...


# --- Data Models ---


@dataclass
class LLMConfig:
    """Configuration for an LLM provider per evaluation type.

    Attributes:
        provider: Which LLM provider to use.
        model: Model identifier (e.g., "claude-3-sonnet-20240229", "gpt-4").
        timeout: Request timeout in seconds (default 30).
        max_retries: Maximum retry attempts on failure (default 3).
        retry_delay: Seconds between retry attempts (default 300 = 5 minutes).
    """

    provider: LLMProvider
    model: str
    timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 300  # 5 minutes


@dataclass
class RelevanceResult:
    """Result of an LLM relevance evaluation.

    Attributes:
        score: Relevance score between 0 and 100.
        reasoning: Explanation of the score, max 500 characters.
        status: Whether evaluation used full or partial context.
        prospect_id: The prospect that was evaluated.
        cached: Whether the result came from cache.
    """

    score: int
    reasoning: str
    status: EvaluationStatus
    prospect_id: str
    cached: bool = False


# --- LLM Router ---


class LLMRouter:
    """Routes LLM calls to configured providers per evaluation type.

    Implements provider routing, 7-day caching with hash invalidation,
    retry logic (3 attempts, 5-min intervals), partial context handling,
    and evaluation_pending queueing.

    The router accepts protocol-based cache and provider interfaces
    for testability—no concrete Redis or HTTP dependencies required.
    """

    CACHE_TTL = 7 * 24 * 3600  # 7 days in seconds
    MAX_REASONING_LENGTH = 500
    MAX_SCORE = 100
    MIN_SCORE = 0

    def __init__(
        self,
        configs: dict[EvaluationType, LLMConfig],
        cache: LLMCache,
        providers: dict[LLMProvider, LLMProviderClient],
    ) -> None:
        """Initialize the LLM Router.

        Args:
            configs: Provider/model configuration per evaluation type.
            cache: Cache implementation (Redis, in-memory, etc.).
            providers: Map of provider enum to client implementation.
        """
        self._configs = configs
        self._cache = cache
        self._providers = providers

    async def evaluate_relevance(
        self,
        prospect: dict,
        profile: dict,
    ) -> tuple[int, str]:
        """Evaluate prospect relevance against a beneficiary profile.

        Returns a tuple of (score 0-100, reasoning max 500 chars).
        Uses cached results when available and valid. Handles partial
        context when enrichment is unavailable. Queues as evaluation_pending
        when all retries fail and no cache exists.

        Args:
            prospect: Prospect data dict containing at minimum:
                - "id": Prospect identifier
                - "description": Job/opportunity description
                - "enrichment": Optional enrichment data dict or None
            profile: Beneficiary profile data dict.

        Returns:
            Tuple of (score: int, reasoning: str).

        Raises:
            No exceptions are raised to callers. On total failure with no
            cache, returns (0, "evaluation_pending: ...") to indicate the
            prospect needs re-evaluation.
        """
        prospect_id = prospect.get("id", "unknown")
        description = prospect.get("description", "")
        enrichment = prospect.get("enrichment")

        # Compute cache key from prospect description + profile hash
        profile_hash = self._compute_profile_hash(description, profile)
        cache_key = self._get_cache_key(prospect_id, profile_hash)

        # Check cache first
        cached = await self._get_cached_result(cache_key)
        if cached is not None:
            logger.debug(f"Cache hit for prospect {prospect_id}")
            return cached["score"], cached["reasoning"]

        # Determine context status
        has_enrichment = self._has_valid_enrichment(enrichment)
        context_status = (
            EvaluationStatus.COMPLETE if has_enrichment else EvaluationStatus.PARTIAL_CONTEXT
        )

        # Build prompt with available context
        prompt = self._build_relevance_prompt(prospect, profile, has_enrichment)

        # Get config for matching evaluation type
        config = self._configs.get(EvaluationType.MATCHING)
        if config is None:
            logger.error("No LLM config for MATCHING evaluation type")
            return 0, "evaluation_pending: no provider configured for matching"

        # Execute with retry logic
        response = await self._execute_with_retry(prompt, config)

        if response is None:
            # All retries exhausted, no cache available
            logger.warning(
                f"All retries exhausted for prospect {prospect_id}, "
                "queuing as evaluation_pending"
            )
            return 0, "evaluation_pending: provider unavailable after retries"

        # Parse LLM response into score and reasoning
        score, reasoning = self._parse_relevance_response(response)

        # Enforce constraints
        score = max(self.MIN_SCORE, min(self.MAX_SCORE, score))
        reasoning = truncate_string(reasoning, self.MAX_REASONING_LENGTH, suffix="")

        # Cache the result
        cache_value = json.dumps({
            "score": score,
            "reasoning": reasoning,
            "context_status": context_status.value,
            "cached_at": int(time.time()),
        })
        await self._cache.set(cache_key, cache_value, ex=self.CACHE_TTL)

        # Log partial context usage
        if context_status == EvaluationStatus.PARTIAL_CONTEXT:
            logger.info(
                f"Evaluated prospect {prospect_id} with partial context "
                "(enrichment unavailable)"
            )

        return score, reasoning

    async def generate_content(
        self,
        prompt: str,
        context: dict,
        material_type: str,
    ) -> str:
        """Generate outreach material content using the configured LLM provider.

        Args:
            prompt: The generation prompt.
            context: Context dict with enrichment data, profile info, etc.
            material_type: Type of material ("cv", "cover_letter", "proposal", "email").

        Returns:
            Generated content string.

        Raises:
            BaseServiceError: If generation fails after all retries.
        """
        config = self._configs.get(EvaluationType.GENERATION)
        if config is None:
            raise BaseServiceError(
                "No LLM config for GENERATION evaluation type",
                service="llm_router",
            )

        # Build full prompt with context
        full_prompt = self._build_generation_prompt(prompt, context, material_type)

        # Execute with retry logic
        response = await self._execute_with_retry(full_prompt, config)

        if response is None:
            raise BaseServiceError(
                f"Content generation failed after {config.max_retries} retries",
                service="llm_router",
                details={"material_type": material_type},
            )

        return response

    # --- Critique / Revision Dispatch ---

    async def dispatch_critique(self, prompt: str, timeout: float = 60.0) -> dict:
        """Dispatch a critique request using the CRITIQUE evaluation type config.

        Returns raw JSON response parsed as dict for parsing by Review_Service.
        Raises APITimeoutError after timeout.

        Args:
            prompt: The full critique prompt (fresh context only).
            timeout: Request timeout in seconds (default 60).

        Returns:
            Parsed JSON dict from the LLM response.

        Raises:
            APITimeoutError: If the provider exceeds the timeout.
            BaseServiceError: For other provider errors.
            json.JSONDecodeError: If response is not valid JSON.
        """
        config = self._configs[EvaluationType.CRITIQUE]
        provider_client = self._providers[config.provider]
        response = await provider_client.complete(
            prompt=prompt,
            model=config.model,
            timeout=int(timeout),
        )
        return json.loads(response)

    async def dispatch_revision(self, prompt: str, timeout: float = 60.0) -> str:
        """Dispatch a targeted revision request using REVISION config.

        Returns revised material text as string.
        Raises APITimeoutError after timeout.

        Args:
            prompt: The revision prompt with material text and narrative findings.
            timeout: Request timeout in seconds (default 60).

        Returns:
            Revised material text string from the LLM.

        Raises:
            APITimeoutError: If the provider exceeds the timeout.
            BaseServiceError: For other provider errors.
        """
        config = self._configs[EvaluationType.REVISION]
        provider_client = self._providers[config.provider]
        return await provider_client.complete(
            prompt=prompt,
            model=config.model,
            timeout=int(timeout),
        )

    async def dispatch_extraction(self, prompt: str, timeout: float = 60.0) -> dict:
        """Dispatch a claim extraction request using EXTRACTION evaluation type.

        Returns raw JSON response containing extracted claims array.
        Raises APITimeoutError after timeout.

        Args:
            prompt: The full extraction prompt with material text.
            timeout: Request timeout in seconds (default 60).

        Returns:
            Parsed JSON dict from the LLM response (containing claims array).

        Raises:
            APITimeoutError: If the provider exceeds the timeout.
            BaseServiceError: For other provider errors.
            json.JSONDecodeError: If response is not valid JSON.
        """
        config = self._configs[EvaluationType.EXTRACTION]
        provider_client = self._providers[config.provider]
        response = await provider_client.complete(
            prompt=prompt,
            model=config.model,
            timeout=int(timeout),
        )
        return json.loads(response)

    # --- Cache Methods ---

    def _get_cache_key(self, prospect_id: str, profile_hash: str) -> str:
        """Generate cache key from prospect ID and profile hash.

        The key is invalidated when the prospect description or profile
        changes because the profile_hash incorporates both.

        Args:
            prospect_id: Unique prospect identifier.
            profile_hash: SHA-256 hash of prospect description + profile data.

        Returns:
            Cache key string.
        """
        return f"llm_eval:{prospect_id}:{profile_hash}"

    def _compute_profile_hash(self, description: str, profile: dict) -> str:
        """Compute SHA-256 hash of prospect description + profile for cache invalidation.

        Uses compute_content_hash from app.core.utils to generate a deterministic
        hash that changes when either the description or profile changes.

        Args:
            description: Prospect job/opportunity description.
            profile: Beneficiary profile data dict.

        Returns:
            64-character hex SHA-256 digest.
        """
        profile_str = json.dumps(profile, sort_keys=True, default=str)
        return compute_content_hash(description, profile_str)

    async def _get_cached_result(self, cache_key: str) -> dict[str, Any] | None:
        """Retrieve a cached evaluation result if still valid.

        Cache entries expire after 7 days (CACHE_TTL). The cache key
        already incorporates the content hash, so hash changes produce
        a cache miss automatically.

        Args:
            cache_key: The cache key to look up.

        Returns:
            Parsed cache entry dict with "score" and "reasoning", or None.
        """
        try:
            raw = await self._cache.get(cache_key)
            if raw is None:
                return None
            data = json.loads(raw)
            return data
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Invalid cache entry for {cache_key}: {e}")
            return None

    # --- Retry Logic ---

    async def _execute_with_retry(self, prompt: str, config: LLMConfig) -> str | None:
        """Execute an LLM call with retry logic.

        Attempts up to config.max_retries times with config.retry_delay
        seconds between attempts. Returns None if all attempts fail.

        Args:
            prompt: The full prompt to send.
            config: LLM configuration with provider, model, timeouts.

        Returns:
            The provider response string, or None if all retries exhausted.
        """
        provider_client = self._providers.get(config.provider)
        if provider_client is None:
            logger.error(f"No provider client configured for {config.provider.value}")
            return None

        last_error: BaseException | None = None

        for attempt in range(1, config.max_retries + 1):
            try:
                response = await provider_client.complete(
                    prompt=prompt,
                    model=config.model,
                    timeout=config.timeout,
                )
                return response
            except (APITimeoutError, BaseServiceError) as e:
                last_error = e
                logger.warning(
                    f"LLM provider {config.provider.value} attempt {attempt}/{config.max_retries} "
                    f"failed: {e}"
                )
                if attempt < config.max_retries:
                    await asyncio.sleep(config.retry_delay)
            except Exception as e:
                last_error = e
                logger.error(
                    f"Unexpected error from LLM provider {config.provider.value} "
                    f"attempt {attempt}/{config.max_retries}: {e}"
                )
                if attempt < config.max_retries:
                    await asyncio.sleep(config.retry_delay)

        logger.error(
            f"All {config.max_retries} attempts failed for provider "
            f"{config.provider.value}. Last error: {last_error}"
        )
        return None

    # --- Context and Prompt Building ---

    def _has_valid_enrichment(self, enrichment: dict | None) -> bool:
        """Check if enrichment data is available and usable.

        Enrichment is considered unavailable if it's None, empty,
        or has a status indicating it's not yet complete (pending_retry).

        Args:
            enrichment: Enrichment data dict or None.

        Returns:
            True if enrichment is available for use in evaluation.
        """
        if not enrichment:
            return False
        status = enrichment.get("status", "")
        if status in ("pending_retry", "enrichment_failed", "not_found", ""):
            return False
        return True

    def _build_relevance_prompt(
        self,
        prospect: dict,
        profile: dict,
        has_enrichment: bool,
    ) -> str:
        """Build the relevance evaluation prompt.

        Includes prospect description and, when available, Apollo enrichment
        context (company size, tech stack, funding stage, intent signals).

        Args:
            prospect: Prospect data dict.
            profile: Beneficiary profile dict.
            has_enrichment: Whether enrichment data is available.

        Returns:
            Formatted prompt string.
        """
        description = prospect.get("description", "No description available")
        profile_summary = json.dumps(profile, indent=2, default=str)

        prompt_parts = [
            "Evaluate the relevance of the following opportunity for the candidate profile.",
            "",
            "Return a JSON object with two fields:",
            '- "score": an integer from 0 to 100 indicating relevance',
            '- "reasoning": a brief explanation (max 500 characters)',
            "",
            "--- OPPORTUNITY DESCRIPTION ---",
            description,
            "",
            "--- CANDIDATE PROFILE ---",
            profile_summary,
        ]

        if has_enrichment:
            enrichment = prospect.get("enrichment", {})
            enrichment_context = self._format_enrichment_context(enrichment)
            prompt_parts.extend([
                "",
                "--- COMPANY ENRICHMENT DATA (Apollo.io) ---",
                enrichment_context,
            ])
        else:
            prompt_parts.extend([
                "",
                "NOTE: Company enrichment data is not yet available. "
                "Evaluate based on the opportunity description only.",
            ])

        return "\n".join(prompt_parts)

    def _format_enrichment_context(self, enrichment: dict) -> str:
        """Format enrichment data for inclusion in the LLM prompt.

        Args:
            enrichment: Enrichment data dict.

        Returns:
            Human-readable enrichment summary string.
        """
        parts = []
        if enrichment.get("industry"):
            parts.append(f"Industry: {enrichment['industry']}")
        if enrichment.get("employee_count"):
            parts.append(f"Company Size: {enrichment['employee_count']} employees")
        if enrichment.get("tech_stack"):
            tech = ", ".join(enrichment["tech_stack"][:20])  # Cap at 20 items
            parts.append(f"Tech Stack: {tech}")
        if enrichment.get("funding_stage"):
            parts.append(f"Funding Stage: {enrichment['funding_stage']}")
        if enrichment.get("revenue_range"):
            parts.append(f"Revenue: {enrichment['revenue_range']}")
        if enrichment.get("intent_signals"):
            signals = enrichment["intent_signals"]
            if isinstance(signals, list):
                signal_strs = [
                    f"{s.get('topic', 'unknown')} ({s.get('strength', 'unknown')})"
                    for s in signals[:5]
                ]
                parts.append(f"Intent Signals: {', '.join(signal_strs)}")
        return "\n".join(parts) if parts else "No enrichment data available"

    def _build_generation_prompt(
        self,
        prompt: str,
        context: dict,
        material_type: str,
    ) -> str:
        """Build the content generation prompt.

        Args:
            prompt: Base generation prompt.
            context: Context dict with enrichment, profile, etc.
            material_type: Type of material to generate.

        Returns:
            Full prompt string for the LLM provider.
        """
        context_str = json.dumps(context, indent=2, default=str)

        return "\n".join([
            f"Generate {material_type} content based on the following instructions and context.",
            "",
            "--- INSTRUCTIONS ---",
            prompt,
            "",
            "--- CONTEXT ---",
            context_str,
            "",
            f"Material type: {material_type}",
            "Generate the content now:",
        ])

    # --- Response Parsing ---

    def _parse_relevance_response(self, response: str) -> tuple[int, str]:
        """Parse the LLM response into a score and reasoning.

        Attempts JSON parsing first, falls back to heuristic extraction.

        Args:
            response: Raw LLM response string.

        Returns:
            Tuple of (score: int, reasoning: str).
        """
        # Try JSON parsing first
        try:
            # Handle potential markdown code blocks
            cleaned = response.strip()
            if cleaned.startswith("```"):
                # Remove markdown code block wrapping
                lines = cleaned.split("\n")
                # Remove first and last lines (``` markers)
                cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

            data = json.loads(cleaned)
            score = int(data.get("score", 0))
            reasoning = str(data.get("reasoning", ""))
            return score, reasoning
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # Fallback: try to extract score from response text
        try:
            # Look for patterns like "Score: 75" or "score: 75"
            import re

            score_match = re.search(r"(?:score|Score)\s*[:=]\s*(\d+)", response)
            if score_match:
                score = int(score_match.group(1))
                # Use remainder as reasoning
                reasoning = response[:500]
                return score, reasoning
        except (ValueError, AttributeError):
            pass

        # Last resort: return 0 with the response as reasoning
        return 0, truncate_string(
            f"Unable to parse LLM response: {response}", self.MAX_REASONING_LENGTH, suffix=""
        )
