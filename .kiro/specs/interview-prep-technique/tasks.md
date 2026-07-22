# Implementation Plan: Interview Prep Technique

## Overview

Implement a state-entry prepare technique (P8) that generates a grounded Interview_Prep_Pack when a pipeline record transitions into the Interview state. The implementation proceeds bottom-up: data models → database schema → schema registry extensions → core service logic → generation prompt → grounding integration → ARQ worker → API routes → pipeline manager hook → dashboard presentation → testing.

## Tasks

- [x] 1. Define domain models and data layer
  - [x] 1.1 Create `app/core/interview_prep_models.py` with all dataclasses and enums
    - Define `PackStatus` enum (generating, grounding, ready, ready_with_flags, failed)
    - Define `GapHandlingStrategy` enum (adjacent_experience, transferable_skill, learning_trajectory)
    - Define `STAR_Talking_Point` dataclass with competency, question, situation, task, action, result, source_asset_refs, is_gap_handled, gap_note
    - Define `Interview_Prep_Pack` dataclass with all fields (id, pipeline_record_id, beneficiary_id, opportunity_type_id, likely_questions, star_talking_points, company_briefing, questions_to_ask, status, omission_notes, grounding_flags, generation_duration_ms, created_at, updated_at)
    - Define `GenerationContext` dataclass with all context assembly fields
    - Define error classes: `InterviewPrepError`, `GenerationTimeoutError`, `DeadlineExceededError`, `PackValidationError`, `ContextAssemblyError`
    - _Requirements: 2.1, 2.2_

  - [x] 1.2 Create `app/models/interview_prep.py` with SQLAlchemy models
    - Define `InterviewPrepPack` SQLAlchemy model mapping to `interview_prep_packs` table
    - Define `InterviewPrepHistory` SQLAlchemy model mapping to `interview_prep_history` table
    - Include proper column types (UUID, JSONB, TIMESTAMPTZ, VARCHAR with constraints)
    - Add indexes: idx_interview_prep_record, idx_interview_prep_status, idx_interview_prep_beneficiary, idx_interview_prep_history_pack
    - _Requirements: 2.1, 3.2_

  - [x] 1.3 Create Alembic migration for interview prep tables
    - Create `interview_prep_packs` table with all columns and constraints
    - Create `interview_prep_history` table with foreign key to interview_prep_packs
    - Add CHECK constraints for status and trigger_reason columns
    - Add `superseded_by` self-referential FK on interview_prep_packs
    - _Requirements: 2.1, 3.2_

  - [x] 1.4 Write unit tests for domain model validation
    - Test enum membership and string values for PackStatus, GapHandlingStrategy
    - Test STAR_Talking_Point instantiation with valid/invalid data
    - Test Interview_Prep_Pack structural validation logic
    - _Requirements: 2.1_

- [x] 2. Extend Schema_Registry with state-entry technique support
  - [x] 2.1 Extend `PrepareTechnique` dataclass in `app/core/schema_registry.py`
    - Add `trigger` field (default "material_preparation", options: "material_preparation" | "state_entry")
    - Add `trigger_state` field (str | None, required when trigger == "state_entry")
    - Add `state_entry_techniques` list to OpportunityType dataclass
    - _Requirements: 3.1_

  - [x] 2.2 Implement `get_state_entry_techniques()` and validation in `app/core/schema_registry.py`
    - Implement `get_state_entry_techniques(opportunity_type_id, state)` that filters techniques by trigger=="state_entry" and trigger_state==state
    - Implement `_validate_state_entry_techniques()` that checks trigger_state exists in the opportunity type's pipeline_states and technique is declared in prepare_techniques
    - Raise `SchemaValidationError` on invalid configurations
    - Wire validation into existing `_validate()` method
    - _Requirements: 3.1_

  - [x] 2.3 Add `interview_preparation` technique to `config/schema.yaml`
    - Declare `interview_preparation` technique with trigger: state_entry, trigger_state: Interview
    - Configure inputs (opportunity_description, tailored_cv, tailored_cover_letter, enrichment_record, consultant_profiles, star_examples) and outputs (interview_prep_pack)
    - Set grounding_technique: standard_grounding
    - Add `state_entry_techniques: [interview_preparation]` to job_site and company opportunity types
    - _Requirements: 3.1_

  - [x] 2.4 Write property test for schema state-entry validation (Property 5)
    - **Property 5: Schema validation — technique attachable only to types with Interview state**
    - Generate random opportunity type configs with/without Interview in pipeline_states
    - Attach interview_preparation technique and verify: types WITH Interview state → accepted; types WITHOUT → SchemaValidationError raised
    - **Validates: Requirements 3.1**

  - [x] 2.5 Write unit tests for Schema_Registry state-entry extensions
    - Test get_state_entry_techniques returns correct techniques for Interview state
    - Test get_state_entry_techniques returns empty list for states with no techniques
    - Test validation rejects technique with trigger_state not in pipeline_states
    - _Requirements: 3.1_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement InterviewPrepService core logic
  - [x] 4.1 Create `app/core/interview_prep_service.py` with class skeleton
    - Initialize with LLMRouter, GroundingVerifier, SchemaRegistry, InterviewPrepRepository, EventPublisher dependencies
    - Set class constants: GENERATION_TIMEOUT=90.0, TOTAL_DEADLINE=120.0, MAX_RETRIES=2, MAX_QUESTIONS=15, MIN_QUESTIONS=8, STAR_COUNT=5, MAX_BRIEFING_WORDS=400, MAX_QUESTIONS_TO_ASK=6, MIN_QUESTIONS_TO_ASK=3
    - Define method signatures for generate_pack, assemble_context, _generate_via_llm, _validate_pack_structure, _ground_talking_points, regenerate_pack
    - _Requirements: 1.1, 2.1_

  - [x] 4.2 Implement `assemble_context()` method
    - Load opportunity description from pipeline_record → prospect
    - Load tailored_cv and tailored_cover_letter from submitted_materials
    - Load Enrichment_Record for the prospect (company data, intent signals, tech stack)
    - Load Consultant's profile assets (resume, cover_letter, consultant_profiles)
    - Load existing STAR example material from profile
    - If submitted materials unavailable, proceed with profile-only and populate omission_notes
    - Ensure opportunity_description and profile_assets always present (raise ContextAssemblyError if not)
    - _Requirements: 1.2, 1.3_

  - [x] 4.3 Implement `_validate_pack_structure()` method
    - Check likely_questions count in [8, 15]
    - Check star_talking_points count == 5
    - Check company_briefing word count <= 400
    - Check questions_to_ask count in [3, 6]
    - Check all STAR points reference at least one source_asset_ref
    - Return list of validation errors (empty = valid)
    - _Requirements: 2.1_

  - [x] 4.4 Create `app/core/interview_prep_prompts.py` with generation prompt template
    - Define INTERVIEW_PREP_GENERATION_PROMPT with placeholders for opportunity_description, profile_assets_text, submitted_materials_section, industry, employee_count, tech_stack, intent_signals, headquarters
    - Include structured JSON output format instructions
    - Include grounding constraint instructions (never fabricate, acknowledge gaps)
    - Include count requirements (8-15 questions, 5 STAR points, max 400 words briefing, 3-6 questions to ask)
    - _Requirements: 2.1, 2.2_

  - [x] 4.5 Implement `_generate_via_llm()` method
    - Build prompt from GenerationContext using the generation prompt template
    - Dispatch to LLM_Router with GENERATION evaluation type, timeout=90s
    - Parse JSON response into Interview_Prep_Pack dataclass
    - Validate pack structure; raise PackValidationError if invalid
    - Implement retry logic (up to MAX_RETRIES) on timeout or LLM errors
    - _Requirements: 1.1, 2.1_

  - [x] 4.6 Implement `_ground_talking_points()` method
    - Extract STAR talking point text from pack
    - Call Grounding_Verifier.verify_material() on talking points as Beneficiary-side claims
    - If all claims grounded: return pack unchanged
    - If ungrounded claims found: regenerate affected talking points ONCE with exclusion constraint
    - Re-verify regenerated points
    - Return pack with any remaining flags in grounding_flags field
    - _Requirements: 2.2, 2.3_

  - [x] 4.7 Implement `generate_pack()` orchestration method
    - Record start time for deadline enforcement
    - Call assemble_context() → GenerationContext
    - Store initial pack record with status=generating
    - Call _generate_via_llm() with deadline awareness
    - Update pack status to grounding
    - Call _ground_talking_points()
    - Update final status (ready or ready_with_flags based on grounding result)
    - Store completed pack, record generation_duration_ms
    - Publish WebSocket notification (pack_ready)
    - Handle DeadlineExceededError: abort, mark failed
    - Handle all errors with retry logic, mark failed after MAX_RETRIES exhausted
    - _Requirements: 1.1, 2.1, 2.3, 3.3_

  - [x] 4.8 Implement `regenerate_pack()` method
    - Reassemble context (may include new profile data)
    - Generate new pack following same flow as generate_pack
    - Mark previous pack with superseded_by pointing to new pack
    - Create interview_prep_history record with trigger_reason="manual_regenerate"
    - _Requirements: 3.2_

  - [x] 4.9 Write property test for pack structural invariants (Property 1)
    - **Property 1: Pack structural invariants**
    - Generate random Interview_Prep_Packs with varying counts and content lengths
    - Verify: _validate_pack_structure returns empty errors iff counts and word limits are within bounds
    - **Validates: Requirements 2.1**

  - [x] 4.10 Write property test for context assembly completeness (Property 2)
    - **Property 2: Context assembly completeness and graceful degradation**
    - Generate random pipeline records with varying presence/absence of CV, cover letter, enrichment, profile assets
    - Verify: context includes all available sources; omission_notes populated for each missing material; generation proceeds without submitted materials
    - **Validates: Requirements 1.2, 1.3**

  - [x] 4.11 Write property test for STAR grounding (Property 3)
    - **Property 3: STAR talking points grounded exclusively in profile assets**
    - Generate random profiles with known competencies + opportunity requirements with/without matches
    - Verify: every STAR point has non-empty source_asset_refs; gap-handled points have non-empty gap_note; non-gap points do not fabricate claims
    - **Validates: Requirements 2.2**

  - [x] 4.12 Write property test for grounding single regeneration (Property 4)
    - **Property 4: Grounding verification with single regeneration**
    - Mock Grounding_Verifier to return varying claim statuses (all grounded, some ungrounded, all ungrounded)
    - Verify: exactly one regeneration attempt when ungrounded claims found; no further regeneration after single attempt; remaining flags surfaced in grounding_flags
    - **Validates: Requirements 2.3**

  - [x] 4.13 Write property test for generation deadline (Property 6)
    - **Property 6: Generation deadline and failure non-blocking**
    - Mock generation with varying execution times, simulate timeouts
    - Verify: total execution never exceeds 120s; failures after 2 retries mark pack as failed; pipeline transitions never blocked by generation failure
    - **Validates: Requirements 1.1, 3.3**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement Interview Prep Repository
  - [x] 6.1 Create `app/core/interview_prep_repository.py` with persistence methods
    - Implement `save_pack(pack: Interview_Prep_Pack)` to insert/update interview_prep_packs
    - Implement `get_pack(pipeline_record_id: str) -> Interview_Prep_Pack | None`
    - Implement `get_pack_by_id(pack_id: str) -> Interview_Prep_Pack | None`
    - Implement `update_pack_status(pack_id: str, status: PackStatus, **kwargs)`
    - Implement `supersede_pack(old_pack_id: str, new_pack_id: str)`
    - Implement `save_history(pack_id: str, trigger_reason: str, context_hash: str)`
    - Implement `get_failed_packs(limit: int) -> list[Interview_Prep_Pack]` for Dashboard "Requires Action"
    - _Requirements: 2.1, 3.2, 3.3_

  - [x] 6.2 Write unit tests for InterviewPrepRepository
    - Test save and retrieval of pack with all fields
    - Test update_pack_status transitions correctly
    - Test supersede_pack marks old pack and links new
    - Test get_failed_packs returns only failed status packs
    - _Requirements: 2.1, 3.2_

- [x] 7. Implement Interview Prep Worker (ARQ background task)
  - [x] 7.1 Create `app/workers/interview_prep_worker.py` with ARQ tasks
    - Implement `process_interview_prep(ctx, pipeline_record_id)` that calls InterviewPrepService.generate_pack()
    - Enforce 120-second overall deadline with asyncio.timeout
    - On failure after MAX_RETRIES: mark pack as failed, surface in Requires Action
    - Return status dict with pack_id and status
    - Implement `regenerate_interview_prep(ctx, pipeline_record_id)` for on-demand regeneration
    - _Requirements: 1.1, 3.3_

  - [x] 7.2 Register interview prep tasks in `app/worker.py`
    - Add process_interview_prep and regenerate_interview_prep to ARQ worker functions list
    - Configure job timeout, retry settings, and queue name
    - _Requirements: 1.1_

  - [x] 7.3 Write unit tests for Interview Prep Worker
    - Test successful generation returns ready status with pack_id
    - Test deadline exceeded marks pack as failed
    - Test retry exhaustion surfaces failure correctly
    - _Requirements: 1.1, 3.3_

- [x] 8. Implement Pipeline Manager state-entry hook
  - [x] 8.1 Extend `app/core/pipeline_manager.py` with state-entry technique dispatch
    - Add `_dispatch_state_entry_techniques(record, new_status)` method
    - Query Schema_Registry for techniques triggered on entry to new_status for this opportunity type
    - Enqueue ARQ job for each matching technique
    - Call `_dispatch_state_entry_techniques` in `_transition()` after successful ADVANCED transition
    - Ensure dispatch is non-blocking (enqueue and return, don't await generation)
    - _Requirements: 1.1, 3.1_

  - [x] 8.2 Write unit tests for Pipeline Manager state-entry dispatch
    - Test Interview state entry enqueues interview_prep job
    - Test non-Interview state entry does not enqueue job
    - Test dispatch is non-blocking (pipeline transition completes immediately)
    - Test opportunity type without interview_preparation technique does not dispatch
    - _Requirements: 1.1, 3.1_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Implement API routes
  - [x] 10.1 Create `app/api/interview_prep.py` with FastAPI router
    - Implement `GET /{pipeline_record_id}` to retrieve Interview_Prep_Pack (returns 404 if no pack exists or still pending)
    - Implement `POST /{pipeline_record_id}/regenerate` to enqueue regeneration job (returns 202 Accepted)
    - Implement `GET /{pipeline_record_id}/status` to check current generation status
    - Add response models with proper serialization of JSONB fields
    - _Requirements: 3.2_

  - [x] 10.2 Register interview prep router in `app/main.py`
    - Import and include the interview_prep router with prefix="/interview-prep" and tags=["interview-prep"]
    - _Requirements: 3.2_

  - [x] 10.3 Write unit tests for API routes
    - Test GET returns pack when ready
    - Test GET returns 404 when no pack exists
    - Test POST regenerate returns 202 and enqueues job
    - Test GET status returns correct PackStatus values
    - _Requirements: 3.2_

- [x] 11. Dashboard integration
  - [x] 11.1 Extend pipeline record detail view with Interview_Prep_Pack presentation
    - Add interview_prep_pack field to pipeline record API response when pack exists
    - Include pack status, likely_questions, star_talking_points, company_briefing, questions_to_ask
    - Add regenerate action endpoint reference
    - _Requirements: 3.2_

  - [x] 11.2 Add failed pack surfacing to Dashboard "Requires Action" section
    - Extend existing Dashboard queries to include failed interview_prep_packs
    - Add WebSocket notification when pack generation fails after retries
    - Surface failure reason and pipeline_record reference for user action
    - _Requirements: 3.3_

  - [x] 11.3 Write unit tests for Dashboard interview prep integration
    - Test pack appears on pipeline record detail when ready
    - Test failed pack appears in "Requires Action" list
    - Test regenerate action is available on detail view
    - _Requirements: 3.2, 3.3_

- [x] 12. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Integration tests
  - [x] 13.1 Write end-to-end integration test for interview prep pipeline flow
    - Test: pipeline transition to Interview → ARQ job enqueued → InterviewPrepService.generate_pack called → pack stored → WebSocket notification sent
    - Mock LLM_Router to return valid pack JSON
    - Verify: pack in database with status=ready, notification published
    - _Requirements: 1.1, 2.1, 3.1_

  - [x] 13.2 Write integration test for grounding flow with regeneration
    - Mock LLM_Router to generate pack with fabricated STAR claim
    - Mock Grounding_Verifier to flag the claim as ungrounded
    - Verify: regeneration triggered once, re-verified, remaining flags stored in grounding_flags
    - _Requirements: 2.2, 2.3_

  - [x] 13.3 Write integration test for on-demand regeneration via API
    - POST regenerate → new pack created with fresh context → old pack superseded
    - Verify: history record created with trigger_reason="manual_regenerate"
    - Verify: new pack returned on subsequent GET
    - _Requirements: 3.2_

  - [x] 13.4 Write integration test for graceful degradation (missing materials)
    - Create pipeline record without submitted CV/cover letter
    - Trigger Interview state entry
    - Verify: pack generated from profile-only, omission_notes populated
    - _Requirements: 1.3_

  - [x] 13.5 Write integration test for failure handling and non-blocking guarantee
    - Mock LLM_Router to timeout on all attempts
    - Verify: pack marked failed after retries, appears in Requires Action
    - Verify: pipeline transition was not blocked (state is Interview regardless)
    - _Requirements: 1.1, 3.3_

- [x] 14. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document (Properties 1-6)
- Unit tests validate specific examples and edge cases
- The implementation language is Python with FastAPI, async/await, PostgreSQL, Redis, ARQ (as specified in the design)
- Integration tests use mocked LLM_Router to avoid external API calls during testing
- The Grounding_Verifier (P2) is an existing service — this feature integrates with it, not reimplements it

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "1.4", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3"] },
    { "id": 3, "tasks": ["2.4", "2.5", "4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4"] },
    { "id": 5, "tasks": ["4.5", "4.6"] },
    { "id": 6, "tasks": ["4.7", "4.8"] },
    { "id": 7, "tasks": ["4.9", "4.10", "4.11", "4.12", "4.13", "6.1"] },
    { "id": 8, "tasks": ["6.2", "7.1"] },
    { "id": 9, "tasks": ["7.2", "7.3", "8.1"] },
    { "id": 10, "tasks": ["8.2", "10.1"] },
    { "id": 11, "tasks": ["10.2", "10.3", "11.1"] },
    { "id": 12, "tasks": ["11.2", "11.3"] },
    { "id": 13, "tasks": ["13.1", "13.2", "13.3", "13.4", "13.5"] }
  ]
}
```
