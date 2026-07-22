# Implementation Plan: Capability Gap Analytics

## Overview

This plan implements the Capability Gap Analytics feature — extracting required capabilities from lost/rejected/low-tier opportunities via LLM, diffing against Beneficiary profiles, and producing prioritized gap heatmaps with blocked pipeline value. Implementation proceeds from database schema and normalization layer, through core gap computation, background worker, API routes, WebSocket integration, and finally wiring everything together.

## Tasks

- [x] 1. Database schema and data models
  - [x] 1.1 Create Alembic migration for gap analytics tables
    - Add 8 new tables: `canonical_capabilities`, `capability_synonyms`, `opportunity_extractions`, `extracted_capabilities`, `beneficiary_capabilities`, `gap_heatmaps`, `gap_heatmap_entries`, `gap_extraction_queue`, `gap_analysis_config`
    - Include all indexes, constraints, CHECK constraints, and UNIQUE constraints from the design
    - Reference existing `pipeline_records` table via foreign keys
    - _Requirements: 1.1, 1.2, 2.1, 2.2_

  - [x] 1.2 Create SQLAlchemy ORM models for gap analytics tables
    - Create `app/models/gap_analytics.py` with ORM models for all 8 tables
    - Define relationships (e.g., extraction → extracted_capabilities, heatmap → entries)
    - Add model exports to `app/models/__init__.py`
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 3.1_

- [x] 2. Capability Normalizer
  - [x] 2.1 Implement CapabilityNormalizer (`app/core/capability_normalizer.py`)
    - Implement `normalize()`: strip, lowercase, synonym lookup, self-canonical fallback
    - Implement `batch_normalize()`, `add_synonym()`, `is_known()`
    - Add a factory function to load synonym map from DB at startup
    - _Requirements: 1.2_

  - [x] 2.2 Write property test for synonym normalization convergence (Property 2)
    - **Property 2: Synonym normalization convergence**
    - Generate random synonym maps (multiple aliases → same canonical) and verify all aliases produce the same canonical string; verify normalization is idempotent
    - **Validates: Requirements 1.2**

- [x] 3. Gap Analyzer core — extraction and caching
  - [x] 3.1 Implement GapAnalyzer class scaffold and extraction (`app/core/gap_analyzer.py`)
    - Create GapAnalyzer class with constructor accepting config, llm_router, schema_registry, db_session, redis_client, ws_manager
    - Implement `extract_capabilities()`: check Redis cache → LLM extraction → normalize → store in DB and Redis
    - Implement `normalize_capability()` delegating to CapabilityNormalizer
    - Define all dataclasses: ExtractedCapability, GapEntry, GapHeatmap, ExtractionResult, OnDemandGapReport, LearningRecommendation, GapAnalysisConfig, enums (GapClassification, GapTrend, CapabilityLevel)
    - _Requirements: 1.1, 1.2_

  - [x] 3.2 Write property test for extraction caching idempotence (Property 3)
    - **Property 3: Extraction caching idempotence**
    - Mock LLM, extract once, extract again for same opportunity_id; assert cached=True and identical result without second LLM call
    - **Validates: Requirements 1.2**

- [x] 4. Gap Analyzer core — computation, ranking, and trends
  - [x] 4.1 Implement `compute_gaps()` and `classify_gap()`
    - Implement pure computation: diff demanded capabilities against profile set
    - Classify each gap as HARD (absent) or SOFT (junior/unevidenced)
    - Compute opportunity_count and blocked_pipeline_value per gap
    - _Requirements: 2.1, 2.2_

  - [x] 4.2 Implement `detect_single_blockers()` and single-blocker 2x weighting
    - For each opportunity, if exactly one required capability is unmet, flag it as single-blocker
    - Apply 2x weight to weighted_rank_score for single-blocker gaps
    - _Requirements: 2.3_

  - [x] 4.3 Implement `rank_gaps()` — sort descending by weighted_rank_score, truncate to top 25
    - _Requirements: 3.1_

  - [x] 4.4 Implement `compute_trend()` — diff current gaps against previous heatmap
    - Classify each gap as new/growing/shrinking/resolved
    - Append "resolved" entries from previous report not in current
    - _Requirements: 3.2_

  - [x] 4.5 Write property test for gap computation as set difference (Property 5)
    - **Property 5: Gap computation as set difference**
    - Generate random demanded capability sets and profile sets; verify gaps == demanded - profile
    - **Validates: Requirements 2.1**

  - [x] 4.6 Write property test for gap aggregation, classification, and single-blocker weighting (Property 6)
    - **Property 6: Gap aggregation, classification, and single-blocker weighting**
    - Generate random extracted capabilities from multiple opportunities with values; verify opportunity_count, blocked_pipeline_value, classification, is_single_blocker, and weighted_rank_score
    - **Validates: Requirements 2.2, 2.3**

  - [x] 4.7 Write property test for heatmap ranking sorted and capped (Property 7)
    - **Property 7: Heatmap ranking sorted and capped**
    - Generate random GapEntry lists (0–100 entries) with random scores; verify output sorted descending and length ≤ max_entries
    - **Validates: Requirements 3.1**

  - [x] 4.8 Write property test for trend diff classification (Property 8)
    - **Property 8: Trend diff classification**
    - Generate random pairs of gap entry lists; verify new/growing/shrinking/resolved annotations
    - **Validates: Requirements 3.2**

- [x] 5. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Gap Analyzer — nightly cycle orchestration
  - [x] 6.1 Implement opportunity eligibility selection
    - Fetch pipeline records with state IN ('rejected', 'lost') OR tier IN ('C-tier', 'D-tier') within analysis_window_days
    - Filter already-extracted opportunities (check opportunity_extractions table)
    - _Requirements: 1.1_

  - [x] 6.2 Implement batch cap enforcement with recency ordering
    - Select top N (max_extractions_per_cycle) by recency from eligible unextracted opportunities
    - Insert remainder into gap_extraction_queue with priority_score = timestamp rank
    - _Requirements: 1.3_

  - [x] 6.3 Implement `run_nightly_cycle()` full orchestration
    - Wire together: eligibility → filter → batch cap → extract loop → compute gaps for each beneficiary → rank → trend → store heatmap → notify via WebSocket
    - Per-opportunity transaction for partial progress preservation
    - Graceful degradation if LLM unavailable (use cached extractions only)
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.2, 3.5_

  - [x] 6.4 Write property test for opportunity eligibility selection (Property 1)
    - **Property 1: Opportunity eligibility selection**
    - Generate random pipeline records with varied states, tiers, timestamps; verify selection returns exactly eligible records
    - **Validates: Requirements 1.1**

  - [x] 6.5 Write property test for batch cap enforcement with recency ordering (Property 4)
    - **Property 4: Batch cap enforcement with recency ordering**
    - Generate N eligible opportunities with cap C < N; verify exactly C most-recent are processed and N-C are carried forward
    - **Validates: Requirements 1.3**

- [x] 7. Gap Analytics Worker
  - [x] 7.1 Implement ARQ worker task (`app/workers/gap_worker.py`)
    - Create `run_gap_analysis_cycle` ARQ task function
    - Schedule at 02:30 UTC (after existing run_analytics_daily at 02:00)
    - Configure `unique=True` to prevent concurrent execution
    - Instantiate GapAnalyzer with shared resources from ARQ context
    - Return summary dict with extracted, carried_forward, heatmaps_generated, duration_seconds
    - _Requirements: 1.1, 1.3_

  - [x] 7.2 Write unit tests for gap worker
    - Test worker instantiation and GapAnalyzer delegation
    - Test error handling and logging on cycle failure
    - _Requirements: 1.1, 1.3_

- [x] 8. Gap Analytics API Routes
  - [x] 8.1 Implement API routes (`app/api/gap_routes.py`)
    - `GET /api/gap-analysis/heatmap/{beneficiary_id}` — return latest heatmap, support opportunity_type filter
    - `POST /api/gap-analysis/on-demand` — trigger on-demand analysis with 120s timeout
    - `GET /api/gap-analysis/recommendation/{capability_name}` — LLM learning recommendation
    - `GET /api/gap-analysis/heatmap/{beneficiary_id}/history` — historical heatmap summaries
    - Define Pydantic request/response models (HeatmapResponse, OnDemandRequest, OnDemandResponse, etc.)
    - _Requirements: 3.1, 3.3, 3.4_

  - [x] 8.2 Implement on-demand analysis in GapAnalyzer (`analyze_on_demand`)
    - Load opportunity text (from DB by pipeline_record_id or fetch from URL)
    - Extract → normalize → load consultant profile → diff → classify → report
    - Enforce 120s timeout via asyncio.wait_for
    - _Requirements: 3.4_

  - [x] 8.3 Implement learning recommendation generation (`generate_learning_recommendation`)
    - Call LLM_Router with capability context
    - Return resources, effort estimate, advisory label
    - _Requirements: 3.3_

  - [x] 8.4 Write unit tests for API routes
    - Test heatmap retrieval (found/not found)
    - Test on-demand validation (must provide URL or ID, not both)
    - Test recommendation response structure and advisory labeling
    - _Requirements: 3.1, 3.3, 3.4_

- [x] 9. WebSocket integration
  - [x] 9.1 Extend WebSocketManager with heatmap notification
    - Add `broadcast_heatmap_available()` method to existing `app/core/websocket_manager.py`
    - Publish to Redis pub/sub channel "gap_updates"
    - Message payload: `{"type": "gap_heatmap_available", "beneficiary_id": ..., "heatmap_id": ..., "generated_at": ...}`
    - _Requirements: 3.5_

  - [x] 9.2 Write unit test for WebSocket heatmap notification
    - Verify broadcast publishes correct payload to Redis channel
    - Verify connected clients receive the notification
    - _Requirements: 3.5_

- [x] 10. Error handling and custom exceptions
  - [x] 10.1 Implement error classes and graceful degradation
    - Create `GapAnalysisError`, `ExtractionError`, `NormalizationError`, `OnDemandTimeoutError` in `app/core/gap_analyzer.py` or dedicated errors module
    - Implement retry logic for LLM failures (3 retries with backoff for timeout, 5 for rate limit)
    - Implement graceful degradation: LLM unavailable → use cached extractions; empty synonym table → self-canonical names
    - _Requirements: 1.1, 1.2, 1.3, 3.4_

- [x] 11. Integration wiring and route registration
  - [x] 11.1 Register gap routes in FastAPI app
    - Include `gap_routes.router` in main app router
    - Wire GapAnalyzer dependencies (config, LLM router, schema registry, DB session, Redis, WS manager) via FastAPI dependency injection
    - Add gap worker to ARQ cron schedule in worker settings
    - _Requirements: 3.1, 3.4, 3.5_

  - [x] 11.2 Write integration tests for full nightly cycle
    - Mock LLM_Router, use test DB
    - Verify: extraction → normalization → gap computation → heatmap storage → WebSocket notification
    - Verify carry-forward queue populated when batch exceeds cap
    - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 3.2, 3.5_

  - [x] 11.3 Write integration test for on-demand analysis
    - Mock LLM_Router, verify response within timeout budget
    - Test error cases: URL fetch failure (422), consultant not found (404), text too short (422)
    - _Requirements: 3.4_

- [x] 12. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The design uses Python with FastAPI, PostgreSQL, Redis, ARQ, Hypothesis, and pytest

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "3.1"] },
    { "id": 3, "tasks": ["2.2", "3.2", "4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4"] },
    { "id": 5, "tasks": ["4.5", "4.6", "4.7", "4.8"] },
    { "id": 6, "tasks": ["6.1", "6.2"] },
    { "id": 7, "tasks": ["6.3", "6.4", "6.5"] },
    { "id": 8, "tasks": ["7.1", "8.1", "9.1", "10.1"] },
    { "id": 9, "tasks": ["7.2", "8.2", "8.3", "9.2"] },
    { "id": 10, "tasks": ["8.4", "11.1"] },
    { "id": 11, "tasks": ["11.2", "11.3"] }
  ]
}
```
