"""Unit tests for the LLM Router.

Tests cover:
- Provider routing per evaluation type
- evaluate_relevance() score (0-100) and reasoning (max 500 chars)
- generate_content() for outreach material generation
- 7-day cache with hash-based invalidation
- Retry logic (3 attempts, 5-min intervals)
- Partial context when enrichment unavailable
- evaluation_pending when all retries exhausted and no cache
"""

import json

import pytest

from app.core.errors import APITimeoutError, BaseServiceError
from app.integrations.llm_router import (
    EvaluationType,
    LLMConfig,
    LLMProvider,
    LLMRouter,
)

# --- Fixtures ---


class FakeLLMCache:
    """In-memory cache implementing the LLMCache protocol."""

    def __init__(self):
        self._store: dict[str, str] = {}
        self._expiry: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value
        if ex is not None:
            self._expiry[key] = ex


class FakeLLMProvider:
    """Fake LLM provider implementing the LLMProviderClient protocol."""

    def __init__(self, response: str | None = None, error: Exception | None = None):
        self.response = response or json.dumps({"score": 75, "reasoning": "Good match"})
        self.error = error
        self.call_count = 0
        self.calls: list[dict] = []

    async def complete(self, prompt: str, model: str, timeout: int) -> str:
        self.call_count += 1
        self.calls.append({"prompt": prompt, "model": model, "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


@pytest.fixture
def fake_cache():
    return FakeLLMCache()


@pytest.fixture
def fake_anthropic():
    return FakeLLMProvider()


@pytest.fixture
def fake_openai():
    return FakeLLMProvider(response=json.dumps({"score": 60, "reasoning": "Moderate match"}))


@pytest.fixture
def default_configs():
    return {
        EvaluationType.MATCHING: LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model="claude-3-sonnet-20240229",
            timeout=30,
            max_retries=3,
            retry_delay=0,  # No delay in tests
        ),
        EvaluationType.GENERATION: LLMConfig(
            provider=LLMProvider.OPENAI,
            model="gpt-4",
            timeout=30,
            max_retries=3,
            retry_delay=0,
        ),
        EvaluationType.RESEARCH: LLMConfig(
            provider=LLMProvider.ANTHROPIC,
            model="claude-3-opus-20240229",
            timeout=30,
            max_retries=3,
            retry_delay=0,
        ),
    }


@pytest.fixture
def router(default_configs, fake_cache, fake_anthropic, fake_openai):
    providers = {
        LLMProvider.ANTHROPIC: fake_anthropic,
        LLMProvider.OPENAI: fake_openai,
    }
    return LLMRouter(configs=default_configs, cache=fake_cache, providers=providers)


@pytest.fixture
def sample_prospect():
    return {
        "id": "prospect-123",
        "description": "Senior Python Developer needed for fintech startup",
        "enrichment": {
            "status": "complete",
            "industry": "Financial Technology",
            "employee_count": 50,
            "tech_stack": ["Python", "Django", "PostgreSQL", "AWS"],
            "funding_stage": "Series A",
        },
    }


@pytest.fixture
def sample_profile():
    return {
        "name": "John Doe",
        "skills": ["Python", "Django", "FastAPI"],
        "experience_years": 8,
        "industry_preference": "fintech",
    }


# --- Provider Routing Tests ---


class TestProviderRouting:
    """Test that the router correctly routes to configured providers."""

    async def test_matching_routes_to_anthropic(
        self, router, fake_anthropic, sample_prospect, sample_profile
    ):
        """Matching evaluations should route to Anthropic."""
        await router.evaluate_relevance(sample_prospect, sample_profile)
        assert fake_anthropic.call_count == 1
        assert fake_anthropic.calls[0]["model"] == "claude-3-sonnet-20240229"

    async def test_generation_routes_to_openai(self, router, fake_openai):
        """Generation calls should route to OpenAI."""
        await router.generate_content("Write an email", {}, "email")
        assert fake_openai.call_count == 1
        assert fake_openai.calls[0]["model"] == "gpt-4"

    async def test_different_providers_per_evaluation_type(
        self, fake_cache, fake_anthropic, fake_openai, sample_prospect, sample_profile
    ):
        """Each evaluation type can be routed to a different provider."""
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.OPENAI, model="gpt-4", retry_delay=0
            ),
            EvaluationType.GENERATION: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="claude-3-sonnet-20240229", retry_delay=0
            ),
        }
        providers = {LLMProvider.ANTHROPIC: fake_anthropic, LLMProvider.OPENAI: fake_openai}
        router = LLMRouter(configs=configs, cache=fake_cache, providers=providers)

        await router.evaluate_relevance(sample_prospect, sample_profile)
        assert fake_openai.call_count == 1
        assert fake_anthropic.call_count == 0

        await router.generate_content("Write", {}, "email")
        assert fake_anthropic.call_count == 1


# --- evaluate_relevance Tests ---


class TestEvaluateRelevance:
    """Test evaluate_relevance returns (score 0-100, reasoning ≤500 chars)."""

    async def test_returns_valid_score_and_reasoning(
        self, router, sample_prospect, sample_profile
    ):
        """Should return score and reasoning from LLM response."""
        score, reasoning = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert 0 <= score <= 100
        assert isinstance(reasoning, str)
        assert len(reasoning) <= 500

    async def test_score_clamped_to_0_100(self, fake_cache, sample_prospect, sample_profile):
        """Scores outside 0-100 are clamped."""
        provider = FakeLLMProvider(response=json.dumps({"score": 150, "reasoning": "Over"}))
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        score, _ = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert score == 100

    async def test_negative_score_clamped_to_0(self, fake_cache, sample_prospect, sample_profile):
        """Negative scores are clamped to 0."""
        provider = FakeLLMProvider(response=json.dumps({"score": -10, "reasoning": "Bad"}))
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        score, _ = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert score == 0

    async def test_reasoning_truncated_to_500_chars(
        self, fake_cache, sample_prospect, sample_profile
    ):
        """Reasoning longer than 500 chars is truncated."""
        long_reasoning = "A" * 600
        provider = FakeLLMProvider(
            response=json.dumps({"score": 50, "reasoning": long_reasoning})
        )
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        _, reasoning = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert len(reasoning) <= 500

    async def test_parses_json_response(self, router, sample_prospect, sample_profile):
        """Should parse JSON response with score and reasoning."""
        score, reasoning = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert score == 75
        assert reasoning == "Good match"

    async def test_handles_markdown_wrapped_json(
        self, fake_cache, sample_prospect, sample_profile
    ):
        """Should handle LLM responses wrapped in markdown code blocks."""
        response = '```json\n{"score": 82, "reasoning": "Great fit"}\n```'
        provider = FakeLLMProvider(response=response)
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        score, reasoning = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert score == 82
        assert reasoning == "Great fit"

    async def test_handles_unparseable_response(
        self, fake_cache, sample_prospect, sample_profile
    ):
        """Should gracefully handle non-JSON responses."""
        provider = FakeLLMProvider(response="This is not JSON at all")
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        score, reasoning = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert score == 0
        assert len(reasoning) <= 500


# --- Cache Tests ---


class TestCaching:
    """Test 7-day cache with hash-based invalidation."""

    async def test_result_is_cached(
        self, router, fake_cache, fake_anthropic, sample_prospect, sample_profile
    ):
        """First call caches result, second call uses cache."""
        await router.evaluate_relevance(sample_prospect, sample_profile)
        assert fake_anthropic.call_count == 1

        # Second call should use cache
        await router.evaluate_relevance(sample_prospect, sample_profile)
        assert fake_anthropic.call_count == 1

    async def test_cache_ttl_is_7_days(
        self, router, fake_cache, sample_prospect, sample_profile
    ):
        """Cache entries should have a 7-day TTL."""
        await router.evaluate_relevance(sample_prospect, sample_profile)
        # Check that at least one key was stored with TTL
        assert any(v == 7 * 24 * 3600 for v in fake_cache._expiry.values())

    async def test_cache_invalidated_on_description_change(
        self, router, fake_anthropic, sample_prospect, sample_profile
    ):
        """Changing prospect description should cause cache miss."""
        await router.evaluate_relevance(sample_prospect, sample_profile)
        assert fake_anthropic.call_count == 1

        # Change description → different hash → cache miss
        modified_prospect = {**sample_prospect, "description": "New totally different role"}
        await router.evaluate_relevance(modified_prospect, sample_profile)
        assert fake_anthropic.call_count == 2

    async def test_cache_invalidated_on_profile_change(
        self, router, fake_anthropic, sample_prospect, sample_profile
    ):
        """Changing profile data should invalidate cache."""
        await router.evaluate_relevance(sample_prospect, sample_profile)
        assert fake_anthropic.call_count == 1

        # Change profile → different hash → cache miss
        modified_profile = {**sample_profile, "skills": ["Java", "Spring"]}
        await router.evaluate_relevance(sample_prospect, modified_profile)
        assert fake_anthropic.call_count == 2

    async def test_same_inputs_hit_cache(
        self, router, fake_anthropic, sample_prospect, sample_profile
    ):
        """Same prospect and profile should hit cache."""
        score1, reason1 = await router.evaluate_relevance(sample_prospect, sample_profile)
        score2, reason2 = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert score1 == score2
        assert reason1 == reason2
        assert fake_anthropic.call_count == 1

    async def test_corrupted_cache_entry_causes_fresh_call(
        self, fake_cache, fake_anthropic, sample_prospect, sample_profile
    ):
        """Corrupted cache entries should trigger a fresh LLM call."""
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: fake_anthropic},
        )

        # Pre-populate cache with invalid data
        profile_hash = router._compute_profile_hash(
            sample_prospect["description"], sample_profile
        )
        cache_key = router._get_cache_key("prospect-123", profile_hash)
        await fake_cache.set(cache_key, "not-valid-json")

        score, reasoning = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert fake_anthropic.call_count == 1
        assert score == 75


# --- Retry Logic Tests ---


class TestRetryLogic:
    """Test retry behavior (3 attempts, delay between each)."""

    async def test_retries_on_timeout(self, fake_cache, sample_prospect, sample_profile):
        """Should retry up to max_retries times on timeout."""
        call_count = 0

        class FailThenSucceed:
            async def complete(self, prompt, model, timeout):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    raise APITimeoutError("Timed out", service="anthropic")
                return json.dumps({"score": 70, "reasoning": "Eventually worked"})

        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", max_retries=3, retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: FailThenSucceed()},
        )
        score, reasoning = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert score == 70
        assert call_count == 3

    async def test_returns_evaluation_pending_after_all_retries_fail(
        self, fake_cache, sample_prospect, sample_profile
    ):
        """When all retries fail and no cache, returns evaluation_pending."""
        provider = FakeLLMProvider(error=APITimeoutError("Timeout", service="anthropic"))
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", max_retries=3, retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        score, reasoning = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert score == 0
        assert "evaluation_pending" in reasoning

    async def test_retries_on_service_error(self, fake_cache, sample_prospect, sample_profile):
        """Should retry on BaseServiceError as well."""
        call_count = 0

        class FailOnce:
            async def complete(self, prompt, model, timeout):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise BaseServiceError("Provider error", service="anthropic")
                return json.dumps({"score": 55, "reasoning": "Recovered"})

        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", max_retries=3, retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: FailOnce()},
        )
        score, _ = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert score == 55
        assert call_count == 2

    async def test_max_retries_is_3(self, fake_cache, sample_prospect, sample_profile):
        """Should attempt exactly 3 times with default config."""
        provider = FakeLLMProvider(error=APITimeoutError("Timeout", service="test"))
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", max_retries=3, retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        await router.evaluate_relevance(sample_prospect, sample_profile)
        assert provider.call_count == 3


# --- Partial Context Tests ---


class TestPartialContext:
    """Test handling of missing/unavailable enrichment data."""

    async def test_proceeds_without_enrichment(
        self, router, fake_anthropic, sample_profile
    ):
        """Should proceed when enrichment is None."""
        prospect_no_enrichment = {
            "id": "prospect-456",
            "description": "Python developer role",
            "enrichment": None,
        }
        score, _ = await router.evaluate_relevance(prospect_no_enrichment, sample_profile)
        assert 0 <= score <= 100
        assert fake_anthropic.call_count == 1

    async def test_partial_context_with_pending_retry_enrichment(
        self, router, fake_anthropic, sample_profile
    ):
        """Enrichment with pending_retry status is treated as unavailable."""
        prospect = {
            "id": "prospect-789",
            "description": "DevOps engineer needed",
            "enrichment": {"status": "pending_retry"},
        }
        await router.evaluate_relevance(prospect, sample_profile)
        # Should still call provider (proceed with partial context)
        assert fake_anthropic.call_count == 1
        # Prompt should note missing enrichment
        prompt = fake_anthropic.calls[0]["prompt"]
        assert "not yet available" in prompt or "enrichment" in prompt.lower()

    async def test_partial_context_with_enrichment_failed(
        self, router, fake_anthropic, sample_profile
    ):
        """Enrichment with enrichment_failed status is treated as unavailable."""
        prospect = {
            "id": "prospect-000",
            "description": "Frontend developer",
            "enrichment": {"status": "enrichment_failed"},
        }
        await router.evaluate_relevance(prospect, sample_profile)
        assert fake_anthropic.call_count == 1

    async def test_full_context_includes_enrichment_in_prompt(
        self, router, fake_anthropic, sample_prospect, sample_profile
    ):
        """Full enrichment data should be included in the prompt."""
        await router.evaluate_relevance(sample_prospect, sample_profile)
        prompt = fake_anthropic.calls[0]["prompt"]
        assert "Financial Technology" in prompt
        assert "Python" in prompt
        assert "Series A" in prompt

    async def test_partial_context_cached_with_flag(
        self, fake_cache, sample_profile
    ):
        """Partial context results should be cached with the context_status flag."""
        provider = FakeLLMProvider(
            response=json.dumps({"score": 40, "reasoning": "Limited info"})
        )
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        prospect = {
            "id": "prospect-partial",
            "description": "Some role",
            "enrichment": None,
        }
        await router.evaluate_relevance(prospect, sample_profile)

        # Check cache has partial_context flag
        for value in fake_cache._store.values():
            data = json.loads(value)
            assert data["context_status"] == "partial_context"


# --- generate_content Tests ---


class TestGenerateContent:
    """Test content generation for outreach materials."""

    async def test_returns_generated_string(self, router, fake_openai):
        """Should return the generated content string."""
        fake_openai.response = "Dear Hiring Manager, I am writing..."
        result = await router.generate_content(
            prompt="Write a cover letter",
            context={"company": "Acme Corp", "role": "Developer"},
            material_type="cover_letter",
        )
        assert result == "Dear Hiring Manager, I am writing..."

    async def test_routes_to_generation_provider(self, router, fake_openai):
        """Generation should use the GENERATION config (OpenAI in test)."""
        await router.generate_content("Write", {}, "email")
        assert fake_openai.call_count == 1
        assert fake_openai.calls[0]["model"] == "gpt-4"

    async def test_raises_on_all_retries_exhausted(self, fake_cache):
        """Should raise BaseServiceError when all retries fail."""
        provider = FakeLLMProvider(error=APITimeoutError("Timeout", service="openai"))
        configs = {
            EvaluationType.GENERATION: LLMConfig(
                provider=LLMProvider.OPENAI, model="gpt-4", max_retries=3, retry_delay=0
            )
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.OPENAI: provider},
        )
        with pytest.raises(BaseServiceError, match="failed after 3 retries"):
            await router.generate_content("Write", {}, "email")

    async def test_includes_context_in_prompt(self, router, fake_openai):
        """Context should be included in the generation prompt."""
        context = {"industry": "HealthTech", "tech_stack": ["React", "Node.js"]}
        await router.generate_content("Write intro", context, "email")
        prompt = fake_openai.calls[0]["prompt"]
        assert "HealthTech" in prompt
        assert "React" in prompt

    async def test_includes_material_type_in_prompt(self, router, fake_openai):
        """Material type should be included in the prompt."""
        await router.generate_content("Write", {}, "proposal")
        prompt = fake_openai.calls[0]["prompt"]
        assert "proposal" in prompt

    async def test_raises_when_no_generation_config(self, fake_cache):
        """Should raise when no config exists for GENERATION type."""
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", retry_delay=0
            )
        }
        router = LLMRouter(configs=configs, cache=fake_cache, providers={})
        with pytest.raises(BaseServiceError, match="No LLM config for GENERATION"):
            await router.generate_content("Write", {}, "email")


# --- Evaluation Pending Tests ---


# --- Critique / Revision Dispatch Tests ---


class TestDispatchCritique:
    """Test dispatch_critique returns parsed JSON on success and propagates errors."""

    @pytest.fixture
    def critique_provider(self):
        """Provider that returns valid critique JSON."""
        return FakeLLMProvider(
            response=json.dumps({
                "structured_edits": [],
                "narrative_findings": {
                    "missed_keywords": [],
                    "company_angles": [],
                    "reframing": [],
                    "tone_style": [],
                },
            })
        )

    @pytest.fixture
    def critique_router(self, fake_cache, critique_provider):
        """Router configured with CRITIQUE evaluation type."""
        configs = {
            EvaluationType.CRITIQUE: LLMConfig(
                provider=LLMProvider.ANTHROPIC,
                model="claude-3-sonnet-20240229",
                timeout=60,
                max_retries=2,
                retry_delay=0,
            ),
        }
        providers = {LLMProvider.ANTHROPIC: critique_provider}
        return LLMRouter(configs=configs, cache=fake_cache, providers=providers)

    async def test_dispatch_critique_returns_parsed_json(
        self, critique_router, critique_provider
    ):
        """dispatch_critique should parse LLM JSON response and return a dict."""
        result = await critique_router.dispatch_critique("Review this material")
        assert isinstance(result, dict)
        assert "structured_edits" in result
        assert "narrative_findings" in result
        assert result["structured_edits"] == []
        assert result["narrative_findings"]["missed_keywords"] == []

    async def test_dispatch_critique_uses_critique_config(
        self, critique_router, critique_provider
    ):
        """dispatch_critique should use the CRITIQUE config's model."""
        await critique_router.dispatch_critique("Review this material")
        assert critique_provider.call_count == 1
        assert critique_provider.calls[0]["model"] == "claude-3-sonnet-20240229"

    async def test_dispatch_critique_passes_timeout(
        self, critique_router, critique_provider
    ):
        """dispatch_critique should pass the timeout to the provider."""
        await critique_router.dispatch_critique("Review this", timeout=45.0)
        assert critique_provider.calls[0]["timeout"] == 45

    async def test_dispatch_critique_default_timeout_is_60(
        self, critique_router, critique_provider
    ):
        """dispatch_critique default timeout should be 60 seconds."""
        await critique_router.dispatch_critique("Review this")
        assert critique_provider.calls[0]["timeout"] == 60

    async def test_dispatch_critique_timeout_raises_api_timeout_error(self, fake_cache):
        """dispatch_critique should propagate APITimeoutError from provider."""
        provider = FakeLLMProvider(
            error=APITimeoutError("Timed out", service="anthropic", timeout_seconds=60)
        )
        configs = {
            EvaluationType.CRITIQUE: LLMConfig(
                provider=LLMProvider.ANTHROPIC,
                model="claude-3-sonnet-20240229",
                timeout=60,
                retry_delay=0,
            ),
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        with pytest.raises(APITimeoutError):
            await router.dispatch_critique("Review this material")

    async def test_dispatch_critique_invalid_json_raises(self, fake_cache):
        """dispatch_critique should raise json.JSONDecodeError on invalid JSON."""
        provider = FakeLLMProvider(response="This is not valid JSON")
        configs = {
            EvaluationType.CRITIQUE: LLMConfig(
                provider=LLMProvider.ANTHROPIC,
                model="claude-3-sonnet-20240229",
                timeout=60,
                retry_delay=0,
            ),
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        with pytest.raises(json.JSONDecodeError):
            await router.dispatch_critique("Review this material")


class TestDispatchRevision:
    """Test dispatch_revision returns raw string on success and propagates errors."""

    @pytest.fixture
    def revision_provider(self):
        """Provider that returns revised text."""
        return FakeLLMProvider(response="This is the revised material text with improvements.")

    @pytest.fixture
    def revision_router(self, fake_cache, revision_provider):
        """Router configured with REVISION evaluation type."""
        configs = {
            EvaluationType.REVISION: LLMConfig(
                provider=LLMProvider.OPENAI,
                model="gpt-4",
                timeout=60,
                max_retries=2,
                retry_delay=0,
            ),
        }
        providers = {LLMProvider.OPENAI: revision_provider}
        return LLMRouter(configs=configs, cache=fake_cache, providers=providers)

    async def test_dispatch_revision_returns_string(
        self, revision_router, revision_provider
    ):
        """dispatch_revision should return the raw text string from the LLM."""
        result = await revision_router.dispatch_revision("Revise this material")
        assert isinstance(result, str)
        assert result == "This is the revised material text with improvements."

    async def test_dispatch_revision_uses_revision_config(
        self, revision_router, revision_provider
    ):
        """dispatch_revision should use the REVISION config's model."""
        await revision_router.dispatch_revision("Revise this material")
        assert revision_provider.call_count == 1
        assert revision_provider.calls[0]["model"] == "gpt-4"

    async def test_dispatch_revision_passes_timeout(
        self, revision_router, revision_provider
    ):
        """dispatch_revision should pass the timeout to the provider."""
        await revision_router.dispatch_revision("Revise this", timeout=30.0)
        assert revision_provider.calls[0]["timeout"] == 30

    async def test_dispatch_revision_default_timeout_is_60(
        self, revision_router, revision_provider
    ):
        """dispatch_revision default timeout should be 60 seconds."""
        await revision_router.dispatch_revision("Revise this")
        assert revision_provider.calls[0]["timeout"] == 60

    async def test_dispatch_revision_timeout_raises_api_timeout_error(self, fake_cache):
        """dispatch_revision should propagate APITimeoutError from provider."""
        provider = FakeLLMProvider(
            error=APITimeoutError("Timed out", service="openai", timeout_seconds=60)
        )
        configs = {
            EvaluationType.REVISION: LLMConfig(
                provider=LLMProvider.OPENAI,
                model="gpt-4",
                timeout=60,
                retry_delay=0,
            ),
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.OPENAI: provider},
        )
        with pytest.raises(APITimeoutError):
            await router.dispatch_revision("Revise this material")

    async def test_dispatch_revision_does_not_parse_json(
        self, fake_cache
    ):
        """dispatch_revision should return raw text even if it looks like JSON."""
        json_like_response = '{"key": "value"}'
        provider = FakeLLMProvider(response=json_like_response)
        configs = {
            EvaluationType.REVISION: LLMConfig(
                provider=LLMProvider.OPENAI,
                model="gpt-4",
                timeout=60,
                retry_delay=0,
            ),
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.OPENAI: provider},
        )
        result = await router.dispatch_revision("Revise this")
        # Should return the raw string, not a parsed dict
        assert isinstance(result, str)
        assert result == json_like_response


class TestDispatchExtraction:
    """Test dispatch_extraction returns parsed JSON on success and propagates errors."""

    @pytest.fixture
    def extraction_provider(self):
        """Provider that returns valid extraction JSON."""
        return FakeLLMProvider(
            response=json.dumps({
                "claims": [
                    {
                        "claim_text": "10 years of Python experience",
                        "category": "experience_duration",
                        "source_span": "10 years of Python experience",
                        "source_span_start": 0,
                        "source_span_end": 30,
                        "is_prospect_side": False,
                    }
                ]
            })
        )

    @pytest.fixture
    def extraction_router(self, fake_cache, extraction_provider):
        """Router configured with EXTRACTION evaluation type."""
        configs = {
            EvaluationType.EXTRACTION: LLMConfig(
                provider=LLMProvider.ANTHROPIC,
                model="claude-3-sonnet-20240229",
                timeout=60,
                max_retries=2,
                retry_delay=0,
            ),
        }
        providers = {LLMProvider.ANTHROPIC: extraction_provider}
        return LLMRouter(configs=configs, cache=fake_cache, providers=providers)

    async def test_dispatch_extraction_returns_parsed_json(
        self, extraction_router, extraction_provider
    ):
        """dispatch_extraction should parse LLM JSON response and return a dict."""
        result = await extraction_router.dispatch_extraction("Extract claims from this")
        assert isinstance(result, dict)
        assert "claims" in result
        assert len(result["claims"]) == 1
        assert result["claims"][0]["claim_text"] == "10 years of Python experience"

    async def test_dispatch_extraction_uses_extraction_config(
        self, extraction_router, extraction_provider
    ):
        """dispatch_extraction should use the EXTRACTION config's model."""
        await extraction_router.dispatch_extraction("Extract claims")
        assert extraction_provider.call_count == 1
        assert extraction_provider.calls[0]["model"] == "claude-3-sonnet-20240229"

    async def test_dispatch_extraction_passes_timeout(
        self, extraction_router, extraction_provider
    ):
        """dispatch_extraction should pass the timeout to the provider."""
        await extraction_router.dispatch_extraction("Extract claims", timeout=45.0)
        assert extraction_provider.calls[0]["timeout"] == 45

    async def test_dispatch_extraction_default_timeout_is_60(
        self, extraction_router, extraction_provider
    ):
        """dispatch_extraction default timeout should be 60 seconds."""
        await extraction_router.dispatch_extraction("Extract claims")
        assert extraction_provider.calls[0]["timeout"] == 60

    async def test_dispatch_extraction_timeout_raises_api_timeout_error(self, fake_cache):
        """dispatch_extraction should propagate APITimeoutError from provider."""
        provider = FakeLLMProvider(
            error=APITimeoutError("Timed out", service="anthropic", timeout_seconds=60)
        )
        configs = {
            EvaluationType.EXTRACTION: LLMConfig(
                provider=LLMProvider.ANTHROPIC,
                model="claude-3-sonnet-20240229",
                timeout=60,
                retry_delay=0,
            ),
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        with pytest.raises(APITimeoutError):
            await router.dispatch_extraction("Extract claims from this")

    async def test_dispatch_extraction_invalid_json_raises(self, fake_cache):
        """dispatch_extraction should raise json.JSONDecodeError on invalid JSON."""
        provider = FakeLLMProvider(response="This is not valid JSON")
        configs = {
            EvaluationType.EXTRACTION: LLMConfig(
                provider=LLMProvider.ANTHROPIC,
                model="claude-3-sonnet-20240229",
                timeout=60,
                retry_delay=0,
            ),
        }
        router = LLMRouter(
            configs=configs,
            cache=fake_cache,
            providers={LLMProvider.ANTHROPIC: provider},
        )
        with pytest.raises(json.JSONDecodeError):
            await router.dispatch_extraction("Extract claims from this")


# --- Evaluation Pending Tests ---


class TestEvaluationPending:
    """Test that evaluation_pending is returned when appropriate."""

    async def test_no_config_returns_evaluation_pending(
        self, fake_cache, sample_prospect, sample_profile
    ):
        """No matching config should return evaluation_pending."""
        # Empty configs = no matching config
        router = LLMRouter(configs={}, cache=fake_cache, providers={})
        score, reasoning = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert score == 0
        assert "evaluation_pending" in reasoning

    async def test_no_provider_returns_evaluation_pending(
        self, fake_cache, sample_prospect, sample_profile
    ):
        """Config exists but no matching provider should return evaluation_pending."""
        configs = {
            EvaluationType.MATCHING: LLMConfig(
                provider=LLMProvider.ANTHROPIC, model="test", retry_delay=0
            )
        }
        # No providers registered
        router = LLMRouter(configs=configs, cache=fake_cache, providers={})
        score, reasoning = await router.evaluate_relevance(sample_prospect, sample_profile)
        assert score == 0
        assert "evaluation_pending" in reasoning
