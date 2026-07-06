# Find Opportunities — Session Summary

**Date:** 31 May 2026
**Status:** Working app, 54 API routes, GEARS style guide applied

---

## What's Built

### Architecture
- Python 3.9, FastAPI, SQLite (local file: `job_finder.db`)
- Vanilla HTML/JS frontend with GEARS style guide
- Anthropic Claude API (claude-haiku-4-5-20251001) — 5 req/min rate limit
- Adzuna API for job search (app_id: 87598395)
- Local file storage for generated documents (`applications/` directory)

### Navigation (5 primary tabs)
1. **Understand Me** — Manage Candidate Profiles | Establish Baseline | Customisation Instructions
2. **Define Where to Look** — Manage Job Sites List | Manage Company Search Criteria
3. **Find Prospects** — Find Opportunities from Job Sites | Find Opportunities from Companies
4. **Application Pipeline** — Dashboard | Form Assistance
5. **Reports** — Resume Gaps

### Key Features Working
- 4 candidate profiles with full Career Goal Set data (role identity, value proposition, target employer signal, narrative emphasis, tone/register, LLM instruction note)
- 10 job sites (categorised: Core, Cambridge, C-Suite)
- 10 company search criteria
- Adzuna job search with progressive broadening (falls back to role title if specific query returns 0)
- Company discovery with Opportunity Matrix
- AI copilot panel (RHS) with chat input
- Application pipeline: Personalise → Approve → Applied → Interview → Offer → Accepted/Rejected/Abandoned
- CV + Cover Letter generation via single LLM call with:
  - Employer website auto-fetch (with manual URL fallback)
  - Full Career Goal Set data in prompt
  - Gap analysis (4th document section)
  - Reasoning log (3rd document section)
  - `---DOCUMENT_BREAK---` delimiter format
- Resume + Cover Letter baseline upload (overwrite model, no delete)
- PDF export (requires weasyprint system dependencies)
- Form assistance (common application questions)
- Triage buttons on opportunities: "+ Add to Pipeline" / "Maybe Later" / "No Thanks"
- Duplicate checking on discovery
- Test Mode / Full Mode toggle
- Reports tab showing resume gaps from all CV generations

### Database Tables (12)
- job_sites (with category column)
- candidate_profiles (with 6 new goal set columns)
- opportunities
- company_search_criteria
- resumes
- cover_letters
- company_opportunities
- application_records
- triage_actions
- cv_instructions
- form_assistance
- resume_gaps

### Config (.env)
```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-api03-...
ADZUNA_APP_ID=87598395
ADZUNA_APP_KEY=c2d9fdb37ec1b1b162d21e04eb90d80c
```

---

## What's Next (Project Marketplace Spec)

### To Build
1. **Third search type:** "Find Projects from Marketplaces" — searching contract/tender sites
2. **International expansion:** Extend Adzuna to US, AU, CA, NZ (already supported by their API — change country code from `gb` to `us` etc.)
3. **Project marketplace sites to seed:**
   - UK Public Sector: Find a Tender, Contracts Finder, Digital Marketplace, MOD Technology
   - Private Sector: Freelancermap, Freelance.co.uk, Contra, Upwork Enterprise, ContractSpy
   - US: SAM.gov, Upwork, Toptal
   - International: Freelancermap (global), Contra (global)
4. **New document types:**
   - Company Capability Statement (upload/manage)
   - Case Studies (2-4, upload/manage)
   - Base Proposal Template (upload/manage)
   - Project Search Criteria (like company search criteria but for contracts)
5. **Proposal generation** — different from CV generation:
   - Input: project brief + company profile + case studies + proposal template
   - Output: tailored proposal document
6. **New sub-tabs:**
   - "Understand Me" → add "Company Profile" sub-tab
   - "Define Where to Look" → add "Manage Project Marketplaces" sub-tab
   - "Find Prospects" → add "Find Projects from Marketplaces" sub-tab

### Documents User Needs to Prepare
- Company Capability Statement (1-2 pages)
- 2-4 Case Studies (short project descriptions with outcomes)
- Base Proposal Template (standard proposal structure)
- Project Search Criteria (phrases for contract marketplaces)

### Key Differences for Projects vs Jobs
- "CV" becomes a proposal/capability statement
- Matching is against project requirements, not job descriptions
- Public sector tenders have deadlines
- Pipeline state might include "Expression of Interest" → "Proposal Submitted" → "Shortlisted" → "Won/Lost"

---

## How to Run
```bash
cd "/Users/mac/LocalRepos/Personal Projects/find-job-opportunities"
python3 -m app.main
# Then open http://127.0.0.1:8000
```

## How to Continue
Start a new session and say:
"Continue with the project marketplace spec for Find Opportunities. See SESSION-SUMMARY.md for context."
