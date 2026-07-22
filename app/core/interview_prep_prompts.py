"""Prompt templates for Interview Prep Pack generation.

Contains the structured prompt template used by InterviewPrepService to generate
Interview_Prep_Packs via the LLM_Router. The prompt enforces grounding constraints,
structural requirements, and JSON output format.

Requirements: 2.1, 2.2
"""

INTERVIEW_PREP_GENERATION_PROMPT = """
You are an expert interview coach. Generate a structured interview preparation pack
for a consultant preparing for an interview.

OPPORTUNITY:
{opportunity_description}

CONSULTANT PROFILE ASSETS:
{profile_assets_text}

{submitted_materials_section}

COMPANY CONTEXT (from Enrichment_Record):
- Industry: {industry}
- Employee count: {employee_count}
- Technology stack: {tech_stack}
- Intent signals: {intent_signals}
- Headquarters: {headquarters}

INSTRUCTIONS:
1. Generate 8-15 likely interview questions based on the opportunity's stated
   requirements and responsibilities. Questions should range from technical to
   behavioral to situational.

2. For the 5 most probable competency-based questions, construct a STAR talking point:
   - Situation: drawn EXCLUSIVELY from the consultant's profile assets
   - Task: what was required in that situation
   - Action: what the consultant did (from profile evidence)
   - Result: measurable outcome (from profile evidence)
   - If the opportunity demands a competency NOT evidenced in the profile,
     include an honest gap-handling note suggesting how to frame adjacent
     experience. Do NOT fabricate.

3. Write a company briefing (max 400 words) synthesized from the enrichment data.
   Focus on what would be useful for interview conversation — recent initiatives,
   technology choices, growth signals.

4. Generate 3-6 informed questions for the consultant to ask, grounded in the
   enrichment record (intent signals, tech stack, company trajectory).

GROUNDING CONSTRAINT:
All STAR talking points MUST be traceable to the profile assets provided above.
Never invent achievements, metrics, certifications, or client names.
If a competency gap exists, acknowledge it honestly with adjacent experience framing.

Return a JSON object with this structure:
{{
  "likely_questions": ["..."],
  "star_talking_points": [
    {{
      "competency": "...",
      "question": "...",
      "situation": "...",
      "task": "...",
      "action": "...",
      "result": "...",
      "source_asset_refs": ["..."],
      "is_gap_handled": false,
      "gap_note": null
    }}
  ],
  "company_briefing": "...",
  "questions_to_ask": ["..."]
}}
"""


INTERVIEW_PREP_REGENERATION_PROMPT = """
You are an expert interview coach. Regenerate the STAR talking points below that
have been flagged as containing ungrounded claims.

ORIGINAL PACK CONTEXT:
{original_context}

FLAGGED TALKING POINTS:
{flagged_points}

EXCLUSION CONSTRAINT:
The following claims were identified as ungrounded and MUST NOT appear in the
regenerated talking points:
{excluded_claims}

CONSULTANT PROFILE ASSETS:
{profile_assets_text}

INSTRUCTIONS:
Regenerate ONLY the flagged talking points using EXCLUSIVELY the consultant's
profile assets. Maintain the same competency and question mapping. Ensure all
narrative elements are traceable to the profile assets.

If a competency cannot be evidenced from the profile, use honest gap-handling
(adjacent experience, transferable skill, or learning trajectory framing).

Return a JSON array of the regenerated talking points in the same structure.
"""
