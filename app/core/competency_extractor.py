"""Competency extraction via LLM Router.

Provides source-type-specific prompts that guide the LLM to extract
structured competency candidates from raw page content. Each source type
gets a tailored prompt to maximize extraction quality.

Requirements: 2.1, 2.3
"""

import json
import logging
from dataclasses import dataclass

from app.integrations.llm_router import LLMRouter

logger = logging.getLogger(__name__)


@dataclass
class CompetencyCandidate:
    """A single extracted competency candidate before deduplication.

    Attributes:
        category: One of "technology", "publication", "certification",
            "course", "project", "community_role".
        name: Human-readable competency name (e.g. "Kubernetes").
        evidence_summary: Brief explanation of why this was extracted.
        confidence: "strong" (directly evidenced) or "inferred" (indirectly).
        source_url: The Public_Source URL this was extracted from.
        raw_evidence: Verbatim snippet from the source content.
    """

    category: str
    name: str
    evidence_summary: str
    confidence: str
    source_url: str
    raw_evidence: str


class CompetencyExtractor:
    """Extracts competency candidates from public source content via LLM.

    Uses source-type-specific prompt templates to guide the LLM toward
    structured JSON output. Handles content truncation, response parsing,
    and candidate capping.
    """

    MAX_CONTENT_LENGTH = 15_000  # chars sent to LLM (truncate if larger)
    MAX_CANDIDATES_PER_SOURCE = 20

    # Source-type-specific prompt templates
    PROMPTS: dict[str, str] = {
        "github": (
            "Analyze this GitHub profile/repository content. Extract:\n"
            "- Technologies the user demonstrably uses (languages, frameworks, tools)\n"
            "- Projects they own or significantly contribute to\n"
            "- Any certifications or badges visible\n"
            "For each, indicate confidence: 'strong' if they are the owner/primary "
            "contributor, 'inferred' if they are a minor contributor or the tech "
            "is only used peripherally.\n\n"
            "Return a JSON array of objects with keys: "
            "category, name, evidence_summary, confidence\n"
            "Valid categories: technology, publication, certification, "
            "course, project, community_role\n"
            "Valid confidence values: strong, inferred"
        ),
        "google_scholar": (
            "Analyze this Google Scholar profile. Extract:\n"
            "- Publications (title, venue, year)\n"
            "- Research areas/expertise evidenced by publication topics\n"
            "- H-index or citation metrics if visible\n"
            "Confidence is 'strong' for authored publications, 'inferred' for "
            "research areas derived from publication topics.\n\n"
            "Return a JSON array of objects with keys: "
            "category, name, evidence_summary, confidence\n"
            "Valid categories: technology, publication, certification, "
            "course, project, community_role\n"
            "Valid confidence values: strong, inferred"
        ),
        "certification_badge": (
            "Analyze this certification/badge page. Extract:\n"
            "- Certifications with issuing body and date if visible\n"
            "- Technologies or skills the certifications validate\n"
            "All certifications with visible badge or verification link are 'strong'.\n\n"
            "Return a JSON array of objects with keys: "
            "category, name, evidence_summary, confidence\n"
            "Valid categories: technology, publication, certification, "
            "course, project, community_role\n"
            "Valid confidence values: strong, inferred"
        ),
        "portfolio": (
            "Analyze this portfolio/personal website. Extract:\n"
            "- Projects showcased with technologies used\n"
            "- Skills or competencies explicitly listed\n"
            "- Publications, talks, or community contributions mentioned\n"
            "Items explicitly listed by the author are 'strong'. "
            "Items inferred from project descriptions are 'inferred'.\n\n"
            "Return a JSON array of objects with keys: "
            "category, name, evidence_summary, confidence\n"
            "Valid categories: technology, publication, certification, "
            "course, project, community_role\n"
            "Valid confidence values: strong, inferred"
        ),
        "default": (
            "Analyze this professional web page. Extract skills, projects, "
            "publications, certifications, and competencies. For each, indicate "
            "confidence: 'strong' if directly stated/evidenced, 'inferred' if "
            "indirectly implied.\n\n"
            "Return a JSON array of objects with keys: "
            "category, name, evidence_summary, confidence\n"
            "Valid categories: technology, publication, certification, "
            "course, project, community_role\n"
            "Valid confidence values: strong, inferred"
        ),
    }

    def __init__(self, llm_router: LLMRouter):
        self._llm = llm_router

    async def extract(
        self, content: str, source_type: str, source_url: str
    ) -> list[CompetencyCandidate]:
        """Extract competency candidates from source content.

        Truncates content to MAX_CONTENT_LENGTH, selects the appropriate
        prompt template by source_type, calls the LLM Router, and parses
        the structured JSON response into CompetencyCandidate objects.

        Args:
            content: Raw text content fetched from the public source.
            source_type: One of the SourceType enum values (github,
                google_scholar, certification_badge, portfolio, etc.).
            source_url: The URL the content was fetched from.

        Returns:
            List of CompetencyCandidate objects, capped at
            MAX_CANDIDATES_PER_SOURCE.
        """
        # Truncate content to respect LLM context limits
        truncated = content[: self.MAX_CONTENT_LENGTH]

        # Select prompt template (fall back to default for unknown types)
        prompt_template = self.PROMPTS.get(source_type, self.PROMPTS["default"])

        full_prompt = (
            f"{prompt_template}\n\n"
            f"--- SOURCE CONTENT ({source_type}) ---\n"
            f"{truncated}"
        )

        response = await self._llm.generate_content(
            prompt=full_prompt,
            context={"source_type": source_type, "source_url": source_url},
            material_type="competency_extraction",
        )

        candidates = self._parse_candidates(response, source_url)
        return candidates[: self.MAX_CANDIDATES_PER_SOURCE]

    def _parse_candidates(
        self, response: str, source_url: str
    ) -> list[CompetencyCandidate]:
        """Parse LLM JSON response into CompetencyCandidate objects.

        Handles common LLM response quirks:
        - Markdown code fences (```json ... ```)
        - Single object instead of array
        - Malformed JSON (returns empty list)
        - Missing fields (uses sensible defaults)

        Args:
            response: Raw string response from the LLM.
            source_url: The source URL to attach to each candidate.

        Returns:
            List of parsed CompetencyCandidate objects. Returns empty
            list if JSON is malformed or unparseable.
        """
        try:
            cleaned = response.strip()

            # Strip markdown code fences if present
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                # Remove first line (```json or ```) and last line (```)
                if len(lines) >= 3:
                    cleaned = "\n".join(lines[1:-1])
                else:
                    cleaned = "\n".join(lines[1:])

            items = json.loads(cleaned)

            # Handle single object response (wrap in list)
            if not isinstance(items, list):
                items = [items]

        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to parse LLM competency extraction response: %s",
                exc,
            )
            return []

        candidates = []
        for item in items:
            if not isinstance(item, dict):
                continue

            # Require at minimum a name to produce a useful candidate
            name = item.get("name", "")
            if not name:
                continue

            # Normalize confidence to valid values
            confidence = item.get("confidence", "inferred")
            if confidence not in ("strong", "inferred"):
                confidence = "inferred"

            candidates.append(
                CompetencyCandidate(
                    category=item.get("category", "unknown"),
                    name=name,
                    evidence_summary=item.get("evidence_summary", ""),
                    confidence=confidence,
                    source_url=source_url,
                    raw_evidence=item.get("evidence_summary", ""),
                )
            )

        return candidates
