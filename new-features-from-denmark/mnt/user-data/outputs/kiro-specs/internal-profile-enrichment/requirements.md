# Requirements Document

## Introduction

Internal Profile Enrichment applies the system's enrichment philosophy to its own side of the table. The system currently enriches external prospects via Apollo.io while Beneficiary profiles decay silently as consultants gain skills, publish work, and ship projects. This feature periodically scans each Consultant's configured public sources (GitHub, portfolio site, Google Scholar, and similar), discovers competencies not yet in the profile, and proposes additive-only updates with source attribution — never modifying existing content, and never merging without human approval. Richer profiles directly improve the LLM-relevance scoring factor, personalization quality, and gap analytics accuracy. Priority: P7.

## Glossary

- **Profile_Enrichment_Worker**: The new scheduled worker that scans a Consultant's configured public sources for competency evidence
- **Public_Source**: A user-configured URL associated with a Consultant: a GitHub profile, portfolio site, publication profile, or certification badge page
- **Competency_Proposal**: A candidate addition to a Consultant's profile: a skill, project, publication, certification, or course, with a pointer to the Public_Source evidence supporting it
- **Proposal_Review**: The human approval step in which a Consultant accepts, edits, or rejects each Competency_Proposal
- Existing terms (Beneficiary, baseline_assets, Dashboard, LLM_Router, enrichment cycle) are as defined in the system-redesign-v2 requirements document

## Requirements

### Requirement 1: Source Configuration and Scanning

**User Story:** As a Consultant user, I want my public professional presence scanned periodically, so that my profile stays current without manual upkeep.

#### Acceptance Criteria

1. THE System SHALL allow each Consultant to configure up to 10 Public_Sources in the Understand stage, each with a source type and URL
2. THE Profile_Enrichment_Worker SHALL scan each configured Public_Source on a schedule of once per 30 days by default (configurable per Consultant), and on demand when the Consultant triggers a scan
3. WHILE scanning, THE Profile_Enrichment_Worker SHALL throttle requests to a maximum of 1 request per second per source domain and SHALL respect a 15-second timeout per page fetch
4. IF a Public_Source is unreachable after 3 attempts, THEN THE Profile_Enrichment_Worker SHALL record the failure, skip the source for this cycle, and surface a notice in the Dashboard if the source has failed for 3 consecutive cycles

### Requirement 2: Competency Proposal Generation

**User Story:** As a Consultant user, I want discovered competencies proposed with evidence, so that I can trust and verify each suggested addition.

#### Acceptance Criteria

1. THE Profile_Enrichment_Worker SHALL extract candidate competencies from scanned content via the LLM_Router, covering: technologies evidenced by repositories or projects, publications, certifications, courses, and volunteer or community roles
2. THE Profile_Enrichment_Worker SHALL deduplicate candidates against the Consultant's existing profile assets and against previously rejected Competency_Proposals, proposing only genuinely new items
3. THE Profile_Enrichment_Worker SHALL attach to each Competency_Proposal: the Public_Source URL, the specific evidence (e.g. repository name and description, publication title), and a confidence level of "strong" (directly evidenced) or "inferred" (indirectly evidenced)
4. THE Profile_Enrichment_Worker SHALL NOT create proposals from any source not explicitly configured by the Consultant, and SHALL NOT scan sources concerning any person other than the Consultant who configured them

### Requirement 3: Human-Approved, Additive-Only Merge

**User Story:** As a Consultant user, I want full control over what enters my profile, so that automation never puts words in my mouth.

#### Acceptance Criteria

1. WHEN new Competency_Proposals exist, THE Dashboard SHALL present them in a Proposal_Review view in the Understand stage, allowing the Consultant to accept, edit-then-accept, or reject each proposal individually or in bulk
2. WHEN a proposal is accepted, THE System SHALL append it to the appropriate profile asset section with its source attribution, and SHALL NOT modify or delete any existing profile content under any circumstances
3. WHEN a proposal is rejected, THE System SHALL record the rejection so the same item is not re-proposed in future cycles
4. WHEN accepted proposals are merged, THE System SHALL record the profile change in an audit log entry containing the timestamp, the added content, and the evidence source
