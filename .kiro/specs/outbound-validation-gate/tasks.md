# Implementation Plan: Outbound Validation Gate

## Overview

Implement a deterministic, rule-based Outbound_Validator service that intercepts every material before submission to Send_Channels (Lemlist_Engine, Gmail). Implementation proceeds bottom-up: data models & interfaces → built-in rule implementations → Schema Registry extension → Pipeline Manager extension → Outbound Validator service → database persistence → ARQ worker integration → property-based & unit tests.

## Tasks

- [x] 1. Define core interfaces and data models
  - [x] 1.1 Create `app/core/outbound_validator.py` with enums, dataclasses, and abstract base
    - Define `RuleSeverity` enum with BLOCKING and WARNING values
    - Define `TextSpan`, `RuleResult`, `ValidationContext`, `Material` dataclasses
    - Define `ValidationRuleConfig`, `ValidationReport`, `ValidationGateResult` dataclasses
    - Define abstract `ValidationRule` base class with `rule_id`, `default_severity`, and `check()` method
    - Define `BUILT_IN_RULES`, `ASYNC_RULES`, and `DEFAULT_BLOCKING_RULE_IDS` module-level registries (empty initially)
    - _Requirements: 1.1, 2.4_

  - [x] 1.2 Create `app/models/validation_report.py` with SQLAlchemy ORM model
    - Define `ValidationReportModel` with UUID primary key, `pipeline_record_id` FK, `outreach_technique`, `passed`, `has_warnings`, `total_execution_ms`, `results` (JSONB), `created_at`
    - Add relationship to `PipelineRecord` model via backref
    - _Requirements: 1.4_

  - [x] 1.3 Create Alembic migration for `validation_reports` table
    - Create migration adding the `validation_reports` table with all columns and constraints
    - Add indexes: `idx_validation_reports_pipeline` on pipeline_record_id, `idx_validation_reports_created` on created_at DESC, `idx_validation_reports_failed` partial index on passed WHERE passed = FALSE
    - _Requirements: 1.4_

- [x] 2. Implement blocking validation rules
  - [x] 2.1 Implement `UnreplacedTokenRule` in `app/core/outbound_validator.py`
    - Detect `{{...}}`, `{word}`, `[PLACEHOLDER]`, and `<INSERT...>` patterns in subject and body
    - Return `RuleResult` with `passed=False` and offending `TextSpan` list when tokens found
    - Register in `BUILT_IN_RULES` dict
    - _Requirements: 2.1_

  - [x] 2.2 Implement `EmptySubjectRule` in `app/core/outbound_validator.py`
    - Fail if `material_type == "email"` and subject is empty/missing/whitespace-only
    - Pass for non-email material types
    - Register in `BUILT_IN_RULES` dict
    - _Requirements: 2.1_

  - [x] 2.3 Implement `MissingSignatureRule` in `app/core/outbound_validator.py`
    - Fail if `params.required` is True and signature is empty/missing
    - Pass if signature not required by params
    - Register in `BUILT_IN_RULES` dict
    - _Requirements: 2.1_

  - [x] 2.4 Implement `RecipientNameMismatchRule` in `app/core/outbound_validator.py`
    - Extract names from greeting patterns (Hi/Hello/Dear/Hey + Name) in body
    - Compare against `context.contact_first_name` and `context.contact_last_name`
    - Return `passed=False` with TextSpans for any mismatched greetings
    - Register in `BUILT_IN_RULES` dict
    - _Requirements: 2.1_

  - [x] 2.5 Implement `EmptyPersonalizationFieldRule` in `app/core/outbound_validator.py`
    - Check all required personalization fields from params or context have non-empty values
    - Return `passed=False` listing missing fields
    - Register in `BUILT_IN_RULES` dict
    - _Requirements: 2.1_

  - [x] 2.6 Write property test for unreplaced token detection (Property 3)
    - **Property 3: Unreplaced token detection**
    - Generate material bodies with/without token patterns using `st.from_regex`
    - Assert `passed == (no tokens present)` and spans identify all tokens
    - **Validates: Requirements 2.1**

  - [x] 2.7 Write property test for recipient name mismatch detection (Property 4)
    - **Property 4: Recipient name mismatch detection**
    - Generate (greeting_name, contact_name) pairs where they match and where they differ
    - Assert `passed=False` when names differ; `passed=True` when they match
    - **Validates: Requirements 2.1**

  - [x] 2.8 Write unit tests for all five blocking rules
    - Test UnreplacedTokenRule: `"Hi {{name}}"` → fail; `"Hi John"` → pass
    - Test EmptySubjectRule: empty subject for email → fail; non-email → pass
    - Test MissingSignatureRule: required + missing → fail; not required → pass
    - Test RecipientNameMismatchRule: `"Hi Sarah"` with contact "John" → fail
    - Test EmptyPersonalizationFieldRule: required field empty → fail
    - _Requirements: 2.1_

- [x] 3. Implement warning validation rules
  - [x] 3.1 Implement `LengthBoundsRule` in `app/core/outbound_validator.py`
    - Warn if body length is below `min_length` or above `max_length` params
    - Default bounds: 50–5000 characters
    - Register in `BUILT_IN_RULES` dict
    - _Requirements: 2.2_

  - [x] 3.2 Implement `MalformedUrlRule` in `app/core/outbound_validator.py`
    - Find URLs matching `https?://...` or `www.` patterns in subject and body
    - Validate each has a netloc with at least one dot
    - Return TextSpans for malformed URLs
    - Register in `BUILT_IN_RULES` dict
    - _Requirements: 2.2_

  - [x] 3.3 Implement `DuplicateContentRule` in `app/core/outbound_validator.py`
    - Detect consecutive duplicate words via regex `\b(\w+)\s+\1\b`
    - Detect repeated sentences by normalizing and comparing
    - Return TextSpans for all duplicate content issues
    - Register in `BUILT_IN_RULES` dict
    - _Requirements: 2.2_

  - [x] 3.4 Implement `LinkLivenessRule` as async rule in `app/core/outbound_validator.py`
    - Use `httpx.AsyncClient` to HEAD-request each URL found in material
    - 5-second timeout per link; treat timeouts and HTTP ≥ 400 as warning failures
    - Only run when `params.enabled` is True
    - Register in `ASYNC_RULES` dict
    - _Requirements: 2.3_

  - [x] 3.5 Write unit tests for warning rules
    - Test LengthBoundsRule: 49 chars → fail, 50 chars → pass, 5001 chars → fail
    - Test MalformedUrlRule: `"http://valid.com"` → pass, `"http://nohost"` → fail
    - Test DuplicateContentRule: `"the the"` → fail, normal text → pass
    - Test LinkLivenessRule with mocked httpx: 200 → pass, 404 → fail, timeout → warning
    - _Requirements: 2.2, 2.3_

- [x] 4. Checkpoint
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Extend Schema Registry with validation_rules support
  - [x] 5.1 Add `ValidationRuleDeclaration` dataclass and parsing to `app/core/schema_registry.py`
    - Define `ValidationRuleDeclaration` frozen dataclass with `rule_id`, `severity`, and `params`
    - Add optional `validation_rules: list[ValidationRuleDeclaration]` field to `Technique` dataclass
    - Parse `validation_rules` from YAML within technique loading logic
    - _Requirements: 3.1_

  - [x] 5.2 Add startup validation for declared rule ids in Schema Registry
    - Implement `_validate_validation_rules()` that checks every declared rule_id exists in `BUILT_IN_RULES` or `ASYNC_RULES`
    - Validate severity values are "blocking" or "warning" only
    - Raise `SchemaValidationError` with descriptive message on unknown rule or invalid severity
    - Wire into existing `_validate()` method
    - _Requirements: 3.2_

  - [x] 5.3 Implement `get_validation_rules()` public method on SchemaRegistry
    - Return `list[ValidationRuleConfig]` when technique has `validation_rules` declaration
    - Return `None` when technique has no declaration (triggers default fallback)
    - Map `ValidationRuleDeclaration` to `ValidationRuleConfig` with severity enum conversion
    - _Requirements: 3.1, 3.3_

  - [x] 5.4 Add `validation_rules` section to outreach techniques in `config/schema.yaml`
    - Add validation_rules to `cold_email_consultant` technique with all 8 rules + link liveness
    - Configure per-rule params (required_fields for personalization, length bounds, signature required)
    - _Requirements: 3.1_

  - [x] 5.5 Write property test for schema config resolution with defaults (Property 5)
    - **Property 5: Schema config resolution with defaults**
    - Generate technique entries with/without validation_rules sections
    - Assert `get_validation_rules()` returns list for configured techniques and None for unconfigured
    - **Validates: Requirements 3.1, 3.3**

  - [x] 5.6 Write property test for unknown rule id rejection at startup (Property 6)
    - **Property 6: Unknown rule id rejection at startup**
    - Generate rule_id strings not in `BUILT_IN_RULES | ASYNC_RULES` keyset
    - Assert `SchemaValidationError` raised during schema validation with correct error message
    - **Validates: Requirements 3.2**

  - [x] 5.7 Write unit tests for Schema Registry validation_rules parsing
    - Test valid YAML produces correct `ValidationRuleDeclaration` instances
    - Test missing validation_rules field results in empty list on Technique
    - Test get_validation_rules returns correct configs with severity overrides
    - _Requirements: 3.1, 3.2_

- [x] 6. Extend Pipeline Manager with validation_failed state
  - [x] 6.1 Add `VALIDATION_FAILED` to `RequiresActionType` enum in `app/core/pipeline_manager.py`
    - Add `VALIDATION_FAILED = "validation_failed"` enum value
    - _Requirements: 1.2_

  - [x] 6.2 Implement `transition_to_validation_failed()` method on PipelineManager
    - Accept `record_id` and `blocking_failures: list[RuleResult]`
    - Transition pipeline record to "validation_failed" state
    - Broadcast detailed failure info (with offending text spans) to Dashboard via WebSocket
    - Handle missing pipeline record gracefully (log error, return INVALID_STATE)
    - _Requirements: 1.2_

  - [x] 6.3 Write unit tests for Pipeline Manager validation_failed transition
    - Test transition updates record state to validation_failed
    - Test WebSocket broadcast includes blocking failure details with text spans
    - Test missing record_id returns INVALID_STATE result
    - _Requirements: 1.2_

- [x] 7. Implement Outbound Validator service
  - [x] 7.1 Implement `OutboundValidator` class in `app/core/outbound_validator.py`
    - Constructor accepts `SchemaRegistry`, `PipelineManager`, and `ValidationRepository` dependencies
    - Implement `get_rules_for_technique()` with default fallback logic
    - _Requirements: 1.1, 3.3_

  - [x] 7.2 Implement `validate()` method on OutboundValidator
    - Load rule configs via `get_rules_for_technique()`
    - Execute sync rules from `BUILT_IN_RULES`, then async rules from `ASYNC_RULES`
    - Track per-rule execution time in `RuleResult.execution_ms`
    - Build and persist `ValidationReport` via repository
    - _Requirements: 1.1, 1.4_

  - [x] 7.3 Implement `validate_and_send()` method on OutboundValidator
    - Call `validate()` first
    - On blocking failures: call `PipelineManager.transition_to_validation_failed()`, return `ValidationGateResult(blocked=True)`
    - On pass: call `send_fn()`, return `ValidationGateResult(blocked=False, send_result=...)`
    - _Requirements: 1.2, 1.3_

  - [x] 7.4 Write property test for gate blocks iff blocking rule fails (Property 1)
    - **Property 1: Gate blocks iff blocking rule fails**
    - Generate materials with varying rule configs and severity combinations
    - Assert `blocked == any(not r.passed and r.severity == BLOCKING for r in results)`
    - **Validates: Requirements 1.2, 1.3**

  - [x] 7.5 Write property test for report completeness (Property 2)
    - **Property 2: Report completeness**
    - Generate random subsets of BUILT_IN_RULES keys as rule configs
    - Assert `len(report.results) == len(configs)` and all rule_ids match configured set
    - **Validates: Requirements 1.1, 1.4**

  - [x] 7.6 Write unit tests for OutboundValidator service
    - Test validate_and_send blocks when blocking rule fails, verify PipelineManager called
    - Test validate_and_send permits send when only warnings present, verify send_fn called
    - Test default rules fallback when technique has no config
    - Test ValidationReport persistence via mock repository
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 8. Implement ValidationRepository for persistence
  - [x] 8.1 Create `app/repositories/validation_repository.py`
    - Implement `save_validation_report()` to serialize and persist `ValidationReport` to PostgreSQL
    - Implement `get_report_by_id()` to retrieve and deserialize a report
    - Implement `get_reports_for_pipeline_record()` to list reports for a pipeline record
    - Handle JSON serialization of `RuleResult` list for JSONB column
    - _Requirements: 1.4_

  - [x] 8.2 Write unit tests for ValidationRepository
    - Test round-trip save and retrieve of ValidationReport
    - Test JSON serialization/deserialization of RuleResult with TextSpans
    - Test query by pipeline_record_id returns correct reports
    - _Requirements: 1.4_

- [x] 9. Integrate Outbound Validator into ARQ workers
  - [x] 9.1 Wire `OutboundValidator.validate_and_send()` into Lemlist Engine outreach worker
    - Replace direct `LemlistEngine.enroll_prospects()` call with `validator.validate_and_send(material, context, send_fn)`
    - Construct `Material` and `ValidationContext` from existing worker parameters
    - Handle `ValidationGateResult.blocked == True` path (log, skip send)
    - _Requirements: 1.1, 1.2_

  - [x] 9.2 Wire `OutboundValidator.validate_and_send()` into Gmail send path
    - Replace direct Gmail send call with `validator.validate_and_send(material, context, send_fn)`
    - Construct `Material` and `ValidationContext` from Gmail worker parameters
    - Handle blocked path same as Lemlist integration
    - _Requirements: 1.1, 1.2_

  - [x] 9.3 Write integration tests for end-to-end validation flow
    - Test material with blocking failure → send_fn never called, pipeline transitions
    - Test material with only warnings → send_fn called, report stored with warnings
    - Test material passing all rules → send_fn called, report stored with passed=True
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 10. Final checkpoint
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- All rules execute no LLM calls — deterministic, fast, and cheap
- The LinkLivenessRule is async and uses httpx; all other rules are synchronous
- The existing Schema_Registry, Pipeline Manager, and ARQ worker patterns are extended rather than replaced

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2", "1.3"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4", "2.5", "6.1"] },
    { "id": 2, "tasks": ["2.6", "2.7", "2.8", "3.1", "3.2", "3.3", "3.4"] },
    { "id": 3, "tasks": ["3.5", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3", "5.4"] },
    { "id": 5, "tasks": ["5.5", "5.6", "5.7", "6.2"] },
    { "id": 6, "tasks": ["6.3", "7.1"] },
    { "id": 7, "tasks": ["7.2", "7.3", "8.1"] },
    { "id": 8, "tasks": ["7.4", "7.5", "7.6", "8.2"] },
    { "id": 9, "tasks": ["9.1", "9.2"] },
    { "id": 10, "tasks": ["9.3"] }
  ]
}
```
