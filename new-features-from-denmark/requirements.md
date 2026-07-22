# Requirements Document

## Introduction

The Review Critique Loop introduces a second, independent LLM evaluation pass over every generated outreach material (CV, cover letter, cold email, proposal) before it can advance in the pipeline. The Personalization_Engine currently generates materials in a single pass; a fresh-context reviewer reliably catches generic phrasing, missed opportunity keywords, weak framing, and tone mismatches that the drafting pass cannot see. The reviewer is grounded in the prospect's existing Enrichment_Record rather than live research, and returns feedback in a machine-applicable structured format so revisions can be applied programmatically. Priority: P1 (implement together with claim-grounding-verification, sharing the same insertion point in the prepare pipeline).

## Glossary

- **Review_Service**: The new service that dispatches a fresh-context LLM critique of a drafted material and applies the resulting revisions
- **Structured_Edit**: A machine-applicable revision instruction containing a target material identifier, an exact `old_string`, a replacement `new_string`, and a one-line reason
- **Narrative_Finding**: A prose critique item that requires drafter judgment rather than mechanical replacement, assigned to one of four fixed categories
- **Review_Cycle**: One complete critique-and-revise iteration (reviewer critique followed by application of revisions)
- **Draft_Material**: The output of a prepare technique (tailored_cv, tailored_cover_letter, draft_email, or proposal) prior to review
- Existing terms (Personalization_Engine, LLM_Router, Enrichment_Record, Beneficiary, Schema_Registry, Pipeline states) are as defined in the system-redesign-v2 requirements document

## Requirements

### Requirement 1: Fresh-Context Reviewer Dispatch

**User Story:** As a Consultant or Team user, I want every generated material critiqued by an independent reviewer pass, so that generic phrasing and missed opportunities are caught before I see the draft.

#### Acceptance Criteria

1. WHEN a prepare technique produces a Draft_Material, THE Review_Service SHALL dispatch a critique request via the LLM_Router within 10 seconds of draft completion
2. THE Review_Service SHALL construct the critique prompt from a fresh context containing only: the Draft_Material text inline, the opportunity description, the prospect's Enrichment_Record (firmographics, technographics, Intent_Signals, contact seniority), and the Beneficiary's profile assets — and SHALL NOT include the drafting pass's conversation, prompt, or reasoning
3. THE Review_Service SHALL instruct the reviewer to critique against four fixed categories: missed keywords/requirements, company-specific angles derived from the Enrichment_Record, action-oriented reframing of passive or generic statements, and tone/style issues
4. THE Review_Service SHALL require the reviewer to report on every category even when a category has no findings, recording an explicit "no issues" result for that category
5. IF the critique LLM call fails or times out after 60 seconds, THEN THE Review_Service SHALL retry up to 2 times, and IF all attempts fail, THEN THE Review_Service SHALL mark the material as "unreviewed", allow it to proceed, and surface the failure in the Dashboard "Requires Action" section

### Requirement 2: Structured Edit Format

**User Story:** As a system maintainer, I want reviewer feedback returned in a machine-applicable format, so that revisions are applied deterministically without a second free-form generation pass.

#### Acceptance Criteria

1. THE Review_Service SHALL require the reviewer to return feedback in two parts: a JSON array of Structured_Edits, and a set of Narrative_Findings grouped by the four fixed categories
2. THE Review_Service SHALL require each Structured_Edit to contain: the target material identifier, an `old_string` quoted exactly from the Draft_Material, a `new_string` replacement, and a one-line reason classified as one of: keyword_match, company_angle, reframing, or style
3. WHEN applying Structured_Edits, THE Review_Service SHALL verify that each `old_string` matches the current material text exactly once, and IF an `old_string` matches zero times or more than once, THEN THE Review_Service SHALL skip that edit and log it with reason "ambiguous_or_stale_target"
4. THE Review_Service SHALL discard any Structured_Edit or Narrative_Finding that introduces a skill, achievement, credential, client name, or metric not present in the Beneficiary's profile assets, logging the discard with reason "ungrounded_suggestion"
5. WHEN Narrative_Findings require judgment-based revision, THE Review_Service SHALL dispatch a single revision request to the LLM_Router containing the current material text and the Narrative_Findings, instructing targeted revision only of the flagged passages

### Requirement 3: Review Cycle Control

**User Story:** As a Consultant or Team user, I want the review loop bounded and observable, so that materials are improved without unbounded LLM cost or latency.

#### Acceptance Criteria

1. THE Review_Service SHALL execute exactly 1 Review_Cycle per material by default, with the maximum number of cycles configurable per prepare technique in the Schema_Registry up to a limit of 3
2. WHEN a Review_Cycle completes, THE Review_Service SHALL recompute the material's quality score and record in the reasoning_log: the count of Structured_Edits applied, skipped, and discarded, the Narrative_Findings by category, and the quality score before and after revision
3. WHEN all Review_Cycles complete, THE Review_Service SHALL transition the material to its normal post-prepare pipeline state (e.g. Personalise) carrying a review status of "reviewed", "unreviewed", or "review_failed"
4. THE Dashboard SHALL display the review status and the count of applied revisions on each pipeline record's detail view
5. WHILE a batch of more than 10 materials is queued for review, THE Review_Service SHALL process critique requests with a maximum concurrency of 3 to bound LLM API load

### Requirement 4: Schema-Driven Wiring

**User Story:** As a system maintainer, I want review behavior declared in the schema, so that adding or tuning review for an opportunity type is a configuration change, not a code change.

#### Acceptance Criteria

1. THE Schema_Registry SHALL support a `review_techniques` section in which each entry declares: an id, a service class, the four critique categories (extensible per technique), and the maximum Review_Cycles
2. THE Schema_Registry SHALL allow each prepare technique to reference a review technique by id via an optional `review_technique` field, and IF the field is absent, THEN THE System SHALL skip review for materials produced by that prepare technique
3. WHEN the schema is loaded, THE Schema_Registry SHALL validate that every `review_technique` reference resolves to a declared review technique, failing startup with a descriptive error if not
