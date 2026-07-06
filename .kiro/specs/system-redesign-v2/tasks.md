# Implementation Plan: System Redesign v2

## Overview

This plan implements the GKIM Opportunity Finder v2 system — a full-stack redesign featuring schema-driven architecture, Apollo.io B2B enrichment, Lemlist multi-channel sequencing, composite scoring, real-time WebSocket updates, and conversion analytics. Implementation proceeds from infrastructure and data layer through core services, integrations, background workers, frontend, and finally integration testing.

## Tasks

- [x] 1. Project scaffolding and infrastructure setup
  - [x] 1.1 Initialize Python project structure with FastAPI
    - Create directory structure: `app/core/`, `app/integrations/`, `app/api/`, `app/workers/`, `app/models/`, `app/tests/`
    - Set up `pyproject.toml` with dependencies: fastapi, uvicorn, sqlalchemy[asyncio], asyncpg, redis, arq, httpx, pyyaml, hypothesis, pytest, pytest-asyncio
    - Create `app/__init__.py`, `app/main.py` with FastAPI app factory
    - Configure `.env.example` with all required environment variables
    - _Requirements: 18.6_

  - [x] 1.2 Set up PostgreSQL database schema and migrations
    - Install and configure Alembic for async migrations
    - Create initial migration with all 16 tables from the design (prospects, enrichment_records, contacts, intent_signals, account_scores, pipeline_records, sequences, sequence_steps, variants, touchpoints, prospect_enrollments, scoring_configs, llm_cache, integration_health, source_health, funnel_snapshots)
    - Include all indexes, constraints, and CHECK constraints from the design
    - Create `app/models/base.py` with SQLAlchemy async engine setup
    - _Requirements: 12.1_

  - [x] 1.3 Create SQLAlchemy ORM models for all database tables
    - Create `app/models/prospect.py`, `app/models/enrichment.py`, `app/models/contact.py`, `app/models/intent_signal.py`, `app/models/account_score.py`, `app/models/pipeline_record.py`, `app/models/sequence.py`, `app/models/touchpoint.py`, `app/models/config.py`
    - Define relationships, constraints, and JSON column types
    - Create `app/models/__init__.py` exporting all models
    - _Requirements: 1.2, 2.2, 3.2, 5.1_

  - [x] 1.4 Set up Redis connection and ARQ worker configuration
    - Create `app/core/redis.py` with async Redis connection pool
    - Create `app/workers/__init__.py` with ARQ worker settings
    - Configure pub/sub channels for WebSocket broadcasting
    - _Requirements: 8.4, 16.2_

  - [x] 1.5 Create base error classes and shared utilities
    - Implement `app/core/errors.py` with BaseServiceError, APITimeoutError, APIAuthError, RateLimitError, QuotaExhaustedError, SchemaValidationError
    - Create `app/core/utils.py` with shared helpers (normalization, hashing)
    - _Requirements: 1.3, 10.5_

  - [x] 1.6 Set up pytest and Hypothesis test infrastructure
    - Create `conftest.py` with async database fixtures, test client, and Redis mock
    - Configure `pytest.ini` with asyncio mode and Hypothesis settings (max_examples=100)
    - Create `app/tests/__init__.py` and test directory structure mirroring source
    - _Requirements: All (testing infrastructure)_

- [x] 2. Schema Registry implementation
  - [x] 2.1 Implement Schema Registry core (`app/core/schema_registry.py`)
    - Implement SchemaRegistry class with YAML loading, validation, and parsing
    - Implement `_validate()` for required top-level keys and structure
    - Implement `_validate_cross_references()` for beneficiary/technique references
    - Implement `_parse()` to produce typed dataclass instances (Beneficiary, OpportunityType, Technique, Stage)
    - Implement `get_beneficiary()`, `get_opportunity_types_for_beneficiary()`, `get_pipeline_states()`
    - Implement `derive_navigation()` to produce navigation structure for frontend
    - Raise SchemaValidationError with entity_id on failure
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_

  - [ ]* 2.2 Write property tests for Schema Registry validation (Property 27)
    - **Property 27: Schema entity validation**
    - Use Hypothesis to generate valid/invalid beneficiary and technique definitions
    - Verify validation passes iff all required fields are present with non-empty values
    - **Validates: Requirements 12.3, 12.4**

  - [ ]* 2.3 Write property tests for Schema cross-reference validation (Property 28)
    - **Property 28: Schema validation rejects invalid cross-references**
    - Generate schemas with invalid beneficiary refs, unknown techniques, zero pipeline states
    - Verify startup validation fails with specific entity_id and failure reason
    - **Validates: Requirements 12.5, 12.6**

  - [ ]* 2.4 Write property tests for navigation derivation (Property 26)
    - **Property 26: Schema-driven navigation derivation**
    - Generate valid schemas with various beneficiaries/opportunity types
    - Verify navigation routes, sub-tabs, and technique bindings are derived correctly
    - **Validates: Requirements 12.2, 12.7**

- [x] 3. Scoring Engine implementation
  - [x] 3.1 Implement Scoring Engine core (`app/core/scoring_engine.py`)
    - Implement ScoringWeights dataclass with validate() method (sum=100 check)
    - Implement ScoreResult dataclass with total_score, tier, factor_scores, missing_factors, multi_source_bonus
    - Implement `compute_score()` with firmographic, technographic, intent, LLM relevance, and historical sub-scores
    - Implement `_weighted_total()` with proportional redistribution for missing factors
    - Implement `_classify_tier()` (A: 75-100, B: 50-74, C: 25-49, D: 0-24)
    - Apply intent boost (+15 for strong signals, applied once) and multi-source bonus (10 per source, max 30)
    - _Requirements: 4.1, 4.2, 4.5, 4.6, 3.3, 10.2_

  - [ ]* 3.2 Write property tests for weighted scoring (Property 6)
    - **Property 6: Weighted scoring with proportional redistribution produces valid score**
    - Generate random sub-scores (0-100) and random missing factor subsets
    - Verify output is always integer in [0, 100]
    - **Validates: Requirements 4.1, 4.2, 4.6**

  - [ ]* 3.3 Write property tests for weight validation (Property 7)
    - **Property 7: Scoring weight validation**
    - Generate random 5-tuples of integers
    - Verify validation accepts iff each in [0,100] and sum == 100
    - **Validates: Requirements 4.3**

  - [ ]* 3.4 Write property tests for tier classification (Property 8)
    - **Property 8: Tier classification is deterministic and exhaustive**
    - Generate random integers 0-100
    - Verify exactly one tier returned per expected ranges
    - **Validates: Requirements 4.5**

  - [ ]* 3.5 Write property tests for intent signal boost (Property 4)
    - **Property 4: Strong intent signal boost is exactly 15 points, applied once**
    - Generate lists of IntentSignals with varying strengths
    - Verify boost is exactly 15 when any strong signal exists, regardless of count
    - **Validates: Requirements 3.3**

- [x] 4. Checkpoint - Core services foundation
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Apollo.io Client implementation
  - [x] 5.1 Implement Apollo Client (`app/integrations/apollo_client.py`)
    - Implement ApolloClient class with httpx.AsyncClient
    - Implement `enrich_company()` with 15s timeout, retry logic (3 retries, 5-min delay)
    - Implement `find_contacts()` with decision-maker title prioritization and broadened search fallback
    - Implement `get_intent_signals()` with topic keyword matching
    - Implement `enrich_batch()` with rate limiting (max 5 req/sec for batches > 20)
    - Implement EnrichmentRecord, Contact, IntentSignal dataclasses with all status enums
    - Handle all error states: pending_retry, enrichment_failed, not_found, contacts_unavailable
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.5, 3.6_

  - [ ]* 5.2 Write property tests for batch rate limiting (Property 1)
    - **Property 1: Batch rate limiting respects maximum throughput**
    - Generate batches of N > 20 companies
    - Verify no more than 5 requests initiated in any 1-second window
    - **Validates: Requirements 1.6**

  - [ ]* 5.3 Write property tests for stale record detection (Property 2)
    - **Property 2: Stale record detection triggers refresh**
    - Generate EnrichmentRecords and IntentSignals with various ages
    - Verify records older than 30 days are flagged for refresh
    - **Validates: Requirements 1.7, 3.5**

  - [ ]* 5.4 Write property tests for contact selection (Property 3)
    - **Property 3: Contact selection prioritizes seniority and requires contact method**
    - Generate lists of contacts with various titles, emails, LinkedIn URLs
    - Verify max 5 selected, prioritized by seniority, each has email or LinkedIn
    - **Validates: Requirements 2.2**

- [x] 6. Lemlist Engine implementation
  - [x] 6.1 Implement Lemlist Engine (`app/integrations/lemlist_engine.py`)
    - Implement LemlistEngine class with sequence CRUD, sync to Lemlist API
    - Implement `create_sequence()` with 10s sync timeout and sync_failed handling
    - Implement `enroll_prospects()` for individual and batch enrollment (max 200)
    - Implement `enroll_by_filter()` with tier, opportunity type, and intent filtering
    - Implement `poll_responses()` for 5-minute polling of reply/bounce/unsubscribe events
    - Implement `pause_prospect()` for reply detection within 60 seconds
    - Implement `promote_variant()` for A/B winner promotion
    - Implement `assign_variant()` for random equal-distribution assignment
    - Implement auto-advance logic: send next touchpoint when delay elapses without reply
    - Implement max 3 follow-ups then sequence_complete logic
    - Implement failed touchpoint skip-and-continue logic
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.5, 7.1, 7.2, 7.3, 7.4, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

  - [ ]* 6.2 Write property tests for sequence definition validation (Property 9)
    - **Property 9: Sequence definition validation**
    - Generate sequence definitions with varying steps, delays, content lengths
    - Verify validation accepts iff 1-10 steps, 1-30 day delays, ≤5000 char templates
    - **Validates: Requirements 5.1**

  - [ ]* 6.3 Write property tests for A/B variant assignment (Property 10)
    - **Property 10: A/B variant assignment achieves equal distribution**
    - Generate 40+ assignments across 2-4 variants
    - Verify each variant's share is within ±5pp of ideal equal share
    - **Validates: Requirements 6.2**

  - [ ]* 6.4 Write property tests for reply pauses touchpoints (Property 30)
    - **Property 30: Reply pauses all pending touchpoints**
    - Generate enrollments with varying touchpoint states
    - Verify all subsequent pending touchpoints are paused on reply detection
    - **Validates: Requirements 14.3**

  - [ ]* 6.5 Write property tests for max follow-ups (Property 31)
    - **Property 31: Maximum 3 automated follow-ups then sequence complete**
    - Generate enrollments with varying follow-up counts
    - Verify status becomes sequence_complete after initial + 3 follow-ups
    - **Validates: Requirements 14.4**

  - [ ]* 6.6 Write property tests for failed touchpoint skip (Property 32)
    - **Property 32: Failed touchpoint is skipped, sequence continues**
    - Generate sequences with failing touchpoints at various positions
    - Verify failed touchpoints are skipped and next touchpoint proceeds
    - **Validates: Requirements 14.6**

- [x] 7. Discovery Pipeline implementation
  - [x] 7.1 Implement Discovery Pipeline (`app/core/discovery_pipeline.py`)
    - Implement DiscoveryPipeline class orchestrating multi-source discovery
    - Implement `run_discovery()` with 5-minute timeout per source
    - Implement `deduplicate_and_merge()` matching by domain or normalized company name
    - Implement `_normalize_company_name()` for deduplication matching
    - Implement `check_source_health()` with consecutive failure tracking (3 failures → suspend)
    - Implement suspension recovery with 1-hour backoff and permanent suspension after 3 recovery failures
    - Apply scoring threshold filtering (configurable, default 25)
    - Apply multi-source bonus (10 per additional source, max 30)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [ ]* 7.2 Write property tests for deduplication and multi-source bonus (Property 21)
    - **Property 21: Prospect deduplication merges records and awards multi-source bonus**
    - Generate prospect pairs matching by domain/name with varying source counts
    - Verify merge retains most recent values and bonus is 10 per additional source (max 30)
    - **Validates: Requirements 10.2**

  - [ ]* 7.3 Write property tests for score threshold filtering (Property 22)
    - **Property 22: Score threshold filtering**
    - Generate scored prospects with various thresholds
    - Verify only prospects at or above threshold are surfaced
    - **Validates: Requirements 10.3**

  - [ ]* 7.4 Write property tests for source suspension state machine (Property 23)
    - **Property 23: Source suspension state machine**
    - Generate sequences of successes and failures
    - Verify 3 consecutive failures → suspend, 3 recovery failures → permanently_suspended
    - **Validates: Requirements 10.5, 10.6**

- [x] 8. Checkpoint - Integration and pipeline services
  - Ensure all tests pass, ask the user if questions arise.

- [x] 9. Personalization Engine implementation
  - [x] 9.1 Implement Personalization Engine (`app/core/personalization_engine.py`)
    - Implement PersonalizationEngine class with LLM router and schema registry
    - Implement `generate_materials()` for cv, cover_letter, proposal, email types
    - Implement `_determine_tone()` based on contact seniority (C-suite/director/manager) with director default
    - Implement `_compute_quality_score()` as (fields_referenced / fields_available) × 100
    - Flag materials below quality score 40 as "low personalization" with 3 unused fields listed
    - Flag "seniority_unknown" when contact seniority is not available
    - Incorporate hooks (news, job postings, tech adoption) into LLM context
    - Handle sparse enrichment (< 3 fields) gracefully
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

  - [ ]* 9.2 Write property tests for personalization tone (Property 24)
    - **Property 24: Personalization tone is determined by seniority with director default**
    - Generate contacts with various/missing seniority levels
    - Verify correct tone mapping and director default with seniority_unknown flag
    - **Validates: Requirements 11.4, 11.7**

  - [ ]* 9.3 Write property tests for quality score and low-quality flagging (Property 25)
    - **Property 25: Personalization quality score and low-quality flagging**
    - Generate materials with varying field references
    - Verify score = (referenced / available) × 100 and flagging when < 40
    - **Validates: Requirements 11.5, 11.6**

- [x] 10. LLM Router implementation
  - [x] 10.1 Implement LLM Router (`app/integrations/llm_router.py`)
    - Implement LLMRouter class with provider routing (Anthropic Claude, OpenAI)
    - Implement `evaluate_relevance()` returning (score 0-100, reasoning max 500 chars)
    - Implement `generate_content()` for outreach material generation
    - Implement 7-day cache with hash-based invalidation (prospect description + profile hash)
    - Implement retry logic (3 attempts, 5-min intervals) for provider unavailability
    - Handle partial context when enrichment unavailable (flag as "partial_context")
    - Queue evaluation_pending when all retries exhausted and no cache available
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7_

  - [ ]* 10.2 Write property tests for LLM evaluation output constraints (Property 37)
    - **Property 37: LLM evaluation output constraints**
    - Generate mock LLM responses
    - Verify score is always integer in [0, 100] and reasoning ≤ 500 characters
    - **Validates: Requirements 17.1**

  - [ ]* 10.3 Write property tests for partial context handling (Property 38)
    - **Property 38: LLM evaluation proceeds with partial context when enrichment unavailable**
    - Generate prospects with missing/pending enrichment
    - Verify evaluation proceeds and result flagged as "partial_context"
    - **Validates: Requirements 17.3**

  - [ ]* 10.4 Write property tests for LLM cache validity (Property 39)
    - **Property 39: LLM cache validity**
    - Generate cache entries with various ages and hash states
    - Verify cache valid iff age < 7 days AND hash matches
    - **Validates: Requirements 17.5**

- [x] 11. Analytics Service implementation
  - [x] 11.1 Implement Analytics Service (`app/core/analytics_service.py`)
    - Implement AnalyticsService class with all funnel, A/B, and ROI computation
    - Implement `compute_funnel()` for stage-to-stage conversion rates (7/30/90 day periods)
    - Implement `compute_conversion_alerts()` for >20% drop below 30-day trailing average (1 alert/stage/day)
    - Implement `compute_ab_results()` with winner detection (2pp margin, 90% confidence) and inconclusive flagging (100 sends)
    - Implement `compute_channel_effectiveness()` with response/meeting/conversion rates and low-confidence indicator
    - Implement `compute_effort_metrics()` for monthly totals (discovered, sent, responses, outcomes)
    - Implement `attribute_outcome()` with earliest-source attribution
    - Handle insufficient data (< 5 records) with indicator and alert exclusion
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 6.3, 6.4, 6.6, 7.5, 15.1, 15.2, 15.3, 15.4, 15.5, 15.6, 15.7_

  - [ ]* 11.2 Write property tests for funnel metrics computation (Property 16)
    - **Property 16: Funnel metrics computation**
    - Generate pipeline records within time periods
    - Verify conversion rate = (exited_to_next / entered) × 100 with 1dp, drop-off computed correctly
    - **Validates: Requirements 9.1, 9.3**

  - [ ]* 11.3 Write property tests for average time in stage (Property 17)
    - **Property 17: Average time in stage computation**
    - Generate records with various entry/exit timestamps
    - Verify arithmetic mean of (exit - entry) in calendar days, rounded to 1dp
    - **Validates: Requirements 9.2**

  - [ ]* 11.4 Write property tests for conversion alerts (Property 18)
    - **Property 18: Conversion alert fires on significant drop**
    - Generate conversion rates and trailing averages
    - Verify alert fires when drop > 20%, exactly one per stage per day
    - **Validates: Requirements 9.4**

  - [ ]* 11.5 Write property tests for source attribution (Property 19)
    - **Property 19: Source attribution assigns earliest discovery source**
    - Generate multi-source prospects with various discovery dates
    - Verify attribution goes to earliest source with correct sequence/variant
    - **Validates: Requirements 9.5, 15.6**

  - [ ]* 11.6 Write property tests for insufficient data indicator (Property 20)
    - **Property 20: Insufficient data indicator for small samples**
    - Generate stages with fewer than 5 records
    - Verify "insufficient data" indicator and alert exclusion
    - **Validates: Requirements 9.6**

  - [ ]* 11.7 Write property tests for A/B winner detection (Property 11)
    - **Property 11: A/B winner detection requires 2pp margin with confidence**
    - Generate variant result sets with various reply rates
    - Verify winner flagged iff reply rate exceeds all others by ≥ 2pp with 90% confidence
    - **Validates: Requirements 6.4**

  - [ ]* 11.8 Write property tests for low response rate recommendation (Property 14)
    - **Property 14: Low response rate triggers revision recommendation**
    - Generate sequences with various send counts and response rates
    - Verify recommendation generated when ≥ 50 sends and < 2% response rate
    - **Validates: Requirements 7.6**

  - [ ]* 11.9 Write property tests for channel effectiveness rates (Property 34)
    - **Property 34: Channel effectiveness rates computed correctly**
    - Generate channel data with varying send/reply/meeting/outcome counts
    - Verify rate formulas and low-confidence indicator when < 10 prospects
    - **Validates: Requirements 15.3, 15.4**

  - [ ]* 11.10 Write property tests for monthly trend zero-fill (Property 35)
    - **Property 35: Monthly trend includes all 12 months with zero-fill**
    - Generate activity data with gaps
    - Verify exactly 12 entries with zero-fill for inactive months
    - **Validates: Requirements 15.2, 15.5**

- [x] 12. Checkpoint - All core and integration services
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Configuration Manager and integration health
  - [x] 13.1 Implement Config Manager (`app/core/config_manager.py`)
    - Implement ConfigManager class with credential validation (10s timeout test calls)
    - Implement `validate_credentials()` for all 5 integrations (Apollo, Lemlist, Adzuna, Gmail, LLM)
    - Implement `get_health()` returning IntegrationHealth with usage/quota tracking
    - Implement `check_quota()` blocking calls at 100% usage
    - Implement 80% warning threshold and 100% critical threshold alerting
    - Implement 15-minute usage data refresh interval
    - Preserve existing credentials on validation failure
    - Store credentials securely (environment variables or encrypted store)
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_

  - [ ]* 13.2 Write property tests for credential preservation (Property 40)
    - **Property 40: Credential preservation on validation failure**
    - Generate validation attempts with various failure modes
    - Verify previously stored credentials remain unchanged on failure
    - **Validates: Requirements 18.3**

  - [ ]* 13.3 Write property tests for quota threshold warnings and blocking (Property 41)
    - **Property 41: Quota threshold warnings and blocking**
    - Generate usage values relative to quotas
    - Verify warning at 80%+, blocking at 100%
    - **Validates: Requirements 18.5**

- [x] 14. WebSocket Manager and real-time infrastructure
  - [x] 14.1 Implement WebSocket Manager (`app/core/websocket_manager.py`)
    - Implement WebSocketManager class with Redis pub/sub for multi-worker broadcast
    - Implement `connect()` and `disconnect()` managing per-user connection lists
    - Implement `broadcast_pipeline_update()` publishing pipeline state changes
    - Implement `broadcast_notification()` for dashboard alerts and actions
    - Handle connection drops and cleanup gracefully
    - _Requirements: 8.4, 16.2, 16.6_

  - [ ]* 14.2 Write property tests for WebSocket reconnection backoff (Property 36)
    - **Property 36: WebSocket reconnection exponential backoff**
    - Generate reconnection attempt sequences (N attempts)
    - Verify delay = min(2^(N-1), 30) seconds, starting at 1s, capping at 30s
    - **Validates: Requirements 16.6**

- [x] 15. Pipeline status management and event handling
  - [x] 15.1 Implement pipeline status transitions and event handlers
    - Create `app/core/pipeline_manager.py` for pipeline state machine transitions
    - Implement reply detection advancing pipeline from "Sent" to "Replied"
    - Implement meeting-booked detection advancing to "Meeting Booked" from Sent or Replied
    - Implement Team-specific "Proposal Requested" transition on keyword detection
    - Wire pipeline changes to WebSocket broadcasts
    - Implement "Requires Action" aggregation (stale follow-ups 7+ days, failed sequences, enrichment errors)
    - _Requirements: 7.2, 7.3, 8.2, 13.5, 13.6_

  - [ ]* 15.2 Write property tests for pipeline advancement on reply (Property 12)
    - **Property 12: Non-auto-reply advances pipeline to Replied**
    - Generate reply events with various classifications (genuine, auto-reply, bounce, etc.)
    - Verify only genuine replies advance pipeline from Sent to Replied
    - **Validates: Requirements 7.2**

  - [ ]* 15.3 Write property tests for meeting signal pipeline advancement (Property 13)
    - **Property 13: Meeting signal advances pipeline regardless of current status**
    - Generate meeting signals with pipeline records in Sent or Replied states
    - Verify advancement to Meeting Booked from either state
    - **Validates: Requirements 7.3**

  - [ ]* 15.4 Write property tests for Requires Action items (Property 15)
    - **Property 15: Requires Action includes all actionable items**
    - Generate datasets with various stale/failed/error records
    - Verify all qualifying items appear in Requires Action section
    - **Validates: Requirements 8.2**

- [x] 16. Checkpoint - Backend services complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. FastAPI REST API routes
  - [x] 17.1 Implement API routes for discovery and prospects
    - Create `app/api/discovery.py` with POST /discovery/run, GET /prospects, GET /prospects/{id}
    - Create `app/api/enrichment.py` with GET /prospects/{id}/enrichment, POST /enrichment/refresh
    - Wire routes to DiscoveryPipeline, ApolloClient services
    - Include schema-driven route loading from SchemaRegistry
    - _Requirements: 10.1, 10.4, 1.1, 1.7_

  - [x] 17.2 Implement API routes for scoring and pipeline
    - Create `app/api/scoring.py` with GET /scores, PUT /settings/scoring-weights, POST /scores/recompute
    - Create `app/api/pipeline.py` with GET /pipeline, PATCH /pipeline/{id}/status, GET /pipeline/requires-action
    - Include tier filtering and beneficiary filtering
    - _Requirements: 4.3, 4.4, 8.2, 8.3_

  - [x] 17.3 Implement API routes for sequences and outreach
    - Create `app/api/sequences.py` with CRUD for sequences, POST /sequences/{id}/enroll, POST /sequences/{id}/promote-variant
    - Create `app/api/personalization.py` with POST /personalize/generate
    - Include batch enrollment endpoint with filter support
    - _Requirements: 5.1, 5.2, 5.4, 6.5, 11.1, 13.4_

  - [x] 17.4 Implement API routes for analytics and settings
    - Create `app/api/analytics.py` with GET /analytics/funnel, GET /analytics/ab-results, GET /analytics/channel-effectiveness, GET /analytics/effort, GET /analytics/trends
    - Create `app/api/settings.py` with GET/PUT /settings/integrations, POST /settings/integrations/validate
    - Include period selection (7/30/90 days) and beneficiary/opportunity type filters
    - _Requirements: 9.1, 9.3, 15.2, 15.7, 18.1, 18.2_

  - [x] 17.5 Implement WebSocket endpoint and connection management
    - Create `app/api/websocket.py` with WS /ws endpoint
    - Wire WebSocketManager for real-time pipeline updates and notifications
    - Implement authentication for WebSocket connections
    - _Requirements: 8.4, 16.2_

- [x] 18. Background workers (ARQ)
  - [x] 18.1 Implement enrichment and polling workers
    - Create `app/workers/enrichment_worker.py` for scheduled Apollo enrichment (30-day refresh)
    - Create `app/workers/polling_worker.py` for Lemlist response polling (5-min interval)
    - Create `app/workers/discovery_worker.py` for scheduled discovery runs (hourly/daily)
    - Wire workers to core services (ApolloClient, LemlistEngine, DiscoveryPipeline)
    - Implement ARQ task scheduling with configurable intervals
    - _Requirements: 1.7, 3.5, 7.1, 10.4, 14.1_

  - [x] 18.2 Implement analytics worker
    - Create `app/workers/analytics_worker.py` for daily funnel snapshots (02:00 UTC)
    - Implement hourly response rate computation
    - Implement conversion alert generation
    - Implement daily A/B metric updates
    - _Requirements: 9.1, 9.4, 7.5, 6.3_

  - [x] 18.3 Implement score recomputation worker
    - Create `app/workers/scoring_worker.py` for bulk score recomputation
    - Triggered when scoring weights change (recompute non-terminal prospects within 60s)
    - Triggered when enrichment data updates
    - Broadcast score changes via WebSocket
    - _Requirements: 4.4_

- [x] 19. Checkpoint - Backend fully wired
  - Ensure all tests pass, ask the user if questions arise.

- [x] 20. Frontend project setup (React + Next.js)
  - [x] 20.1 Initialize Next.js frontend project
    - Create `frontend/` directory with Next.js 14 (App Router)
    - Install dependencies: react, next, tailwindcss, websocket client, chart library (recharts)
    - Set up TypeScript configuration and ESLint
    - Create layout with responsive navigation (desktop/tablet/mobile)
    - Implement dark/light mode toggle with localStorage persistence and OS preference default
    - _Requirements: 16.1, 16.3, 16.5_

  - [x] 20.2 Implement WebSocket client and real-time state management
    - Create `frontend/lib/websocket.ts` with connection management
    - Implement exponential backoff reconnection (1s start, 30s cap)
    - Implement connection status indicator (connected/disconnected/reconnecting)
    - Implement state resynchronization on reconnect
    - Create React context for real-time updates across components
    - _Requirements: 16.2, 16.6_

  - [x] 20.3 Implement Dashboard view
    - Create `frontend/app/dashboard/page.tsx` as primary entry point
    - Implement pipeline counts by stage with real-time updates (< 10s reflect)
    - Implement 30-day conversion rates display
    - Implement top 5 highest-scored pending prospects
    - Implement "Requires Action" section (stale follow-ups, failed sequences, enrichment errors)
    - Implement "Hot Prospects" section (intent signals, sorted by strength then date, max 50)
    - Implement "Quick Actions" panel (enroll, approve, trigger discovery)
    - Implement beneficiary toggle (Consultant / Team)
    - Target < 2 second LCP on 10 Mbps+ connections
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 3.4_

  - [ ]* 20.4 Write property tests for Hot Prospects sorting (Property 5)
    - **Property 5: Hot Prospects sorted by strength then date, capped at 50**
    - Generate IntentSignal collections with various strengths and dates
    - Verify sorting (strong > moderate > weak, then date desc) and max 50 cap
    - **Validates: Requirements 3.4**

- [x] 21. Frontend Pipeline and Analytics views
  - [x] 21.1 Implement Pipeline view
    - Create `frontend/app/pipeline/page.tsx` with kanban-style pipeline board
    - Implement filters by beneficiary, opportunity type, and status
    - Implement real-time status updates via WebSocket
    - Implement pipeline record detail view with touchpoint history
    - Implement score tier badges and partial score indicators
    - Schema-driven pipeline states (columns derived from SchemaRegistry)
    - _Requirements: 8.3, 8.4, 4.5, 4.6, 12.1_

  - [x] 21.2 Implement Analytics views
    - Create `frontend/app/analytics/page.tsx` with conversion funnel visualization
    - Implement visual funnel chart with stage counts and drop-off percentages
    - Implement period selector (7/30/90 days) with opportunity type and beneficiary filters
    - Implement A/B test results display with winner/inconclusive badges
    - Implement channel effectiveness comparison view
    - Implement monthly trend chart (trailing 12 months with zero-fill)
    - Implement effort metrics display (discovered, sent, responses, outcomes)
    - Implement "insufficient data" indicators for small sample sizes
    - _Requirements: 9.1, 9.2, 9.3, 9.6, 6.3, 6.4, 6.6, 15.2, 15.3, 15.5, 15.7_

  - [x] 21.3 Implement Settings view
    - Create `frontend/app/settings/page.tsx` with integration management
    - Implement integration status cards (connected/disconnected/error) for all 5 integrations
    - Implement credential input forms with validation feedback (success/failure within 10s)
    - Implement usage/quota displays with warning (80%) and critical (100%) indicators
    - Implement scoring weight configuration form with sum=100 validation
    - Implement discovery schedule configuration (hourly/daily/manual per source)
    - Mask credentials after entry (never display in plaintext)
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 4.3_

- [x] 22. Frontend accessibility and responsiveness
  - [x] 22.1 Implement WCAG 2.1 AA compliance and responsive design
    - Add keyboard navigation to all interactive components
    - Add screen reader support with ARIA labels and landmarks
    - Ensure 44x44px minimum touch targets on mobile viewports
    - Implement responsive breakpoints: desktop (1200px+), tablet (768-1199px), mobile (320-767px)
    - Verify no horizontal scrolling at any viewport width
    - _Requirements: 16.3, 16.4_

- [x] 23. Multi-beneficiary and schema-driven wiring
  - [x] 23.1 Implement multi-beneficiary support and schema-driven routing
    - Wire frontend navigation from SchemaRegistry derive_navigation() output
    - Implement dynamic sub-tab generation per beneficiary per stage
    - Implement Team cold outreach pipeline (Drafted → Sent → Replied → Proposal Requested → Won → Lost)
    - Implement Team discovery with outreach criteria filtering (company size, tech stack, public sector)
    - Ensure Lemlist sequences are independently configurable per beneficiary
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6, 13.7, 12.2, 12.7_

- [x] 24. Checkpoint - Frontend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 25. End-to-end integration and remaining property tests
  - [x] 25.1 Implement end-to-end integration tests for discovery-to-outreach flow
    - Test complete flow: discovery → enrichment → scoring → sequence enrollment → response tracking
    - Test pipeline state transitions from discovery through outcome
    - Test WebSocket broadcast delivery on state changes
    - Test multi-source deduplication and merge with scoring
    - Mock all external APIs (Apollo, Lemlist, Adzuna, LLM providers)
    - _Requirements: 1.1, 4.1, 5.4, 7.2, 10.2_

  - [ ]* 25.2 Write property tests for time-to-outcome computation (Property 33)
    - **Property 33: Time-to-outcome computation**
    - Generate pipeline records with various discovery and outcome dates
    - Verify time-to-outcome = (outcome_date - discovery_date) in calendar days
    - **Validates: Requirements 15.1**

  - [ ]* 25.3 Write property tests for sequence auto-advance (Property 29)
    - **Property 29: Sequence auto-advance on no reply**
    - Generate enrollments with elapsed delay intervals and no replies
    - Verify next touchpoint is automatically sent
    - **Validates: Requirements 14.1**

- [x] 26. Final checkpoint - All tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation after logical groupings
- Property tests validate the 41 universal correctness properties from the design using Hypothesis
- Unit tests validate specific examples and edge cases
- All external API interactions use mocked responses in tests
- Backend uses Python FastAPI (async), PostgreSQL, Redis, ARQ workers
- Frontend uses React + Next.js with TypeScript and Tailwind CSS
- WebSocket infrastructure uses Redis pub/sub for multi-worker broadcast
- Hypothesis configured with `max_examples=100` per property test

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.4", "1.5", "1.6"] },
    { "id": 2, "tasks": ["1.3"] },
    { "id": 3, "tasks": ["2.1", "3.1"] },
    { "id": 4, "tasks": ["2.2", "2.3", "2.4", "3.2", "3.3", "3.4", "3.5"] },
    { "id": 5, "tasks": ["5.1", "6.1"] },
    { "id": 6, "tasks": ["5.2", "5.3", "5.4", "6.2", "6.3", "6.4", "6.5", "6.6"] },
    { "id": 7, "tasks": ["7.1", "9.1", "10.1"] },
    { "id": 8, "tasks": ["7.2", "7.3", "7.4", "9.2", "9.3", "10.2", "10.3", "10.4"] },
    { "id": 9, "tasks": ["11.1", "13.1"] },
    { "id": 10, "tasks": ["11.2", "11.3", "11.4", "11.5", "11.6", "11.7", "11.8", "11.9", "11.10", "13.2", "13.3"] },
    { "id": 11, "tasks": ["14.1", "15.1"] },
    { "id": 12, "tasks": ["14.2", "15.2", "15.3", "15.4"] },
    { "id": 13, "tasks": ["17.1", "17.2", "17.3", "17.4", "17.5"] },
    { "id": 14, "tasks": ["18.1", "18.2", "18.3"] },
    { "id": 15, "tasks": ["20.1"] },
    { "id": 16, "tasks": ["20.2", "20.3", "20.4"] },
    { "id": 17, "tasks": ["21.1", "21.2", "21.3"] },
    { "id": 18, "tasks": ["22.1", "23.1"] },
    { "id": 19, "tasks": ["25.1", "25.2", "25.3"] }
  ]
}
```
