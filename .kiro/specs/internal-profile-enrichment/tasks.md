# Implementation Plan: Internal Profile Enrichment

## Overview

Convert the feature design into incremental implementation steps — starting with database schema and ORM models, building the core services (throttler, extractor, deduplicator, review), wiring the ARQ worker, exposing FastAPI routes, and finally adding the frontend Proposal Review UI. Each step builds on the previous; no orphaned code.

## Tasks

- [x] 1. Database schema and ORM models
  - [x] 1.1 Create Alembic migration for the 4 new tables
    - Create migration file adding `public_sources`, `competency_proposals`, `profile_enrichment_audit_log`, and `enrichment_scan_history` tables
    - Include all columns, constraints, CHECK constraints, unique constraints, and indexes as specified in design
    - _Requirements: 1.1, 1.2, 1.4, 2.1, 2.3, 3.2, 3.4_

  - [x] 1.2 Create SQLAlchemy ORM models
    - Create `app/models/public_source.py` with the `PublicSource` model
    - Create `app/models/competency_proposal.py` with the `CompetencyProposal` model
    - Create `app/models/profile_enrichment_audit.py` with the `ProfileEnrichmentAudit` model
    - Create `app/models/enrichment_scan_history.py` with the `EnrichmentScanHistory` model
    - Register all models in `app/models/__init__.py`
    - _Requirements: 1.1, 1.2, 1.4, 2.1, 2.3, 3.4_

  - [x] 1.3 Write unit tests for ORM model instantiation and constraints
    - Verify constraint enforcement (source_type values, confidence enum, status enum)
    - Verify unique constraint on (consultant_id, url) for public_sources
    - _Requirements: 1.1, 2.3_

- [x] 2. Domain Throttler
  - [x] 2.1 Implement DomainThrottler with Redis-backed per-domain rate limiting
    - Create `app/core/domain_throttler.py`
    - Implement `acquire(url)` method that enforces 1 req/s per domain using Redis keys
    - Implement `_extract_domain(url)` for consistent domain grouping
    - Handle Redis unavailability gracefully (fallback to 2s fixed delay)
    - _Requirements: 1.3_

  - [x] 2.2 Write property test for domain extraction determinism (Property 3)
    - **Property 3: Domain Extraction Determinism**
    - For any valid URL, `_extract_domain()` produces consistent domain strings; same-host URLs produce same key, different-host URLs produce different keys
    - Use Hypothesis strategies for generating random valid URLs
    - **Validates: Requirements 1.3**

  - [x] 2.3 Write unit tests for DomainThrottler
    - Test acquire blocks when called twice in rapid succession for same domain
    - Test acquire permits immediate call for different domains
    - Test Redis fallback behavior on connection failure
    - _Requirements: 1.3_

- [x] 3. Competency Extractor
  - [x] 3.1 Implement CompetencyExtractor with source-type-specific LLM prompts
    - Create `app/core/competency_extractor.py`
    - Implement `extract(content, source_type, source_url)` using the LLM_Router
    - Include all prompt templates (github, google_scholar, certification_badge, portfolio, default)
    - Implement `_parse_candidates(response, source_url)` for JSON response parsing
    - Enforce MAX_CONTENT_LENGTH truncation and MAX_CANDIDATES_PER_SOURCE cap
    - _Requirements: 2.1, 2.3_

  - [x] 3.2 Write property test for candidate parsing completeness (Property 5)
    - **Property 5: Competency Candidate Parsing Completeness**
    - For any valid JSON array of candidate objects, the parser produces CompetencyCandidate objects each with non-empty category, name, evidence_summary, confidence in {"strong","inferred"}, and source_url
    - Use Hypothesis to generate random valid JSON arrays
    - **Validates: Requirements 2.1, 2.3**

  - [x] 3.3 Write unit tests for CompetencyExtractor
    - Test correct prompt template selection per source type
    - Test content truncation at MAX_CONTENT_LENGTH
    - Test handling of malformed JSON from LLM (returns empty list)
    - Test MAX_CANDIDATES_PER_SOURCE cap
    - _Requirements: 2.1, 2.3_

- [x] 4. Proposal Deduplicator
  - [x] 4.1 Implement ProposalDeduplicator with exact + fuzzy matching
    - Create `app/core/proposal_deduplicator.py`
    - Implement `deduplicate(candidates, consultant_id)` checking against existing profile assets, rejected proposals, and pending proposals
    - Implement `_normalize(name)` for case/version-insensitive comparison
    - Implement `_fuzzy_match_any(name, existing)` using SequenceMatcher with 0.85 threshold
    - _Requirements: 2.2, 3.3_

  - [x] 4.2 Write property test for deduplication soundness (Property 6)
    - **Property 6: Deduplication Soundness**
    - For any set of existing assets, rejected proposals, and new candidates: output contains only candidates whose normalized name doesn't match existing (exact or ≥85% fuzzy) and whose (name, category) doesn't match rejected. No genuinely new candidates are filtered.
    - Use Hypothesis for random asset sets, rejection lists, and candidate lists
    - **Validates: Requirements 2.2, 3.3**

  - [x] 4.3 Write unit tests for ProposalDeduplicator
    - Test exact match deduplication against profile
    - Test fuzzy match at threshold boundary (84% passes, 86% filtered)
    - Test normalization stripping version suffixes
    - Test rejection history check prevents re-proposal
    - _Requirements: 2.2, 3.3_

- [x] 5. Checkpoint — Core services complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Proposal Review Service
  - [x] 6.1 Implement ProposalReviewService with additive-only merge
    - Create `app/core/proposal_review_service.py`
    - Implement `accept_proposal(proposal_id, consultant_id, edited_content)` with additive-only append
    - Implement `reject_proposal(proposal_id, consultant_id)` recording rejection for deduplication
    - Implement `bulk_action(proposal_ids, action, consultant_id)` with MAX_BULK_SIZE=50
    - Implement `_append_to_profile(consultant_id, content, section)` — INSERT only, never UPDATE/DELETE existing rows
    - Implement `_create_audit_entry(...)` for immutable audit trail
    - Authorization check: consultant must own the proposal
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 6.2 Write property test for additive-only merge invariant (Property 7)
    - **Property 7: Additive-Only Merge Invariant**
    - For any profile state and accepted proposal, after merge the profile section contains all previous content unchanged plus the new content appended. No existing content modified, reordered, or deleted.
    - Use Hypothesis for random profile content + proposal content
    - **Validates: Requirements 3.2**

  - [x] 6.3 Write property test for audit log completeness (Property 8)
    - **Property 8: Audit Log Completeness**
    - For any accepted and merged proposal, exactly one audit log entry is created containing: non-null timestamp, added_content matching merged content, evidence_source_url from proposal, and target profile_section
    - **Validates: Requirements 3.4**

  - [x] 6.4 Write unit tests for ProposalReviewService
    - Test accept creates audit entry and appends to profile
    - Test reject marks proposal as rejected
    - Test edit-then-accept stores edited content
    - Test bulk reject/accept up to 50 proposals
    - Test accept of non-pending proposal raises ValueError (409)
    - Test unauthorized access raises PermissionError (403)
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 7. Profile Enrichment Worker (ARQ)
  - [x] 7.1 Implement the Profile_Enrichment_Worker scan orchestration
    - Create `app/workers/profile_enrichment_worker.py`
    - Implement scheduled scan logic: get consultants due for scan, iterate sources, fetch with throttling, extract, deduplicate, generate proposals
    - Implement HTTP fetch with 15-second timeout and 3-retry logic
    - Implement consecutive failure tracking and Dashboard notice at threshold (3 consecutive failures)
    - Implement on-demand scan trigger support
    - Wire DomainThrottler, CompetencyExtractor, ProposalDeduplicator together
    - Emit WebSocket notifications for new proposals and source failure notices
    - Record scan history (enrichment_scan_history table)
    - _Requirements: 1.2, 1.3, 1.4, 2.1, 2.2, 2.4_

  - [x] 7.2 Write property test for scan scheduling correctness (Property 2)
    - **Property 2: Scan Scheduling Correctness**
    - For any source with configured scan_interval_days and last_scanned_at, the source is due iff current_time - last_scanned_at >= scan_interval_days OR last_scanned_at is null
    - Use Hypothesis for random intervals, timestamps, and current times
    - **Validates: Requirements 1.2**

  - [x] 7.3 Write property test for failure counter monotonicity (Property 4)
    - **Property 4: Failure Counter Monotonicity and Reset**
    - For any sequence of scan outcomes, consecutive_failures increments by 1 on failure, resets to 0 on success, and Dashboard notice is emitted iff counter reaches exactly 3
    - Use Hypothesis to generate random sequences of (success, failure) booleans
    - **Validates: Requirements 1.4**

  - [x] 7.4 Write unit tests for Profile_Enrichment_Worker
    - Test full scan cycle with mocked HTTP, LLM, and DB
    - Test source timeout after 15 seconds
    - Test 3-retry logic for unreachable source
    - Test consecutive failure counter behavior
    - Test on-demand scan trigger
    - _Requirements: 1.2, 1.3, 1.4, 2.4_

- [x] 8. FastAPI Routes
  - [x] 8.1 Implement source configuration endpoints
    - Create `app/api/profile_enrichment.py` with router prefix `/profile-enrichment`
    - Implement `GET /sources` — list configured sources for current Consultant
    - Implement `POST /sources` — add source (enforce max 10 per Consultant)
    - Implement `DELETE /sources/{source_id}` — remove source
    - Add Pydantic request/response schemas (PublicSourceCreate, PublicSourceResponse)
    - _Requirements: 1.1_

  - [x] 8.2 Write property test for source limit enforcement (Property 1)
    - **Property 1: Source Limit Enforcement**
    - For any Consultant and sequence of source additions, system accepts at most 10; any 11th attempt is rejected while existing 10 remain unchanged
    - Use Hypothesis for random sequences of add/remove operations
    - **Validates: Requirements 1.1**

  - [x] 8.3 Implement proposal management and scan trigger endpoints
    - Implement `GET /proposals` — list proposals with optional status filter
    - Implement `POST /proposals/{id}/accept` — accept single proposal (optional edited_content)
    - Implement `POST /proposals/{id}/reject` — reject single proposal
    - Implement `POST /proposals/bulk` — bulk accept/reject (max 50)
    - Implement `POST /scan` — trigger on-demand scan
    - Add Pydantic schemas (ProposalResponse, AcceptRequest, BulkActionRequest)
    - _Requirements: 1.2, 3.1, 3.2, 3.3_

  - [x] 8.4 Write unit tests for API routes
    - Test add source succeeds (201), test add 11th source fails (422)
    - Test list proposals returns filtered results
    - Test accept/reject endpoints with valid and invalid proposal IDs
    - Test bulk action respects max 50 limit
    - Test authorization: Consultant A cannot access Consultant B resources
    - _Requirements: 1.1, 3.1_

- [x] 9. Checkpoint — Backend complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Frontend Proposal Review UI
  - [x] 10.1 Implement Source Configuration UI component
    - Create React component for managing public sources in the Understand stage
    - List configured sources with status indicators (last scanned, failure count)
    - Add source form with source type selector and URL input
    - Delete source with confirmation
    - Display failure notices for sources with 3+ consecutive failures
    - Wire to `/profile-enrichment/sources` API endpoints
    - _Requirements: 1.1, 1.4_

  - [x] 10.2 Implement Proposal Review UI component
    - Create React component for reviewing competency proposals in the Understand stage
    - Display proposals grouped by status (pending by default) with evidence and confidence badges
    - Accept button with inline edit capability (edit-then-accept flow)
    - Reject button with immediate effect
    - Bulk selection with bulk accept/reject actions
    - Wire to `/profile-enrichment/proposals` API endpoints
    - _Requirements: 3.1_

  - [x] 10.3 Implement WebSocket real-time updates for proposals
    - Subscribe to WebSocket channel for new proposal notifications
    - Auto-refresh proposal list when new proposals arrive
    - Show toast notification for source failure notices on Dashboard
    - Wire to existing WebSocket infrastructure
    - _Requirements: 1.4, 3.1_

  - [x] 10.4 Write unit tests for frontend components
    - Test Source Configuration renders sources and handles add/delete
    - Test Proposal Review renders proposals and handles accept/reject/bulk
    - Test WebSocket notification triggers refresh
    - _Requirements: 1.1, 3.1_

- [x] 11. Integration wiring and final verification
  - [x] 11.1 Wire worker registration and ARQ cron schedule
    - Register `profile_enrichment_worker` in the ARQ worker configuration
    - Configure cron schedule for periodic scanning
    - Ensure on-demand scan API correctly enqueues ARQ job
    - Wire WebSocket manager integration for real-time notifications
    - _Requirements: 1.2_

  - [x] 11.2 Write integration tests for full scan-to-review flow
    - Test: configure source → trigger scan → proposals created → accept → profile updated → audit log written
    - Test: 3 consecutive failures → Dashboard notice emitted
    - Test: rejected proposal not re-proposed in next cycle
    - Test: privacy isolation — Consultant A's scan never surfaces in Consultant B's proposals
    - _Requirements: 1.2, 1.4, 2.2, 2.4, 3.2, 3.4_

- [x] 12. Final checkpoint — All tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 8 universal correctness properties defined in the design
- Unit tests validate specific examples and edge cases
- The system uses Python (FastAPI + async), PostgreSQL, Redis, ARQ, and React + Next.js as specified in the existing codebase
- All ORM models follow the existing pattern in `app/models/`
- The worker follows the existing ARQ pattern in `app/workers/`

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3", "2.1"] },
    { "id": 3, "tasks": ["2.2", "2.3", "3.1", "4.1"] },
    { "id": 4, "tasks": ["3.2", "3.3", "4.2", "4.3"] },
    { "id": 5, "tasks": ["6.1"] },
    { "id": 6, "tasks": ["6.2", "6.3", "6.4", "7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "7.4", "8.1"] },
    { "id": 8, "tasks": ["8.2", "8.3"] },
    { "id": 9, "tasks": ["8.4", "10.1", "10.2"] },
    { "id": 10, "tasks": ["10.3", "10.4", "11.1"] },
    { "id": 11, "tasks": ["11.2"] }
  ]
}
```
