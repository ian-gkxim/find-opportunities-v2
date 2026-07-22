# Implementation Plan: Form Submission Automation

## Overview

This plan implements the form submission automation feature — a new outreach technique (`form_submission`) that automates web form filling via LLM-powered form analysis and Playwright browser automation with human-in-the-loop approval. Implementation proceeds from infrastructure layer (schemas, models, browser pool, rate limiter) through core services (FormAnalyzer, FieldMappingEngine, FormExecutor), pipeline state machine, API routes, ARQ workers, analytics extensions, and finally Schema Registry integration and frontend components.

## Tasks

- [ ] 1. Infrastructure layer — Pydantic schemas and data models
  - [-] 1.1 Create Pydantic schemas for form submission domain
    - Create `app/schemas/form_submission.py` with all Pydantic models: FormField, FormFieldType, FieldMapping, FieldMappingStatus, FormExtractionResult, ExecutionResult, ScreenshotRef, ValidationError, RateLimitConfig, FieldMapResult, RateLimitResult
    - Include FormAnalyzerConfig and FieldMappingConfig and FormExecutorConfig dataclasses
    - Implement InitiateSubmissionRequest, MappingEditsRequest, AssistedCompleteRequest, SubmissionResponse, SubmissionDetailResponse, SubmissionAnalyticsResponse API request/response schemas
    - Ensure all field constraints from the design (confidence_score 0-100, field_type enum, status enum, etc.)
    - _Requirements: 1.2, 2.1, 2.2, 4.2, 5.6_

  - [~] 1.2 Create SubmissionRecord SQLAlchemy ORM model and Alembic migration
    - Create `app/models/submission_record.py` with the SubmissionRecord model per the design
    - Include all columns: id, pipeline_record_id (FK), beneficiary_id, form_url, status, assisted_mode_reason, extracted_fields (JSON), extraction_timestamp, is_multi_step, steps_extracted, partial_extraction_step, field_mapping (JSON), mapping_approved, mapping_approved_at, fields_filled, fields_skipped, validation_errors (JSON), submission_confirmed, screenshots (JSON), audit_log (JSON), created_at, updated_at
    - Add relationship to PipelineRecord model (back_populates)
    - Create Alembic migration adding `submission_records` table with indexes on pipeline_record_id, beneficiary_id, status, and created_at
    - _Requirements: 1.7, 5.6, 8.1_

  - [-] 1.3 Implement BrowserPool service
    - Create `app/core/browser_pool.py` with the BrowserPool class
    - Implement `acquire()` returning a configured BrowserContext with anti-detection settings (current Chrome user-agent, random viewport from VIEWPORT_OPTIONS, JS enabled)
    - Implement `release()` to return contexts to the pool
    - Implement `shutdown()` to close all browser instances
    - Configure max_contexts=3, use asyncio.Semaphore for concurrency control
    - _Requirements: 10.2_

  - [-] 1.4 Implement ScreenshotStore service
    - Create `app/core/screenshot_store.py` with the ScreenshotStore class
    - Implement `save()` storing PNG data to filesystem path organized by record_id and stage, returning relative path
    - Implement `get_path()` for retrieving screenshot filesystem path
    - Implement `cleanup_expired()` removing screenshots older than retention_days (default 90)
    - Use configurable base_path from environment variable
    - _Requirements: 5.1, 5.3, 5.5_

  - [-] 1.5 Implement DomainRateLimiter service
    - Create `app/core/domain_rate_limiter.py` with the DomainRateLimiter class
    - Implement `acquire()` checking per-domain minimum interval (default 60s) and daily submission cap (default 10/day, resets midnight UTC) using Redis counters
    - Implement `record_submission()` incrementing domain counters
    - Implement `extract_registrable_domain()` extracting registrable domain from URL (e.g., "jobs.example.com" → "example.com") using tldextract
    - Implement RateLimitConfig with min_interval_seconds, max_daily_submissions, field_delay_min_ms, field_delay_max_ms, http_429_default_wait, http_429_max_wait
    - Fall back to in-memory counters with a warning if Redis is unavailable
    - _Requirements: 10.1, 10.4, 10.5, 10.6_

- [~] 2. Checkpoint - Infrastructure layer
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 3. Core services — FormAnalyzerService
  - [~] 3.1 Implement FormAnalyzerService
    - Create `app/core/form_analyzer.py` with the FormAnalyzerService class
    - Implement `analyze_form()` orchestrating: page navigation (30s timeout), DOM extraction, LLM field extraction, multi-step detection and navigation (up to 10 steps, 15s per step)
    - Implement `_extract_dom()` rendering page and extracting simplified DOM for LLM consumption
    - Implement `_detect_multi_step()` identifying multi-step form indicators (next/continue buttons, step indicators)
    - Implement `_navigate_next_step()` clicking navigation controls with 15s timeout per step
    - Implement `_detect_auth_required()` checking for login redirects and 401/403 responses
    - Handle error states: CrawlFailedError on network/timeout errors, "extraction_uncertain" when < 2 fields extracted, "auth_required" on auth detection, "partial_extraction" when step navigation fails
    - Store extracted field structure in SubmissionRecord with timestamp
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9_

  - [ ]* 3.2 Write property test for field extraction parsing (Property 1)
    - **Property 1: Field extraction parsing produces valid FormField objects**
    - Use Hypothesis to generate well-formed LLM field extraction JSON responses
    - Verify every parsed FormField has non-empty label, valid FormFieldType, boolean is_required, and non-empty css_selector
    - **Validates: Requirements 1.2**

  - [ ]* 3.3 Write property test for extraction uncertainty threshold (Property 2)
    - **Property 2: Extraction uncertainty threshold**
    - Generate FormExtractionResults with varying field counts (0, 1, 2+)
    - Verify status is "extraction_uncertain" when fewer than 2 fields extracted and no prior error
    - **Validates: Requirements 1.5**

  - [ ]* 3.4 Write property test for partial extraction preservation (Property 3)
    - **Property 3: Partial extraction preserves completed steps**
    - Generate multi-step extraction scenarios failing at step K (K > 1)
    - Verify all fields from steps 1 through K-1 are retained and partial_extraction_step == K
    - **Validates: Requirements 1.8**

- [ ] 4. Core services — FieldMappingEngine
  - [~] 4.1 Implement FieldMappingEngine
    - Create `app/core/field_mapping_engine.py` with the FieldMappingEngine class
    - Implement `generate_mapping()` using LLM semantic matching with 15s timeout
    - Implement `_gather_source_data()` collecting data from all source tiers via PersonalizationEngine (baseline_assets, generated_materials, enrichment_data, profile_fields)
    - Implement `_apply_transformations()` for date format conversion, text truncation, name splitting
    - Apply SOURCE_PRIORITY ordering (baseline_assets > generated_materials > enrichment_data > profile_fields)
    - Assign confidence scores (0-100) per mapping, mark fields below 30 as "requires_manual_input"
    - Handle file upload fields: match to generated documents by label semantics (resume → tailored_cv, cover letter → tailored_cover_letter, proposal → proposal_document)
    - Generate exactly N FieldMapping entries for N input FormFields
    - Set status to "mapping_failed" on LLM timeout or no source data
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9_

  - [ ]* 4.2 Write property test for confidence score invariants (Property 4)
    - **Property 4: Confidence score invariants and classification**
    - Generate FieldMapping entries with varying confidence scores and source matches
    - Verify confidence_score is integer in [0, 100] and status is "requires_manual_input" when score < 30 with no suitable source
    - **Validates: Requirements 2.2, 2.4**

  - [ ]* 4.3 Write property test for source priority ordering (Property 5)
    - **Property 5: Source data priority ordering**
    - Generate scenarios with multiple source tiers containing data for the same field
    - Verify the highest-priority tier value is selected (baseline_assets > generated_materials > enrichment_data > profile_fields)
    - **Validates: Requirements 2.3**

  - [ ]* 4.4 Write property test for file upload field mapping (Property 6)
    - **Property 6: File upload field mapping**
    - Generate file-type fields with labels matching document types and scenarios with no matching documents
    - Verify matching documents are referenced correctly and missing documents result in "requires_manual_input"
    - **Validates: Requirements 2.5, 2.6**

  - [ ]* 4.5 Write property test for transformation detection (Property 7)
    - **Property 7: Transformation detection**
    - Generate source value / target field constraint pairs requiring format conversion
    - Verify non-null transformation instruction is included when conversion is needed
    - **Validates: Requirements 2.7**

  - [ ]* 4.6 Write property test for mapping completeness (Property 8)
    - **Property 8: Mapping completeness**
    - Generate lists of N extracted FormFields (varying N)
    - Verify the FieldMapResult contains exactly N FieldMapping entries
    - **Validates: Requirements 2.8**

  - [ ]* 4.7 Write property test for mapping response serialization (Property 9)
    - **Property 9: Mapping response serialization completeness**
    - Generate FieldMapping objects with varying states (mapped, manual, skipped, edited)
    - Verify serialized representation always includes field_label, proposed_value (or null), confidence_score (or null if edited), and is_required
    - **Validates: Requirements 3.1**

  - [ ]* 4.8 Write property test for user edit nullifies confidence (Property 10)
    - **Property 10: User edit nullifies confidence score**
    - Generate FieldMapping objects and simulate user edits (changed proposed_value)
    - Verify confidence_score becomes None after edit
    - **Validates: Requirements 3.2**

- [ ] 5. Core services — FormExecutorService
  - [~] 5.1 Implement FormExecutorService
    - Create `app/core/form_executor.py` with the FormExecutorService class
    - Implement `execute_submission()` orchestrating: navigate to URL (15s), fill fields with appropriate interaction methods, capture pre-submit screenshot, click submit, wait for confirmation (30s), capture post-submit screenshot
    - Implement `_fill_field()` dispatching per field type: type() for text/textarea/number, select_option() for select, click() for radio/checkbox, set_input_files() for file, fill() for date
    - Implement randomized inter-field delays (uniform 100-500ms)
    - Implement `_capture_screenshot()` full-page PNG capture with graceful failure handling
    - Implement `_detect_captcha()` for CAPTCHA/anti-bot challenge detection
    - Implement `_detect_submission_confirmation()` via URL change, success message, or confirmation elements
    - Handle error states: "page_changed" when > 30% fields not found, "partial_fill" when individual fields not found, "captcha_detected", "submission_failed" (submit button not found), "submission_unconfirmed" (no confirmation within 30s), "navigation_failed" for multi-step failures
    - Implement multi-step form handling: fill fields per step, navigate between steps, verify step loads (10s timeout), capture per-step screenshots
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 5.1, 5.2, 5.5, 10.3_

  - [ ]* 5.2 Write property test for approval validation rules (Property 11)
    - **Property 11: Approval validation rules**
    - Generate mappings with required fields having "requires_manual_input" status and fields with values exceeding character limits
    - Verify approval is rejected when required fields lack user-provided values or edited values exceed constraints
    - **Validates: Requirements 3.7, 3.8**

  - [ ]* 5.3 Write property test for field type interaction dispatch (Property 12)
    - **Property 12: Field type interaction dispatch**
    - Generate FormFields of each type (text, textarea, select, radio, checkbox, file, date, number)
    - Verify correct Playwright interaction method is selected per type
    - **Validates: Requirements 4.2**

  - [ ]* 5.4 Write property test for page change abort threshold (Property 13)
    - **Property 13: Page change abort threshold**
    - Generate execution scenarios with varying fractions of fields not found (0% to 100%)
    - Verify execution aborts with "page_changed" status when > 30% of fields are missing
    - **Validates: Requirements 4.8**

  - [ ]* 5.5 Write property test for screenshot count per step (Property 14)
    - **Property 14: Screenshot count per step**
    - Generate successful multi-step submissions with K steps
    - Verify at least K pre-submission screenshots plus 1 post-submission screenshot
    - **Validates: Requirements 5.2**

  - [ ]* 5.6 Write property test for audit log structure (Property 15)
    - **Property 15: Audit log structure and timestamp validity**
    - Generate complete submission lifecycles with varying actions
    - Verify every audit entry has ISO 8601 timestamp with millisecond precision and action types are a superset of performed actions
    - **Validates: Requirements 5.6**

  - [ ]* 5.7 Write property test for field interaction delay bounds (Property 23)
    - **Property 23: Field interaction delay bounds**
    - Generate field interaction delay values
    - Verify all delays are in [100, 500] milliseconds
    - **Validates: Requirements 10.3**

- [~] 6. Checkpoint - Core services complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Pipeline state machine and assisted mode integration
  - [~] 7.1 Implement form submission pipeline state machine
    - Extend `app/core/pipeline_manager.py` with form_submission state transitions
    - Define valid transitions: Personalise→Crawling, Crawling→Mapping, Mapping→Awaiting Approval, Awaiting Approval→Submitting, Submitting→Submitted, any→error states, any→Assisted, Assisted→Submitted, error→preceding state (retry)
    - Implement transition validation rejecting invalid state pairs
    - Wire state changes to WebSocket broadcasts (within 10s per Requirement 8.6)
    - Implement "Requires Action" surfacing for error states and Awaiting Approval
    - _Requirements: 7.3, 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8, 8.9, 8.10_

  - [~] 7.2 Implement assisted mode logic
    - Add assisted mode trigger logic to pipeline manager: auto-trigger on extraction_uncertain, auth_required, captcha_detected, page_changed, or user_choice
    - Track assisted_mode_reason in SubmissionRecord
    - Implement 7-day timeout surfacing as "awaiting_manual_submission" in Dashboard
    - Implement cancellation (marks SubmissionRecord as "cancelled", removes from active tracking)
    - Implement manual completion confirmation advancing to "Submitted"
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7_

  - [ ]* 7.3 Write property test for pipeline state machine correctness (Property 17)
    - **Property 17: Pipeline state machine correctness**
    - Generate all possible (current_state, target_state) pairs
    - Verify transitions succeed iff the pair is in the valid transition set and all other pairs are rejected
    - **Validates: Requirements 7.3, 8.8, 8.10**

  - [ ]* 7.4 Write property test for assisted mode reason validity (Property 16)
    - **Property 16: Assisted mode reason validity**
    - Generate SubmissionRecords in "assisted" status with various reason values
    - Verify assisted_mode_reason is always one of: extraction_uncertain, auth_required, captcha_detected, user_choice, page_changed
    - **Validates: Requirements 6.6**

- [ ] 8. FastAPI router — Form submission API endpoints
  - [~] 8.1 Implement form submission API router
    - Create `app/api/form_submission.py` with APIRouter(prefix="/api/form-submissions")
    - Implement POST `/initiate` — creates SubmissionRecord, advances to "Crawling", enqueues crawl task
    - Implement GET `/{record_id}` — returns full SubmissionDetailResponse with field map, screenshots, audit log
    - Implement PUT `/{record_id}/mapping/approve` — validates required fields filled, validates character limits, makes mapping read-only, advances to "Submitting", enqueues submission task
    - Implement PUT `/{record_id}/mapping/reject` — sets status to "mapping_rejected"
    - Implement POST `/{record_id}/re-crawl` — triggers fresh crawl overwriting existing extraction
    - Implement PUT `/{record_id}/assisted/complete` — marks assisted submission complete with optional screenshot upload (PNG/JPEG, max 10MB)
    - Implement PUT `/{record_id}/assisted/cancel` — marks as "cancelled"
    - Implement POST `/{record_id}/retry` — resets to preceding state and re-initiates failed step
    - Implement GET `/analytics/summary` — returns SubmissionAnalyticsResponse with time_period filter (7/30/90 days)
    - Wire all endpoints to appropriate services and PipelineManager
    - _Requirements: 1.9, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 6.3, 6.7, 8.8, 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ]* 8.2 Write unit tests for form submission API endpoints
    - Test request validation (invalid UUIDs, missing required fields, oversized uploads)
    - Test approval validation (missing required manual fields, character limit violations)
    - Test error responses (404 for unknown record_id, 409 for invalid state transitions)
    - Test analytics endpoint with time_period and opportunity_type filters
    - _Requirements: 3.7, 3.8, 8.8_

- [ ] 9. ARQ workers — Background tasks for crawl and submission execution
  - [~] 9.1 Implement form submission ARQ workers
    - Create `app/workers/form_submission_worker.py` with two task functions:
    - Implement `execute_crawl_task()` — acquires browser from pool, runs FormAnalyzerService.analyze_form(), advances pipeline state, enqueues mapping generation on success
    - Implement `execute_submission_task()` — checks rate limit via DomainRateLimiter, acquires browser, runs FormExecutorService.execute_submission(), advances pipeline state
    - Implement `execute_mapping_task()` — runs FieldMappingEngine.generate_mapping(), advances to "Awaiting Approval", triggers WebSocket notification
    - Handle task failures with proper error state transitions and audit log entries
    - Implement HTTP 429 handling: pause for Retry-After (capped at 30 min) or 5 min default, retry once, then mark "rate_limited"
    - Register tasks in ARQ worker settings
    - _Requirements: 1.1, 2.1, 4.1, 10.4, 10.7_

  - [ ]* 9.2 Write property test for HTTP 429 wait time capping (Property 24)
    - **Property 24: HTTP 429 wait time capping**
    - Generate 429 responses with various Retry-After header values (including absent)
    - Verify computed wait = min(V, 1800) when header present, 300 when absent
    - **Validates: Requirements 10.4**

- [~] 10. Checkpoint - API and workers complete
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 11. Analytics extensions for form submissions
  - [~] 11.1 Extend AnalyticsService with form submission metrics
    - Add submission success rate computation (submitted / total attempts) per opportunity type and beneficiary
    - Add automation rate computation (submitted without assisted mode / total) per opportunity type
    - Add average time from initiation to submission in hours (rounded to 1 decimal)
    - Add assisted mode reason distribution (counts and percentages)
    - Add weekly confidence score trend (mean per ISO week)
    - Implement "insufficient data" indicator when < 5 submissions
    - Refresh all metrics daily
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ]* 11.2 Write property test for analytics ratio computation (Property 18)
    - **Property 18: Analytics ratio computation**
    - Generate non-empty sets of submission records with varying statuses
    - Verify success_rate = submitted / total and automation_rate = (submitted AND no assisted) / total, both in [0.0, 1.0]
    - **Validates: Requirements 9.1, 9.2**

  - [ ]* 11.3 Write property test for analytics time computation (Property 19)
    - **Property 19: Analytics time computation**
    - Generate submission records with created_at and completion timestamps
    - Verify average_time_hours = mean of (completion - created_at) in hours, rounded to 1 decimal
    - **Validates: Requirements 9.3**

  - [ ]* 11.4 Write property test for assisted mode reason distribution (Property 20)
    - **Property 20: Assisted mode reason distribution**
    - Generate non-empty sets of assisted-mode records with various reasons
    - Verify sum of percentages = 100% (within tolerance) and each = (count / total) × 100
    - **Validates: Requirements 9.4**

  - [ ]* 11.5 Write property test for weekly confidence aggregation (Property 21)
    - **Property 21: Weekly confidence score aggregation**
    - Generate submission records spanning multiple ISO weeks with confidence scores
    - Verify each weekly data point = arithmetic mean of that week's scores, ordered chronologically
    - **Validates: Requirements 9.6**

- [ ] 12. Rate limiter property tests
  - [ ]* 12.1 Write property test for rate limit interval enforcement (Property 22)
    - **Property 22: Rate limit interval enforcement**
    - Generate domains with configured intervals and submission timestamps
    - Verify submissions blocked when time since last < interval, allowed otherwise
    - **Validates: Requirements 10.1**

  - [ ]* 12.2 Write property test for daily submission limit enforcement (Property 25)
    - **Property 25: Daily submission limit enforcement**
    - Generate domains with configured daily limits and submission counts
    - Verify submissions 1 through L allowed, L+1 onwards blocked until midnight UTC reset
    - **Validates: Requirements 10.5**

- [ ] 13. Schema Registry update and configuration
  - [~] 13.1 Add form_submission outreach technique to schema.yaml
    - Add new entry to `outreach_techniques` section: id "form_submission", service_class "FormSubmissionService", description "Automated web form filling via LLM analysis and Playwright browser automation with human approval"
    - Add form_submission pipeline_states to any opportunity types that should use it (e.g., job_site, project_marketplace) or create a new opportunity type configuration demonstrating the technique
    - Ensure SchemaRegistry cross-reference validation passes with the new technique
    - Implement graceful degradation: if FormSubmissionService class unavailable at startup, log error and disable technique for affected opportunity types without preventing system startup
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ] 14. Frontend components — Mapping approval and submission views
  - [~] 14.1 Implement field mapping approval view
    - Create `frontend/app/form-submissions/[id]/approve/page.tsx`
    - Display each form field: label, proposed value, confidence score, required indicator
    - Implement inline value editing (up to 5000 chars per field) with confidence score removal on edit
    - Implement "skip" toggle for optional fields
    - Visually highlight fields with confidence < 60 using warning indicator
    - Implement "Approve and Submit" button with validation (all required manual fields filled, character limits respected)
    - Implement "Reject" action with option to request new mapping or switch to Assisted Mode
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [~] 14.2 Implement assisted mode sidebar panel
    - Create `frontend/components/form-submissions/AssistedModePanel.tsx`
    - Display form URL with "Open in Browser" action
    - Show relevant Source_Data (generated materials, profile data) in a copy-paste-friendly sidebar
    - Implement "Mark as Complete" with optional screenshot upload (PNG/JPEG, max 10MB)
    - Implement "Cancel Submission" action
    - _Requirements: 6.1, 6.2, 6.3, 6.7_

  - [~] 14.3 Implement submission detail view
    - Create `frontend/app/form-submissions/[id]/page.tsx`
    - Display submission status, pipeline stage, and audit timeline
    - Show pre-submission and post-submission screenshots with lightbox viewer
    - Display approved field mapping (read-only) with field values
    - Show error details and retry options for failed submissions
    - _Requirements: 5.4, 8.7_

- [~] 15. Final checkpoint - Full integration verification
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation between layers
- Property tests validate universal correctness properties from the design document (25 total)
- Unit tests validate specific examples and edge cases
- The implementation uses Python throughout (FastAPI, SQLAlchemy, Playwright async, Pydantic, pytest + Hypothesis)
- Frontend components use the existing Next.js 14 + TypeScript + Tailwind CSS stack
- All services integrate with existing infrastructure: LLMRouter, PersonalizationEngine, PipelineManager, AnalyticsService, WebSocketManager, ARQ workers

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3", "1.4", "1.5"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["3.1"] },
    { "id": 3, "tasks": ["3.2", "3.3", "3.4", "4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3", "4.4", "4.5", "4.6", "4.7", "4.8", "5.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4", "5.5", "5.6", "5.7"] },
    { "id": 6, "tasks": ["7.1", "7.2"] },
    { "id": 7, "tasks": ["7.3", "7.4", "8.1"] },
    { "id": 8, "tasks": ["8.2", "9.1"] },
    { "id": 9, "tasks": ["9.2", "11.1", "13.1"] },
    { "id": 10, "tasks": ["11.2", "11.3", "11.4", "11.5", "12.1", "12.2"] },
    { "id": 11, "tasks": ["14.1", "14.2", "14.3"] }
  ]
}
```
