# Requirements Document

## Introduction

Claim Grounding Verification ensures that no generated outreach material asserts a skill, achievement, credential, client engagement, or quantified result that cannot be traced to the Beneficiary's verified profile assets. The current quality score rewards referencing more enrichment data but performs no truthfulness check, creating pressure toward fabrication at volume. This feature adds a deterministic gate: claims are extracted from every Draft_Material, verified against profile sources, and ungrounded claims block pipeline advancement until resolved. Genuine gaps are acknowledged and reframed, never papered over. Priority: P2 (implement together with review-critique-loop).

## Glossary

- **Grounding_Verifier**: The new service that extracts factual claims from generated materials and verifies each against the Beneficiary's profile assets
- **Claim**: A discrete factual assertion in a material about the Beneficiary: a skill or technology proficiency, an achievement or outcome, a quantified metric, a credential or certification, a named client or employer, or a duration of experience
- **Grounding_Status**: The verification outcome for a Claim: "grounded" (traceable to a profile source), "partially_grounded" (supported but overstated or imprecise), or "ungrounded" (no supporting source)
- **Grounding_Report**: The structured record of all Claims in a material with their Grounding_Status and source pointers
- Existing terms (Personalization_Engine, Review_Service, Beneficiary, baseline_assets, Pipeline states, reasoning_log) are as defined in the system-redesign-v2 and review-critique-loop requirements documents

## Requirements

### Requirement 1: Claim Extraction

**User Story:** As a Team user, I want every factual claim in outgoing materials identified automatically, so that nothing asserted about our consultants or firm goes unchecked.

#### Acceptance Criteria

1. WHEN a Draft_Material completes its final Review_Cycle (or completes generation where no review technique is configured), THE Grounding_Verifier SHALL extract all Claims from the material via a single LLM_Router call within 60 seconds
2. THE Grounding_Verifier SHALL extract Claims in the categories: skill/technology proficiency, achievement/outcome, quantified metric, credential/certification, named client/employer, and experience duration
3. THE Grounding_Verifier SHALL record each Claim with its exact source text span in the material, so that flagged claims can be highlighted in the UI
4. IF claim extraction fails after 2 retries, THEN THE Grounding_Verifier SHALL mark the material "grounding_unverified" and surface it in the Dashboard "Requires Action" section without blocking pipeline advancement

### Requirement 2: Verification Against Profile Sources

**User Story:** As a Consultant user, I want each claim checked against my actual profile, so that materials sent in my name never overstate my experience.

#### Acceptance Criteria

1. THE Grounding_Verifier SHALL verify each Claim against the Beneficiary's baseline_assets and offerings assets (resume, cover_letter baseline, consultant_profiles for Consultant; company_profile, capability_statement, company_documents for Team), assigning a Grounding_Status and, for grounded and partially_grounded Claims, a pointer to the supporting asset and passage
2. THE Grounding_Verifier SHALL treat prospect-side facts sourced from the Enrichment_Record (company size, industry, technology stack, intent topics) as exempt from Beneficiary grounding, verifying them instead against the Enrichment_Record
3. THE Grounding_Verifier SHALL classify a quantified metric as "partially_grounded" when the profile supports the underlying achievement but not the specific number, and SHALL include the discrepancy in the Grounding_Report
4. THE Grounding_Verifier SHALL store the complete Grounding_Report in the material's reasoning_log

### Requirement 3: Pipeline Gate

**User Story:** As a Team user, I want ungrounded claims to block sending, so that fabricated content cannot reach a prospect through automation.

#### Acceptance Criteria

1. IF a material contains one or more Claims with Grounding_Status "ungrounded", THEN THE System SHALL block the material's pipeline transition into any of the states Approve, Applied, Sent, or Proposal Submitted, and SHALL surface the material in the Dashboard "Requires Action" section listing each ungrounded Claim with its source text span
2. WHEN a user resolves a flagged material, THE System SHALL offer three resolution paths: regenerate the flagged passages with an explicit constraint excluding the ungrounded content, manually edit the material, or confirm the claim as true and add the supporting fact to the relevant profile asset
3. WHEN a resolution path completes, THE Grounding_Verifier SHALL re-verify only the affected Claims within 30 seconds and unblock the pipeline transition if no ungrounded Claims remain
4. IF a material contains only "partially_grounded" Claims and no "ungrounded" Claims, THEN THE System SHALL permit pipeline advancement while displaying a warning badge on the pipeline record

### Requirement 4: Generation-Time Prevention

**User Story:** As a system maintainer, I want fabrication discouraged at generation time, so that the gate rarely needs to fire.

#### Acceptance Criteria

1. THE Personalization_Engine SHALL include in every generation prompt an explicit instruction that all Beneficiary claims must be traceable to the provided profile assets, and that genuine gaps against the opportunity's requirements must be acknowledged and reframed using adjacent experience rather than invented
2. THE Analytics_Service SHALL track the ungrounded-claim rate per prepare technique per week, and THE Dashboard SHALL display this rate in the Reports stage so that prompt regressions are observable
