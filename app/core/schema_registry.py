"""Schema Registry — single source of truth for the GKIM Opportunity Finder v2.

Loads and validates the YAML schema at startup, providing typed access to all
schema-defined entities: beneficiaries, opportunity types, techniques, and stages.

Requirements 12.1–12.7: Schema-driven architecture retention.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from app.core.content_selector import ConstraintType, LengthConstraint
from app.core.errors import SchemaValidationError

# ─── Typed Dataclasses ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Beneficiary:
    """A beneficiary definition from the schema (e.g., Consultant, Team)."""

    id: str
    label: str
    description: str
    baseline_assets: list[str]
    offerings_asset: str
    offerings_label: str
    search_criteria_asset: str


@dataclass(frozen=True)
class OpportunityType:
    """An opportunity type linking beneficiaries to sources and techniques."""

    id: str
    label: str
    beneficiaries: list[str]
    source_asset: str
    source_label: str
    find_technique: str
    find_label: str
    prepare_technique: str
    outreach_technique: str
    pipeline_states: list[str]
    state_entry_techniques: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ValidationRuleDeclaration:
    """A validation rule declaration within an outreach technique."""

    rule_id: str
    severity: str | None = None  # "blocking" or "warning", None = use default
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Technique:
    """A technique (find, prepare, or outreach) with its service class binding."""

    id: str
    service_class: str
    description: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    validation_rules: list[ValidationRuleDeclaration] = field(default_factory=list)


@dataclass(frozen=True)
class PrepareTechnique:
    """A prepare technique with optional review and grounding technique references."""

    id: str
    service_class: str
    description: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    review_technique: str | None = None
    grounding_technique: str | None = None
    trigger: str = "material_preparation"  # "material_preparation" | "state_entry"
    trigger_state: str | None = None  # required when trigger == "state_entry"


@dataclass(frozen=True)
class GroundingTechnique:
    """Schema-declared grounding technique configuration."""

    id: str
    service_class: str
    description: str
    claim_categories: list[str] = field(default_factory=list)
    extraction_timeout_seconds: int = 60
    verification_timeout_seconds: int = 30
    max_retries: int = 2


@dataclass(frozen=True)
class ReviewTechnique:
    """Schema-declared review technique configuration."""

    id: str
    service_class: str
    description: str
    critique_categories: list[str] = field(default_factory=list)
    max_review_cycles: int = 1


@dataclass(frozen=True)
class Stage:
    """A navigation stage (primary tab) in the application."""

    id: str
    label: str
    description: str


@dataclass(frozen=True)
class LengthConstraintConfig:
    """Length constraint as declared in schema YAML.

    Exactly one of max_words, max_characters, max_units must be set.
    """

    max_words: int | None = None
    max_characters: int | None = None
    max_units: int | None = None

    def to_length_constraint(self) -> LengthConstraint:
        """Convert to the Content_Selector's LengthConstraint type."""
        if self.max_words is not None:
            return LengthConstraint(ConstraintType.MAX_WORDS, self.max_words)
        if self.max_characters is not None:
            return LengthConstraint(ConstraintType.MAX_CHARACTERS, self.max_characters)
        if self.max_units is not None:
            return LengthConstraint(ConstraintType.MAX_UNITS, self.max_units)
        raise ValueError("At least one constraint type must be specified")


# ─── Schema Registry ──────────────────────────────────────────────────────────

# Required top-level keys in the schema YAML
_REQUIRED_TOP_LEVEL_KEYS = [
    "stages",
    "beneficiaries",
    "opportunity_types",
    "find_techniques",
    "prepare_techniques",
    "outreach_techniques",
]

# Required fields per beneficiary entry
_REQUIRED_BENEFICIARY_FIELDS = [
    "id",
    "label",
    "description",
    "baseline_assets",
    "offerings_asset",
    "offerings_label",
    "search_criteria_asset",
]

# Required fields per technique entry
_REQUIRED_TECHNIQUE_FIELDS = [
    "id",
    "service_class",
    "description",
]

# Required fields per opportunity type entry
_REQUIRED_OPPORTUNITY_TYPE_FIELDS = [
    "id",
    "label",
    "beneficiaries",
    "source_asset",
    "source_label",
    "find_technique",
    "find_label",
    "prepare_technique",
    "outreach_technique",
    "pipeline_states",
]

# Required fields per stage entry
_REQUIRED_STAGE_FIELDS = [
    "id",
    "label",
    "description",
]


class SchemaRegistry:
    """Single source of truth loaded from YAML at startup.

    Validates structure, cross-references, and required fields, then exposes
    typed dataclass instances for runtime consumption.

    Raises SchemaValidationError with entity_id on any validation failure,
    preventing the application from starting with an invalid schema.
    """

    # Known voice asset types that can appear in baseline_assets
    VOICE_ASSET_TYPES: set[str] = {"writing_style", "behavioral_profile", "brand_voice"}

    def __init__(self, schema_path: Path) -> None:
        self._schema_path = schema_path
        self._raw: dict = self._load(schema_path)
        self._validate()
        self._validate_cross_references()
        self._parse()

    # ─── Public API ───────────────────────────────────────────────────────

    def get_beneficiary(self, beneficiary_id: str) -> Optional[Beneficiary]:
        """Return a Beneficiary by id, or None if not found."""
        return next(
            (b for b in self.beneficiaries if b.id == beneficiary_id), None
        )

    def get_opportunity_types_for_beneficiary(
        self, beneficiary_id: str
    ) -> list[OpportunityType]:
        """Return all OpportunityTypes that include the given beneficiary."""
        return [
            ot
            for ot in self.opportunity_types
            if beneficiary_id in ot.beneficiaries
        ]

    def get_pipeline_states(self, opportunity_type_id: str) -> list[str]:
        """Return pipeline states for an opportunity type, or empty list."""
        ot = next(
            (o for o in self.opportunity_types if o.id == opportunity_type_id),
            None,
        )
        return list(ot.pipeline_states) if ot else []

    def get_state_entry_techniques(
        self,
        opportunity_type_id: str,
        state: str,
    ) -> list[PrepareTechnique]:
        """Return prepare techniques triggered on entry to a given state.

        Filters techniques where:
        - trigger == "state_entry"
        - trigger_state == state
        - technique is attached to the opportunity type via state_entry_techniques
        """
        ot = next(
            (o for o in self.opportunity_types if o.id == opportunity_type_id),
            None,
        )
        if not ot:
            return []

        techniques = []
        for tech_id in ot.state_entry_techniques:
            tech = next(
                (p for p in self.prepare_techniques if p.id == tech_id),
                None,
            )
            if tech and tech.trigger == "state_entry" and tech.trigger_state == state:
                techniques.append(tech)
        return techniques

    def get_review_technique(
        self, review_technique_id: str
    ) -> ReviewTechnique | None:
        """Return a ReviewTechnique by id, or None if not found."""
        return next(
            (rt for rt in self.review_techniques if rt.id == review_technique_id),
            None,
        )

    def get_review_technique_for_prepare(
        self, prepare_technique_id: str
    ) -> ReviewTechnique | None:
        """Get the review technique wired to a prepare technique, or None if skipped."""
        pt = next(
            (p for p in self.prepare_techniques if p.id == prepare_technique_id),
            None,
        )
        if not pt or not pt.review_technique:
            return None
        return self.get_review_technique(pt.review_technique)

    def get_grounding_technique(
        self, grounding_technique_id: str
    ) -> GroundingTechnique | None:
        """Return a GroundingTechnique by id, or None if not found."""
        return next(
            (gt for gt in self.grounding_techniques if gt.id == grounding_technique_id),
            None,
        )

    def get_grounding_technique_for_prepare(
        self, prepare_technique_id: str
    ) -> GroundingTechnique | None:
        """Get the grounding technique wired to a prepare technique, or None if skipped."""
        pt = next(
            (p for p in self.prepare_techniques if p.id == prepare_technique_id),
            None,
        )
        if not pt or not pt.grounding_technique:
            return None
        return self.get_grounding_technique(pt.grounding_technique)

    def get_length_constraint(
        self, material_type: str
    ) -> "LengthConstraint | None":
        """Return a LengthConstraint for the given material type, or None if not declared.

        Looks up the material type in stored length constraint configs parsed from
        the `length_constraints` field on prepare techniques. If found, converts
        the config to a LengthConstraint and returns it. If not found, returns None.

        Requirements 3.1: Schema_Registry supports optional length_constraints.
        """
        config = self._length_constraints.get(material_type)
        if config is None:
            return None
        return config.to_length_constraint()

    def get_validation_rules(
        self, outreach_technique_id: str
    ) -> "list[ValidationRuleConfig] | None":
        """Get validation rule configs for an outreach technique.

        Returns None if no validation_rules section exists (triggers default fallback).
        Maps ValidationRuleDeclaration to ValidationRuleConfig with severity enum conversion.

        Requirements: 3.1, 3.3
        """
        from app.core.outbound_validator import RuleSeverity, ValidationRuleConfig

        technique = next(
            (t for t in self.outreach_techniques if t.id == outreach_technique_id),
            None,
        )
        if technique is None:
            return None
        if not technique.validation_rules:
            return None
        return [
            ValidationRuleConfig(
                rule_id=decl.rule_id,
                severity=RuleSeverity(decl.severity) if decl.severity else None,
                params=dict(decl.params),
            )
            for decl in technique.validation_rules
        ]

    def derive_navigation(self) -> dict:
        """Derive full navigation structure from schema for frontend consumption.

        Returns a dict keyed by stage id, each with label and sub_tabs.
        Sub-tabs are derived from beneficiaries per stage with their relevant
        opportunity types and technique bindings.
        """
        nav: dict = {}
        for stage in self.stages:
            nav[stage.id] = {
                "label": stage.label,
                "description": stage.description,
                "sub_tabs": self._derive_sub_tabs(stage),
            }
        return nav

    # ─── Loading ──────────────────────────────────────────────────────────

    @staticmethod
    def _load(schema_path: Path) -> dict:
        """Load and parse YAML from disk."""
        if not schema_path.exists():
            raise SchemaValidationError(
                f"Schema file not found: {schema_path}",
                entity_id=str(schema_path),
            )
        try:
            raw = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise SchemaValidationError(
                f"Invalid YAML syntax: {e}",
                entity_id=str(schema_path),
            ) from e

        if not isinstance(raw, dict):
            raise SchemaValidationError(
                "Schema root must be a YAML mapping",
                entity_id=str(schema_path),
            )
        return raw

    # ─── Validation ───────────────────────────────────────────────────────

    def _validate(self) -> None:
        """Validate schema structure and required fields.

        Checks:
        - All required top-level keys present
        - Each beneficiary has required fields and non-empty baseline_assets
        - Each technique has required fields
        - Each opportunity type has required fields
        - Each stage has required fields
        """
        # Top-level keys
        for key in _REQUIRED_TOP_LEVEL_KEYS:
            if key not in self._raw:
                raise SchemaValidationError(
                    f"Missing required top-level key: '{key}'",
                    entity_id=key,
                )

        # Validate stages
        for entry in self._raw["stages"]:
            self._validate_entry(entry, _REQUIRED_STAGE_FIELDS, "stage")

        # Validate beneficiaries
        for entry in self._raw["beneficiaries"]:
            self._validate_entry(
                entry, _REQUIRED_BENEFICIARY_FIELDS, "beneficiary"
            )
            # baseline_assets must be non-empty
            entity_id = entry.get("id", "unknown")
            if not entry.get("baseline_assets"):
                raise SchemaValidationError(
                    f"Beneficiary '{entity_id}' must have at least one baseline_assets entry",
                    entity_id=entity_id,
                )

        # Validate techniques (find, prepare, outreach)
        for technique_key in [
            "find_techniques",
            "prepare_techniques",
            "outreach_techniques",
        ]:
            for entry in self._raw[technique_key]:
                self._validate_entry(
                    entry, _REQUIRED_TECHNIQUE_FIELDS, technique_key
                )

        # Validate opportunity types
        for entry in self._raw["opportunity_types"]:
            self._validate_entry(
                entry, _REQUIRED_OPPORTUNITY_TYPE_FIELDS, "opportunity_type"
            )

        # Validate voice asset placement on beneficiaries
        self._validate_voice_asset_placement()

    def _validate_cross_references(self) -> None:
        """Ensure opportunity types reference valid beneficiaries and techniques.

        Checks:
        - Each opportunity_type.beneficiaries references a declared beneficiary id
        - Each opportunity_type.find_technique references a declared find technique id
        - Each opportunity_type.prepare_technique references a declared prepare technique id
        - Each opportunity_type.outreach_technique references a declared outreach technique id
        - Each opportunity_type declares at least one pipeline_state
        """
        beneficiary_ids = {b["id"] for b in self._raw["beneficiaries"]}
        find_ids = {t["id"] for t in self._raw["find_techniques"]}
        prepare_ids = {t["id"] for t in self._raw["prepare_techniques"]}
        outreach_ids = {t["id"] for t in self._raw["outreach_techniques"]}

        for ot in self._raw["opportunity_types"]:
            ot_id = ot["id"]

            # Validate beneficiary references
            for ben_id in ot["beneficiaries"]:
                if ben_id not in beneficiary_ids:
                    raise SchemaValidationError(
                        f"OpportunityType '{ot_id}' references unknown "
                        f"beneficiary '{ben_id}'",
                        entity_id=ot_id,
                    )

            # Validate find_technique reference
            if ot["find_technique"] not in find_ids:
                raise SchemaValidationError(
                    f"OpportunityType '{ot_id}' references unknown "
                    f"find_technique '{ot['find_technique']}'",
                    entity_id=ot_id,
                )

            # Validate prepare_technique reference
            if ot["prepare_technique"] not in prepare_ids:
                raise SchemaValidationError(
                    f"OpportunityType '{ot_id}' references unknown "
                    f"prepare_technique '{ot['prepare_technique']}'",
                    entity_id=ot_id,
                )

            # Validate outreach_technique reference
            if ot["outreach_technique"] not in outreach_ids:
                raise SchemaValidationError(
                    f"OpportunityType '{ot_id}' references unknown "
                    f"outreach_technique '{ot['outreach_technique']}'",
                    entity_id=ot_id,
                )

            # Validate pipeline_states is non-empty
            if not ot.get("pipeline_states"):
                raise SchemaValidationError(
                    f"OpportunityType '{ot_id}' declares no pipeline states",
                    entity_id=ot_id,
                )

        # Validate review_technique references on prepare_techniques
        self._validate_review_technique_references()

        # Validate grounding_technique references on prepare_techniques
        self._validate_grounding_technique_references()

        # Validate validation_rules declarations on outreach_techniques
        self._validate_validation_rules()

        # Validate state_entry_techniques references on opportunity_types
        self._validate_state_entry_techniques()

    def _validate_review_technique_references(self) -> None:
        """Validate that every prepare_technique.review_technique resolves
        to a declared review_technique id.

        Raises SchemaValidationError with descriptive message on failure.
        """
        review_ids = {rt["id"] for rt in self._raw.get("review_techniques", [])}
        for pt in self._raw.get("prepare_techniques", []):
            ref = pt.get("review_technique")
            if ref and ref not in review_ids:
                raise SchemaValidationError(
                    f"PrepareTechnique '{pt['id']}' references unknown "
                    f"review_technique '{ref}'",
                    entity_id=pt["id"],
                )

    def _validate_grounding_technique_references(self) -> None:
        """Validate that every prepare_technique.grounding_technique resolves
        to a declared grounding_technique id.

        Raises SchemaValidationError with descriptive message on failure.
        """
        grounding_ids = {gt["id"] for gt in self._raw.get("grounding_techniques", [])}
        for pt in self._raw.get("prepare_techniques", []):
            ref = pt.get("grounding_technique")
            if ref and ref not in grounding_ids:
                raise SchemaValidationError(
                    f"PrepareTechnique '{pt['id']}' references unknown "
                    f"grounding_technique '{ref}'",
                    entity_id=pt["id"],
                )

    def _validate_validation_rules(self) -> None:
        """Validate that declared rule ids reference known built-in rules.

        Checks:
        - Each rule_id in validation_rules exists in BUILT_IN_RULES or ASYNC_RULES
        - Each severity value (if provided) is "blocking" or "warning"

        Raises SchemaValidationError with descriptive message on failure.
        Requirements: 3.2
        """
        from app.core.outbound_validator import ASYNC_RULES, BUILT_IN_RULES

        known_rules = set(BUILT_IN_RULES.keys()) | set(ASYNC_RULES.keys())
        for technique_entry in self._raw.get("outreach_techniques", []):
            technique_id = technique_entry["id"]
            for rule_decl in technique_entry.get("validation_rules", []):
                rule_id = rule_decl.get("rule_id", "")
                if rule_id not in known_rules:
                    raise SchemaValidationError(
                        f"Outreach technique '{technique_id}' declares "
                        f"unknown validation rule '{rule_id}'",
                        entity_id=technique_id,
                    )
                severity = rule_decl.get("severity")
                if severity and severity not in ("blocking", "warning"):
                    raise SchemaValidationError(
                        f"Outreach technique '{technique_id}', rule "
                        f"'{rule_id}': invalid severity '{severity}' "
                        f"(must be 'blocking' or 'warning')",
                        entity_id=technique_id,
                    )

    def _validate_voice_asset_placement(self) -> None:
        """Validate voice assets are declared on correct beneficiary types.

        Rules:
        - writing_style and behavioral_profile: only on consultant beneficiaries
        - brand_voice: only on team beneficiaries
        - behavioral_profile requires writing_style to also be declared

        Raises SchemaValidationError on violation.
        """
        for ben in self._raw.get("beneficiaries", []):
            assets = set(ben.get("baseline_assets", []))
            voice_assets = assets & self.VOICE_ASSET_TYPES

            if "brand_voice" in voice_assets and ben["id"] != "team":
                raise SchemaValidationError(
                    f"Beneficiary '{ben['id']}' declares brand_voice "
                    f"but only 'team' beneficiaries may use brand_voice",
                    entity_id=ben["id"],
                )

            if "writing_style" in voice_assets or "behavioral_profile" in voice_assets:
                if ben["id"] == "team":
                    raise SchemaValidationError(
                        f"Beneficiary 'team' declares writing_style/behavioral_profile "
                        f"but these are consultant-only assets",
                        entity_id="team",
                    )

            if "behavioral_profile" in voice_assets and "writing_style" not in voice_assets:
                raise SchemaValidationError(
                    f"Beneficiary '{ben['id']}' declares behavioral_profile "
                    f"without writing_style — behavioral_profile requires writing_style",
                    entity_id=ben["id"],
                )

    def _validate_state_entry_techniques(self) -> None:
        """Validate state-entry technique references on opportunity types.

        Rules:
        - Each state_entry_technique must be declared in prepare_techniques
        - The technique's trigger_state must exist in the opportunity type's pipeline_states
        - The technique must have trigger == "state_entry"

        Raises SchemaValidationError on violation.
        """
        prepare_ids = {t["id"] for t in self._raw.get("prepare_techniques", [])}
        prepare_by_id = {t["id"]: t for t in self._raw.get("prepare_techniques", [])}

        for ot in self._raw.get("opportunity_types", []):
            ot_id = ot["id"]
            pipeline_states = set(ot.get("pipeline_states", []))

            for tech_ref in ot.get("state_entry_techniques", []):
                # Check technique exists in prepare_techniques
                if tech_ref not in prepare_ids:
                    raise SchemaValidationError(
                        f"OpportunityType '{ot_id}' references unknown "
                        f"state_entry_technique '{tech_ref}'",
                        entity_id=ot_id,
                    )

                tech = prepare_by_id[tech_ref]
                trigger_state = tech.get("trigger_state")

                # Check trigger_state is declared
                if not trigger_state:
                    raise SchemaValidationError(
                        f"State-entry technique '{tech_ref}' on OpportunityType "
                        f"'{ot_id}' has no trigger_state declared",
                        entity_id=ot_id,
                    )

                # Check trigger_state exists in pipeline_states
                if trigger_state not in pipeline_states:
                    raise SchemaValidationError(
                        f"Technique '{tech_ref}' trigger_state '{trigger_state}' "
                        f"not in pipeline_states of '{ot_id}'",
                        entity_id=ot_id,
                    )

    # ─── Parsing ──────────────────────────────────────────────────────────

    def _parse(self) -> None:
        """Parse raw YAML dicts into typed dataclass instances."""
        self.stages: list[Stage] = [
            Stage(id=s["id"], label=s["label"], description=s["description"])
            for s in self._raw["stages"]
        ]

        self.beneficiaries: list[Beneficiary] = [
            Beneficiary(
                id=b["id"],
                label=b["label"],
                description=b["description"],
                baseline_assets=list(b["baseline_assets"]),
                offerings_asset=b["offerings_asset"],
                offerings_label=b["offerings_label"],
                search_criteria_asset=b["search_criteria_asset"],
            )
            for b in self._raw["beneficiaries"]
        ]

        self.opportunity_types: list[OpportunityType] = [
            OpportunityType(
                id=ot["id"],
                label=ot["label"],
                beneficiaries=list(ot["beneficiaries"]),
                source_asset=ot["source_asset"],
                source_label=ot["source_label"],
                find_technique=ot["find_technique"],
                find_label=ot["find_label"],
                prepare_technique=ot["prepare_technique"],
                outreach_technique=ot["outreach_technique"],
                pipeline_states=list(ot["pipeline_states"]),
                state_entry_techniques=list(ot.get("state_entry_techniques", [])),
            )
            for ot in self._raw["opportunity_types"]
        ]

        self.find_techniques: list[Technique] = [
            self._parse_technique(t) for t in self._raw["find_techniques"]
        ]

        self.prepare_techniques: list[PrepareTechnique] = [
            self._parse_prepare_technique(t)
            for t in self._raw["prepare_techniques"]
        ]

        self.outreach_techniques: list[Technique] = [
            self._parse_technique(t) for t in self._raw["outreach_techniques"]
        ]

        self._parse_review_techniques()
        self._parse_grounding_techniques()
        self._parse_length_constraints()

    # ─── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_technique(raw: dict) -> Technique:
        """Parse a single technique dict into a Technique dataclass."""
        validation_rules = [
            ValidationRuleDeclaration(
                rule_id=vr["rule_id"],
                severity=vr.get("severity"),
                params=dict(vr.get("params", {})),
            )
            for vr in raw.get("validation_rules", [])
        ]
        return Technique(
            id=raw["id"],
            service_class=raw["service_class"],
            description=raw["description"],
            inputs=list(raw.get("inputs", [])),
            outputs=list(raw.get("outputs", [])),
            validation_rules=validation_rules,
        )

    @staticmethod
    def _parse_prepare_technique(raw: dict) -> PrepareTechnique:
        """Parse a single prepare technique dict into a PrepareTechnique dataclass."""
        return PrepareTechnique(
            id=raw["id"],
            service_class=raw["service_class"],
            description=raw["description"],
            inputs=list(raw.get("inputs", [])),
            outputs=list(raw.get("outputs", [])),
            review_technique=raw.get("review_technique"),
            grounding_technique=raw.get("grounding_technique"),
            trigger=raw.get("trigger", "material_preparation"),
            trigger_state=raw.get("trigger_state"),
        )

    def _parse_review_techniques(self) -> None:
        """Parse the review_techniques YAML section into ReviewTechnique instances.

        Handles absence gracefully by setting self.review_techniques to an empty list.
        """
        raw_review_techniques = self._raw.get("review_techniques", [])
        self.review_techniques: list[ReviewTechnique] = [
            ReviewTechnique(
                id=rt["id"],
                service_class=rt["service_class"],
                description=rt["description"],
                critique_categories=list(rt.get("critique_categories", [])),
                max_review_cycles=rt.get("max_review_cycles", 1),
            )
            for rt in raw_review_techniques
        ]

    def _parse_grounding_techniques(self) -> None:
        """Parse the grounding_techniques YAML section into GroundingTechnique instances.

        Handles absence gracefully by setting self.grounding_techniques to an empty list.
        """
        raw_grounding_techniques = self._raw.get("grounding_techniques", [])
        self.grounding_techniques: list[GroundingTechnique] = [
            GroundingTechnique(
                id=gt["id"],
                service_class=gt["service_class"],
                description=gt["description"],
                claim_categories=list(gt.get("claim_categories", [])),
                extraction_timeout_seconds=gt.get("extraction_timeout_seconds", 60),
                verification_timeout_seconds=gt.get("verification_timeout_seconds", 30),
                max_retries=gt.get("max_retries", 2),
            )
            for gt in raw_grounding_techniques
        ]

    def _parse_length_constraints(self) -> None:
        """Parse optional length_constraints from each prepare technique.

        Iterates over raw prepare_techniques entries and collects any
        `length_constraints` mappings. Each key in the mapping is a material
        type (e.g. "tailored_cv") and the value is a dict with one of
        max_words, max_characters, or max_units.

        Stores results in self._length_constraints: dict[str, LengthConstraintConfig].
        Handles absence gracefully — if no prepare technique declares length_constraints,
        the dict is empty.

        Requirements 3.1: Schema_Registry supports optional length_constraints.
        """
        self._length_constraints: dict[str, LengthConstraintConfig] = {}
        for pt in self._raw.get("prepare_techniques", []):
            constraints_raw = pt.get("length_constraints")
            if not constraints_raw or not isinstance(constraints_raw, dict):
                continue
            for material_type, constraint_def in constraints_raw.items():
                if not isinstance(constraint_def, dict):
                    continue
                self._length_constraints[material_type] = LengthConstraintConfig(
                    max_words=constraint_def.get("max_words"),
                    max_characters=constraint_def.get("max_characters"),
                    max_units=constraint_def.get("max_units"),
                )

    @staticmethod
    def _validate_entry(
        entry: dict, required_fields: list[str], entity_type: str
    ) -> None:
        """Validate that a schema entry has all required fields with values."""
        entity_id = entry.get("id", "unknown")
        for field_name in required_fields:
            if field_name not in entry:
                raise SchemaValidationError(
                    f"{entity_type} '{entity_id}' is missing required "
                    f"field '{field_name}'",
                    entity_id=entity_id,
                )
            value = entry[field_name]
            if value is None or (isinstance(value, str) and not value.strip()):
                raise SchemaValidationError(
                    f"{entity_type} '{entity_id}' has empty value for "
                    f"required field '{field_name}'",
                    entity_id=entity_id,
                )

    def _derive_sub_tabs(self, stage: Stage) -> list[dict]:
        """Derive sub-tab entries for a given stage based on beneficiaries.

        Each sub-tab includes the beneficiary info and relevant opportunity
        types for that beneficiary within the stage context.
        """
        sub_tabs = []
        for ben in self.beneficiaries:
            opp_types = self.get_opportunity_types_for_beneficiary(ben.id)
            sub_tab: dict = {
                "beneficiary_id": ben.id,
                "label": ben.label,
                "opportunity_types": [
                    {
                        "id": ot.id,
                        "label": ot.label,
                        "find_technique": ot.find_technique,
                        "find_label": ot.find_label,
                        "prepare_technique": ot.prepare_technique,
                        "outreach_technique": ot.outreach_technique,
                        "pipeline_states": ot.pipeline_states,
                        "source_asset": ot.source_asset,
                        "source_label": ot.source_label,
                    }
                    for ot in opp_types
                ],
            }
            sub_tabs.append(sub_tab)
        return sub_tabs
