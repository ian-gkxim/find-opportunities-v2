"""Schema Registry — single source of truth for the GKIM Opportunity Finder v2.

Loads and validates the YAML schema at startup, providing typed access to all
schema-defined entities: beneficiaries, opportunity types, techniques, and stages.

Requirements 12.1–12.7: Schema-driven architecture retention.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

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


@dataclass(frozen=True)
class Technique:
    """A technique (find, prepare, or outreach) with its service class binding."""

    id: str
    service_class: str
    description: str
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Stage:
    """A navigation stage (primary tab) in the application."""

    id: str
    label: str
    description: str


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
            )
            for ot in self._raw["opportunity_types"]
        ]

        self.find_techniques: list[Technique] = [
            self._parse_technique(t) for t in self._raw["find_techniques"]
        ]

        self.prepare_techniques: list[Technique] = [
            self._parse_technique(t) for t in self._raw["prepare_techniques"]
        ]

        self.outreach_techniques: list[Technique] = [
            self._parse_technique(t) for t in self._raw["outreach_techniques"]
        ]

    # ─── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_technique(raw: dict) -> Technique:
        """Parse a single technique dict into a Technique dataclass."""
        return Technique(
            id=raw["id"],
            service_class=raw["service_class"],
            description=raw["description"],
            inputs=list(raw.get("inputs", [])),
            outputs=list(raw.get("outputs", [])),
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
