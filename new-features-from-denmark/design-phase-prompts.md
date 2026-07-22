# Design Phase Prompts — 8 Feature Specs

Use each prompt in a fresh Kiro spec session. When prompted for spec type, choose **"Build a Feature"**, then **"Technical Design"** (with both High-Level and Low-Level Design selected). Point it at the existing requirements.md in `.kiro/specs/<feature-slug>/`.

---

## P1: review-critique-loop

```
I have an existing requirements.md at .kiro/specs/review-critique-loop/requirements.md for the Review Critique Loop feature. This introduces a second, independent LLM evaluation pass (fresh-context reviewer) over every generated outreach material before it advances in the pipeline. The reviewer returns Structured_Edits (machine-applicable find-and-replace instructions) and Narrative_Findings, bounded to a configurable number of Review_Cycles.

Please review the requirements document, then generate the technical design (design.md) for this feature. Key design considerations:
- How Review_Service integrates into the existing prepare pipeline (it shares an insertion point with claim-grounding-verification P2)
- The structured response schema for Structured_Edits and Narrative_Findings
- Concurrency control for batch processing (max 3 concurrent critiques)
- The reasoning_log format for review cycle telemetry
- Schema_Registry extensions for review_techniques declarations
- Retry and graceful degradation when the LLM critique fails

Reference the system-redesign-v2 spec at .kiro/specs/system-redesign-v2/ for existing architecture context (Personalization_Engine, LLM_Router, Pipeline states, Schema_Registry patterns).
```

---

## P2: claim-grounding-verification

```
I have an existing requirements.md at .kiro/specs/claim-grounding-verification/requirements.md for the Claim Grounding Verification feature. This adds a deterministic gate ensuring no outreach material asserts a skill, achievement, credential, or metric not traceable to the Beneficiary's verified profile assets. Claims are extracted, verified against profile sources, and ungrounded claims block pipeline advancement.

Please review the requirements document, then generate the technical design (design.md). Key design considerations:
- Grounding_Verifier service architecture and its position after Review_Service (P1) in the pipeline
- Claim extraction prompt design and the Claim data model (categories, source spans, Grounding_Status)
- Verification logic: matching claims against baseline_assets vs. Enrichment_Record for prospect-side facts
- The pipeline gate mechanism: blocking transitions to Approve/Applied/Sent/Proposal Submitted
- Resolution paths (regenerate, manual edit, confirm-and-add) and re-verification flow
- Generation-time prevention: prompt injection of grounding constraints
- Analytics: ungrounded-claim rate tracking per prepare technique

Reference the system-redesign-v2 spec at .kiro/specs/system-redesign-v2/ and the review-critique-loop spec at .kiro/specs/review-critique-loop/ since P2 assumes P1's reasoning_log conventions and they share the prepare-pipeline insertion point.
```

---

## P3: sender-voice-assets

```
I have an existing requirements.md at .kiro/specs/sender-voice-assets/requirements.md for the Sender Voice Assets feature. This gives every Beneficiary a persistent voice definition (Writing_Style_Asset for Consultants, Brand_Voice_Asset for Team) consumed at generation time and checked at review time. The goal is making cold outreach sound like the specific person sending it.

Please review the requirements document, then generate the technical design (design.md). Key design considerations:
- Voice_Asset data model: the structured template covering register, rhythm, vocabulary preferences/prohibitions, and exemplar passages
- Schema_Registry extensions for declaring writing_style, behavioral_profile, and brand_voice in baseline_assets
- How Personalization_Engine combines Voice_Asset with recipient Formality_Level (conflict resolution rules)
- Integration with Review_Service: extending the tone/style critique category for voice-mismatch detection
- The `voice_applied` tagging mechanism for A/B observability in Analytics_Service
- Graceful degradation when no Voice_Asset is configured

Reference the system-redesign-v2 spec at .kiro/specs/system-redesign-v2/ and the review-critique-loop spec at .kiro/specs/review-critique-loop/ for Review_Service integration patterns.
```

---

## P4: capability-gap-analytics

```
I have an existing requirements.md at .kiro/specs/capability-gap-analytics/requirements.md for the Capability Gap Analytics feature. This aggregates requirements from lost/rejected/low-tier opportunities, diffs them against Beneficiary capability profiles, and produces a prioritized gap heatmap with estimated blocked pipeline value — at both Consultant and firm level.

Please review the requirements document, then generate the technical design (design.md). Key design considerations:
- Gap_Analyzer component architecture within the existing Analytics_Service
- Capability extraction and normalization: LLM-based extraction, synonym merging, caching per opportunity
- Gap computation: individual Consultant vs. firm-level union diffing, hard-gap vs. soft-gap classification, single-blocker weighting
- Nightly batch scheduling with configurable extraction caps (default 200) and carry-forward logic
- Gap_Heatmap data model: ranking, diff against previous report (new/growing/shrinking/resolved)
- On-demand single-opportunity gap analysis within 120 seconds
- WebSocket notification to Dashboard when new heatmap is available
- Learning recommendation generation (advisory, LLM-based)

Reference the system-redesign-v2 spec at .kiro/specs/system-redesign-v2/ for Analytics_Service, Scoring_Engine, and Dashboard patterns.
```

---

## P5: relevance-weighted-selection

```
I have an existing requirements.md at .kiro/specs/relevance-weighted-selection/requirements.md for the Relevance-Weighted Content Selection feature. This is a pure-function module (no I/O, no async, property-testable) that scores content units for inclusion/cutting when materials exceed length constraints. It scores by Relevance (keyword match), Uniqueness (deduplication), and Narrative_Dependency (companion material references).

Please review the requirements document, then generate the technical design (design.md). Key design considerations:
- Content_Selector module architecture: pure function signature, input/output contracts
- Content_Unit representation: how to atomize materials into scorable units (bullets, sentences, skill entries)
- Sub-score computation algorithms: Relevance_Score (keyword/capability matching), Uniqueness_Score (information overlap detection), Narrative_Dependency_Score (cross-material reference tracking)
- Composite scoring with configurable weights (must total 100, validated at input)
- Cutting algorithm: ordered cut list, protection threshold for high narrative-dependency units, paragraph-internal sentence cutting logic
- Tie-breaking rules (Relevance_Score first, then document order)
- Schema_Registry extension: length_constraints per prepare technique output
- Property-based testing strategy: what invariants to test (ordering, totals, protection threshold behavior)

Reference the system-redesign-v2 spec at .kiro/specs/system-redesign-v2/ for Scoring_Engine pure-function patterns and Schema_Registry conventions.
```

---

## P6: outbound-validation-gate

```
I have an existing requirements.md at .kiro/specs/outbound-validation-gate/requirements.md for the Outbound Validation Gate feature. This is a deterministic, rule-based final check running immediately before any material leaves via Lemlist_Engine or Gmail — catching unreplaced tokens, missing signatures, wrong recipient names, broken links. No LLM calls; fast, cheap, always-on.

Please review the requirements document, then generate the technical design (design.md). Key design considerations:
- Outbound_Validator service architecture: interception point in the send flow (before Lemlist_Engine and Gmail integration)
- Validation_Rule interface: id, severity (blocking/warning), parameters, pass/fail + offending text span
- Built-in rule implementations: template token regex patterns, subject line check, signature detection, recipient name matching, URL syntax and optional liveness checking
- Validation_Report data model and storage
- Schema_Registry extensions: validation_rules declaration per outreach technique with severity overrides and parameters
- Performance: all rules completing within 5 seconds (excluding link liveness), link liveness with 5s per-link timeout
- Pipeline state transition to "validation_failed" on blocking failure

Reference the system-redesign-v2 spec at .kiro/specs/system-redesign-v2/ for Lemlist_Engine, Pipeline states, and Schema_Registry patterns.
```

---

## P7: internal-profile-enrichment

```
I have an existing requirements.md at .kiro/specs/internal-profile-enrichment/requirements.md for the Internal Profile Enrichment feature. This periodically scans each Consultant's configured public sources (GitHub, portfolio, Google Scholar, etc.), discovers competencies not yet in the profile, and proposes additive-only updates with source attribution — never modifying existing content, never merging without human approval.

Please review the requirements document, then generate the technical design (design.md). Key design considerations:
- Profile_Enrichment_Worker architecture: scheduler, per-source scanning logic, throttling (1 req/sec per domain, 15s timeout)
- Public_Source configuration model: up to 10 sources per Consultant, source types and URLs
- Competency extraction via LLM_Router: prompt design for different source types (GitHub repos, publications, certifications)
- Deduplication logic: against existing profile assets AND previously rejected proposals
- Competency_Proposal data model: evidence, confidence level (strong/inferred), source attribution
- Proposal_Review UX flow in Dashboard Understand stage: accept/edit/reject, bulk operations
- Additive-only merge: append to profile asset section, audit log entry
- Privacy and safety: only configured sources, only the configuring Consultant's data
- Failure handling: 3 consecutive cycle failures trigger Dashboard notice

Reference the system-redesign-v2 spec at .kiro/specs/system-redesign-v2/ for enrichment cycle patterns, baseline_assets structure, and Dashboard conventions.
```

---

## P8: interview-prep-technique

```
I have an existing requirements.md at .kiro/specs/interview-prep-technique/requirements.md for the Interview Prep Technique feature. This generates a grounded preparation pack when an opportunity reaches the Interview pipeline state — likely questions, STAR-format talking points from verified profile data, a company briefing from the Enrichment_Record, and suggested questions to ask. All Beneficiary-side content passes through the Grounding_Verifier.

Please review the requirements document, then generate the technical design (design.md). Key design considerations:
- Interview_Prep_Service as a schema-declared prepare technique triggered on Interview state entry (not material-preparation time)
- Generation context assembly: opportunity description, submitted tailored_cv/cover_letter, Enrichment_Record, profile assets including STAR examples
- Interview_Prep_Pack structure: likely questions (8-15), STAR_Talking_Points (top 5 competency questions), company briefing (≤400 words), questions to ask (3-6)
- STAR_Talking_Point construction: exclusively from profile assets, honest gap-handling for unmet competencies
- Grounding_Verifier integration: verify all Beneficiary-side claims, regenerate affected talking points once on failure
- Schema_Registry wiring: declaring interview_preparation technique, attachable to opportunity types with Interview state
- Regeneration on demand (profile update, rescheduled interview)
- 120-second generation deadline, retry and failure surfacing

Reference the system-redesign-v2 spec at .kiro/specs/system-redesign-v2/ for pipeline state transitions and Schema_Registry prepare technique patterns, and .kiro/specs/claim-grounding-verification/ for Grounding_Verifier integration.
```

---

## Recommended Execution Order

1. **P1 + P2 together** (shared insertion point, P2 depends on P1's reasoning_log)
2. **P5** (pure function, no dependencies, prerequisite for CVGeneratorService)
3. **P6** (independent, small, deterministic)
4. **P3** (extends P1's reviewer but degrades gracefully)
5. **P4** (independent, medium effort)
6. **P7** (independent, medium effort)
7. **P8** (depends on P2's Grounding_Verifier)
