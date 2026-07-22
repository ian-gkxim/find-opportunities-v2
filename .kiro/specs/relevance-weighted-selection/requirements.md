# Requirements Document

## Introduction

Relevance-Weighted Content Selection provides a deterministic, testable algorithm for deciding what to cut when a generated material exceeds its length constraint, and what to include when composing from a larger pool of profile content than fits. Instead of static priority orders (e.g. "cut oldest first"), every candidate content unit is scored on relevance to the specific opportunity, uniqueness within the material, and narrative dependency from companion materials — and the lowest-scoring units are cut first regardless of section or recency. The module follows the scoring_engine pattern: pure computation, no I/O, no async, property-testable. Priority: P5 (a dependency of the future CVGeneratorService).

## Glossary

- **Content_Selector**: The new pure-computation module that scores and ranks content units for inclusion or cutting
- **Content_Unit**: An atomic piece of material content that can be independently included or cut: an experience bullet, a skill entry, a sentence in a paragraph, or a profile statement line
- **Relevance_Score**: A 0–100 sub-score measuring a Content_Unit's match to the opportunity's extracted keywords, required capabilities, and responsibilities
- **Uniqueness_Score**: A 0–100 sub-score penalizing Content_Units whose information is duplicated elsewhere in the same material set
- **Narrative_Dependency_Score**: A 0–100 sub-score measuring whether a companion material (e.g. the cover letter) references or depends on the Content_Unit
- **Length_Constraint**: A per-material-type limit declared in the Schema_Registry (e.g. maximum words, characters, or bullets)
- Existing terms (Schema_Registry, Personalization_Engine) are as defined in the system-redesign-v2 requirements document

## Requirements

### Requirement 1: Pure Scoring Module

**User Story:** As a system maintainer, I want content selection implemented as a pure function module, so that its behavior is deterministic and property-testable like the Scoring_Engine.

#### Acceptance Criteria

1. THE Content_Selector SHALL be implemented with no database access, no async operations, and no I/O, accepting Content_Units, opportunity keywords, and companion material references as plain inputs
2. THE Content_Selector SHALL compute for each Content_Unit a composite score from the weighted sub-scores: Relevance_Score (default weight 50%), Uniqueness_Score (default weight 25%), and Narrative_Dependency_Score (default weight 25%)
3. THE Content_Selector SHALL accept a configurable weight distribution where each weight is an integer between 0 and 100 and all weights total exactly 100, rejecting invalid configurations with a descriptive error
4. WHEN two Content_Units have equal composite scores, THE Content_Selector SHALL break the tie by higher Relevance_Score, then by document order

### Requirement 2: Cutting Behavior

**User Story:** As a Consultant user, I want cuts made by relevance to this specific opportunity, so that an older but keyword-matching achievement survives over a recent but irrelevant one.

#### Acceptance Criteria

1. WHEN a material exceeds its Length_Constraint, THE Content_Selector SHALL return a cut list ordered lowest-composite-score-first, sufficient to bring the material within the constraint, regardless of the section or recency of the cut units
2. THE Content_Selector SHALL NOT cut a Content_Unit with a Narrative_Dependency_Score above a configurable protection threshold (default 80) unless no other cuts can satisfy the Length_Constraint, and in that case SHALL include a warning in its output identifying the dependent companion passage
3. WHEN cutting sentences within a paragraph, THE Content_Selector SHALL prioritize cutting sentences that restate information already carried by a bullet or other Content_Unit (low Uniqueness_Score) before cutting sentences carrying unique information

### Requirement 3: Schema and Integration

**User Story:** As a system maintainer, I want length constraints declared per material type in the schema, so that constraints are configuration rather than code.

#### Acceptance Criteria

1. THE Schema_Registry SHALL support an optional `length_constraints` declaration on each prepare technique output, expressed as maximum words, maximum characters, or maximum units per section
2. WHEN a prepare technique produces a material exceeding its declared Length_Constraint, THE Personalization_Engine SHALL invoke the Content_Selector and apply the returned cut list before the material enters review, recording the cut units and their scores in the reasoning_log
3. WHERE no Length_Constraint is declared for a material type, THE Personalization_Engine SHALL skip content selection entirely
