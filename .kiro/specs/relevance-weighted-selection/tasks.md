# Implementation Plan: Relevance-Weighted Content Selection

## Overview

Implement the Content_Selector module as a pure-computation engine that scores content units and generates cut lists when generated materials exceed their length constraints. Follows the existing ScoringEngine pattern: frozen dataclasses, no I/O, deterministic output. Integrates into the PersonalizationEngine pipeline and reads constraints from Schema_Registry YAML.

## Tasks

- [x] 1. Define core dataclasses and enums
  - [x] 1.1 Create `app/core/content_selector.py` with enums and input dataclasses
    - Define `ContentUnitType` and `ConstraintType` enums
    - Implement `ContentUnit`, `CompanionReference`, `SelectionWeights`, `LengthConstraint`, and `SelectionConfig` frozen dataclasses
    - Implement `SelectionWeights.validate()` returning `(bool, str)` tuple
    - _Requirements: 1.1, 1.2, 1.3_

  - [x] 1.2 Add output dataclasses to `app/core/content_selector.py`
    - Implement `ScoredUnit`, `CutEntry`, `ProtectionWarning`, and `SelectionResult` frozen dataclasses
    - _Requirements: 1.2, 2.1, 2.2_

- [x] 2. Implement ContentSelector class and sub-score algorithms
  - [x] 2.1 Implement `ContentSelector` class skeleton and `_measure_length` helper
    - Create `ContentSelector` class with docstring following ScoringEngine style
    - Implement `_measure_length(units, constraint)` supporting MAX_WORDS, MAX_CHARACTERS, MAX_UNITS
    - _Requirements: 1.1, 2.1_

  - [x] 2.2 Implement `_compute_relevance_score` method
    - Substring matching of opportunity keywords against unit text (case-insensitive)
    - Handle edge cases: empty keywords → 100, empty text → 0
    - _Requirements: 1.2_

  - [x] 2.3 Implement `_compute_uniqueness_scores` method
    - Pairwise token overlap via Jaccard similarity (lowercase, stopwords removed)
    - Each unit's uniqueness = 100 - (max_overlap * 100), clamped to [0, 100]
    - _Requirements: 1.2, 2.3_

  - [x] 2.4 Implement `_compute_narrative_dependency_score` method
    - Match CompanionReferences by target_unit_id
    - Score = max(strength) of matching references, 0 if no matches
    - _Requirements: 1.2, 2.2_

  - [x] 2.5 Implement `_compute_composite_score` and `_score_all_units` methods
    - Weighted combination: `round((R * w_r + U * w_u + N * w_n) / 100)`
    - `_score_all_units` orchestrates calling all three sub-score functions and builds `ScoredUnit` list
    - _Requirements: 1.2, 1.3_

  - [x] 2.6 Write property test for composite score formula
    - **Property 1: Composite Score Formula**
    - **Validates: Requirements 1.2**

  - [x] 2.7 Write property test for weight validation
    - **Property 2: Weight Validation Acceptance and Rejection**
    - **Validates: Requirements 1.3**

- [x] 3. Implement cut list generation with protection logic
  - [x] 3.1 Implement `_generate_cut_list` method
    - Sort scored units ascending by composite score with tie-breaking: `(composite_score, relevance_score, -document_order)`
    - Iteratively cut lowest-scoring unprotected units until constraint is satisfied
    - If only protected units remain and constraint still exceeded, force-cut with warnings
    - Return `(list[CutEntry], list[ProtectionWarning])`
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.2 Implement `select_content` public method
    - Validate config, orchestrate scoring, generate cut list, compute retained units and lengths
    - Handle edge cases: empty units list, constraint already satisfied
    - Raise ValueError for invalid weights or protection threshold
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.1, 2.2_

  - [x] 3.3 Write property test for cut list ordering and constraint satisfaction
    - **Property 3: Cut List Satisfies Constraint with Correct Ordering**
    - **Validates: Requirements 2.1, 2.3**

  - [x] 3.4 Write property test for tie-breaking determinism
    - **Property 4: Tie-Breaking Determinism**
    - **Validates: Requirements 1.4**

  - [x] 3.5 Write property test for protection threshold invariant
    - **Property 5: Protection Threshold Invariant**
    - **Validates: Requirements 2.2**

- [x] 4. Checkpoint - Core module complete
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Extend Schema_Registry with length constraints
  - [x] 5.1 Add `LengthConstraintConfig` dataclass to `app/core/schema_registry.py`
    - Frozen dataclass with optional `max_words`, `max_characters`, `max_units` fields
    - Implement `to_length_constraint()` method converting to Content_Selector's `LengthConstraint`
    - _Requirements: 3.1_

  - [x] 5.2 Extend Schema_Registry parsing to load `length_constraints` from YAML
    - Parse optional `length_constraints` mapping on each prepare technique output
    - Add `get_length_constraint(material_type: str) -> LengthConstraint | None` method
    - _Requirements: 3.1_

  - [x] 5.3 Write property test for schema length constraints parsing round-trip
    - **Property 6: Schema Length Constraints Parsing Round-Trip**
    - **Validates: Requirements 3.1**

- [x] 6. Integrate Content_Selector into PersonalizationEngine
  - [x] 6.1 Wire Content_Selector invocation in PersonalizationEngine
    - After material generation, check if length constraint exists via Schema_Registry
    - If material exceeds constraint, invoke `ContentSelector.select_content()`
    - Apply returned cut list to the material
    - Record cut units and scores in `reasoning_log`
    - _Requirements: 3.2, 3.3_

  - [x] 6.2 Write unit tests for Content_Selector edge cases
    - Test default weights produce expected scores for known inputs
    - Test all-zero relevance (no keyword matches → score 0)
    - Test single-unit material (never cut if constraint ≥ 1)
    - Test exact constraint boundary (no cuts)
    - Test force-cut scenario (all protected, over limit → warnings)
    - Test document order stability (identical scores → last-in-document cut first)
    - _Requirements: 1.2, 1.4, 2.1, 2.2_

  - [x] 6.3 Write integration tests for PersonalizationEngine wiring
    - Test PersonalizationEngine invokes ContentSelector when material exceeds constraint
    - Test PersonalizationEngine skips when no constraint declared
    - Test reasoning_log records cuts with scores
    - Test Schema_Registry loads length_constraints from real YAML
    - _Requirements: 3.1, 3.2, 3.3_

- [x] 7. Final checkpoint - All tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirement acceptance criteria for traceability
- Property tests use Hypothesis with `@settings(max_examples=200)`
- Unit tests and integration tests use pytest following existing project conventions
- The module lives at `app/core/content_selector.py`; tests at `app/tests/core/test_content_selector.py`
- Follows the existing ScoringEngine pattern: frozen dataclasses, weight validation, pure functions

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["2.5", "2.6", "2.7"] },
    { "id": 4, "tasks": ["3.1"] },
    { "id": 5, "tasks": ["3.2", "3.3", "3.4", "3.5"] },
    { "id": 6, "tasks": ["5.1"] },
    { "id": 7, "tasks": ["5.2", "5.3"] },
    { "id": 8, "tasks": ["6.1"] },
    { "id": 9, "tasks": ["6.2", "6.3"] }
  ]
}
```
