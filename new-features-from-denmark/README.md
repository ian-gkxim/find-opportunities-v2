# Kiro Specs: Enhancements from ai-job-search Patterns

Eight feature specs for GKIM Opportunity Finder v2, adapting proven patterns from the ai-job-search Claude Code workspace. Each folder follows the `.kiro/specs/<feature-slug>/requirements.md` convention (Introduction, Glossary, EARS-format acceptance criteria) matching `system-redesign-v2/requirements.md`. Drop the folders into `.kiro/specs/` and run Kiro's design phase per feature.

## Priority Order

| # | Spec | Origin pattern (ai-job-search) | Effort | Rationale |
|---|------|-------------------------------|--------|-----------|
| P1 | `review-critique-loop` | Drafter–reviewer two-agent workflow in `/apply` | Medium | Largest quality lift; lands in the not-yet-built generation services, so no rework |
| P2 | `claim-grounding-verification` | "All claims grounded in profile data" rule | Medium | Business-risk mitigation for automated volume sending; shares P1's insertion point — build together |
| P3 | `sender-voice-assets` | `02-behavioral-profile.md` + `03-writing-style.md` | Small | Config + prompt change; direct reply-rate lever for cold outreach |
| P4 | `capability-gap-analytics` | `/upskill` gap heatmap | Medium | Most differentiating analytics feature; strategic firm-level insight |
| P5 | `relevance-weighted-selection` | Relevance-weighted CV cutting algorithm | Small | Pure-function module; prerequisite for a quality CVGeneratorService |
| P6 | `outbound-validation-gate` | PDF compile-and-inspect verification loop (principle) | Small | Cheap, deterministic, always-on protection before Lemlist/Gmail |
| P7 | `internal-profile-enrichment` | `/expand` competency discovery | Medium | Keeps profiles current; improves scoring and personalization upstream |
| P8 | `interview-prep-technique` | `07-interview-prep.md` STAR workflow | Small | Makes the Interview state productive; depends on P2 |

## Dependency Map

- **P1 + P2** share the prepare-pipeline insertion point and should be implemented in the same milestone. P2's gate assumes P1's reasoning_log conventions.
- **P3** extends P1's reviewer (voice check category) but degrades gracefully without it.
- **P5** is consumed by the future `CVGeneratorService` (declared in `config/schema.yaml` but not yet implemented) and by any length-constrained material type.
- **P8** requires P2 (Grounding_Verifier) for talking-point verification.
- **P4, P6, P7** are independent and can be scheduled opportunistically.

## Deliberate Exclusions

The LaTeX toolchain from ai-job-search was intentionally not ported (dual compile engines, font fragility, high maintenance). P6 adopts its verification-loop *philosophy* at the delivery layer instead; if rendered documents are needed later, prefer an HTML-to-PDF pipeline with the same render-inspect-iterate discipline.
