# Requirements Document

## Introduction

The Outbound Validation Gate is a deterministic, rule-based final check that runs immediately before any material leaves the system via the Lemlist_Engine or Gmail integration. Its premise, borrowed from render-verification practice: content that looks fine at the source layer routinely breaks at the delivery layer — unreplaced template tokens, missing signatures, broken links, wrong recipient names. The gate uses no LLM calls; it is a fast, cheap, always-on rules engine whose checks are declared per outreach technique in the schema. Priority: P6.

## Glossary

- **Outbound_Validator**: The new rule-based service that validates a material immediately prior to submission to an external send channel
- **Validation_Rule**: A single deterministic check with an id, a severity ("blocking" or "warning"), and a pass/fail result
- **Validation_Report**: The structured record of all Validation_Rule results for one send attempt
- **Send_Channel**: An external delivery integration: Lemlist_Engine sequence enrollment or Gmail API send
- Existing terms (Lemlist_Engine, Schema_Registry, Pipeline states, Dashboard) are as defined in the system-redesign-v2 requirements document

## Requirements

### Requirement 1: Pre-Send Interception

**User Story:** As a Team user, I want every outgoing material validated at the last moment before send, so that delivery-layer defects never reach a prospect.

#### Acceptance Criteria

1. WHEN a material is submitted to any Send_Channel, THE Outbound_Validator SHALL execute all configured Validation_Rules and complete within 5 seconds, excluding optional link liveness checks
2. IF any blocking Validation_Rule fails, THEN THE Outbound_Validator SHALL prevent the submission, transition the pipeline record to a "validation_failed" requires-action state, and surface each failed rule with the offending text span in the Dashboard "Requires Action" section
3. IF only warning-severity Validation_Rules fail, THEN THE Outbound_Validator SHALL permit the submission and attach the warnings to the Validation_Report
4. THE Outbound_Validator SHALL store a Validation_Report for every send attempt, retrievable from the pipeline record's detail view

### Requirement 2: Core Rule Set

**User Story:** As a Consultant user, I want the common failure modes checked automatically, so that embarrassing template errors are impossible to send.

#### Acceptance Criteria

1. THE Outbound_Validator SHALL provide built-in blocking rules that fail when a material contains: unreplaced template tokens matching `{{...}}`, `{...}`, `[PLACEHOLDER]`, or `<INSERT...>` patterns; an empty or missing subject line for email materials; a missing signature block where the outreach technique requires one; a recipient first or last name that does not match the pipeline record's contact; or an empty required personalization field
2. THE Outbound_Validator SHALL provide built-in warning rules that fail when a material: exceeds or falls below configured length bounds for its material type; contains a URL that is syntactically malformed; or contains consecutive duplicate words or repeated sentences
3. WHERE link liveness checking is enabled for an outreach technique, THE Outbound_Validator SHALL verify each URL responds with HTTP status < 400 within a 5-second timeout per link, treating timeouts as warning-severity failures rather than blocking
4. THE Outbound_Validator SHALL execute no LLM calls in any Validation_Rule

### Requirement 3: Schema-Driven Configuration

**User Story:** As a system maintainer, I want the active rule set declared per outreach technique, so that email, sequence, and tender submissions each get appropriate checks.

#### Acceptance Criteria

1. THE Schema_Registry SHALL support a `validation_rules` declaration per outreach technique listing enabled rule ids, per-rule severity overrides, and rule parameters (length bounds, required signature, link checking on/off)
2. WHEN the schema is loaded, THE Schema_Registry SHALL validate that every declared rule id corresponds to a built-in rule, failing startup with a descriptive error if not
3. WHERE no `validation_rules` declaration exists for an outreach technique, THE Outbound_Validator SHALL apply the built-in blocking rules with default parameters
