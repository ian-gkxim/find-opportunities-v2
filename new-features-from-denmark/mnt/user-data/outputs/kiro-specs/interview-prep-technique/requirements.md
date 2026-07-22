# Requirements Document

## Introduction

The Interview Prep Technique makes the Interview pipeline state productive. Today a record entering Interview triggers nothing; this feature adds a prepare technique that generates a grounded preparation pack the moment an opportunity reaches that state — likely interview questions derived from the opportunity's requirements, STAR-format talking points drawn strictly from the Consultant's verified profile, a company briefing assembled from the existing Enrichment_Record, and suggested questions for the Consultant to ask. All Beneficiary-side content passes through the Grounding_Verifier so the pack never coaches a consultant to claim something untrue. Priority: P8.

## Glossary

- **Interview_Prep_Service**: The new prepare technique service that generates an Interview_Prep_Pack
- **Interview_Prep_Pack**: The generated preparation document containing likely questions, STAR talking points, a company briefing, and questions to ask
- **STAR_Talking_Point**: A Situation–Task–Action–Result narrative constructed from the Consultant's profile, mapped to a specific anticipated question or opportunity requirement
- Existing terms (Enrichment_Record, Grounding_Verifier, Pipeline states, Schema_Registry, LLM_Router, tailored_cv) are as defined in the system-redesign-v2 and claim-grounding-verification requirements documents

## Requirements

### Requirement 1: Trigger and Inputs

**User Story:** As a Consultant user, I want prep material generated automatically when I land an interview, so that preparation starts the moment the pipeline state changes.

#### Acceptance Criteria

1. WHEN a pipeline record transitions into the Interview state, THE Interview_Prep_Service SHALL generate an Interview_Prep_Pack within 120 seconds
2. THE Interview_Prep_Service SHALL construct generation context from: the opportunity description, the tailored_cv and tailored_cover_letter actually submitted for this record, the prospect's Enrichment_Record (including Intent_Signals and technology stack), and the Consultant's profile assets including STAR example material where present
3. WHERE the submitted materials for the record are unavailable, THE Interview_Prep_Service SHALL proceed using the profile assets alone and note the omission in the pack

### Requirement 2: Pack Content

**User Story:** As a Consultant user, I want a complete, specific prep pack, so that I walk in knowing what they will ask and what I will say.

#### Acceptance Criteria

1. THE Interview_Prep_Service SHALL generate: between 8 and 15 likely interview questions derived from the opportunity's stated requirements and responsibilities; one STAR_Talking_Point for each of the 5 most probable competency questions; a company briefing of at most 400 words synthesized from the Enrichment_Record; and between 3 and 6 informed questions for the Consultant to ask, grounded in the Enrichment_Record
2. THE Interview_Prep_Service SHALL construct every STAR_Talking_Point exclusively from the Consultant's profile assets, and WHERE the opportunity demands a competency the profile does not evidence, THE Interview_Prep_Service SHALL include an honest gap-handling note suggesting how to frame adjacent experience rather than a fabricated narrative
3. WHEN the Interview_Prep_Pack is generated, THE Grounding_Verifier SHALL verify all Beneficiary-side claims in the pack, and IF ungrounded claims are found, THEN THE Interview_Prep_Service SHALL regenerate the affected talking points once with an exclusion constraint before surfacing any remaining flags to the user

### Requirement 3: Delivery and Schema Wiring

**User Story:** As a system maintainer, I want interview prep declared as a schema-level prepare technique, so that it can be attached to any opportunity type with an Interview state.

#### Acceptance Criteria

1. THE Schema_Registry SHALL support declaring an `interview_preparation` prepare technique with its inputs and the Interview_Prep_Pack output, attachable to any opportunity type whose pipeline_states include Interview, triggered on state entry rather than at material-preparation time
2. THE Dashboard SHALL present the Interview_Prep_Pack on the pipeline record's detail view, with an action to regenerate the pack on demand (e.g. after profile updates or a rescheduled interview round)
3. IF pack generation fails after 2 retries, THEN THE System SHALL surface the failure in the Dashboard "Requires Action" section without blocking any pipeline transition
