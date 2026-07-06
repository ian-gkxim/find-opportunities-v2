# Requirements Document

## Introduction

Form Submission Automation extends the GKIM Opportunity Finder v2 outreach capabilities by adding automated web form filling as a new outreach technique. Many opportunities (job applications, vendor portals, RFP submissions, grant applications) require filling in web forms rather than sending emails or LinkedIn messages. This feature uses a hybrid LLM + browser automation approach: an LLM analyzes crawled form pages to extract field structure, generates a mapping from the user's data to form fields, presents the mapping for human approval, then executes the submission via Playwright browser automation with screenshot verification. It sits alongside the existing Lemlist sequence and manual apply techniques as a schema-registered outreach technique.

## Glossary

- **System**: The GKIM Opportunity Finder v2 application
- **Form_Analyzer**: The service that crawls a form page URL and uses an LLM to extract field labels, types, validation rules, and structural relationships from the page DOM
- **Field_Mapping_Engine**: The service that generates a proposed mapping between the user's source data (profile fields, generated materials, enrichment data) and the extracted form fields
- **Form_Executor**: The service that uses Playwright browser automation to navigate to a form page, fill fields according to an approved mapping, and submit the form
- **Submission_Record**: A structured data object tracking the full lifecycle of a form submission attempt including the URL, extracted fields, approved mapping, execution status, and verification screenshot
- **Field_Map**: A structured mapping object that pairs each target form field with a source data value, a confidence score, and an optional transformation instruction
- **Assisted_Mode**: A fallback workflow triggered when the Form_Analyzer cannot reliably extract form structure, in which the System presents the form URL to the user for manual completion while still tracking the submission attempt
- **Screenshot_Capture**: A verification artifact (PNG image) taken by the Form_Executor after form submission to provide an audit trail of what was submitted
- **Source_Data**: The collection of user profile fields, generated outreach materials, enrichment data, and beneficiary baseline assets available for mapping to form fields
- **Schema_Registry**: The YAML-based single source of truth that drives navigation, pipeline states, technique wiring, and data model structure
- **Dashboard**: The primary UI view providing at-a-glance pipeline status, actionable insights, and conversion metrics
- **Beneficiary**: Either a Consultant (individual pursuing roles) or Team (firm pursuing contracts)

## Requirements

### Requirement 1: Form Page Crawling and Field Extraction

**User Story:** As a user, I want the system to automatically analyze a web form and extract its field structure, so that I do not have to manually identify what data each field requires.

#### Acceptance Criteria

1. WHEN a user provides a form page URL for an opportunity, THE Form_Analyzer SHALL crawl the page using a headless browser and extract the rendered DOM within 30 seconds
2. THE Form_Analyzer SHALL pass the extracted DOM to an LLM to identify all fillable form fields, extracting for each field: the field label, field type (text, textarea, select, radio, checkbox, file upload, date, number), whether the field is required, any placeholder text, and any visible validation constraints
3. WHEN the form page contains multiple pages or steps (multi-step forms), THE Form_Analyzer SHALL detect the multi-step structure and extract fields from all reachable steps by navigating "next" or "continue" controls, up to a maximum of 10 steps, with a per-step timeout of 15 seconds
4. IF the Form_Analyzer cannot load the page (network error, HTTP 4xx/5xx response, or page load timeout exceeding 30 seconds), THEN THE Form_Analyzer SHALL mark the Submission_Record as "crawl_failed" and surface the opportunity in the Dashboard "Requires Action" section with the failure reason
5. IF the Form_Analyzer extracts fewer than 2 fillable fields from a page, THEN THE Form_Analyzer SHALL mark the Submission_Record as "extraction_uncertain" and trigger Assisted_Mode
6. IF the form page requires authentication (detected by login page redirect or HTTP 401/403 response), THEN THE Form_Analyzer SHALL mark the Submission_Record as "auth_required" and prompt the user to provide session credentials or switch to Assisted_Mode
7. THE Form_Analyzer SHALL store the extracted field structure in the Submission_Record with a timestamp, enabling re-crawling if the form page changes
8. IF the Form_Analyzer fails to navigate to the next step in a multi-step form (navigation control not found, next page fails to load within 15 seconds, or navigation results in a redirect away from the form domain), THEN THE Form_Analyzer SHALL stop multi-step extraction, retain fields extracted from completed steps, and flag the Submission_Record with "partial_extraction" indicating the step number where navigation failed
9. WHEN the user requests a re-crawl of a previously extracted form, THE Form_Analyzer SHALL overwrite the existing field structure in the Submission_Record with the new extraction results and update the timestamp

### Requirement 2: Field Mapping Generation

**User Story:** As a user, I want the system to automatically propose how my profile data maps to each form field, so that I can review and approve the mapping before submission.

#### Acceptance Criteria

1. WHEN the Form_Analyzer successfully extracts the field structure, THE Field_Mapping_Engine SHALL generate a Field_Map within 15 seconds by matching extracted form fields to available Source_Data using an LLM
2. THE Field_Mapping_Engine SHALL assign a confidence score between 0 and 100 to each field mapping, where the score reflects the LLM's certainty that the Source_Data value correctly corresponds to the form field's intent
3. THE Field_Mapping_Engine SHALL identify Source_Data from the following sources in priority order: beneficiary baseline assets (resume, cover letter, company profile), generated outreach materials (tailored CV, tailored cover letter, proposal), enrichment data (company information, contact details), and user profile fields (name, email, phone, address, LinkedIn URL); WHEN multiple sources contain data suitable for the same form field, THE Field_Mapping_Engine SHALL select the value from the highest-priority source that matches
4. IF a form field has no suitable Source_Data match (confidence score below 30), THEN THE Field_Mapping_Engine SHALL mark that field as "requires_manual_input" in the Field_Map and include a suggestion of what type of data the field expects based on the field label and any placeholder text
5. IF a form field is of type "file upload" and a matching generated document exists, THEN THE Field_Mapping_Engine SHALL map it to the most relevant generated document (tailored CV for resume uploads, tailored cover letter for cover letter uploads, proposal document for proposal uploads) based on the field label
6. IF a form field is of type "file upload" and no matching generated document is available for that field, THEN THE Field_Mapping_Engine SHALL mark that field as "requires_manual_input" in the Field_Map with a suggestion indicating the expected document type
7. WHEN Source_Data requires transformation to fit a form field (date format conversion, text truncation to character limits, splitting a full name into first and last name), THE Field_Mapping_Engine SHALL include the transformation instruction in the Field_Map entry
8. THE Field_Mapping_Engine SHALL generate mappings for all extracted fields regardless of whether the field is marked as required, distinguishing required fields from optional fields in the Field_Map presentation
9. IF the Field_Mapping_Engine fails to generate a Field_Map (LLM timeout exceeding 15 seconds, LLM service error, or no Source_Data available for the beneficiary), THEN THE Field_Mapping_Engine SHALL mark the Submission_Record as "mapping_failed" and surface the opportunity in the Dashboard "Requires Action" section with the failure reason

### Requirement 3: Human-in-the-Loop Mapping Approval

**User Story:** As a user, I want to review, edit, and approve the proposed field mapping before any form is submitted, so that I maintain control over what data is sent.

#### Acceptance Criteria

1. WHEN the Field_Mapping_Engine generates a Field_Map, THE System SHALL present the mapping to the user in the Dashboard showing: each form field label, the proposed value to be filled, the confidence score, and whether the field is required
2. THE System SHALL allow the user to edit any mapped value directly in the approval interface, replacing the proposed value with custom text of up to 5000 characters per field, and SHALL remove the confidence score display for any field whose value has been manually edited
3. THE System SHALL allow the user to mark any optional field as "skip" to leave it empty during submission
4. THE System SHALL visually highlight fields with confidence scores below 60 using a warning indicator to draw the user's attention to uncertain mappings
5. WHEN the user approves the Field_Map (by clicking an "Approve and Submit" action), THE System SHALL make the Submission_Record mapping read-only (preventing further edits), and advance the pipeline record to "Submitting" status within 5 seconds
6. IF the user rejects the mapping entirely, THEN THE System SHALL retain the Submission_Record in "mapping_rejected" status and allow the user to either request a new mapping generation or switch to Assisted_Mode
7. THE System SHALL require the user to provide values for all fields marked as "requires_manual_input" that are also marked as required before allowing approval, preventing submission with missing required fields
8. IF a user edits a mapped value and the extracted form field has a character limit detected during crawl, THEN THE System SHALL display a validation warning when the entered text exceeds the form field's character limit, and SHALL prevent approval until all field values comply with their detected constraints

### Requirement 4: Browser Automation Execution

**User Story:** As a user, I want the system to automatically fill and submit the web form using the approved mapping, so that I do not have to manually enter data into each field.

#### Acceptance Criteria

1. WHEN a user approves a Field_Map, THE Form_Executor SHALL launch a Playwright browser instance, navigate to the form page URL, and begin filling fields within 15 seconds of approval
2. THE Form_Executor SHALL fill each form field according to the approved Field_Map, using appropriate interaction methods per field type: typing for text inputs, selecting options for dropdowns, clicking for radio buttons and checkboxes, and attaching files for file upload fields
3. WHEN the form is a multi-step form, THE Form_Executor SHALL fill fields on each step and navigate to the next step using the detected navigation controls, verifying that each step loads successfully (page content changes detected within 10 seconds) before proceeding
4. WHEN all fields are filled, THE Form_Executor SHALL click the submit button and wait up to 30 seconds for a submission confirmation (detected by URL change, confirmation message, or success page elements)
5. IF the Form_Executor encounters a CAPTCHA or anti-bot challenge during execution, THEN THE Form_Executor SHALL pause execution, capture a screenshot of the current state, and notify the user in the Dashboard to complete the CAPTCHA manually or switch to Assisted_Mode
6. IF the Form_Executor encounters a validation error after attempting submission (detected by error messages appearing on the page), THEN THE Form_Executor SHALL capture the validation error messages, associate them with the relevant fields in the Submission_Record, and notify the user to correct the mapping
7. IF the Form_Executor cannot locate a form field on the page within 5 seconds of searching (element not found or page structure changed since crawl), THEN THE Form_Executor SHALL skip that field, log the discrepancy, continue with remaining fields, and flag the Submission_Record as "partial_fill" for user review
8. IF the form page has changed significantly since the original crawl (more than 30% of expected fields not found), THEN THE Form_Executor SHALL abort execution, mark the Submission_Record as "page_changed", and prompt the user to re-crawl the form
9. IF the Form_Executor cannot locate the submit button on the form page, THEN THE Form_Executor SHALL capture a screenshot of the current state, mark the Submission_Record as "submission_failed" with reason "submit_button_not_found", and notify the user to review
10. IF the Form_Executor does not detect a submission confirmation within 30 seconds after clicking submit, THEN THE Form_Executor SHALL capture a screenshot of the current page state, mark the Submission_Record as "submission_unconfirmed", and surface the opportunity in the Dashboard for user verification
11. IF the Form_Executor fails to navigate to the next step in a multi-step form (navigation control not found or next page fails to load within 10 seconds), THEN THE Form_Executor SHALL capture a screenshot, mark the Submission_Record as "navigation_failed" with the step number, and notify the user

### Requirement 5: Screenshot Verification and Audit Trail

**User Story:** As a user, I want a screenshot of the submitted form captured for my records, so that I have proof of what was submitted and can verify correctness.

#### Acceptance Criteria

1. WHEN the Form_Executor detects a successful submission (confirmation page or success message), THE Form_Executor SHALL capture a full-page Screenshot_Capture of the confirmation state within 5 seconds
2. WHEN the Form_Executor fills all fields but before clicking submit, THE Form_Executor SHALL capture a pre-submission Screenshot_Capture showing the filled form state; WHEN the form is a multi-step form, THE Form_Executor SHALL capture a pre-submission screenshot of each completed step before navigating to the next step
3. THE System SHALL store each Screenshot_Capture as a PNG image associated with the Submission_Record, retaining screenshots for a minimum of 90 days
4. THE Dashboard SHALL display the pre-submission and post-submission screenshots in the submission detail view, allowing the user to visually verify what was submitted
5. IF the Form_Executor fails to capture a screenshot (browser crash or rendering error), THEN THE Form_Executor SHALL log the failure, notify the user that the screenshot could not be captured for that step, and continue with the submission workflow without blocking the process
6. THE Submission_Record SHALL store a complete audit log including: timestamp of each action in ISO 8601 format with millisecond precision (crawl, mapping, approval, fill start, submit, confirmation), the approved Field_Map values, and any validation errors encountered

### Requirement 6: Assisted Mode Fallback

**User Story:** As a user, I want a graceful fallback for forms that cannot be reliably automated, so that I can still track submissions through complex or unusual forms.

#### Acceptance Criteria

1. WHEN Assisted_Mode is triggered (by extraction uncertainty, authentication requirements, CAPTCHA detection, page change, or user choice), THE System SHALL open the form URL in the user's default browser and display a tracking prompt in the Dashboard within 5 seconds
2. WHILE a Submission_Record is in Assisted_Mode, THE System SHALL display the available Source_Data relevant to the form (generated materials, profile data) in a sidebar panel for easy copy-paste access
3. WHEN the user completes a manual submission in Assisted_Mode, THE System SHALL allow the user to mark the submission as complete and optionally upload a screenshot (PNG or JPEG, maximum 10 MB) for the audit trail
4. THE System SHALL advance the pipeline record to "Submitted" status when the user confirms completion of an Assisted_Mode submission
5. IF the user does not confirm completion of an Assisted_Mode submission within 7 days, THEN THE System SHALL surface the opportunity in the Dashboard "Requires Action" section as "awaiting_manual_submission"
6. THE System SHALL track the reason for entering Assisted_Mode (extraction_uncertain, auth_required, captcha_detected, user_choice, page_changed) in the Submission_Record for analytics purposes
7. WHILE in Assisted_Mode, THE System SHALL allow the user to cancel the submission attempt entirely, marking the Submission_Record as "cancelled" and removing it from active pipeline tracking

### Requirement 7: Schema Registry Integration

**User Story:** As a developer, I want the form submission automation registered as an outreach technique in the Schema Registry, so that it can be wired to opportunity types through configuration.

#### Acceptance Criteria

1. THE Schema_Registry SHALL declare a new outreach technique with id "form_submission", service_class "FormSubmissionService", and description "Automated web form filling via LLM analysis and Playwright browser automation with human approval"
2. THE Schema_Registry SHALL allow opportunity types to declare "form_submission" as their outreach_technique, enabling form-based submission for job sites, vendor portals, and project marketplaces through configuration alone
3. WHEN an opportunity type uses the "form_submission" outreach technique, THE System SHALL derive the pipeline states for that opportunity type from the Schema_Registry, supporting at minimum: Personalise, Crawling, Mapping, Awaiting Approval, Submitting, Submitted, and outcome states specific to the opportunity type
4. THE System SHALL support opportunity types that declare "form_submission" as their outreach technique for both Consultant and Team beneficiaries without code changes
5. IF the Schema_Registry references the "form_submission" technique but the FormSubmissionService class is not available at startup, THEN THE System SHALL log an error identifying the missing service and disable the form submission workflow for affected opportunity types without preventing system startup
6. WHEN an opportunity type transitions from a different outreach_technique to "form_submission" in the Schema_Registry, THE System SHALL preserve existing pipeline records in their current states and apply the new pipeline state machine only to newly created records

### Requirement 8: Submission Pipeline State Management

**User Story:** As a user, I want form submissions tracked through clear pipeline stages, so that I can see the status of each submission at a glance.

#### Acceptance Criteria

1. WHEN a user initiates a form submission for an opportunity, THE System SHALL create a Submission_Record and advance the pipeline record to "Crawling" status within 2 seconds
2. WHEN the Form_Analyzer completes field extraction, THE System SHALL advance the pipeline record to "Mapping" status
3. WHEN the Field_Mapping_Engine generates a Field_Map, THE System SHALL advance the pipeline record to "Awaiting Approval" status
4. WHEN the user approves the mapping, THE System SHALL advance the pipeline record to "Submitting" status
5. WHEN the Form_Executor confirms successful submission, THE System SHALL advance the pipeline record to "Submitted" status
6. IF any step in the submission pipeline fails, THEN THE System SHALL set the pipeline record to an error state corresponding to the failure point (crawl_failed, mapping_failed, submission_failed, captcha_detected, page_changed, rate_limited) and surface the opportunity in the Dashboard "Requires Action" section within 10 seconds of failure detection
7. WHILE a pipeline record is in "Awaiting Approval" status, THE Dashboard SHALL display the opportunity with a visually distinct action indicator (badge or icon differentiated from non-actionable items) to review and approve the mapping
8. IF a pipeline record is in an error state (crawl_failed, mapping_failed, or submission_failed), THEN THE System SHALL allow the user to retry from the failed step, resetting the pipeline record to the status immediately preceding the failure point and re-initiating that step
9. WHEN the System triggers Assisted_Mode for a Submission_Record, THE System SHALL advance the pipeline record to "Assisted" status, and WHEN the user confirms manual completion, THE System SHALL advance the pipeline record to "Submitted" status
10. THE System SHALL enforce valid pipeline state transitions, only allowing forward progression through the defined sequence (Crawling → Mapping → Awaiting Approval → Submitting → Submitted) or transitions to error states or "Assisted" status, and SHALL reject any other state transition attempt

### Requirement 9: Submission Analytics and Performance Tracking

**User Story:** As a user, I want to see analytics on form submission success rates and automation effectiveness, so that I can understand how well the automation is working.

#### Acceptance Criteria

1. THE Analytics_Service SHALL track and display the form submission success rate (successful submissions divided by total submission attempts) per opportunity type and per beneficiary, refreshed daily
2. THE Analytics_Service SHALL track and display the automation rate (submissions completed fully automatically without Assisted_Mode divided by total submissions) per opportunity type, refreshed daily
3. THE Analytics_Service SHALL track and display the average time from submission initiation to confirmed submission in hours (rounded to 1 decimal place), broken down by automated submissions and Assisted_Mode submissions, refreshed daily over the user-selected time period (7, 30, or 90 days)
4. THE Analytics_Service SHALL track and display the distribution of Assisted_Mode trigger reasons (extraction_uncertain, auth_required, captcha_detected, user_choice, page_changed) as counts and percentages over a user-selected time period (7, 30, or 90 days)
5. IF fewer than 5 submissions have been attempted for a given opportunity type, THEN THE Analytics_Service SHALL display metrics with an "insufficient data" indicator
6. THE Analytics_Service SHALL track the average field mapping confidence score (0-100) across all submissions and display a trend as weekly data points over the user-selected time period (7, 30, or 90 days), with each data point representing the mean confidence score of submissions completed in that week

### Requirement 10: Rate Limiting and Responsible Automation

**User Story:** As a user, I want the system to respect target website rate limits and behave like a responsible automated agent, so that submissions are not blocked or flagged as abuse.

#### Acceptance Criteria

1. THE Form_Executor SHALL execute a maximum of one form submission per target domain within a configurable minimum interval (default: 60 seconds, configurable range: 10 to 3600 seconds) to avoid triggering rate limiting or abuse detection, where target domain is determined by the registrable domain (e.g., "example.com" from "jobs.example.com")
2. THE Form_Executor SHALL use browser fingerprints that include a current-release Chrome user-agent string, a viewport size of 1920x1080 or 1366x768 (selected randomly per session), and JavaScript enabled, to avoid detection as a headless browser
3. THE Form_Executor SHALL introduce randomized delays between field interactions (uniformly distributed between 100 and 500 milliseconds per field) to simulate human typing patterns
4. IF the Form_Executor receives an HTTP 429 (Too Many Requests) response during navigation or submission, THEN THE Form_Executor SHALL pause execution for the duration specified in the Retry-After header (capped at a maximum of 30 minutes regardless of header value) or 5 minutes if no header is present, and retry once before marking the submission as "rate_limited"
5. THE System SHALL allow users to configure a maximum number of automated submissions per day per target domain (default: 10, configurable range: 1 to 100), where the daily counter resets at midnight UTC
6. IF the daily submission limit for a target domain is reached, THEN THE System SHALL queue remaining submissions for the next UTC day and notify the user in the Dashboard indicating the domain name and the number of queued submissions
7. IF the Form_Executor is paused due to an HTTP 429 response and the pause duration exceeds 10 minutes, THEN THE Form_Executor SHALL notify the user in the Dashboard with the affected domain and estimated resume time
