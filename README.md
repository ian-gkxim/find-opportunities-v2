# GKIM Opportunity Finder v2

A comprehensive redesign of the opportunity-finding platform for GKIM consulting.

## Status

- **Requirements**: Complete (18 requirements in `.kiro/specs/system-redesign-v2/requirements.md`)
- **Design**: Pending
- **Tasks**: Pending

## Key Integrations

- **Apollo.io** — B2B enrichment, contact discovery, intent signals
- **Lemlist** — Multi-channel outreach sequences, A/B testing, response tracking
- **Adzuna** — Job aggregator API
- **Gmail API** — Email sending (OAuth2)
- **LLM** — Anthropic Claude / OpenAI for matching, generation, research

## Architecture

- Backend: Python (FastAPI), PostgreSQL
- Frontend: Component-based (React/Vue/Svelte), WebSockets
- Schema-driven: YAML single source of truth (navigation, pipeline states, technique wiring)
- Two beneficiaries: Consultant (individual) and Team (firm)

## Reference Docs

- `docs/v1-application-schema.yaml` — The v1 schema pattern to retain and extend
- `docs/v1-session-summary.md` — Summary of the v1 system capabilities
# find-opportunities-v2
