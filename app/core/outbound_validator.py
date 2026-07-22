"""Core interfaces and data models for the Outbound Validation Gate.

Defines enums, dataclasses, and abstract base class used by the
Outbound_Validator to execute deterministic, rule-based checks on
outbound materials before submission to Send_Channels.

Requirements: 1.1, 2.4
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import uuid

import httpx

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.core.pipeline_manager import PipelineManager
    from app.core.schema_registry import SchemaRegistry


# ─── ENUMS ────────────────────────────────────────────────────────────────────


class RuleSeverity(str, Enum):
    """Severity level for a validation rule."""

    BLOCKING = "blocking"
    WARNING = "warning"


# ─── DATACLASSES ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TextSpan:
    """Identifies an offending span within the material text."""

    start: int  # character offset from start of field
    end: int  # character offset (exclusive)
    field_name: str  # which field (e.g., "body", "subject")
    text: str  # the offending text content


@dataclass
class RuleResult:
    """Result of a single validation rule execution."""

    rule_id: str
    passed: bool
    severity: RuleSeverity
    message: str = ""
    offending_spans: list[TextSpan] = field(default_factory=list)
    execution_ms: float = 0.0


@dataclass
class ValidationContext:
    """Context passed to each rule for validation."""

    pipeline_record_id: str
    contact_first_name: str
    contact_last_name: str
    outreach_technique: str
    material_type: str  # "email", "linkedin_message", "proposal"
    required_fields: list[str] = field(default_factory=list)


@dataclass
class Material:
    """The outbound material to validate."""

    subject: str | None = None  # None for non-email channels
    body: str = ""
    signature: str | None = None
    personalization_fields: dict[str, str] = field(default_factory=dict)


@dataclass
class ValidationRuleConfig:
    """Schema-declared configuration for a single rule."""

    rule_id: str
    severity: RuleSeverity | None = None  # None = use rule default
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationReport:
    """Complete validation report for a send attempt."""

    id: str
    pipeline_record_id: str
    outreach_technique: str
    results: list[RuleResult]
    passed: bool  # True if no blocking failures
    has_warnings: bool
    total_execution_ms: float
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def blocking_failures(self) -> list[RuleResult]:
        """Return all blocking-severity rule failures."""
        return [
            r
            for r in self.results
            if not r.passed and r.severity == RuleSeverity.BLOCKING
        ]

    @property
    def warnings(self) -> list[RuleResult]:
        """Return all warning-severity rule failures."""
        return [
            r
            for r in self.results
            if not r.passed and r.severity == RuleSeverity.WARNING
        ]


@dataclass
class ValidationGateResult:
    """Result returned to the caller after validation gate."""

    blocked: bool
    report: ValidationReport
    send_result: Any | None = None  # Result from Send_Channel if not blocked


# ─── ABSTRACT BASE CLASS ─────────────────────────────────────────────────────


class ValidationRule(ABC):
    """Abstract base class for all validation rules.

    Subclasses must define rule_id, default_severity, and a synchronous
    check() method. Rules must be deterministic with no LLM or network
    calls (except LinkLivenessRule which is explicitly async and separate).
    """

    @property
    @abstractmethod
    def rule_id(self) -> str:
        """Unique identifier for this rule."""
        ...

    @property
    @abstractmethod
    def default_severity(self) -> RuleSeverity:
        """Default severity if not overridden in schema."""
        ...

    @abstractmethod
    def check(
        self,
        material: Material,
        context: ValidationContext,
        params: dict[str, Any],
    ) -> RuleResult:
        """Execute the rule against the material.

        Must be synchronous and deterministic. No LLM or network calls
        (except LinkLivenessRule which is explicitly async).
        """
        ...


# ─── BLOCKING RULE IMPLEMENTATIONS ───────────────────────────────────────────

import re


class UnreplacedTokenRule(ValidationRule):
    """Detects unreplaced template tokens in material body and subject.

    Patterns: {{...}}, {single_word}, [PLACEHOLDER], <INSERT...>
    """

    rule_id = "unreplaced_tokens"
    default_severity = RuleSeverity.BLOCKING

    PATTERNS = [
        re.compile(r"\{\{[^}]+\}\}"),  # {{first_name}}
        re.compile(r"\{[a-z_]+\}"),  # {company_name}
        re.compile(r"\[PLACEHOLDER\]", re.I),  # [PLACEHOLDER]
        re.compile(r"<INSERT[^>]*>", re.I),  # <INSERT_NAME>
    ]

    def check(self, material: Material, context: ValidationContext, params: dict[str, Any]) -> RuleResult:
        spans: list[TextSpan] = []
        for field_name, text in [("subject", material.subject or ""), ("body", material.body)]:
            for pattern in self.PATTERNS:
                for match in pattern.finditer(text):
                    spans.append(
                        TextSpan(
                            start=match.start(),
                            end=match.end(),
                            field_name=field_name,
                            text=match.group(),
                        )
                    )
        return RuleResult(
            rule_id=self.rule_id,
            passed=len(spans) == 0,
            severity=params.get("severity", self.default_severity),
            message=f"Found {len(spans)} unreplaced token(s)" if spans else "",
            offending_spans=spans,
        )


class EmptySubjectRule(ValidationRule):
    """Fails if subject line is empty/missing for email materials."""

    rule_id = "empty_subject"
    default_severity = RuleSeverity.BLOCKING

    def check(self, material: Material, context: ValidationContext, params: dict[str, Any]) -> RuleResult:
        if context.material_type != "email":
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                severity=self.default_severity,
            )
        has_subject = bool(material.subject and material.subject.strip())
        return RuleResult(
            rule_id=self.rule_id,
            passed=has_subject,
            severity=params.get("severity", self.default_severity),
            message="" if has_subject else "Email has empty or missing subject",
        )


class MissingSignatureRule(ValidationRule):
    """Fails if signature block is missing when technique requires one."""

    rule_id = "missing_signature"
    default_severity = RuleSeverity.BLOCKING

    def check(self, material: Material, context: ValidationContext, params: dict[str, Any]) -> RuleResult:
        requires_sig = params.get("required", True)
        if not requires_sig:
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                severity=self.default_severity,
            )
        has_sig = bool(material.signature and material.signature.strip())
        return RuleResult(
            rule_id=self.rule_id,
            passed=has_sig,
            severity=params.get("severity", self.default_severity),
            message="" if has_sig else "Missing required signature block",
        )


class RecipientNameMismatchRule(ValidationRule):
    """Fails if recipient name in body doesn't match pipeline contact."""

    rule_id = "recipient_name_mismatch"
    default_severity = RuleSeverity.BLOCKING

    # Common greeting patterns that contain a name
    GREETING_PATTERNS = [
        re.compile(r"(?:Hi|Hello|Dear|Hey)\s+([A-Z][a-z]+)", re.MULTILINE),
    ]

    def check(self, material: Material, context: ValidationContext, params: dict[str, Any]) -> RuleResult:
        expected_first = context.contact_first_name.strip().lower()
        expected_last = context.contact_last_name.strip().lower()
        if not expected_first:
            # No contact name to validate against
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                severity=self.default_severity,
            )

        spans: list[TextSpan] = []
        for pattern in self.GREETING_PATTERNS:
            for match in pattern.finditer(material.body):
                found_name = match.group(1).lower()
                if found_name != expected_first and found_name != expected_last:
                    spans.append(
                        TextSpan(
                            start=match.start(1),
                            end=match.end(1),
                            field_name="body",
                            text=match.group(1),
                        )
                    )
        return RuleResult(
            rule_id=self.rule_id,
            passed=len(spans) == 0,
            severity=params.get("severity", self.default_severity),
            message=f"Name mismatch: expected '{context.contact_first_name}'" if spans else "",
            offending_spans=spans,
        )


class EmptyPersonalizationFieldRule(ValidationRule):
    """Fails if a required personalization field is empty."""

    rule_id = "empty_personalization_field"
    default_severity = RuleSeverity.BLOCKING

    def check(self, material: Material, context: ValidationContext, params: dict[str, Any]) -> RuleResult:
        required = params.get("required_fields", context.required_fields)
        missing = [f for f in required if not material.personalization_fields.get(f, "").strip()]
        return RuleResult(
            rule_id=self.rule_id,
            passed=len(missing) == 0,
            severity=params.get("severity", self.default_severity),
            message=f"Empty required fields: {missing}" if missing else "",
        )


# ─── WARNING RULE IMPLEMENTATIONS ─────────────────────────────────────────────


class LengthBoundsRule(ValidationRule):
    """Warns if material body length is outside configured bounds."""

    rule_id = "length_bounds"
    default_severity = RuleSeverity.WARNING

    def check(self, material: Material, context: ValidationContext, params: dict[str, Any]) -> RuleResult:
        min_len = params.get("min_length", 50)
        max_len = params.get("max_length", 5000)
        body_len = len(material.body)
        passed = min_len <= body_len <= max_len
        msg = ""
        if body_len < min_len:
            msg = f"Body too short ({body_len} < {min_len} chars)"
        elif body_len > max_len:
            msg = f"Body too long ({body_len} > {max_len} chars)"
        return RuleResult(
            rule_id=self.rule_id,
            passed=passed,
            severity=params.get("severity", self.default_severity),
            message=msg,
        )


class MalformedUrlRule(ValidationRule):
    """Warns if material contains syntactically malformed URLs."""

    rule_id = "malformed_url"
    default_severity = RuleSeverity.WARNING

    URL_PATTERN = re.compile(
        r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.IGNORECASE
    )

    def check(self, material: Material, context: ValidationContext, params: dict[str, Any]) -> RuleResult:
        spans: list[TextSpan] = []
        for field_name, text in [("subject", material.subject or ""),
                                  ("body", material.body)]:
            for match in self.URL_PATTERN.finditer(text):
                url = match.group()
                parsed = urlparse(url if "://" in url else f"http://{url}")
                if not parsed.netloc or "." not in parsed.netloc:
                    spans.append(TextSpan(
                        start=match.start(),
                        end=match.end(),
                        field_name=field_name,
                        text=url,
                    ))
        return RuleResult(
            rule_id=self.rule_id,
            passed=len(spans) == 0,
            severity=params.get("severity", self.default_severity),
            message=f"Found {len(spans)} malformed URL(s)" if spans else "",
            offending_spans=spans,
        )


class DuplicateContentRule(ValidationRule):
    """Warns on consecutive duplicate words or repeated sentences."""

    rule_id = "duplicate_content"
    default_severity = RuleSeverity.WARNING

    DUPLICATE_WORD = re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)

    def check(self, material: Material, context: ValidationContext, params: dict[str, Any]) -> RuleResult:
        spans: list[TextSpan] = []
        # Check consecutive duplicate words
        for match in self.DUPLICATE_WORD.finditer(material.body):
            spans.append(TextSpan(
                start=match.start(),
                end=match.end(),
                field_name="body",
                text=match.group(),
            ))
        # Check repeated sentences
        sentences = [s.strip() for s in material.body.split(".")
                     if s.strip()]
        seen: dict[str, int] = {}
        for sentence in sentences:
            normalized = sentence.lower()
            if normalized in seen:
                offset = material.body.find(sentence, seen[normalized] + 1)
                if offset >= 0:
                    spans.append(TextSpan(
                        start=offset,
                        end=offset + len(sentence),
                        field_name="body",
                        text=sentence,
                    ))
            else:
                seen[normalized] = material.body.find(sentence)
        return RuleResult(
            rule_id=self.rule_id,
            passed=len(spans) == 0,
            severity=params.get("severity", self.default_severity),
            message=f"Found {len(spans)} duplicate content issue(s)" if spans else "",
            offending_spans=spans,
        )


# ─── ASYNC RULE IMPLEMENTATIONS ──────────────────────────────────────────────


class LinkLivenessRule:
    """Async rule that verifies URLs respond with HTTP < 400.

    Not a subclass of ValidationRule because it requires async I/O.
    Has its own 5-second per-link timeout. Timeouts are warning-severity.
    """

    rule_id = "link_liveness"
    default_severity = RuleSeverity.WARNING
    PER_LINK_TIMEOUT = 5.0  # seconds

    URL_PATTERN = re.compile(
        r"https?://[^\s<>\"']+", re.IGNORECASE
    )

    async def check(
        self,
        material: Material,
        context: ValidationContext,
        params: dict[str, Any],
    ) -> RuleResult:
        if not params.get("enabled", False):
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                severity=self.default_severity,
            )

        urls = self.URL_PATTERN.findall(material.body)
        if material.subject:
            urls.extend(self.URL_PATTERN.findall(material.subject))

        if not urls:
            return RuleResult(
                rule_id=self.rule_id,
                passed=True,
                severity=self.default_severity,
            )

        spans: list[TextSpan] = []
        async with httpx.AsyncClient(
            timeout=self.PER_LINK_TIMEOUT, follow_redirects=True
        ) as client:
            tasks = [self._check_url(client, url) for url in set(urls)]
            results = await asyncio.gather(*tasks)

        for url, status_ok, error_msg in results:
            if not status_ok:
                # Find offset of URL in body
                offset = material.body.find(url)
                field_name = "body"
                if offset < 0 and material.subject:
                    offset = material.subject.find(url)
                    field_name = "subject"
                spans.append(TextSpan(
                    start=max(offset, 0),
                    end=max(offset, 0) + len(url),
                    field_name=field_name,
                    text=f"{url} ({error_msg})",
                ))

        return RuleResult(
            rule_id=self.rule_id,
            passed=len(spans) == 0,
            severity=RuleSeverity.WARNING,
            message=f"{len(spans)} URL(s) failed liveness check" if spans else "",
            offending_spans=spans,
        )

    async def _check_url(
        self, client: httpx.AsyncClient, url: str
    ) -> tuple[str, bool, str]:
        try:
            resp = await client.head(url)
            if resp.status_code >= 400:
                return (url, False, f"HTTP {resp.status_code}")
            return (url, True, "")
        except httpx.TimeoutException:
            return (url, False, "timeout")
        except httpx.HTTPError as e:
            return (url, False, str(e)[:100])


# ─── MODULE-LEVEL REGISTRIES ─────────────────────────────────────────────────

# Rule registry — all built-in rules instantiated at module level
BUILT_IN_RULES: dict[str, ValidationRule] = {
    "unreplaced_tokens": UnreplacedTokenRule(),
    "empty_subject": EmptySubjectRule(),
    "missing_signature": MissingSignatureRule(),
    "recipient_name_mismatch": RecipientNameMismatchRule(),
    "empty_personalization_field": EmptyPersonalizationFieldRule(),
    "length_bounds": LengthBoundsRule(),
    "malformed_url": MalformedUrlRule(),
    "duplicate_content": DuplicateContentRule(),
}

# Async rules (e.g., LinkLivenessRule) that require I/O
ASYNC_RULES: dict[str, Any] = {
    "link_liveness": LinkLivenessRule(),
}

# Default blocking rules applied when no schema config exists
DEFAULT_BLOCKING_RULE_IDS: list[str] = [
    "unreplaced_tokens",
    "empty_subject",
    "missing_signature",
    "recipient_name_mismatch",
    "empty_personalization_field",
]


# ─── OUTBOUND VALIDATOR SERVICE ──────────────────────────────────────────────


class OutboundValidator:
    """Pre-send validation gate service.

    Intercepts materials before Send_Channel submission, executes configured
    rules, and blocks on any blocking-severity failure.

    Performance target: all sync rules < 5 seconds total.
    """

    MAX_SYNC_DURATION = 5.0  # seconds, excluding link liveness

    def __init__(
        self,
        schema_registry: "SchemaRegistry",
        pipeline_manager: "PipelineManager",
        db_repo: "ValidationRepository",
    ):
        self._schema = schema_registry
        self._pipeline = pipeline_manager
        self._db = db_repo

    def get_rules_for_technique(
        self, outreach_technique: str
    ) -> list[ValidationRuleConfig]:
        """Load rule configs from schema, or return defaults.

        If the schema has a validation_rules declaration for the given
        outreach technique, those configs are returned directly.
        Otherwise, the default blocking rules are applied with default params.
        """
        technique_config = self._schema.get_validation_rules(outreach_technique)
        if technique_config is None:
            return [
                ValidationRuleConfig(rule_id=rid)
                for rid in DEFAULT_BLOCKING_RULE_IDS
            ]
        return technique_config

    async def validate(
        self,
        material: Material,
        context: ValidationContext,
    ) -> ValidationReport:
        """Execute all configured rules and produce a report.

        Loads rule configs for the given outreach technique, executes
        sync rules from BUILT_IN_RULES, then async rules from ASYNC_RULES,
        tracks per-rule execution time, and persists the report.

        Requirements: 1.1, 1.4
        """
        configs = self.get_rules_for_technique(context.outreach_technique)
        results: list[RuleResult] = []
        start = time.monotonic()

        # Execute synchronous rules
        for config in configs:
            if config.rule_id in BUILT_IN_RULES:
                rule = BUILT_IN_RULES[config.rule_id]
                severity = config.severity or rule.default_severity
                params = {**config.params, "severity": severity}
                rule_start = time.monotonic()
                result = rule.check(material, context, params)
                result.execution_ms = (time.monotonic() - rule_start) * 1000
                results.append(result)

        # Execute async rules (link liveness)
        for config in configs:
            if config.rule_id in ASYNC_RULES:
                rule = ASYNC_RULES[config.rule_id]
                severity = config.severity or rule.default_severity
                params = {**config.params, "severity": severity}
                rule_start = time.monotonic()
                result = await rule.check(material, context, params)
                result.execution_ms = (time.monotonic() - rule_start) * 1000
                results.append(result)

        total_ms = (time.monotonic() - start) * 1000
        has_blocking = any(
            not r.passed and r.severity == RuleSeverity.BLOCKING
            for r in results
        )
        has_warnings = any(
            not r.passed and r.severity == RuleSeverity.WARNING
            for r in results
        )

        report = ValidationReport(
            id=self._generate_id(),
            pipeline_record_id=context.pipeline_record_id,
            outreach_technique=context.outreach_technique,
            results=results,
            passed=not has_blocking,
            has_warnings=has_warnings,
            total_execution_ms=total_ms,
        )

        # Persist report
        await self._db.save_validation_report(report)
        logger.info(
            "Validation report %s for pipeline record %s: passed=%s, "
            "warnings=%s, total_ms=%.1f",
            report.id,
            report.pipeline_record_id,
            report.passed,
            report.has_warnings,
            report.total_execution_ms,
        )
        return report

    async def validate_and_send(
        self,
        material: Material,
        context: ValidationContext,
        send_fn,  # async callable: the actual send operation
    ) -> ValidationGateResult:
        """Full gate: validate, then send or block.

        Calls validate() first. If any blocking rules fail, transitions
        the pipeline record to validation_failed and returns blocked.
        Otherwise, calls send_fn() and returns the send result.

        Args:
            material: The outbound material to validate.
            context: Validation context with contact and technique info.
            send_fn: Async callable that performs the actual send.

        Returns:
            ValidationGateResult with blocking status and report.

        Requirements: 1.2, 1.3
        """
        report = await self.validate(material, context)

        if not report.passed:
            # Transition pipeline to validation_failed
            await self._pipeline.transition_to_validation_failed(
                record_id=context.pipeline_record_id,
                blocking_failures=report.blocking_failures,
            )
            logger.warning(
                "Validation gate BLOCKED send for pipeline record %s: "
                "%d blocking failure(s)",
                context.pipeline_record_id,
                len(report.blocking_failures),
            )
            return ValidationGateResult(blocked=True, report=report)

        # All blocking rules passed — proceed with send
        send_result = await send_fn()
        logger.info(
            "Validation gate PASSED for pipeline record %s, send completed",
            context.pipeline_record_id,
        )
        return ValidationGateResult(
            blocked=False, report=report, send_result=send_result
        )

    @staticmethod
    def _generate_id() -> str:
        """Generate a UUID string for report IDs."""
        return str(uuid.uuid4())
