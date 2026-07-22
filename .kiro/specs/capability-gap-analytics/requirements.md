# Requirements Document

## Introduction

Capability Gap Analytics answers the question conversion metrics cannot: *why* are opportunities being lost or scored low, and which missing capabilities would unlock the most pipeline value if acquired? The feature aggregates requirements from lost, rejected, and low-tier opportunities over a rolling window, diffs them against Beneficiary capability profiles, and produces a prioritized gap heatmap with estimated blocked pipeline value — at both the individual Consultant level and the aggregated firm level. It runs as part of the nightly analytics cycle and on demand. Priority: P4.

## Glossary

- **Gap_Analyzer**: The new analytics component that extracts required capabilities from opportunities and diffs them against Beneficiary capability profiles
- **Capability**: A normalized skill, technology, methodology, domain expertise, or certification extracted from an opportunity description
- **Gap**: A Capability required by one or more analyzed opportunities that is absent from (or weak in) the relevant Beneficiary's profile
- **Gap_Heatmap**: The report ranking Gaps by frequency of occurrence and estimated blocked pipeline value
- **Blocked_Pipeline_Value**: The sum of estimated opportunity values (or, where value is unknown, a count weighted by Account_Score tier) of analyzed opportunities requiring a given Gap
- **Analysis_Window**: The rolling period of opportunities included in aggregate analysis, default 90 days
- Existing terms (Analytics_Service, Scoring_Engine, Account_Score, Beneficiary, LLM_Router, Dashboard) are as defined in the system-redesign-v2 requirements document

## Requirements

### Requirement 1: Capability Extraction and Normalization

**User Story:** As a Team user, I want the capabilities demanded by our target market extracted from real opportunities, so that gap analysis reflects actual demand rather than guesswork.

#### Acceptance Criteria

1. WHEN the nightly analytics cycle runs, THE Gap_Analyzer SHALL extract Capabilities via the LLM_Router from every opportunity within the Analysis_Window that is in a Rejected or Lost pipeline state, or that carries a C-tier or D-tier Account_Score, distinguishing required from preferred capabilities
2. THE Gap_Analyzer SHALL normalize extracted Capabilities to canonical names, merging synonyms and aliases (e.g. "K8s" and "Kubernetes") into a single Capability, and SHALL cache extraction results per opportunity so that an opportunity is extracted at most once
3. WHILE processing a nightly batch, THE Gap_Analyzer SHALL bound LLM extraction calls to a configurable maximum per run (default 200 opportunities), processing the most recent opportunities first and carrying the remainder to the next cycle

### Requirement 2: Gap Computation

**User Story:** As a Consultant user, I want my personal skill gaps identified and weighted, so that I know which single skill would have qualified me for the most opportunities.

#### Acceptance Criteria

1. THE Gap_Analyzer SHALL diff the normalized Capability demand against each Consultant's profile assets individually, and against the union of all Consultant profiles plus Team capability assets for the firm-level analysis
2. THE Gap_Analyzer SHALL compute for each Gap: the count of opportunities requiring it within the Analysis_Window, the Blocked_Pipeline_Value, and a classification of "hard gap" (capability absent) or "soft gap" (capability present but junior-level or unevidenced relative to the requirement)
3. WHEN a Gap appears in an opportunity where it was the only unmet required Capability, THE Gap_Analyzer SHALL flag it as a "single-blocker" Gap and weight it 2x in the Gap_Heatmap ranking

### Requirement 3: Reporting

**User Story:** As a Team user, I want a gap heatmap in the Reports stage, so that capability investment decisions are grounded in pipeline data.

#### Acceptance Criteria

1. THE Dashboard SHALL display the Gap_Heatmap in the Reports stage, filterable by Beneficiary (individual Consultant or firm-level) and by opportunity type, showing at most the top 25 Gaps ranked by Blocked_Pipeline_Value descending
2. WHEN a new Gap_Heatmap is produced, THE Gap_Analyzer SHALL compute a diff against the previous report, marking each Gap as new, growing, shrinking, or resolved
3. WHEN a user requests it for a specific Gap, THE Gap_Analyzer SHALL generate a learning recommendation via the LLM_Router containing suggested study resources and a rough effort estimate, clearly labeled as advisory
4. WHEN a user triggers an on-demand analysis for a single opportunity URL or pipeline record, THE Gap_Analyzer SHALL produce a targeted gap report for that opportunity against a selected Consultant within 120 seconds
5. THE Analytics_Service SHALL notify connected Dashboard clients via WebSocket when a new Gap_Heatmap is available
