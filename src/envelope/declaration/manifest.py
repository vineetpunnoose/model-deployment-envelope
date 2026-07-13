"""
Model Manifest Loader and Validator (A1)

Loads and validates model deployment manifests against JSON schema.
Provides immutable manifest objects that define deployment boundaries.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from envelope.types import ValidationError, ModelId


SCHEMA_DIR = Path(__file__).parent.parent.parent.parent / "schemas"


@dataclass(frozen=True)
class ModelConfig:
    """Model runtime configuration."""
    id: ModelId
    backend: str
    endpoint: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolsConfig:
    """Tools configuration specifying allowed tools."""
    allowed: frozenset[str]
    manifests: tuple[str, ...] = ()


@dataclass(frozen=True)
class DataClassesConfig:
    """Data classes configuration."""
    allowed: frozenset[str]
    taxonomy: str


@dataclass(frozen=True)
class PlacementConfig:
    """Placement configuration."""
    policy: str
    current_placement: str | None = None


@dataclass(frozen=True)
class EscalationCondition:
    """Single escalation condition."""
    id: str
    trigger: str
    threshold: float | None = None
    custom_rule: str | None = None


@dataclass(frozen=True)
class EscalationHandler:
    """Escalation handler configuration."""
    type: str
    endpoint: str | None = None
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EscalationConfig:
    """Escalation configuration."""
    conditions: tuple[EscalationCondition, ...]
    handler: EscalationHandler


@dataclass(frozen=True)
class CallersConfig:
    """Allowed callers configuration."""
    allowed_roles: frozenset[str] = frozenset()
    allowed_caller_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class GoldenSetConfig:
    """Golden set testing configuration."""
    path: str | None = None
    run_on_load: bool = True
    run_on_schedule: str | None = None


@dataclass(frozen=True)
class ManifestMetadata:
    """Manifest metadata."""
    name: str
    version: str
    description: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ManifestSpec:
    """Manifest specification containing all deployment rules."""
    model: ModelConfig
    tools: ToolsConfig
    data_classes: DataClassesConfig
    placement: PlacementConfig
    escalation: EscalationConfig
    callers: CallersConfig = field(default_factory=CallersConfig)
    golden_set: GoldenSetConfig | None = None


@dataclass(frozen=True)
class ModelManifest:
    """
    Immutable model deployment manifest.

    Represents the complete declarative specification of what a model
    deployment is permitted to do, including tools, data classes,
    placement constraints, and escalation rules.
    """
    api_version: str
    kind: str
    metadata: ManifestMetadata
    spec: ManifestSpec
    source_path: Path | None = None

    def allows_tool(self, tool_name: str) -> bool:
        """Check if a tool is explicitly allowed."""
        return tool_name in self.spec.tools.allowed

    def allows_data_class(self, data_class: str) -> bool:
        """Check if a data class is allowed."""
        return data_class in self.spec.data_classes.allowed

    def allows_caller_role(self, role: str) -> bool:
        """Check if a caller role is allowed (empty means all allowed)."""
        if not self.spec.callers.allowed_roles:
            return True
        return role in self.spec.callers.allowed_roles

    def allows_caller_id(self, caller_id: str) -> bool:
        """Check if a specific caller ID is allowed (empty means all allowed)."""
        if not self.spec.callers.allowed_caller_ids:
            return True
        return caller_id in self.spec.callers.allowed_caller_ids

    @property
    def model_id(self) -> ModelId:
        return self.spec.model.id

    @property
    def backend(self) -> str:
        return self.spec.model.backend

    def to_dict(self) -> dict[str, Any]:
        """Convert manifest to dictionary representation."""
        return {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {
                "name": self.metadata.name,
                "version": self.metadata.version,
                "description": self.metadata.description,
                "labels": dict(self.metadata.labels),
                "annotations": dict(self.metadata.annotations),
            },
            "spec": {
                "model": {
                    "id": self.spec.model.id,
                    "backend": self.spec.model.backend,
                    "endpoint": self.spec.model.endpoint,
                    "parameters": dict(self.spec.model.parameters),
                },
                "tools": {
                    "allowed": list(self.spec.tools.allowed),
                    "manifests": list(self.spec.tools.manifests),
                },
                "dataClasses": {
                    "allowed": list(self.spec.data_classes.allowed),
                    "taxonomy": self.spec.data_classes.taxonomy,
                },
                "placement": {
                    "policy": self.spec.placement.policy,
                    "currentPlacement": self.spec.placement.current_placement,
                },
                "escalation": {
                    "conditions": [
                        {
                            "id": c.id,
                            "trigger": c.trigger,
                            "threshold": c.threshold,
                            "customRule": c.custom_rule,
                        }
                        for c in self.spec.escalation.conditions
                    ],
                    "handler": {
                        "type": self.spec.escalation.handler.type,
                        "endpoint": self.spec.escalation.handler.endpoint,
                        "config": dict(self.spec.escalation.handler.config),
                    },
                },
                "callers": {
                    "allowedRoles": list(self.spec.callers.allowed_roles),
                    "allowedCallerIds": list(self.spec.callers.allowed_caller_ids),
                },
            },
        }


class ManifestLoader:
    """
    Loads and validates model manifests from YAML files.

    Uses JSON Schema validation to ensure manifests conform to
    the expected structure before creating immutable manifest objects.
    """

    def __init__(self, schema_dir: Path | None = None):
        self._schema_dir = schema_dir or SCHEMA_DIR
        self._schema: dict[str, Any] | None = None

    @property
    def schema(self) -> dict[str, Any]:
        """Load and cache the manifest schema."""
        if self._schema is None:
            schema_path = self._schema_dir / "model-manifest.schema.json"
            if not schema_path.exists():
                raise FileNotFoundError(f"Schema not found: {schema_path}")
            with open(schema_path) as f:
                import json
                self._schema = json.load(f)
        return self._schema

    def load(self, path: Path | str) -> ModelManifest:
        """
        Load and validate a manifest from a YAML file.

        Args:
            path: Path to the YAML manifest file

        Returns:
            Validated ModelManifest instance

        Raises:
            ValidationError: If manifest fails schema validation
            FileNotFoundError: If manifest file doesn't exist
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Manifest not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        return self.load_from_dict(data, source_path=path)

    def load_from_dict(
        self, data: dict[str, Any], source_path: Path | None = None
    ) -> ModelManifest:
        """
        Load and validate a manifest from a dictionary.

        Args:
            data: Manifest data dictionary
            source_path: Optional source path for error reporting

        Returns:
            Validated ModelManifest instance

        Raises:
            ValidationError: If manifest fails schema validation
        """
        errors = self.validate(data)
        if errors:
            raise ValidationError(
                f"Manifest validation failed: {len(errors)} error(s)",
                errors=errors
            )

        return self._parse_manifest(data, source_path)

    def validate(self, data: dict[str, Any]) -> list[str]:
        """
        Validate manifest data against JSON schema.

        Returns list of error messages (empty if valid).
        """
        errors: list[str] = []
        validator = jsonschema.Draft202012Validator(self.schema)

        for error in validator.iter_errors(data):
            path = ".".join(str(p) for p in error.absolute_path) or "(root)"
            errors.append(f"{path}: {error.message}")

        return errors

    def _parse_manifest(
        self, data: dict[str, Any], source_path: Path | None
    ) -> ModelManifest:
        """Parse validated data into a ModelManifest."""
        metadata = data["metadata"]
        spec = data["spec"]

        # Parse model config
        model_data = spec["model"]
        model = ModelConfig(
            id=model_data["id"],
            backend=model_data["backend"],
            endpoint=model_data.get("endpoint"),
            parameters=model_data.get("parameters", {}),
        )

        # Parse tools config
        tools_data = spec["tools"]
        tools = ToolsConfig(
            allowed=frozenset(tools_data["allowed"]),
            manifests=tuple(tools_data.get("manifests", [])),
        )

        # Parse data classes config
        dc_data = spec["dataClasses"]
        data_classes = DataClassesConfig(
            allowed=frozenset(dc_data["allowed"]),
            taxonomy=dc_data["taxonomy"],
        )

        # Parse placement config
        placement_data = spec["placement"]
        placement = PlacementConfig(
            policy=placement_data["policy"],
            current_placement=placement_data.get("currentPlacement"),
        )

        # Parse escalation config
        esc_data = spec["escalation"]
        conditions = tuple(
            EscalationCondition(
                id=c["id"],
                trigger=c["trigger"],
                threshold=c.get("threshold"),
                custom_rule=c.get("customRule"),
            )
            for c in esc_data["conditions"]
        )
        handler = EscalationHandler(
            type=esc_data["handler"]["type"],
            endpoint=esc_data["handler"].get("endpoint"),
            config=esc_data["handler"].get("config", {}),
        )
        escalation = EscalationConfig(conditions=conditions, handler=handler)

        # Parse callers config
        callers_data = spec.get("callers", {})
        callers = CallersConfig(
            allowed_roles=frozenset(callers_data.get("allowedRoles", [])),
            allowed_caller_ids=frozenset(callers_data.get("allowedCallerIds", [])),
        )

        # Parse golden set config
        golden_set = None
        if "goldenSet" in spec:
            gs_data = spec["goldenSet"]
            golden_set = GoldenSetConfig(
                path=gs_data.get("path"),
                run_on_load=gs_data.get("runOnLoad", True),
                run_on_schedule=gs_data.get("runOnSchedule"),
            )

        # Build metadata
        manifest_metadata = ManifestMetadata(
            name=metadata["name"],
            version=metadata["version"],
            description=metadata.get("description", ""),
            labels=metadata.get("labels", {}),
            annotations=metadata.get("annotations", {}),
        )

        # Build spec
        manifest_spec = ManifestSpec(
            model=model,
            tools=tools,
            data_classes=data_classes,
            placement=placement,
            escalation=escalation,
            callers=callers,
            golden_set=golden_set,
        )

        return ModelManifest(
            api_version=data["apiVersion"],
            kind=data["kind"],
            metadata=manifest_metadata,
            spec=manifest_spec,
            source_path=source_path,
        )
