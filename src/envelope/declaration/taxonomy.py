"""
Data Class Taxonomy (A3)

Defines data classification taxonomy with sensitivity levels and handling rules.
Provides hierarchical data classification with inheritance support.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from envelope.types import DataClassName, Sensitivity, ValidationError


SCHEMA_DIR = Path(__file__).parent.parent.parent.parent / "schemas"


class SensitivityLevel(IntEnum):
    """
    Data sensitivity levels ranked by sensitivity.

    Higher values indicate more sensitive data requiring
    stricter controls and placement restrictions.
    """
    PUBLIC = 0
    INTERNAL = 1
    CONFIDENTIAL = 2
    RESTRICTED = 3
    PROHIBITED = 4

    @classmethod
    def from_string(cls, value: str) -> "SensitivityLevel":
        """Convert string to SensitivityLevel."""
        mapping = {
            "public": cls.PUBLIC,
            "internal": cls.INTERNAL,
            "confidential": cls.CONFIDENTIAL,
            "restricted": cls.RESTRICTED,
            "prohibited": cls.PROHIBITED,
        }
        if value.lower() not in mapping:
            raise ValueError(f"Unknown sensitivity level: {value}")
        return mapping[value.lower()]

    def to_sensitivity(self) -> Sensitivity:
        """Convert to Sensitivity enum."""
        mapping = {
            self.PUBLIC: Sensitivity.PUBLIC,
            self.INTERNAL: Sensitivity.INTERNAL,
            self.CONFIDENTIAL: Sensitivity.CONFIDENTIAL,
            self.RESTRICTED: Sensitivity.RESTRICTED,
            self.PROHIBITED: Sensitivity.PROHIBITED,
        }
        return mapping[self]


@dataclass(frozen=True)
class DataClassPlacements:
    """Placement constraints for a data class."""
    allowed: frozenset[str] = frozenset()
    denied: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DataClass:
    """
    Definition of a data class within the taxonomy.

    Data classes categorize data by sensitivity, regulatory requirements,
    and permitted placements. They support inheritance through parent_class.
    """
    name: DataClassName
    sensitivity: SensitivityLevel
    display_name: str = ""
    description: str = ""
    pii_fields: tuple[str, ...] = ()
    retention_days: int | None = None
    encryption_required: bool = False
    placements: DataClassPlacements = field(default_factory=DataClassPlacements)
    regulatory_frameworks: tuple[str, ...] = ()
    parent_class: DataClassName | None = None

    def is_more_sensitive_than(self, other: "DataClass") -> bool:
        """Check if this data class is more sensitive than another."""
        return self.sensitivity > other.sensitivity

    def requires_placement(self, placement_id: str) -> bool | None:
        """
        Check if data class is allowed at a placement.

        Returns:
            True if explicitly allowed
            False if explicitly denied
            None if neither (defer to policy)
        """
        if placement_id in self.placements.denied:
            return False
        if placement_id in self.placements.allowed:
            return True
        return None


@dataclass(frozen=True)
class SensitivityLevelConfig:
    """Configuration for a sensitivity level."""
    name: str
    rank: int
    description: str = ""
    handling_rules: tuple[str, ...] = ()


class DataClassTaxonomy:
    """
    Data classification taxonomy with sensitivity levels.

    Provides hierarchical classification of data types with inheritance,
    sensitivity levels, and placement constraints.
    """

    def __init__(self, name: str = "", version: str = "", description: str = ""):
        self._name = name
        self._version = version
        self._description = description
        self._classes: dict[DataClassName, DataClass] = {}
        self._levels: dict[str, SensitivityLevelConfig] = {}
        self._schema: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def description(self) -> str:
        return self._description

    @property
    def taxonomy_schema(self) -> dict[str, Any]:
        """Load and cache the taxonomy schema."""
        if self._schema is None:
            schema_path = SCHEMA_DIR / "data-class.schema.json"
            if not schema_path.exists():
                raise FileNotFoundError(f"Schema not found: {schema_path}")
            with open(schema_path) as f:
                import json
                self._schema = json.load(f)
        return self._schema

    def register_class(self, data_class: DataClass) -> None:
        """Register a data class in the taxonomy."""
        self._classes[data_class.name] = data_class

    def unregister_class(self, name: DataClassName) -> bool:
        """Unregister a data class. Returns True if removed."""
        if name in self._classes:
            del self._classes[name]
            return True
        return False

    def get_class(self, name: DataClassName) -> DataClass | None:
        """Get a data class by name."""
        return self._classes.get(name)

    def has_class(self, name: DataClassName) -> bool:
        """Check if a data class exists."""
        return name in self._classes

    def list_classes(self) -> list[DataClassName]:
        """List all registered data class names."""
        return list(self._classes.keys())

    def get_all_classes(self) -> dict[DataClassName, DataClass]:
        """Get all registered data classes."""
        return dict(self._classes)

    def get_effective_sensitivity(self, name: DataClassName) -> SensitivityLevel | None:
        """
        Get effective sensitivity level considering inheritance.

        If a class has a parent, returns the higher sensitivity
        of the class and its parent chain.
        """
        data_class = self._classes.get(name)
        if data_class is None:
            return None

        max_sensitivity = data_class.sensitivity

        # Walk up parent chain
        current = data_class
        while current.parent_class:
            parent = self._classes.get(current.parent_class)
            if parent is None:
                break
            if parent.sensitivity > max_sensitivity:
                max_sensitivity = parent.sensitivity
            current = parent

        return max_sensitivity

    def get_classes_by_sensitivity(
        self, min_level: SensitivityLevel | None = None,
        max_level: SensitivityLevel | None = None
    ) -> list[DataClass]:
        """Get data classes within a sensitivity range."""
        result = []
        for data_class in self._classes.values():
            if min_level is not None and data_class.sensitivity < min_level:
                continue
            if max_level is not None and data_class.sensitivity > max_level:
                continue
            result.append(data_class)
        return result

    def get_classes_for_placement(self, placement_id: str) -> list[DataClass]:
        """Get data classes allowed at a specific placement."""
        return [
            dc for dc in self._classes.values()
            if dc.requires_placement(placement_id) is not False
        ]

    def get_classes_denied_at_placement(self, placement_id: str) -> list[DataClass]:
        """Get data classes explicitly denied at a placement."""
        return [
            dc for dc in self._classes.values()
            if dc.requires_placement(placement_id) is False
        ]

    def check_data_class_allowed(
        self, data_class: DataClassName, allowed: frozenset[DataClassName]
    ) -> bool:
        """Check if a data class is in the allowed set."""
        return data_class in allowed

    def get_regulatory_frameworks(self, name: DataClassName) -> set[str]:
        """
        Get all applicable regulatory frameworks for a data class.

        Includes frameworks from parent classes.
        """
        data_class = self._classes.get(name)
        if data_class is None:
            return set()

        frameworks: set[str] = set(data_class.regulatory_frameworks)

        # Add parent frameworks
        current = data_class
        while current.parent_class:
            parent = self._classes.get(current.parent_class)
            if parent is None:
                break
            frameworks.update(parent.regulatory_frameworks)
            current = parent

        return frameworks

    def load_from_file(self, path: Path | str) -> None:
        """Load taxonomy from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Taxonomy file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        self.load_from_dict(data)

    def load_from_dict(self, data: dict[str, Any]) -> None:
        """Load taxonomy from a dictionary."""
        errors = self.validate(data)
        if errors:
            raise ValidationError(
                f"Taxonomy validation failed: {len(errors)} error(s)",
                errors=errors
            )

        self._parse_taxonomy(data)

    def validate(self, data: dict[str, Any]) -> list[str]:
        """Validate taxonomy data against JSON schema."""
        errors: list[str] = []
        validator = jsonschema.Draft202012Validator(self.taxonomy_schema)

        for error in validator.iter_errors(data):
            path = ".".join(str(p) for p in error.absolute_path) or "(root)"
            errors.append(f"{path}: {error.message}")

        return errors

    def _parse_taxonomy(self, data: dict[str, Any]) -> None:
        """Parse validated data into the taxonomy."""
        metadata = data["metadata"]
        spec = data["spec"]

        self._name = metadata["name"]
        self._version = metadata.get("version", "")
        self._description = metadata.get("description", "")

        # Parse sensitivity levels
        self._levels = {}
        for level_data in spec.get("sensitivityLevels", []):
            level = SensitivityLevelConfig(
                name=level_data["name"],
                rank=level_data["rank"],
                description=level_data.get("description", ""),
                handling_rules=tuple(level_data.get("handlingRules", [])),
            )
            self._levels[level.name] = level

        # Parse data classes
        self._classes = {}
        for class_data in spec.get("classes", []):
            placements_data = class_data.get("placements", {})
            placements = DataClassPlacements(
                allowed=frozenset(placements_data.get("allowed", [])),
                denied=frozenset(placements_data.get("denied", [])),
            )

            data_class = DataClass(
                name=class_data["name"],
                sensitivity=SensitivityLevel.from_string(class_data["sensitivity"]),
                display_name=class_data.get("displayName", ""),
                description=class_data.get("description", ""),
                pii_fields=tuple(class_data.get("piiFields", [])),
                retention_days=class_data.get("retentionDays"),
                encryption_required=class_data.get("encryptionRequired", False),
                placements=placements,
                regulatory_frameworks=tuple(class_data.get("regulatoryFrameworks", [])),
                parent_class=class_data.get("parentClass"),
            )
            self._classes[data_class.name] = data_class

    def to_dict(self) -> dict[str, Any]:
        """Convert taxonomy to dictionary representation."""
        return {
            "apiVersion": "envelope.ai/v1",
            "kind": "DataClassTaxonomy",
            "metadata": {
                "name": self._name,
                "version": self._version,
                "description": self._description,
            },
            "spec": {
                "sensitivityLevels": [
                    {
                        "name": level.name,
                        "rank": level.rank,
                        "description": level.description,
                        "handlingRules": list(level.handling_rules),
                    }
                    for level in self._levels.values()
                ],
                "classes": [
                    {
                        "name": dc.name,
                        "displayName": dc.display_name,
                        "description": dc.description,
                        "sensitivity": dc.sensitivity.name.lower(),
                        "piiFields": list(dc.pii_fields),
                        "retentionDays": dc.retention_days,
                        "encryptionRequired": dc.encryption_required,
                        "placements": {
                            "allowed": list(dc.placements.allowed),
                            "denied": list(dc.placements.denied),
                        },
                        "regulatoryFrameworks": list(dc.regulatory_frameworks),
                        "parentClass": dc.parent_class,
                    }
                    for dc in self._classes.values()
                ],
            },
        }
