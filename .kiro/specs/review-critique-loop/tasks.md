# Implementation Plan: Review Critique Loop

## Overview

Implement a fresh-context LLM critique pass for all generated outreach materials. The Review_Service sits between the Personalization_Engine's material generation and claim-grounding-verification, dispatching structured critiques via the LLM_Router and applying machine-applicable edits with bounded cycle control. Implementation proceeds bottom-up: domain models → schema extensions → LLM routing → core service logic → persistence → background worker → dashboard integration → testing.

## Tasks

- [x] 1. Define domain models and enums
  - [x] 1.1 Create `app/core/review_models.py` with all enums and dataclasses
    - Define `ReviewStatus`, `EditReason`, `EditSkipReason`, `CritiqueCategory` enums
    - Define `StructuredEdit`, `NarrativeFinding`, `CritiqueResponse`, `EditOutcome`, `CycleLog`, `ReasoningLog`, `ReviewResult`, `DraftMaterial` dataclasses
    - Define `ReviewLLMError`, `ReviewTimeoutError`, `CritiqueParseError` exception classes
    - _Requirements: 2.1, 2.2, 3.2, 3.3_

  - [x] 1.2 Write unit tests for domain model validation
    - Test enum membership and string values
    - Test dataclass instantiation with valid/invalid data
    - Test CritiqueResponse requires all four category keys
    - _Requirements: 1.4, 2.1_

- [x] 2. Extend Schema_Registry with review techniques
  - [x] 2.1 Add `ReviewTechnique` dataclass and parsing to `app/core/schema_registry.py`
    - Add `ReviewTechnique` dataclass with fields: id, service_class, description, critique_categories, max_review_cycles
    - Extend `PrepareTechnique` dataclass with optional `review_technique: str | None` field
    - Add `_parse_review_techniques()` to parse the new YAML section into `ReviewTechnique` instances
    - Add `get_review_technique()` and `get_review_technique_for_prepare()` lookup methods
    - _Requirements: 4.1, 4.2_

  - [x] 2.2 Add cross-reference validation to Schema_Registry
    - Implement `_validate_review_technique_references()` that checks every `prepare_technique.review_technique` reference resolves to a declared review technique id
    - Raise `SchemaValidationError` with descriptive message on dangling reference, including the prepare_technique id and invalid reference
    - Wire validation into existing `_validate()` method
    - _Requirements: 4.3_

  - [x] 2.3 Add `review_techniques` section to `config/schema.yaml`
    - Add `standard_material_review` technique (max_cycles=2, all 4 categories)
    - Add `email_review` technique (max_cycles=1, all 4 categories)
    - Add `review_technique` field to existing prepare techniques (cv_and_cover_letter, cold_email_composition, proposal_composition)
    - _Requirements: 4.1, 4.2_

  - [x] 2.4 Write property test for schema cross-reference validation (Property 9)
    - **Property 9: Schema validation rejects dangling review_technique references**
    - Generate random schema configs with valid and invalid review_technique references
    - Verify invalid references always raise SchemaValidationError with correct identifiers
    - **Validates: Requirement 4, AC 3**

  - [x] 2.5 Write unit tests for Schema_Registry review technique parsing
    - Test valid YAML parsing produces correct ReviewTechnique instances
    - Test missing review_technique field on prepare technique results in None
    - Test get_review_technique_for_prepare returns correct config or None
    - _Requirements: 4.1, 4.2_

- [x] 3. Extend LLM_Router with CRITIQUE and REVISION evaluation types
  - [x] 3.1 Add CRITIQUE and REVISION to `EvaluationType` enum in `app/core/llm_router.py`
    - Add `CRITIQUE = "critique"` and `REVISION = "revision"` enum values
    - Add LLM configuration entries for both evaluation types (model, temperature, max_tokens)
    - _Requirements: 1.1, 2.5_

  - [x] 3.2 Implement `dispatch_critique()` and `dispatch_revision()` methods on LLM_Router
    - `dispatch_critique(prompt, timeout=60.0)` → returns raw JSON dict for parsing
    - `dispatch_revision(prompt, timeout=60.0)` → returns revised material text as string
    - Both methods use the appropriate EvaluationType config for model selection
    - Raise `APITimeoutError` on timeout
    - _Requirements: 1.1, 2.5_

  - [x] 3.3 Write unit tests for LLM_Router critique/revision dispatch
    - Test dispatch_critique returns parsed JSON on success
    - Test dispatch_revision returns string on success
    - Test timeout raises APITimeoutError
    - _Requirements: 1.1, 2.5_

- [x] 4. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement Review_Service core logic
  - [x] 5.1 Create `app/core/review_service.py` with `ReviewService` class skeleton
    - Initialize with LLM_Router, SchemaRegistry, ReviewRepository, PersonalizationEngine dependencies
    - Set class constants: CRITIQUE_TIMEOUT=60.0, MAX_RETRIES=2, DISPATCH_DEADLINE=10.0, BATCH_CONCURRENCY=3
    - Create asyncio.Semaphore for concurrency control
    - Implement `review_material()` method signature with cycle loop structure
    - _Requirements: 1.1, 3.1, 3.5_

  - [x] 5.2 Implement `_build_fresh_context_prompt()` method
    - Construct critique prompt containing ONLY: draft material text (XML-tagged), opportunity description, Enrichment_Record (firmographics, technographics, Intent_Signals, contact seniority), and Beneficiary profile assets
    - Explicitly exclude drafting pass conversation history, prompt template, and reasoning
    - Include structured output format instructions (JSON schema for CritiqueResponse)
    - Instruct reviewer to report on all four categories even when no issues found
    - _Requirements: 1.2, 1.3, 1.4_

  - [x] 5.3 Implement `_dispatch_critique()` with retry logic
    - Call `llm_router.dispatch_critique()` with 60-second timeout
    - On timeout or error, retry up to 2 additional times (3 total attempts)
    - Parse JSON response into `CritiqueResponse` dataclass
    - On parse failure, retry (counts toward retry limit)
    - After all retries exhausted, raise `ReviewLLMError`
    - _Requirements: 1.1, 1.5_

  - [x] 5.4 Implement `_apply_structured_edits()` method
    - For each StructuredEdit, count occurrences of `old_string` in current material text
    - If exactly 1 match: check for ungrounded content, then apply replacement
    - If 0 or >1 matches: skip with `AMBIGUOUS_OR_STALE_TARGET` reason
    - If edit introduces content not in beneficiary assets: discard with `UNGROUNDED_SUGGESTION`
    - Apply edits sequentially so each edit operates on the running (modified) text
    - Return tuple of (revised_text, list[EditOutcome])
    - _Requirements: 2.3, 2.4_

  - [x] 5.5 Implement `_dispatch_narrative_revision()` method
    - Build revision prompt containing current material text and all Narrative_Findings
    - Instruct LLM to revise ONLY flagged passages, preserving all other content verbatim
    - Call `llm_router.dispatch_revision()` with 60-second timeout
    - On failure after retries, return original material (graceful degradation)
    - _Requirements: 2.5_

  - [x] 5.6 Implement `review_material()` orchestration with cycle control
    - Look up review technique config via SchemaRegistry
    - Execute 1..max_review_cycles iterations
    - Each cycle: dispatch critique → apply structured edits → dispatch narrative revision (if findings) → recompute quality score → record CycleLog
    - After all cycles: assemble ReasoningLog, determine final ReviewStatus, persist to database
    - Handle graceful degradation: mark "unreviewed" on total failure, surface in Dashboard
    - _Requirements: 3.1, 3.2, 3.3_

  - [x] 5.7 Implement `review_batch()` with semaphore-bounded concurrency
    - Create asyncio tasks for each material wrapped in `_review_with_semaphore()`
    - `_review_with_semaphore()` acquires semaphore before calling `review_material()`
    - Use `asyncio.gather()` to await all tasks
    - Ensure at most BATCH_CONCURRENCY (3) critique requests are in-flight simultaneously
    - _Requirements: 3.5_

  - [x] 5.8 Write property test for structured edit application (Property 1)
    - **Property 1: Structured edit applies if and only if old_string matches exactly once**
    - Generate random material texts and random substrings as old_string
    - Verify: exactly 1 match → edit applied; 0 or >1 matches → edit skipped with correct reason
    - **Validates: Requirement 2, AC 3**

  - [x] 5.9 Write property test for ungrounded filtering (Property 2)
    - **Property 2: Ungrounded suggestions are always discarded**
    - Generate random edits with new_string content, random beneficiary asset sets
    - Verify: edits introducing content not in assets are always discarded with correct reason
    - **Validates: Requirement 2, AC 4**

  - [x] 5.10 Write property test for cycle count bounds (Property 3)
    - **Property 3: Review cycles bounded by schema configuration**
    - Generate random max_review_cycles (1-3), mock LLM responses
    - Verify: total cycles executed never exceeds max_review_cycles and never exceeds 3
    - **Validates: Requirement 3, AC 1**

  - [x] 5.11 Write property test for category completeness (Property 4)
    - **Property 4: All four critique categories are always present in response**
    - Generate random CritiqueResponse objects
    - Verify: narrative_findings always contains all four CritiqueCategory keys
    - **Validates: Requirement 1, AC 4**

  - [x] 5.12 Write property test for batch concurrency (Property 5)
    - **Property 5: Batch concurrency never exceeds 3 concurrent critiques**
    - Generate random batch sizes (1-50), track concurrent execution via counter
    - Verify: peak concurrency never exceeds BATCH_CONCURRENCY (3)
    - **Validates: Requirement 3, AC 5**

  - [x] 5.13 Write property test for graceful degradation (Property 6)
    - **Property 6: Failed critique degrades gracefully to "unreviewed"**
    - Simulate LLM failures (timeout, error, malformed JSON) exhausting all retries
    - Verify: material marked "unreviewed", proceeds to post-prepare state
    - **Validates: Requirement 1, AC 5**

  - [x] 5.14 Write property test for quality score recomputation (Property 7)
    - **Property 7: Quality score is recomputed after each cycle**
    - Generate random edit applications, mock quality score formula
    - Verify: CycleLog always records quality_score_before and quality_score_after with recomputed values
    - **Validates: Requirement 3, AC 2**

  - [x] 5.15 Write property test for fresh context exclusion (Property 8)
    - **Property 8: Fresh context excludes drafting pass artifacts**
    - Generate random drafting conversation histories and prompt templates
    - Verify: built prompt never contains drafting conversation, prompt template, or reasoning chain
    - **Validates: Requirement 1, AC 2**

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Create PostgreSQL schema migration
  - [x] 7.1 Create Alembic migration for review tables
    - Create `review_reasoning_logs` table with columns: id (UUID PK), material_id, pipeline_record_id (FK to pipeline_records), prepare_technique_id, review_technique_id, total_cycles_executed, max_cycles_configured, final_review_status, started_at, completed_at, created_at
    - Create `review_cycle_details` table with columns: id (UUID PK), reasoning_log_id (FK to review_reasoning_logs ON DELETE CASCADE), cycle_number, edits_applied, edits_skipped, edits_discarded, narrative_findings (JSONB), quality_score_before, quality_score_after, duration_ms, skipped_edits_detail (JSONB), discarded_edits_detail (JSONB), created_at
    - Add UNIQUE constraint on (reasoning_log_id, cycle_number)
    - Add indexes: idx_review_logs_pipeline, idx_review_logs_status
    - _Requirements: 3.2_

  - [x] 7.2 Create `app/repositories/review_repository.py` with persistence methods
    - Implement `save_reasoning_log(log: ReasoningLog)` to insert into review_reasoning_logs and review_cycle_details
    - Implement `get_reasoning_log(material_id: str) -> ReasoningLog | None`
    - Implement `get_unreviewed_materials(limit: int) -> list[dict]` for Dashboard queries
    - Implement `mark_unreviewed(material_id: str)` for graceful degradation path
    - _Requirements: 3.2, 3.4_

  - [x] 7.3 Write unit tests for ReviewRepository
    - Test save and retrieval of ReasoningLog with multiple CycleLogs
    - Test mark_unreviewed updates status correctly
    - Test get_unreviewed_materials returns correct records
    - _Requirements: 3.2_

- [x] 8. Implement Review Worker (ARQ background task)
  - [x] 8.1 Create `app/workers/review_worker.py` with ARQ task registration
    - Implement `ReviewWorker` class with BATCH_SIZE=10, CONCURRENCY_LIMIT=3
    - Implement `process_review_queue(ctx)` that fetches pending reviews and calls `review_service.review_batch()`
    - Implement `_fetch_pending_reviews(limit)` to query pending materials
    - Register as ARQ task with appropriate schedule/trigger
    - _Requirements: 3.5_

  - [x] 8.2 Write unit tests for Review Worker
    - Test batch processing respects BATCH_SIZE limit
    - Test worker returns correct summary counts (reviewed, unreviewed, failed)
    - Test empty queue returns early with processed=0
    - _Requirements: 3.5_

- [x] 9. Dashboard integration
  - [x] 9.1 Add review status display to pipeline record detail view
    - Extend pipeline record API response with `review_status` and `edits_applied_count` fields
    - Query review_reasoning_logs for the pipeline record's review data
    - _Requirements: 3.4_

  - [x] 9.2 Add "Requires Action" notification for unreviewed materials
    - Add endpoint or extend existing Dashboard query to surface materials with `final_review_status = 'unreviewed'`
    - Broadcast WebSocket notification when a material is marked unreviewed
    - _Requirements: 1.5, 3.4_

  - [x] 9.3 Write unit tests for Dashboard review status endpoints
    - Test review status is included in pipeline record response
    - Test unreviewed materials appear in "Requires Action" list
    - _Requirements: 3.4_

- [x] 10. Wire Review_Service into prepare pipeline
  - [x] 10.1 Integrate Review_Service call into the prepare pipeline after material generation
    - After Personalization_Engine produces DraftMaterial, check Schema_Registry for review_technique
    - If review_technique is configured: call `review_service.review_material()` and pass reviewed material downstream
    - If review_technique is absent: skip review, pass material directly to next pipeline stage
    - Ensure dispatch occurs within 10 seconds of draft completion (DISPATCH_DEADLINE)
    - _Requirements: 1.1, 4.2_

  - [x] 10.2 Write property test for dispatch timing (Property 10)
    - **Property 10: Dispatch occurs within 10 seconds of draft completion**
    - Generate random draft completion timestamps, measure dispatch time
    - Verify: first critique dispatch always occurs within 10 seconds
    - **Validates: Requirement 1, AC 1**

  - [x] 10.3 Write property test for review status pipeline transition (Property 11)
    - **Property 11: Review status correctly transitions pipeline state**
    - Generate random review outcomes (success, failure, degradation)
    - Verify: material always transitions to post-prepare state with correct status enum value
    - **Validates: Requirement 3, AC 3**

  - [x] 10.4 Write property test for narrative revision targeting (Property 12)
    - **Property 12: Narrative revision targets only flagged passages**
    - Generate random materials with narrative findings pointing to specific passages
    - Verify: revision prompt instructs modification of only flagged passages
    - **Validates: Requirement 2, AC 5**

- [x] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 12. Integration tests
  - [x] 12.1 Write end-to-end integration test for review pipeline flow
    - Test: PersonalizationEngine → ReviewService → pipeline state transition
    - Mock LLM_Router to return valid CritiqueResponse
    - Verify: material proceeds with "reviewed" status, reasoning_log persisted
    - _Requirements: 1.1, 3.3_

  - [x] 12.2 Write integration test for batch processing with concurrency
    - Submit 15 materials for review with mocked LLM (add artificial delay)
    - Verify: max 3 concurrent via timing assertions (batch of 15 takes ≥5× single critique time)
    - _Requirements: 3.5_

  - [x] 12.3 Write integration test for graceful degradation and Dashboard notification
    - Mock LLM_Router to fail all attempts for a material
    - Verify: material marked "unreviewed", appears in Dashboard "Requires Action" query
    - _Requirements: 1.5, 3.4_

- [x] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 12 universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation language is Python (as specified in the design document)
- Integration tests use mocked LLM_Router to avoid external API calls during testing

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "3.1"] },
    { "id": 3, "tasks": ["2.4", "2.5", "3.2"] },
    { "id": 4, "tasks": ["3.3", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "5.5"] },
    { "id": 6, "tasks": ["5.6", "5.7"] },
    { "id": 7, "tasks": ["5.8", "5.9", "5.10", "5.11", "5.12", "5.13", "5.14", "5.15"] },
    { "id": 8, "tasks": ["7.1"] },
    { "id": 9, "tasks": ["7.2", "8.1"] },
    { "id": 10, "tasks": ["7.3", "8.2", "9.1"] },
    { "id": 11, "tasks": ["9.2", "9.3", "10.1"] },
    { "id": 12, "tasks": ["10.2", "10.3", "10.4"] },
    { "id": 13, "tasks": ["12.1", "12.2", "12.3"] }
  ]
}
```
