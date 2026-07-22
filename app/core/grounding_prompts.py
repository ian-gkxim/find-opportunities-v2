"""Prompt templates for claim grounding verification.

These prompts are used by the Grounding_Verifier for LLM-based claim extraction
and by the Personalization_Engine for generation-time fabrication prevention.

Requirements: 1.1, 1.2, 1.3, 4.1
"""

CLAIM_EXTRACTION_PROMPT = """
You are a factual claim extractor. Analyze the following outreach material and
extract every discrete factual claim about the Beneficiary (the person or company
the material represents).

MATERIAL:
{material_text}

INSTRUCTIONS:
1. Extract claims in these categories ONLY:
   - skill_technology: Any assertion of a skill or technology proficiency
   - achievement_outcome: Any stated achievement or outcome
   - quantified_metric: Any claim with a specific number, percentage, or duration
   - credential_certification: Any certification, degree, or formal credential
   - named_client_employer: Any named company, client, or employer
   - experience_duration: Any claim about years/months of experience

2. For each claim, record:
   - The factual assertion (claim_text)
   - The exact text span in the material where it appears (source_span)
   - The character offset start and end of the span (source_span_start, source_span_end)
   - Whether the claim is about the prospect (is_prospect_side=true) or the
     beneficiary (is_prospect_side=false)

3. Prospect-side claims are those about the target company: their size, industry,
   technology stack, funding, or intent signals. These are NOT beneficiary claims.

4. Do NOT extract:
   - Opinions or subjective statements
   - Future intentions or proposals
   - Generic statements without specific claims

Return a JSON array of claim objects with fields: claim_text, category, source_span, source_span_start, source_span_end, is_prospect_side.
"""

GROUNDING_CONSTRAINT_INJECTION = """
CRITICAL GROUNDING CONSTRAINT:
All claims about the Beneficiary MUST be traceable to the provided profile assets below.
Do NOT invent, embellish, or fabricate skills, achievements, metrics, credentials,
client names, or experience durations.

If the opportunity requires a skill or experience the Beneficiary does not possess,
you MUST:
1. Acknowledge the gap honestly
2. Reframe using adjacent or transferable experience from the profile
3. Never paper over the gap with invented content

BENEFICIARY PROFILE ASSETS:
{profile_assets_text}
"""
