# Requirements Document

## Introduction

GKIM Opportunity Finder v2 is a comprehensive redesign of the existing local opportunity-finding platform. The v2 system retains the proven schema-driven architecture, multi-beneficiary model, and LLM-powered evaluation from v1, while introducing Apollo.io for B2B enrichment, enhanced Lemlist multi-channel sequencing, a dashboard-first UX, and conversion analytics. The goal is to dramatically improve discovery accuracy, personalization depth, outreach effectiveness, and conversion rates for both Consultant and Team beneficiaries.

## Glossary

- **System**: The GKIM Opportunity Finder v2 application
- **Apollo_Client**: The integration layer communicating with the Apollo.io API for B2B enrichment, contact discovery, intent signals, and account scoring
- **Lemlist_Engine**: The integration layer communicating with the Lemlist API for multi-channel sequence management, A/B testing, and response tracking
- **Discovery_Pipeline**: The orchestration service that coordinates opportunity discovery across all configured sources (Adzuna, Apollo, internet search, project marketplaces)
- **Scoring_Engine**: The service responsible for computing composite opportunity scores by combining LLM relevance, Apollo enrichment signals, and historical conversion data
- **Personalization_Engine**: The service that generates tailored outreach materials (CVs, cover letters, proposals, emails) using Apollo enrichment data and LLM capabilities
- **Analytics_Service**: The service that computes funnel metrics, conversion rates, A/B test outcomes, and ROI tracking data
- **Dashboard**: The primary UI view providing at-a-glance pipeline status, actionable insights, and conversion metrics
- **Sequence**: An ordered series of multi-channel outreach steps (email, LinkedIn, call) managed by the Lemlist_Engine
- **Enrichment_Record**: A structured data object containing Apollo-sourced firmographic, technographic, and contact data for a prospect company or individual
- **Intent_Signal**: A data point from Apollo indicating a prospect's active interest in topics relevant to the beneficiary's offerings
- **Account_Score**: A composite numeric score (0–100) indicating how well a prospect matches the ideal customer profile, derived from Apollo data and LLM evaluation
- **Beneficiary**: Either a Consultant (individual pursuing roles) or Team (firm pursuing contracts)
- **Schema_Registry**: The YAML-based single source of truth that drives navigation, pipeline states, technique wiring, and data model structure
- **Conversion_Funnel**: The sequence of pipeline stages from discovery through to outcome (accepted/won), with drop-off tracking at each stage
- **Touchpoint**: A single interaction within a Sequence (one email send, one LinkedIn connection request, one phone call)

## Requirements

### Requirement 1: Apollo.io Account Enrichment

**User Story:** As a Consultant or Team user, I want prospect companies automatically enriched with firmographic and technographic data from Apollo.io, so that I can make informed decisions about which opportunities to pursue.

#### Acceptance Criteria

1. WHEN a new prospect company is discovered by the Discovery_Pipeline, THE Apollo_Client SHALL request enrichment data from Apollo.io within 30 seconds of discovery
2. THE Apollo_Client SHALL store the Enrichment_Record containing company size (employee count), revenue range, industry classification, technology stack (as a list of technology names), funding stage, and headquarters location (city, country)
3. IF the Apollo.io API returns an error or times out after 15 seconds, THEN THE Apollo_Client SHALL mark the Enrichment_Record as "pending_retry" and schedule a retry within 5 minutes, up to a maximum of 3 retry attempts
4. IF all retry attempts are exhausted without a successful response, THEN THE Apollo_Client SHALL mark the Enrichment_Record as "enrichment_failed" and surface the company in the Dashboard "Requires Action" section
5. IF the Apollo.io API returns no matching company, THEN THE Apollo_Client SHALL mark the Enrichment_Record as "not_found" and log the company name to the application log for manual review
6. WHILE the System is processing a batch of more than 20 companies, THE Apollo_Client SHALL throttle requests to a maximum of 5 per second to respect Apollo.io rate limits
7. IF an Enrichment_Record already exists for a company and is older than 30 days, THEN THE Apollo_Client SHALL refresh the enrichment data on the next scheduled enrichment cycle

### Requirement 2: Apollo.io Contact Discovery

**User Story:** As a Consultant or Team user, I want to automatically find decision-maker contacts at prospect companies, so that I can direct outreach to the right people.

#### Acceptance Criteria

1. WHEN an Enrichment_Record is successfully stored for a prospect company, THE Apollo_Client SHALL search for contacts matching configured decision-maker titles (CEO, CTO, VP Engineering, Founder, Head of Delivery) within 30 seconds
2. THE Apollo_Client SHALL store up to 5 contacts per company, prioritized by title seniority and email verification status, each containing full name and job title as required fields, and email address, LinkedIn URL, and phone number as optional fields, storing only contacts that have at least an email address or LinkedIn URL
3. IF no contacts matching decision-maker titles are found, THEN THE Apollo_Client SHALL broaden the search to include director-level titles (Director of Engineering, Director of Technology, Director of Operations, Director of Sales, Director of Delivery) and store results with a "broadened_search" flag
4. IF no contacts are found after broadening, THEN THE Apollo_Client SHALL mark the company as "contacts_unavailable" and surface the company in the Dashboard for manual research
5. THE Apollo_Client SHALL flag email addresses with a verification status of "verified", "unverified", or "catch_all" as returned by Apollo.io
6. IF the Apollo.io API returns an error or times out after 15 seconds during contact search, THEN THE Apollo_Client SHALL mark the contact search as "pending_retry" and schedule a retry within 5 minutes, up to a maximum of 3 retry attempts before marking the company as "contacts_unavailable"

### Requirement 3: Apollo.io Intent Signals

**User Story:** As a Consultant or Team user, I want to see which prospect companies are actively showing buying intent for services I offer, so that I can prioritize high-probability outreach.

#### Acceptance Criteria

1. WHEN enrichment is complete for a prospect company, THE Apollo_Client SHALL query Apollo.io for Intent_Signals matching configured topic keywords derived from the beneficiary's offerings, storing up to 20 Intent_Signals per company
2. THE Apollo_Client SHALL store each Intent_Signal with the topic name, signal strength (strong, moderate, weak), and detection date
3. WHEN a company has one or more Intent_Signals with strength "strong", THE Scoring_Engine SHALL add a single priority boost of 15 points to that company's Account_Score regardless of how many strong signals exist
4. THE Dashboard SHALL display companies with Intent_Signals detected within the last 30 days in a dedicated "Hot Prospects" section, sorted by signal strength descending then by detection date descending, showing a maximum of 50 companies
5. IF Intent_Signal data is older than 30 days, THEN THE Apollo_Client SHALL refresh the signal data on the next scheduled enrichment cycle
6. IF the Apollo.io intent signal query returns an error or times out after 15 seconds, THEN THE Apollo_Client SHALL mark the intent data as "pending_retry" and schedule a retry within 5 minutes

### Requirement 4: Account Scoring

**User Story:** As a Consultant or Team user, I want each prospect company scored on how well it matches my ideal target profile, so that I can focus effort on the highest-value opportunities.

#### Acceptance Criteria

1. WHEN an Enrichment_Record is complete for a prospect company, THE Scoring_Engine SHALL compute an Account_Score as an integer between 0 and 100 by normalizing each scoring factor to a sub-score of 0–100 and applying the configured weight distribution
2. THE Scoring_Engine SHALL derive the Account_Score from weighted factors: firmographic fit (default 30%), technographic overlap (default 25%), intent signals (default 20%), LLM relevance assessment (default 15%), and historical conversion rate for similar companies (default 10%)
3. THE Scoring_Engine SHALL allow users to configure the weight distribution across the five scoring factors through the System settings, enforcing that each weight is an integer between 0 and 100 and the total of all five weights equals 100
4. WHEN a user adjusts scoring weights, THE Scoring_Engine SHALL recompute Account_Scores for all prospects not in a terminal pipeline state (Converted, Won, Lost, or Abandoned) within 60 seconds
5. THE Dashboard SHALL categorize prospects into tiers: "A-tier" (score 75–100), "B-tier" (score 50–74), "C-tier" (score 25–49), and "D-tier" (score 0–24)
6. IF one or more scoring factor data points are unavailable for a prospect at the time of scoring, THEN THE Scoring_Engine SHALL compute the Account_Score using only the available factors, redistributing the missing factors' weights proportionally among the remaining factors, and SHALL flag the score in the Dashboard as "partial" indicating which factors were missing

### Requirement 5: Enhanced Lemlist Sequence Management

**User Story:** As a Consultant or Team user, I want to create and manage multi-step, multi-channel outreach sequences through Lemlist, so that I can automate follow-up and increase response rates.

#### Acceptance Criteria

1. THE Lemlist_Engine SHALL support creating Sequences with up to 10 steps, where each step specifies a channel (email, LinkedIn, manual task), a delay interval between 1 and 30 days, and a content template of up to 5000 characters
2. WHEN a user creates a new Sequence, THE Lemlist_Engine SHALL synchronize the sequence definition to Lemlist via API within 10 seconds
3. IF synchronization to Lemlist fails (API error or timeout after 10 seconds), THEN THE Lemlist_Engine SHALL mark the Sequence as "sync_failed", display the error in the Dashboard, and allow the user to retry synchronization
4. THE Lemlist_Engine SHALL support enrolling individual prospects or batch-enrolling up to 200 prospects matching a filter (by Account_Score tier, opportunity type, or intent signal presence) in a single operation
5. WHILE a Sequence is active, THE Lemlist_Engine SHALL track the delivery status of each Touchpoint (sent, opened, clicked, replied, bounced)
6. WHEN a prospect replies to any Touchpoint in a Sequence, THE Lemlist_Engine SHALL pause the sequence for that prospect and create a notification in the Dashboard within 60 seconds

### Requirement 6: Lemlist A/B Testing

**User Story:** As a user, I want to A/B test different outreach message variants within a sequence, so that I can identify which messaging drives the highest response rates.

#### Acceptance Criteria

1. THE Lemlist_Engine SHALL support creating between 2 and 4 variants (A, B, C, D) for any Touchpoint within a Sequence
2. WHEN a Touchpoint has multiple variants, THE Lemlist_Engine SHALL distribute prospects across variants using random assignment such that each variant receives an equal share within a tolerance of ±5 percentage points after at least 40 total assignments
3. THE Analytics_Service SHALL compute per-variant metrics (open rate, click rate, reply rate) within 24 hours of a variant reaching the minimum sample size of 20 sends, and update metrics daily thereafter
4. WHEN one variant achieves a reply rate at least 2 percentage points higher than every other variant with statistical confidence of 90%, THE Analytics_Service SHALL flag that variant as "winner" in the Dashboard
5. THE Lemlist_Engine SHALL support manual promotion of any variant to 100% allocation for subsequent enrollees, while prospects already assigned to other variants continue their current variant to completion
6. IF no variant achieves statistical significance after all variants have reached 100 sends each, THEN THE Analytics_Service SHALL flag the test as "inconclusive" in the Dashboard

### Requirement 7: Lemlist Response Tracking and Feedback Loop

**User Story:** As a user, I want outreach responses automatically tracked and fed back into the system, so that the pipeline reflects real engagement and the system learns from outcomes.

#### Acceptance Criteria

1. THE Lemlist_Engine SHALL poll Lemlist for response events (replies, bounces, out-of-office, and unsubscribes) every 5 minutes and update the corresponding pipeline record status accordingly
2. WHEN a prospect reply is detected that is not an auto-reply, bounce, or unsubscribe, THE System SHALL advance the pipeline record from "Sent" to "Replied" automatically
3. WHEN a prospect books a meeting (detected via calendar link click or manual marking), THE System SHALL advance the pipeline record to "Meeting Booked" regardless of whether the current status is "Sent" or "Replied"
4. IF the Lemlist API is unreachable or returns an error during a poll cycle, THEN THE Lemlist_Engine SHALL retry on the next scheduled poll interval and log the failure, without altering any pipeline record status
5. THE Analytics_Service SHALL compute response rates (number of replies divided by number of successfully delivered sends) per Sequence, per beneficiary, per opportunity type, and per Account_Score tier, refreshed every 60 minutes
6. IF a Sequence achieves a response rate below 2% after a minimum of 50 successfully delivered sends, THEN THE System SHALL display a recommendation in the Dashboard "Requires Action" section to revise the messaging or targeting for that Sequence

### Requirement 8: Dashboard-First UX

**User Story:** As a user, I want a dashboard as my primary entry point that shows pipeline health, actionable insights, and key metrics at a glance, so that I can quickly understand what needs attention.

#### Acceptance Criteria

1. WHEN a user opens the System, THE Dashboard SHALL display within 2 seconds showing: active pipeline counts by stage, conversion rates for the last 30 days, and top 5 highest-scored pending prospects
2. THE Dashboard SHALL display a "Requires Action" section listing prospects with stale follow-ups (no activity for 7+ days), failed sequences, and enrichment errors
3. THE Dashboard SHALL display separate pipeline summaries for each Beneficiary (Consultant and Team) with the ability to toggle between them
4. WHEN any pipeline record changes status, THE Dashboard SHALL reflect the update within 10 seconds without requiring a page refresh
5. THE Dashboard SHALL include a "Quick Actions" panel allowing users to: enroll prospects in sequences, approve drafted materials, and trigger manual discovery runs with a single click

### Requirement 9: Conversion Funnel Analytics

**User Story:** As a user, I want to see detailed conversion funnel metrics from discovery through to outcome, so that I can identify bottlenecks and optimize my process.

#### Acceptance Criteria

1. THE Analytics_Service SHALL compute stage-to-stage conversion rates for each opportunity type's pipeline, recalculated once daily by 02:00 UTC, expressed as a percentage with one decimal place precision
2. THE Analytics_Service SHALL compute average time spent in each pipeline stage (in calendar days, rounded to one decimal), per opportunity type and per beneficiary, based only on records that have completed the transition out of that stage within the selected time period
3. THE Analytics_Service SHALL display a visual funnel chart showing the count of records entering each stage and the drop-off percentage between consecutive stages, for a user-selected time period (7, 30, or 90 days), filterable by opportunity type and beneficiary
4. WHEN conversion rate at any stage drops below its 30-day trailing average by more than 20%, THE Analytics_Service SHALL generate an alert displayed in the Dashboard, limited to one alert per stage per day to avoid duplicate notifications
5. THE Analytics_Service SHALL track and display first-touch source attribution for positive-outcome opportunities (Converted for Consultant, Won for Team), showing the originating discovery channel and the Sequence that produced the first prospect response
6. IF a pipeline stage contains fewer than 5 records within the selected time period, THEN THE Analytics_Service SHALL display the computed metrics with an "insufficient data" indicator and exclude that stage from alert threshold evaluation

### Requirement 10: Improved Discovery Pipeline with Multi-Source Scoring

**User Story:** As a user, I want the discovery pipeline to combine results from multiple sources (Apollo, Adzuna, internet search) with intelligent scoring and deduplication, so that I get higher-quality prospects with less noise.

#### Acceptance Criteria

1. THE Discovery_Pipeline SHALL support four source types: Adzuna API, Apollo.io company search, internet search (via configured search backend), and project marketplace APIs
2. WHEN the Discovery_Pipeline discovers a prospect matching an existing record by company domain name or normalized company name, THE System SHALL merge the records by retaining the most recent value for each enrichment field, combine enrichment data from all sources, and assign a "multi-source confidence" bonus of 10 points to the Account_Score for each additional source (maximum 30 bonus points for 4 sources)
3. THE Discovery_Pipeline SHALL apply the Scoring_Engine to all discovered prospects before surfacing them in the pipeline, filtering out prospects with an Account_Score below a user-configurable minimum threshold (default: 25, configurable range: 0 to 100)
4. THE Discovery_Pipeline SHALL execute discovery runs on a configurable schedule (hourly, daily, or manual) independently per source type, with each run completing or timing out within 5 minutes
5. IF the Discovery_Pipeline encounters 3 consecutive source failures (defined as API error responses, network timeouts exceeding 30 seconds, or authentication failures) for a source, THEN THE System SHALL suspend that source, send a notification to the Dashboard, and attempt recovery after a 1-hour backoff period
6. IF a suspended source fails recovery 3 consecutive times, THEN THE System SHALL mark that source as "permanently_suspended" and surface it in the Dashboard "Requires Action" section for manual intervention

### Requirement 11: Enhanced Personalization Engine

**User Story:** As a user, I want outreach materials (CVs, cover letters, proposals, emails) personalized using Apollo enrichment data combined with LLM generation, so that each piece of communication feels tailored and relevant.

#### Acceptance Criteria

1. WHEN generating outreach materials for a prospect, THE Personalization_Engine SHALL incorporate the prospect's Enrichment_Record (industry, tech stack, company size, recent funding, intent signals) into the LLM prompt context and return the generated material within 30 seconds
2. WHEN generating outreach materials for a prospect whose Enrichment_Record contains identified hooks (recent news, job postings, technology adoption signals), THE Personalization_Engine SHALL reference at least one hook in the generated content
3. IF the prospect's Enrichment_Record contains fewer than 3 populated data fields, THEN THE Personalization_Engine SHALL proceed with generation using available data and automatically assign a personalization quality score reflecting the limited data
4. WHEN generating outreach materials, THE Personalization_Engine SHALL adapt tone based on the target contact's seniority level: C-suite contacts receive company-vision and ROI-focused language; director-level contacts receive implementation-focused and team-impact language; manager-level and below contacts receive hands-on and collaboration-focused language
5. WHEN a piece of outreach material is generated, THE Personalization_Engine SHALL compute a personalization quality score (0–100) calculated as the percentage of available Enrichment_Record fields (industry, tech stack, company size, recent funding, intent signals, hooks) that are referenced in the generated content, scaled to the 0–100 range
6. IF the personalization quality score is below 40, THEN THE Personalization_Engine SHALL flag the material in the Dashboard as "low personalization" and list up to 3 specific Enrichment_Record fields that are available but were not incorporated
7. IF the target contact's seniority level is not available in the Enrichment_Record, THEN THE Personalization_Engine SHALL default to director-level tone and flag the material with "seniority_unknown" for user review

### Requirement 12: Schema-Driven Architecture Retention

**User Story:** As a developer, I want the v2 system to retain the schema-driven architecture from v1 so that adding new beneficiaries, opportunity types, and pipeline states remains a configuration change rather than a code change.

#### Acceptance Criteria

1. THE Schema_Registry SHALL serve as the single source of truth for navigation structure, pipeline state machines, technique wiring, and beneficiary definitions, such that no navigation route, pipeline state, or technique binding is defined outside the YAML configuration
2. WHEN a new opportunity type is added to the Schema_Registry, THE System SHALL derive navigation routes, pipeline states, and technique bindings from the new entry upon application startup without requiring code changes
3. THE Schema_Registry SHALL support declaring new beneficiaries by requiring at minimum: a unique id, label, description, at least one baseline_assets entry, an offerings_asset identifier, an offerings_label, and a search_criteria_asset identifier through YAML configuration alone
4. THE Schema_Registry SHALL support declaring find techniques, prepare techniques, and outreach techniques each requiring at minimum: a unique id, a service_class name that maps to an importable class, and a description
5. WHEN the Schema_Registry is modified, THE System SHALL validate the schema structure at startup by checking: presence of all required top-level keys, valid cross-references between opportunity types and their declared beneficiaries, valid cross-references between opportunity types and their declared find/prepare/outreach techniques, and that each opportunity type declares at least one pipeline state
6. IF the Schema_Registry fails validation at startup, THEN THE System SHALL refuse to start and report an error message identifying the specific validation failure including the entity id and the nature of the invalid reference or missing field
7. WHEN a new beneficiary is added to the Schema_Registry, THE System SHALL derive sub-tab navigation entries for that beneficiary across all applicable stages upon application startup without requiring code changes

### Requirement 13: Multi-Beneficiary Outreach Expansion

**User Story:** As a Team user, I want proactive cold outreach capabilities (currently Consultant-only), so that the firm can pursue contract opportunities through targeted outreach sequences.

#### Acceptance Criteria

1. THE System SHALL support cold outreach as an opportunity type for both Consultant and Team beneficiaries, declared in the Schema_Registry with their respective pipeline state machines and technique bindings
2. WHEN a Team user configures outreach criteria specifying at least one filter from: company size range, technology stack keywords, or public sector classification, THE Discovery_Pipeline SHALL discover up to 50 target companies per run using Apollo.io company search filtered by the specified criteria
3. THE Personalization_Engine SHALL generate Team outreach materials using the beneficiary's configured baseline assets (past project references, team capability statements, and relevant certifications) rather than individual CVs
4. THE Lemlist_Engine SHALL support separate Sequence configurations per beneficiary, allowing independent step definitions, delay intervals, and content templates for Consultant and Team outreach
5. THE System SHALL maintain separate pipeline state machines for Consultant cold outreach (Drafted → Sent → Replied → Meeting Booked → Converted) and Team cold outreach (Drafted → Sent → Replied → Proposal Requested → Won → Lost), with each state machine declared in the Schema_Registry
6. WHEN a Team prospect requests a proposal (detected via reply keyword matching or manual marking), THE System SHALL advance the pipeline record from "Replied" to "Proposal Requested"
7. IF the Discovery_Pipeline returns zero companies matching the configured Team outreach criteria, THEN THE System SHALL notify the user in the Dashboard with a suggestion to broaden filter criteria

### Requirement 14: Automated Follow-Up Sequences

**User Story:** As a user, I want the system to automatically send follow-up messages when prospects do not respond within configured timeframes, so that I maintain engagement without manual tracking.

#### Acceptance Criteria

1. WHEN a Touchpoint in a Sequence receives no reply within the configured delay interval, THE Lemlist_Engine SHALL automatically send the next Touchpoint in the sequence
2. THE Lemlist_Engine SHALL support configuring delay intervals between 1 and 30 days for each step in a Sequence
3. IF a prospect replies at any point during the Sequence, THEN THE Lemlist_Engine SHALL pause all pending Touchpoints for that prospect within 60 seconds of reply detection
4. THE Lemlist_Engine SHALL send a maximum of 3 automated follow-up Touchpoints (after the initial Touchpoint) before marking the prospect as "sequence_complete" and stopping outreach for that Sequence
5. WHILE a prospect's Sequence is paused due to a reply, THE System SHALL surface the prospect in the Dashboard "Requires Action" section for manual review
6. IF a Touchpoint fails to send (delivery error or bounce), THEN THE Lemlist_Engine SHALL log the failure, skip that Touchpoint, and continue with the next scheduled Touchpoint in the Sequence

### Requirement 15: ROI and Performance Tracking

**User Story:** As a user, I want to see the return on investment of my outreach efforts measured in time spent, response rates, and outcomes achieved, so that I can make data-driven decisions about where to focus.

#### Acceptance Criteria

1. THE Analytics_Service SHALL track time-to-outcome in calendar days for each pipeline record from discovery date to final outcome date, where final outcomes are: Accepted, Won, Rejected, Lost, or Abandoned
2. THE Analytics_Service SHALL compute and display effort metrics per calendar month: total prospects discovered, total outreach Touchpoints sent, total responses received, and total positive outcomes (Accepted or Won)
3. THE Analytics_Service SHALL compute channel effectiveness broken down by discovery source, sequence type, and beneficiary, where response rate equals replies divided by Touchpoints sent, meeting-booked rate equals meetings booked divided by Touchpoints sent, and conversion rate equals positive outcomes divided by total prospects entered into outreach
4. IF fewer than 10 prospects have been sent outreach for a given channel breakdown, THEN THE Analytics_Service SHALL display the metrics with a "low confidence" indicator and suppress percentage-based rates
5. THE Analytics_Service SHALL display a monthly trend chart showing the count of records entering each funnel stage and the stage-to-stage conversion rate for each stage over the trailing 12 months, displaying zero for months with no activity
6. WHEN a positive outcome occurs (Accepted or Won), THE Analytics_Service SHALL attribute the outcome to the originating discovery source, the Sequence used, and the specific variant that generated the first reply; IF the prospect was discovered from multiple sources, THEN attribution SHALL be assigned to the source with the earliest discovery date
7. THE Analytics_Service SHALL provide a comparison view displaying attributed outcomes, response rates, and conversion rates side by side for each discovery source and Sequence, enabling the user to identify the highest-performing approaches

### Requirement 16: Modern Frontend Architecture

**User Story:** As a user, I want a responsive, modern web interface with real-time updates and rich interactions, so that my workflow is efficient and the experience feels professional.

#### Acceptance Criteria

1. THE System SHALL implement the frontend using a component-based framework (React, Vue, or Svelte) with server-side rendering, achieving a Largest Contentful Paint (LCP) under 2 seconds on a standard broadband connection (10 Mbps+)
2. THE System SHALL implement real-time pipeline updates via WebSocket connections, reflecting status changes within 5 seconds of the backend state change without page refresh
3. THE System SHALL implement responsive design supporting desktop (1200px+), tablet (768px–1199px), and mobile (320px–767px) viewports, ensuring all content is readable without horizontal scrolling and all interactive elements meet a minimum touch target size of 44x44 pixels on mobile
4. THE System SHALL implement accessible navigation compliant with WCAG 2.1 Level AA, including keyboard navigation and screen reader support
5. WHEN a user toggles between dark mode and light mode, THE System SHALL apply the selected theme immediately and persist the preference in local storage so that it is retained across browser sessions on the same device, defaulting to the operating system's color scheme preference on first visit
6. IF the WebSocket connection is lost, THEN THE System SHALL display a visible connection status indicator, attempt automatic reconnection with exponential backoff (starting at 1 second, maximum 30 seconds between attempts), and resynchronize missed updates upon successful reconnection

### Requirement 17: LLM Evaluation Retention and Enhancement

**User Story:** As a user, I want the LLM-powered relevance evaluation from v1 retained and enhanced with Apollo enrichment context, so that matching accuracy improves while keeping the AI-driven assessment approach.

#### Acceptance Criteria

1. THE Scoring_Engine SHALL retain the existing LLM-based relevance matching that evaluates opportunities against candidate profiles, producing a relevance score between 0 and 100 and a reasoning explanation of no more than 500 characters
2. WHEN evaluating a prospect, THE Scoring_Engine SHALL provide the LLM with both the prospect's job description and the Apollo Enrichment_Record (company size, tech stack, funding stage, intent signals) as context
3. IF the Enrichment_Record is not yet available or has status "pending_retry" when evaluation is triggered, THEN THE Scoring_Engine SHALL proceed with LLM evaluation using only the job description and flag the result as "partial_context"
4. THE Scoring_Engine SHALL support configuring which LLM provider (Anthropic Claude or OpenAI) to use for evaluation, with model selection per evaluation type (matching, generation, research)
5. THE Scoring_Engine SHALL cache LLM evaluation results for 7 days, invalidating the cache when any field in the prospect's job description or the beneficiary's profile data is modified
6. IF the LLM provider is unavailable (API error response or no response within 30 seconds), THEN THE Scoring_Engine SHALL queue the evaluation for retry with a maximum of 3 attempts at 5-minute intervals, and continue processing other prospects using cached scores where available
7. IF the LLM provider remains unavailable after 3 retry attempts and no cached score exists for the prospect, THEN THE Scoring_Engine SHALL assign the prospect a status of "evaluation_pending" and surface it in the Dashboard "Requires Action" section

### Requirement 18: Configuration and Integration Management

**User Story:** As a user, I want a unified settings interface to configure all external integrations (Apollo, Lemlist, Adzuna, Gmail, LLM providers), so that I can manage API keys, connection status, and usage quotas in one place.

#### Acceptance Criteria

1. THE System SHALL provide a settings interface displaying connection status (connected, disconnected, error) for each configured integration: Apollo.io, Lemlist, Adzuna, Gmail, and LLM provider
2. WHEN a user provides API credentials for an integration, THE System SHALL validate the credentials by making a test API call and display the validation outcome (success with connection confirmed, or failure with an error indication describing the reason) within 10 seconds
3. IF credential validation fails due to invalid credentials, network error, or API unavailability, THEN THE System SHALL display the integration status as "error", retain the previously stored credentials unchanged, and indicate the failure reason to the user
4. THE System SHALL display current usage against quota limits for rate-limited integrations (Apollo monthly credits, Adzuna daily calls, LLM token consumption), refreshing usage data at least every 15 minutes
5. IF an integration's usage reaches 80% of its quota, THEN THE System SHALL display a warning indicator in the Dashboard and in the settings interface; IF usage reaches 100% of its quota, THEN THE System SHALL display a critical alert and prevent the System from making further calls to that integration until the quota resets
6. THE System SHALL store API credentials securely using environment variables or an encrypted local credential store, and credentials SHALL NOT be visible in plaintext in the UI after initial entry
