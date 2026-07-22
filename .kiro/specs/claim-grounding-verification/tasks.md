# Implementation Plan: Claim Grounding Verification

## Overview

This plan implements the Claim Grounding Verification feature (P2), which adds a deterministic truthfulness gate to the prepare pipeline. The implementation follows incremental steps: domain models → database schema → core verification logic → LLM integration → pipeline gate → resolution paths → analytics → API endpoints → dashboard integration → background workers.

**Dependency:** This feature requires the review-critique-loop (P1) feature to be implemented first, as the Grounding_Verifier runs AFTER the Review_Service in the pipeline (Personalization_Engine → Review_Service P1 → Grounding_Verifier P2 → post-prepare state).

## Tasks

- [x] 1. Domain models, enums, and error classes
  - [x] 1.1 Create domain models and enums in `app/core/grounding_verifier.py`
    - Define `GroundingStatus`, `ClaimCategory`, `MaterialGroundingStatus`, `ResolutionPath` enums
    - Define `SourcePointer`, `Claim`, `GroundingReport`, `GroundingResult` dataclasses
    - All enum values must match the design exactly (e.g., `grounded`, `partially_grounded`, `ungrounded`)
    - _Requirements: 1.2, 2.1, 2.3, 3.1_

  - [x] 1.2 Create error hierarchy in `app/core/grounding_errors.py`
    - Define `GroundingError`, `ExtractionError`, `ExtractionTimeoutError`, `ExtractionParseError`, `VerificationTimeoutError`
    - Each error class must carry `material_id` and `retryable` flag
    - `ExtractionError` must track `attempts` count
    - _Requirements: 1.4_

  - [x] 1.3 Create `GroundingTechnique` dataclass and extend `PrepareTechnique` in Schema_Registry
    - Add `GroundingTechnique` dataclass with fields: `id`, `service_class`, `description`, `claim_categories`, `extraction_timeout_seconds`, `verification_timeout_seconds`, `max_retries`
    - Add optional `grounding_technique: str | None` field to `PrepareTechnique` dataclass
    - Add `_validate_grounding_technique_references()` method that raises `SchemaValidationError` on dangling references
    - Add `get_grounding_technique()` and `get_grounding_technique_for_prepare()` lookup methods
    - _Requirements: 1.1, 1.2_

- [x] 2. Database schema and repository layer
  - [x] 2.1 Create Alembic migration for grounding tables
    - Create `grounding_reports` table with columns: `id`, `material_id`, `pipeline_record_id`, `prepare_technique_id`, `grounding_technique_id`, `total_claims`, `grounded_count`, `partially_grounded_count`, `ungrounded_count`, `material_grounding_status`, `extraction_duration_ms`, `verification_duration_ms`, `created_at`, `updated_at`
    - Create `grounding_claims` table with columns: `id`, `grounding_report_id`, `category`, `claim_text`, `source_span`, `source_span_start`, `source_span_end`, `grounding_status`, `is_prospect_side`, `source_asset_type`, `source_asset_id`, `source_passage`, `discrepancy`, `created_at`, `updated_at`
    - Create `grounding_resolutions` table with columns: `id`, `grounding_report_id`, `claim_id`, `resolution_path`, `resolved_by`, `resolution_detail` (JSONB), `re_verification_status`, `re_verification_duration_ms`, `resolved_at`
    - Create `grounding_analytics_weekly` table with columns: `id`, `prepare_technique_id`, `week_start`, `week_end`, `total_claims_extracted`, `grounded_claims`, `partially_grounded_claims`, `ungrounded_claims`, `ungrounded_rate`, `materials_verified`, `materials_blocked`, `created_at` with UNIQUE constraint on `(prepare_technique_id, week_start)`
    - Add all indexes specified in the design (composite index on `prepare_technique_id, created_at` for analytics queries)
    - _Requirements: 2.4, 3.1, 3.3, 4.2_

  - [x] 2.2 Create `GroundingRepository` in `app/repositories/grounding_repository.py`
    - Implement `store_grounding_report(report: GroundingReport)` — inserts report + claims in a transaction
    - Implement `get_latest_grounding_report(pipeline_record_id: str) -> GroundingReport | None`
    - Implement `update_grounding_report(report: GroundingReport)` — updates counts and claim statuses
    - Implement `store_resolution(resolution)` — inserts resolution record
    - Implement `get_pending_verifications(limit: int)` — fetches unverified materials for batch worker
    - Implement `get_reports_for_analytics(technique_id: str, week_start: date, week_end: date)` — for analytics aggregation
    - _Requirements: 2.4, 3.3_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. LLM_Router extension and extraction prompts
  - [x] 4.1 Extend `LLM_Router` with EXTRACTION evaluation type
    - Add `EXTRACTION = "extraction"` to `EvaluationType` enum
    - Implement `dispatch_extraction(prompt: str, timeout: float = 60.0) -> dict` method
    - Method must use the EXTRACTION config from `_configs` and respect timeout parameter
    - On timeout, raise `APITimeoutError`
    - _Requirements: 1.1_

  - [x] 4.2 Create extraction prompts in `app/core/grounding_prompts.py`
    - Define `CLAIM_EXTRACTION_PROMPT` template with `{material_text}` placeholder
    - Prompt must instruct extraction of all 6 categories: skill_technology, achievement_outcome, quantified_metric, credential_certification, named_client_employer, experience_duration
    - Prompt must instruct returning JSON array with `claim_text`, `category`, `source_span`, `source_span_start`, `source_span_end`, `is_prospect_side` fields
    - Define `GROUNDING_CONSTRAINT_INJECTION` template with `{profile_assets_text}` placeholder
    - Constraint text must instruct: no fabrication, acknowledge gaps, reframe using adjacent experience
    - _Requirements: 1.1, 1.2, 1.3, 4.1_

  - [x] 4.3 Write property test for extraction category validity
    - **Property 6: Extraction produces claims in all and only the six defined categories**
    - **Validates: Requirement 1, AC 2**

- [x] 5. Core Grounding_Verifier implementation
  - [x] 5.1 Implement `extract_claims` method in `GroundingVerifier`
    - Build extraction prompt using `CLAIM_EXTRACTION_PROMPT` with material text
    - Call `llm_router.dispatch_extraction()` with 60s timeout
    - Parse JSON response into list of `Claim` objects (grounding_status=None at this stage)
    - Implement retry logic: up to 2 retries (3 total attempts) with exponential backoff
    - On `ExtractionParseError`: retry (malformed JSON)
    - On `ExtractionTimeoutError`: retry
    - After all retries exhausted: raise `ExtractionError`
    - Validate that each claim's `source_span` is an exact substring of material_text
    - Skip claims with invalid spans (log warning, continue with remaining)
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [x] 5.2 Write property test for source span validity
    - **Property 7: Every extracted claim has a valid source span**
    - **Validates: Requirement 1, AC 3**

  - [x] 5.3 Implement `verify_claims` method in `GroundingVerifier`
    - For each claim, determine if prospect-side via `_is_prospect_side_claim()`
    - If prospect-side: call `_verify_against_enrichment()` — check enrichment fields (employee_count, revenue_range, industry, tech_stack, funding_stage, headquarters)
    - If not prospect-side with category `QUANTIFIED_METRIC`: check if underlying achievement exists in assets but number differs → mark `partially_grounded` with `discrepancy` field
    - Otherwise: call `_verify_against_assets()` — search baseline_assets and offerings_assets for supporting passage
    - Assign `grounding_status` and `source_pointer` (for grounded/partially_grounded)
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 5.4 Write property test for prospect-side exemption
    - **Property 2: Prospect-side claims are verified against EnrichmentRecord, not Beneficiary assets**
    - **Validates: Requirement 2, AC 2**

  - [x] 5.5 Write property test for quantified metric partial grounding
    - **Property 3: Quantified metrics with matching achievement but differing numbers are partially_grounded**
    - **Validates: Requirement 2, AC 3**

  - [x] 5.6 Write property test for source pointer population
    - **Property 12: Grounded and partially_grounded claims have source pointers**
    - **Validates: Requirement 2, AC 1**

  - [x] 5.7 Implement `verify_material` orchestration method
    - Call `extract_claims()` with timeout/retry handling
    - On extraction failure after retries: mark material `grounding_unverified`, store report, return result
    - On success: call `verify_claims()` with beneficiary assets and enrichment
    - Build `GroundingReport` with counts and timing
    - Call `apply_pipeline_gate()` to determine gate decision
    - Store report via `db_repo.store_grounding_report()`
    - Return `GroundingResult` with status, report, and blocked states
    - _Requirements: 1.1, 1.4, 2.1, 2.4, 3.1_

  - [x] 5.8 Write property test for extraction failure handling
    - **Property 8: Extraction failure after retries marks material grounding_unverified**
    - **Validates: Requirement 1, AC 4**

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Pipeline Gate Service
  - [x] 7.1 Implement `PipelineGateService` in `app/core/pipeline_gate.py`
    - Define `GATED_STATES = {"Approve", "Applied", "Sent", "Proposal Submitted"}`
    - Implement `can_transition(pipeline_record_id, target_state) -> tuple[bool, list[Claim] | None]`
    - If `target_state` not in `GATED_STATES`: return `(True, None)`
    - If no grounding report exists: return `(False, [])`
    - If report status is `GROUNDING_BLOCKED`: return `(False, ungrounded_claims)`
    - Otherwise: return `(True, None)`
    - Implement `get_warning_badge(pipeline_record_id) -> bool`
    - Return `True` if `partially_grounded_count > 0` and `ungrounded_count == 0`
    - _Requirements: 3.1, 3.4_

  - [x] 7.2 Write property test for pipeline gate blocking logic
    - **Property 1: Pipeline gate blocks if and only if ungrounded claims exist**
    - **Validates: Requirement 3, AC 1 and AC 4**

  - [x] 7.3 Write property test for gate state completeness
    - **Property 7 (Testing Strategy): Gate state completeness — all MaterialGroundingStatus values produce correct gate decision**
    - **Validates: Requirement 3, AC 1 and AC 4**

  - [x] 7.4 Write property test for warning badge logic
    - **Property 13: Warning badge displayed if only partially_grounded claims exist**
    - **Validates: Requirement 3, AC 4**

  - [x] 7.5 Integrate `PipelineGateService` into pipeline state machine
    - Hook `can_transition()` check into the existing pipeline state transition logic
    - Before any transition to Approve/Applied/Sent/Proposal Submitted, call `can_transition()`
    - If blocked, prevent transition and return ungrounded claims list for UI display
    - _Requirements: 3.1_

- [x] 8. Resolution paths and re-verification
  - [x] 8.1 Implement `re_verify_claims` method in `GroundingVerifier`
    - Accept `affected_claim_ids`, optional `updated_material_text`, optional `updated_assets`
    - If `updated_material_text` provided: re-extract claims from updated text, match to affected IDs
    - Re-verify only the affected claims (do NOT touch other claims in the report)
    - Update grounding report counts and material_grounding_status
    - Store resolution record via `db_repo.store_resolution()`
    - Must complete within 30 seconds
    - _Requirements: 3.3_

  - [x] 8.2 Write property test for re-verification scope
    - **Property 4: Re-verification only checks affected claims**
    - **Validates: Requirement 3, AC 3**

  - [x] 8.3 Write property test for re-verification timeout
    - **Property 5: Re-verification completes within 30 seconds**
    - **Validates: Requirement 3, AC 3**

  - [x] 8.4 Implement `resolve_regenerate` method in `GroundingVerifier`
    - Call `personalization_engine.regenerate_passages()` with excluded claims
    - Re-extract and re-verify the regenerated passages
    - Update grounding report and return new `GroundingResult`
    - _Requirements: 3.2_

  - [x] 8.5 Implement `resolve_confirm_and_add` method in `GroundingVerifier`
    - Add `supporting_fact` to the specified `target_asset_id` profile asset
    - Re-verify the confirmed claim against the updated assets
    - Store resolution record with path=`confirm_and_add`
    - _Requirements: 3.2_

  - [x] 8.6 Write property test for resolution path availability
    - **Property 11: Three resolution paths are always offered for blocked materials**
    - **Validates: Requirement 3, AC 2**

- [x] 9. PersonalizationEngine extension
  - [x] 9.1 Extend `PersonalizationEngine` with grounding constraint injection
    - Modify `_build_generation_prompt()` to always append `GROUNDING_CONSTRAINT_INJECTION` with full Beneficiary profile assets text
    - Ensure constraint injection happens for ALL material types (CV, cover letter, cold email, proposal)
    - _Requirements: 4.1_

  - [x] 9.2 Write property test for grounding constraint injection
    - **Property 9: Generation prompt always includes grounding constraint injection**
    - **Validates: Requirement 4, AC 1**

  - [x] 9.3 Implement `regenerate_passages` method in `PersonalizationEngine`
    - Accept `material_id`, `excluded_claims` (list of Claim objects), `beneficiary`
    - Build regeneration prompt that excludes ungrounded content and constrains to verifiable assets
    - Call LLM to regenerate only the flagged passages
    - Return full material text with flagged passages replaced
    - _Requirements: 3.2_

- [x] 10. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Analytics extension
  - [x] 11.1 Implement `compute_ungrounded_claim_rates` in `AnalyticsService`
    - Query `grounding_reports` grouped by `prepare_technique_id` and ISO week
    - Compute `ungrounded_rate = ungrounded_claims / total_claims_extracted` (0 if total is 0)
    - Store results in `grounding_analytics_weekly` table (upsert on unique constraint)
    - Implement `get_grounding_trend(technique_id, weeks)` for trailing N weeks with zero-fill
    - _Requirements: 4.2_

  - [x] 11.2 Write property test for analytics rate computation
    - **Property 10: Ungrounded-claim rate is correctly computed per technique per week**
    - **Validates: Requirement 4, AC 2**

- [x] 12. Schema_Registry YAML configuration
  - [x] 12.1 Add `grounding_techniques` section to `config/schema.yaml`
    - Add `standard_grounding` technique with all 6 claim categories, 60s extraction timeout, 30s verification timeout, 2 max retries
    - Add `grounding_technique: standard_grounding` reference to `cv_and_cover_letter`, `cold_email_composition`, and `proposal_composition` prepare techniques
    - Ensure schema validation catches dangling `grounding_technique` references at startup
    - _Requirements: 1.1, 1.2_

- [x] 13. API endpoints for resolution paths
  - [x] 13.1 Create grounding resolution API routes in `app/api/routes/grounding.py`
    - `POST /grounding/resolve` — accepts `{ material_id, resolution_path, claim_ids, ...path-specific fields }`
    - For `regenerate` path: calls `grounding_verifier.resolve_regenerate()`
    - For `manual_edit` path: accepts edited content, calls `re_verify_claims()` on affected claims
    - For `confirm_and_add` path: calls `grounding_verifier.resolve_confirm_and_add()` with `supporting_fact` and `target_asset_id`
    - All endpoints return updated `GroundingResult` with new gate status
    - _Requirements: 3.2, 3.3_

  - [x] 13.2 Create grounding report retrieval endpoints
    - `GET /grounding/reports/{pipeline_record_id}` — returns latest grounding report with all claims
    - `GET /grounding/reports/{pipeline_record_id}/claims` — returns claims with filtering by `grounding_status`
    - `GET /grounding/analytics/rates` — returns weekly ungrounded rates per technique
    - `GET /grounding/analytics/trend/{technique_id}` — returns trailing weekly trend
    - _Requirements: 2.4, 3.1, 4.2_

- [x] 14. Grounding Worker (ARQ background processing)
  - [x] 14.1 Implement `GroundingWorker` in `app/workers/grounding_worker.py`
    - Implement `process_grounding_queue(ctx)` — fetches pending verifications (batch size 10), calls `verify_batch()`
    - Use `GroundingVerifier.verify_batch()` with semaphore-bounded concurrency (max 3)
    - Return summary dict with `processed`, `verified`, `blocked`, `unverified` counts
    - Register worker function with ARQ worker settings
    - _Requirements: 1.1_

  - [x] 14.2 Implement analytics aggregation worker task
    - Create ARQ task that runs daily to compute `grounding_analytics_weekly` for the current week
    - Call `analytics_service.compute_ungrounded_claim_rates()` for the trailing period
    - Register with ARQ cron schedule
    - _Requirements: 4.2_

- [x] 15. Dashboard integration
  - [x] 15.1 Implement "Requires Action" notifications for grounding
    - When material is blocked (`grounding_blocked`) or unverified (`grounding_unverified`): push WebSocket notification
    - Dashboard "Requires Action" section lists each blocked material with ungrounded claims and their source text spans
    - Materials marked `grounding_unverified` appear with informational notice (not blocking)
    - _Requirements: 1.4, 3.1_

  - [x] 15.2 Implement warning badge display for partially_grounded materials
    - Call `PipelineGateService.get_warning_badge()` when rendering pipeline records
    - Display warning badge on records where `partially_grounded_count > 0` and `ungrounded_count == 0`
    - Badge indicates claims exist that are supported but imprecise
    - _Requirements: 3.4_

  - [x] 15.3 Implement analytics display in Reports stage
    - Display ungrounded-claim rate per prepare technique per week in Reports stage
    - Use `GET /grounding/analytics/rates` endpoint data
    - Show trend over trailing 12 weeks per technique
    - _Requirements: 4.2_

- [x] 16. Integration wiring and end-to-end flow
  - [x] 16.1 Wire `GroundingVerifier` into the prepare pipeline after Review_Service
    - After Review_Service (P1) returns reviewed material, invoke `grounding_verifier.verify_material()`
    - If prepare technique has `grounding_technique` configured (via Schema_Registry): run verification
    - If no `grounding_technique` configured: skip grounding, proceed to post-prepare state
    - Handle `grounding_unverified` gracefully: allow pipeline to proceed, surface in Dashboard
    - _Requirements: 1.1, 1.4_

  - [x] 16.2 Wire resolution endpoint responses to pipeline unblocking
    - After successful resolution (no ungrounded claims remain): update pipeline record status to allow transitions
    - Emit WebSocket notification that material is unblocked
    - If still blocked: return remaining ungrounded claims for continued resolution
    - _Requirements: 3.2, 3.3_

- [x] 17. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional property-based test sub-tasks and can be skipped for faster MVP
- This feature (P2) depends on review-critique-loop (P1) being implemented first — the Grounding_Verifier receives materials FROM the Review_Service
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at stable boundaries
- Property tests validate the 13 correctness properties from the design document
- The verification logic in `verify_claims` is deterministic (no LLM call) — only `extract_claims` calls the LLM
- The pipeline gate integration (task 7.5) requires coordination with existing pipeline state machine code

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "4.1", "4.2"] },
    { "id": 3, "tasks": ["4.3", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3"] },
    { "id": 5, "tasks": ["5.4", "5.5", "5.6", "5.7"] },
    { "id": 6, "tasks": ["5.8", "7.1", "9.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "7.4", "7.5", "9.2", "9.3"] },
    { "id": 8, "tasks": ["8.1"] },
    { "id": 9, "tasks": ["8.2", "8.3", "8.4", "8.5"] },
    { "id": 10, "tasks": ["8.6", "11.1", "12.1"] },
    { "id": 11, "tasks": ["11.2", "13.1", "13.2"] },
    { "id": 12, "tasks": ["14.1", "14.2"] },
    { "id": 13, "tasks": ["15.1", "15.2", "15.3"] },
    { "id": 14, "tasks": ["16.1", "16.2"] }
  ]
}
```
