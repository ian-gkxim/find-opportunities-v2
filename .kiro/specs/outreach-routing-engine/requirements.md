# Requirements Document

## Introduction

The Outreach Routing Engine extends GKIM Opportunity Finder v2 by adding intelligent routing logic that evaluates each prospect and decides whether outreach should flow through the existing Lemlist automated sequences or through a new Personal Creative Playbook path. The Creative Playbook provides high-touch, multi-channel outreach for high-value prospects where automated sequences are insufficient. The routing decision is driven by configurable rules based on Account_Score tier, deal size, prospect seniority, intent signal strength, and other qualifying criteria. The engine integrates with the existing Third-Party Integration API layer to allow external applications to trigger and manage playbook execution programmatically.

## Glossary

- **Routing_Engine**: The decision service that evaluates a prospect against configurable routing rules and assigns the prospect to either the Lemlist automated path or the Creative Playbook path
- **Creative_Playbook**: A structured, multi-step outreach plan consisting of high-touch channel actions (personalized emails, LinkedIn outreach, video messages, gifts, referrals, custom content, direct calendar invites) designed for high-value prospects
- **Playbook_Step**: A single action within a Creative_Playbook, specifying a channel type, content instructions, scheduling window, and completion criteria
- **Routing_Rule**: A single condition within the routing configuration that evaluates a prospect attribute against a threshold or value set to produce a routing signal
- **Routing_Ruleset**: The complete collection of Routing_Rules and their combination logic (weighted score or all-must-pass) that determines the final routing decision
- **Outreach_Path**: The assigned outreach strategy for a prospect, either "lemlist_automated" or "creative_playbook"
- **Playbook_Execution**: A record tracking the progress of a specific prospect through a Creative_Playbook, including step completion status and outcomes
- **Channel_Type**: One of the supported outreach channels in the Creative Playbook: personalized_email, linkedin_connect, linkedin_message, video_message, gift_send, referral_introduction, custom_content, calendar_invite
- **Routing_Score**: A numeric value (0–100) computed by the Routing_Engine from weighted Routing_Rules, used to determine the Outreach_Path threshold
- **Integration_API**: The Third-Party Integration API layer that exposes routing and playbook operations to external applications via REST endpoints
- **Override**: A manual action by a user that changes a prospect's assigned Outreach_Path regardless of routing rule evaluation
- **System**: The GKIM Opportunity Finder v2 application
- **Account_Score**: A composite numeric score (0–100) indicating how well a prospect matches the ideal customer profile, derived from Apollo data and LLM evaluation
- **Lemlist_Engine**: The integration layer communicating with the Lemlist API for multi-channel sequence management
- **Scoring_Engine**: The service responsible for computing composite opportunity scores
- **Analytics_Service**: The service that computes funnel metrics, conversion rates, and performance tracking data
- **Dashboard**: The primary UI view providing at-a-glance pipeline status, actionable insights, and conversion metrics

## Requirements

### Requirement 1: Routing Decision Engine

**User Story:** As a user, I want each prospect automatically evaluated against routing rules so that high-value prospects receive personalized creative outreach while others continue through automated Lemlist sequences.

#### Acceptance Criteria

1. WHEN a prospect reaches the "ready_for_outreach" pipeline state, THE Routing_Engine SHALL evaluate the prospect against the active Routing_Ruleset and assign an Outreach_Path within 5 seconds
2. THE Routing_Engine SHALL compute a Routing_Score (0–100) by evaluating each Routing_Rule in the active Routing_Ruleset, normalizing each rule result to 0–100, and applying the configured weight for that rule, where each rule weight is an integer between 0 and 100 and the sum of all rule weights in the Routing_Ruleset equals 100
3. WHEN the computed Routing_Score meets or exceeds the configurable creative_playbook_threshold (default: 70, configurable range: 0–100), THE Routing_Engine SHALL assign the prospect to the "creative_playbook" Outreach_Path and queue the prospect for the Personalization_Engine to generate outreach materials
4. WHEN the computed Routing_Score is below the creative_playbook_threshold, THE Routing_Engine SHALL assign the prospect to the "lemlist_automated" Outreach_Path and enroll the prospect in the configured default Lemlist Sequence for the prospect's opportunity type
5. THE Routing_Engine SHALL evaluate the following prospect attributes as inputs to Routing_Rules: Account_Score (0–100), deal_size_estimate (0.01–999,999,999.99 in configured currency), contact_seniority_level (C-suite, director, manager, individual_contributor), intent_signal_strength (strong, moderate, weak, none), industry_vertical, engagement_history (email opens, clicks, and replies within the trailing 90 days), and lead_source_quality_score (0–100)
6. IF one or more Routing_Rule input attributes are unavailable for a prospect, THEN THE Routing_Engine SHALL compute the Routing_Score using only available attributes, redistributing missing rule weights proportionally among available rules, and SHALL flag the routing decision as "partial_evaluation" in the Dashboard
7. IF all Routing_Rule input attributes are unavailable for a prospect, THEN THE Routing_Engine SHALL assign the prospect to the "lemlist_automated" Outreach_Path by default and flag the routing decision as "no_evaluation" in the Dashboard
8. THE Routing_Engine SHALL log each routing decision with the prospect identifier, computed Routing_Score, individual rule contributions, assigned Outreach_Path, evaluation timestamp, and partial_evaluation flag (if applicable), retaining logs for a minimum of 90 days

### Requirement 2: Routing Rules Configuration

**User Story:** As a user, I want to configure the rules and thresholds that drive routing decisions so that I can tune the system to my business context without code changes.

#### Acceptance Criteria

1. THE System SHALL allow users to configure up to 20 Routing_Rules per Routing_Ruleset through a settings interface, where each rule specifies: a prospect attribute to evaluate (from the set defined in Requirement 1 criterion 5), an operator (greater_than, less_than, equals, in_set, between), a threshold value or value set compatible with the selected operator, and a weight (integer, 0–100)
2. THE System SHALL enforce that the sum of all active Routing_Rule weights in a Routing_Ruleset equals 100, rejecting configuration changes that violate this constraint and displaying an error message indicating the current weight sum and the required total of 100
3. THE System SHALL provide the following default Routing_Rules in the initial Routing_Ruleset: Account_Score tier is A-tier (weight: 30), deal_size_estimate greater_than 50000 (weight: 20), contact_seniority_level in_set [C-suite, VP] (weight: 20), intent_signal_strength equals "strong" (weight: 15), engagement_history greater_than 3 interactions (weight: 15)
4. WHEN a user modifies the Routing_Ruleset, THE System SHALL validate that all rules reference a valid prospect attribute, use an operator compatible with that attribute's data type, specify a non-empty threshold value, and that active rule weights sum to 100, then apply the updated rules to all subsequent routing evaluations without requiring a system restart
5. IF validation of a modified Routing_Ruleset fails, THEN THE System SHALL reject the save, preserve the previously active Routing_Ruleset unchanged, and display an error message indicating each validation failure found
6. THE System SHALL support enabling and disabling individual Routing_Rules within a Routing_Ruleset, redistributing disabled rule weights proportionally among remaining active rules during evaluation
7. THE System SHALL store a version history of up to 50 Routing_Ruleset configurations with timestamps and the identifier of the user who made the change, allowing users to view previous configurations and revert to any prior version
8. IF a user attempts to save a Routing_Ruleset with zero active rules, THEN THE System SHALL reject the save and display an error indicating at least one active rule is required

### Requirement 3: Creative Playbook Definition and Structure

**User Story:** As a user, I want to define multi-step creative playbooks with various high-touch channel types so that I have a structured plan for engaging high-value prospects personally.

#### Acceptance Criteria

1. THE System SHALL support creating Creative_Playbooks with 1 to 15 Playbook_Steps, where each step specifies a Channel_Type, content instructions (up to 10000 characters), a scheduling window with minimum days (0 to 89) and maximum days (1 to 90) from playbook start or previous step completion where minimum days is less than maximum days, and a completion criteria description (up to 500 characters)
2. THE System SHALL support the following Channel_Types for Playbook_Steps: personalized_email, linkedin_connect, linkedin_message, video_message, gift_send, referral_introduction, custom_content, calendar_invite
3. WHEN a Playbook_Step has Channel_Type "personalized_email", THE System SHALL generate a draft email using the Personalization_Engine with the prospect's enrichment data and the step's content instructions, and present the draft to the user with options to approve, edit, or regenerate before marking the step as ready to send
4. WHEN a Playbook_Step has Channel_Type "linkedin_connect" or "linkedin_message", THE System SHALL generate a suggested connection request (up to 300 characters) or message draft (up to 8000 characters) using the Personalization_Engine and present it to the user with options to approve, edit, or regenerate
5. THE System SHALL allow users to create multiple Creative_Playbook templates (up to 20 templates), each targeting a prospect profile defined by one or more of the following criteria: industry (selected from available industries), seniority level (selected from available seniority levels), or deal size range (minimum and maximum dollar values)
6. THE System SHALL support conditional branching in Creative_Playbooks, where subsequent steps can differ based on the outcome of a previous step (responded, accepted_connection, no_response, declined), with "no_response" determined after a configurable wait period of 1 to 14 days following step execution
7. WHEN creating a Creative_Playbook, THE System SHALL validate that the scheduling windows produce a total playbook duration not exceeding 90 calendar days from first step to last step maximum day
8. THE System SHALL allow users to clone an existing Creative_Playbook template and modify the clone independently
9. IF the Personalization_Engine fails to generate a draft for a Playbook_Step, THEN THE System SHALL display the step's content instructions as a manual template and indicate that automatic generation is unavailable, allowing the user to compose the content manually
10. IF a user attempts to create a Creative_Playbook with a conditional branch that references an outcome not applicable to the preceding step's Channel_Type (e.g., "accepted_connection" after a "personalized_email" step), THEN THE System SHALL reject the configuration and indicate which branch outcome is invalid for the specified Channel_Type

### Requirement 4: Creative Playbook Orchestration and Execution

**User Story:** As a user, I want the system to orchestrate playbook execution by scheduling steps, tracking progress, and surfacing action items so that I can execute high-touch outreach consistently without losing track.

#### Acceptance Criteria

1. WHEN a prospect is assigned to the "creative_playbook" Outreach_Path, THE System SHALL create a Playbook_Execution record linking the prospect to the first Creative_Playbook template whose industry, seniority level, and deal size range criteria all match the prospect's attributes, evaluated in template priority order, within 10 seconds of path assignment
2. IF no Creative_Playbook template matches the prospect's industry, seniority level, and deal size range, THEN THE System SHALL surface the prospect in the Dashboard "Requires Action" section indicating no matching playbook template was found, and SHALL not create a Playbook_Execution until a user manually assigns a template
3. WHEN a Playbook_Execution is created, THE System SHALL schedule the first Playbook_Step according to its configured scheduling window (minimum and maximum days) and surface the action item in the Dashboard "Creative Outreach" section within 30 seconds of Playbook_Execution creation
4. WHEN a Playbook_Step reaches its scheduled window, THE System SHALL generate any required content drafts (personalized emails, LinkedIn messages) within 30 seconds and notify the user in the Dashboard that the step is ready for execution
5. WHEN a user marks a Playbook_Step as completed, THE System SHALL require the user to select an outcome (responded, accepted_connection, no_response, declined), record the completion timestamp and selected outcome, advance the Playbook_Execution to the next step determined by the conditional branching rules for the selected outcome, and schedule the next step according to its configured scheduling window
6. IF a Playbook_Step remains incomplete beyond its maximum scheduled day, THEN THE System SHALL surface a single escalation alert in the Dashboard "Requires Action" section indicating the overdue step and prospect name, and SHALL not generate duplicate alerts for the same overdue step
7. WHEN all steps in a Playbook_Execution are completed or the playbook reaches a terminal branch, THE System SHALL mark the Playbook_Execution as "completed" and record the final outcome (responded, meeting_booked, converted, no_response)
8. THE System SHALL track the following metrics for each Playbook_Execution: total elapsed days, steps completed, steps skipped, response received (yes/no), meeting booked (yes/no), and final outcome
9. WHILE a Playbook_Execution is active, THE System SHALL prevent the prospect from being enrolled in any Lemlist automated sequence; IF the prospect is already enrolled in a Lemlist sequence at the time the Playbook_Execution is created, THEN THE System SHALL pause the active Lemlist sequence before beginning playbook execution

### Requirement 5: Override and Path Switching

**User Story:** As a user, I want to manually override routing decisions and switch prospects between outreach paths so that I retain control when the automated routing does not match my judgment.

#### Acceptance Criteria

1. THE System SHALL allow users to override a prospect's assigned Outreach_Path, switching from "lemlist_automated" to "creative_playbook" or from "creative_playbook" to "lemlist_automated", for any prospect not in a terminal pipeline state (Converted, Won, Lost, or Abandoned)
2. WHEN a user overrides a prospect from "lemlist_automated" to "creative_playbook", THE System SHALL pause the active Lemlist sequence for that prospect within 10 seconds, create a new Playbook_Execution, and prompt the user to select a Creative_Playbook template
3. WHEN a user overrides a prospect from "creative_playbook" to "lemlist_automated", THE System SHALL mark the active Playbook_Execution as "cancelled" with reason "manual_override" within 10 seconds and allow the user to select a Lemlist Sequence for enrollment
4. THE System SHALL record each Override with the user identifier, original Outreach_Path, new Outreach_Path, reason (free text up to 500 characters), and timestamp
5. THE System SHALL display Override history for each prospect in the prospect detail view, showing all path changes with reasons and timestamps, ordered by timestamp descending
6. IF a prospect has been overridden more than 2 times within 30 days, THEN THE System SHALL display a recommendation in the Dashboard suggesting the user review the Routing_Ruleset configuration for potential tuning
7. IF the Lemlist_Engine fails to pause the active sequence during an override from "lemlist_automated" to "creative_playbook" (API error or timeout after 10 seconds), THEN THE System SHALL abort the override, retain the current Outreach_Path unchanged, and display an error indication to the user describing the failure
8. IF a user initiates an override from "lemlist_automated" to "creative_playbook" and no active Lemlist sequence exists for that prospect, THEN THE System SHALL proceed with the override by creating the new Playbook_Execution without attempting a sequence pause

### Requirement 6: Integration API for Routing and Playbook Operations

**User Story:** As an external application developer, I want to trigger routing evaluations, manage playbook executions, and receive routing decisions via the Integration_API so that third-party tools can participate in the outreach workflow programmatically.

#### Acceptance Criteria

1. THE Integration_API SHALL expose a GET endpoint at /routing/{prospect_id}/evaluation that returns the current routing evaluation result including the Routing_Score, assigned Outreach_Path, and individual rule contributions, responding within 3 seconds
2. THE Integration_API SHALL expose a POST endpoint at /routing/{prospect_id}/evaluate that triggers a new routing evaluation, returning the updated Outreach_Path assignment and Routing_Score within 5 seconds
3. THE Integration_API SHALL expose endpoints for managing Playbook_Executions: POST /playbooks/executions (create — assign prospect to a specified playbook template), POST /playbooks/executions/{id}/advance (mark current step as completed with outcome), POST /playbooks/executions/{id}/pause, POST /playbooks/executions/{id}/resume, and POST /playbooks/executions/{id}/cancel
4. THE Integration_API SHALL expose a GET endpoint at /playbooks/executions that lists all active Playbook_Executions with their current step, scheduled dates, and status, supporting cursor-based pagination with a maximum of 50 results per page
5. THE Integration_API SHALL authenticate all requests using API key authentication passed via the X-API-Key header and enforce rate limiting of 100 requests per minute per API key using a Redis sliding window; WHEN a request exceeds the rate limit, THE Integration_API SHALL return a 429 status code with a Retry-After header indicating seconds until the next allowed request
6. IF an Integration_API request provides an invalid or missing API key, THEN THE Integration_API SHALL return a 401 status code with an error message indicating authentication failure without revealing whether the key exists or is expired
7. IF an Integration_API request references a prospect that does not exist, THEN THE Integration_API SHALL return a 404 status code with a descriptive error message identifying the missing resource
8. IF an Integration_API request attempts an invalid state transition (advancing a completed playbook, cancelling an already-cancelled execution), THEN THE Integration_API SHALL return a 409 status code with a message describing the conflict and the current execution state
9. THE Integration_API SHALL emit webhook events for routing decisions and playbook step completions to configured webhook URLs, delivering each event within 30 seconds of occurrence with up to 3 retry attempts on delivery failure using exponential backoff (5s, 15s, 45s)
10. IF all webhook delivery attempts fail for an event, THEN THE Integration_API SHALL store the failed event in a dead-letter queue accessible via a GET endpoint at /webhooks/dead-letter, retaining failed events for 7 days

### Requirement 7: Routing and Playbook Performance Analytics

**User Story:** As a user, I want to compare the performance of Lemlist automated sequences versus Creative Playbook outreach so that I can refine routing rules and optimize overall conversion rates.

#### Acceptance Criteria

1. THE Analytics_Service SHALL compute and display response rates (replies divided by prospects enrolled), meeting-booked rates (meetings booked divided by prospects enrolled), and conversion rates (positive outcomes divided by prospects enrolled) separately for the "lemlist_automated" and "creative_playbook" Outreach_Paths, refreshed daily by 02:00 UTC, expressed as percentages with one decimal place precision
2. THE Analytics_Service SHALL compute and display average time-to-first-response in calendar days (rounded to one decimal place) for each Outreach_Path, broken down by Account_Score tier (A, B, C, D), refreshed daily by 02:00 UTC, counting only prospects that have received at least one reply within the selected time period
3. THE Analytics_Service SHALL display a side-by-side comparison view showing response rate, meeting-booked rate, conversion rate, average time-to-first-response, and total prospects enrolled for each Outreach_Path for a user-selected time period (7, 30, or 90 days)
4. WHEN the "creative_playbook" Outreach_Path achieves a response rate more than 10 percentage points higher than "lemlist_automated" for A-tier prospects over a 30-day period with at least 10 prospects in each path, THE Analytics_Service SHALL surface a recommendation to increase the creative_playbook_threshold routing sensitivity
5. WHEN the "creative_playbook" Outreach_Path achieves a response rate within 5 percentage points of "lemlist_automated" for A-tier prospects over a 30-day period with at least 10 prospects in each path, THE Analytics_Service SHALL surface a recommendation to review whether the creative playbook effort is justified for that segment
6. THE Analytics_Service SHALL track and display per-Channel_Type effectiveness within Creative_Playbook executions, showing response rates (replies divided by Playbook_Steps executed for that channel) broken down by channel type (personalized_email, linkedin_connect, video_message, gift_send, referral_introduction, custom_content, calendar_invite), refreshed daily by 02:00 UTC
7. IF fewer than 10 prospects have completed the outreach path within the selected time period, THEN THE Analytics_Service SHALL display the computed metrics with a "low confidence" indicator and suppress percentage-based recommendations
8. THE Analytics_Service SHALL compute the Routing_Engine's routing success rate by tracking the percentage of "creative_playbook" prospects that achieve a positive outcome (responded, meeting_booked, or converted) versus those that reached "sequence_complete" or exceeded 90 calendar days since Playbook_Execution creation without a positive outcome, displayed as a monthly trend
9. IF the daily analytics computation fails to complete by 02:00 UTC due to a processing error or database unavailability, THEN THE Analytics_Service SHALL retry the computation within 30 minutes up to a maximum of 3 attempts, and IF all retries fail, THEN THE Analytics_Service SHALL display a stale data indicator on all affected metrics showing the date of the last successful computation
