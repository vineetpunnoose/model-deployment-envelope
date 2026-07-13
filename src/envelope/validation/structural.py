"""
Structural Validator (B1)

Validates that a manifest's declarations match reality:
- All declared tools exist in the registry
- All data classes exist in the taxonomy
- Referenced files exist and are valid
- Backend configuration is valid

Returns non-zero exit on validation failure - no override.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from envelope.declaration.manifest import ModelManifest, ManifestLoader
from envelope.declaration.tools import ToolRegistry
from envelope.declaration.taxonomy import DataClassTaxonomy
from envelope.declaration.placement import PlacementPolicy


@dataclass
class StructuralError:
    """
    A structural validation error with location information.

    Provides precise error location for debugging and audit.
    """
    code: str
    message: str
    path: str
    file: str | None = None
    line: int | None = None
    severity: str = "error"

    def __str__(self) -> str:
        location = ""
        if self.file:
            location = f" [{self.file}"
            if self.line:
                location += f":{self.line}"
            location += "]"
        return f"{self.severity.upper()}: {self.code} at {self.path}{location}: {self.message}"


@dataclass
class StructuralValidationResult:
    """Result of structural validation."""
    valid: bool
    errors: list[StructuralError] = field(default_factory=list)
    warnings: list[StructuralError] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def __bool__(self) -> bool:
        return self.valid


class StructuralValidator:
    """
    Validates manifest structure against actual system state.

    Ensures all declarations in a manifest correspond to real,
    registered entities in the system. Validation failures
    REFUSE deployment - there is no override mechanism.
    """

    VALID_BACKENDS = {"ollama", "vllm", "openai", "anthropic"}
    VALID_TOOL_TYPES = {"function", "api", "database", "file", "custom"}
    VALID_ESCALATION_TRIGGERS = {
        "confidence_low",
        "tool_failure",
        "policy_violation",
        "explicit_request",
        "data_class_mismatch",
        "custom",
    }

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        taxonomy: DataClassTaxonomy | None = None,
        placement_policy: PlacementPolicy | None = None,
    ):
        self._tool_registry = tool_registry or ToolRegistry()
        self._taxonomy = taxonomy or DataClassTaxonomy()
        self._placement_policy = placement_policy or PlacementPolicy()

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    @property
    def taxonomy(self) -> DataClassTaxonomy:
        return self._taxonomy

    @property
    def placement_policy(self) -> PlacementPolicy:
        return self._placement_policy

    def validate(
        self, manifest: ModelManifest, base_path: Path | None = None
    ) -> StructuralValidationResult:
        """
        Validate a manifest for structural correctness.

        Args:
            manifest: The manifest to validate
            base_path: Base path for resolving relative file references

        Returns:
            StructuralValidationResult with errors and warnings
        """
        errors: list[StructuralError] = []
        warnings: list[StructuralError] = []

        source_file = str(manifest.source_path) if manifest.source_path else None
        base_path = base_path or (manifest.source_path.parent if manifest.source_path else Path.cwd())

        # Validate model configuration
        self._validate_model(manifest, errors, warnings, source_file)

        # Validate tools
        self._validate_tools(manifest, errors, warnings, source_file, base_path)

        # Validate data classes
        self._validate_data_classes(manifest, errors, warnings, source_file, base_path)

        # Validate placement
        self._validate_placement(manifest, errors, warnings, source_file, base_path)

        # Validate escalation
        self._validate_escalation(manifest, errors, warnings, source_file)

        # Validate golden set
        self._validate_golden_set(manifest, errors, warnings, source_file, base_path)

        return StructuralValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _validate_model(
        self,
        manifest: ModelManifest,
        errors: list[StructuralError],
        warnings: list[StructuralError],
        source_file: str | None,
    ) -> None:
        """Validate model configuration."""
        model = manifest.spec.model

        # Check backend is valid
        if model.backend not in self.VALID_BACKENDS:
            errors.append(StructuralError(
                code="INVALID_BACKEND",
                message=f"Backend '{model.backend}' is not valid. Must be one of: {', '.join(self.VALID_BACKENDS)}",
                path="spec.model.backend",
                file=source_file,
            ))

        # Check model ID format
        if not model.id or len(model.id) < 2:
            errors.append(StructuralError(
                code="INVALID_MODEL_ID",
                message="Model ID must be at least 2 characters",
                path="spec.model.id",
                file=source_file,
            ))

        # Validate endpoint URL if provided
        if model.endpoint:
            if not model.endpoint.startswith(("http://", "https://")):
                errors.append(StructuralError(
                    code="INVALID_ENDPOINT",
                    message=f"Endpoint '{model.endpoint}' must be a valid HTTP/HTTPS URL",
                    path="spec.model.endpoint",
                    file=source_file,
                ))

        # Validate parameters
        params = model.parameters
        if "temperature" in params:
            temp = params["temperature"]
            if not isinstance(temp, (int, float)) or temp < 0 or temp > 2:
                errors.append(StructuralError(
                    code="INVALID_TEMPERATURE",
                    message=f"Temperature must be between 0 and 2, got {temp}",
                    path="spec.model.parameters.temperature",
                    file=source_file,
                ))

        if "maxTokens" in params:
            max_tokens = params["maxTokens"]
            if not isinstance(max_tokens, int) or max_tokens < 1:
                errors.append(StructuralError(
                    code="INVALID_MAX_TOKENS",
                    message=f"maxTokens must be a positive integer, got {max_tokens}",
                    path="spec.model.parameters.maxTokens",
                    file=source_file,
                ))

    def _validate_tools(
        self,
        manifest: ModelManifest,
        errors: list[StructuralError],
        warnings: list[StructuralError],
        source_file: str | None,
        base_path: Path,
    ) -> None:
        """Validate tool declarations against registry."""
        tools_config = manifest.spec.tools

        # Check each allowed tool exists in registry
        for tool_name in tools_config.allowed:
            if not self._tool_registry.is_registered(tool_name):
                errors.append(StructuralError(
                    code="TOOL_NOT_REGISTERED",
                    message=f"Tool '{tool_name}' is not registered in the tool registry",
                    path=f"spec.tools.allowed['{tool_name}']",
                    file=source_file,
                ))

        # Check tool manifest files exist and are valid
        for manifest_path in tools_config.manifests:
            full_path = base_path / manifest_path
            if not full_path.exists():
                errors.append(StructuralError(
                    code="TOOL_MANIFEST_NOT_FOUND",
                    message=f"Tool manifest file not found: {manifest_path}",
                    path=f"spec.tools.manifests['{manifest_path}']",
                    file=source_file,
                ))
            else:
                # Try to validate the tool manifest
                try:
                    self._tool_registry.load_from_manifest(full_path)
                except Exception as e:
                    errors.append(StructuralError(
                        code="TOOL_MANIFEST_INVALID",
                        message=f"Tool manifest validation failed: {e}",
                        path=f"spec.tools.manifests['{manifest_path}']",
                        file=str(full_path),
                    ))

        # Warn if no tools are allowed
        if not tools_config.allowed:
            warnings.append(StructuralError(
                code="NO_TOOLS_ALLOWED",
                message="No tools are allowed - model will have no tool access",
                path="spec.tools.allowed",
                file=source_file,
                severity="warning",
            ))

    def _validate_data_classes(
        self,
        manifest: ModelManifest,
        errors: list[StructuralError],
        warnings: list[StructuralError],
        source_file: str | None,
        base_path: Path,
    ) -> None:
        """Validate data class declarations against taxonomy."""
        dc_config = manifest.spec.data_classes

        # Check taxonomy file exists
        taxonomy_path = base_path / dc_config.taxonomy
        if not taxonomy_path.exists():
            errors.append(StructuralError(
                code="TAXONOMY_NOT_FOUND",
                message=f"Taxonomy file not found: {dc_config.taxonomy}",
                path="spec.dataClasses.taxonomy",
                file=source_file,
            ))
        else:
            # Try to load and validate taxonomy
            try:
                temp_taxonomy = DataClassTaxonomy()
                temp_taxonomy.load_from_file(taxonomy_path)

                # Check each allowed data class exists in taxonomy
                for dc_name in dc_config.allowed:
                    if not temp_taxonomy.has_class(dc_name):
                        errors.append(StructuralError(
                            code="DATA_CLASS_NOT_IN_TAXONOMY",
                            message=f"Data class '{dc_name}' not found in taxonomy",
                            path=f"spec.dataClasses.allowed['{dc_name}']",
                            file=source_file,
                        ))
            except Exception as e:
                errors.append(StructuralError(
                    code="TAXONOMY_INVALID",
                    message=f"Taxonomy validation failed: {e}",
                    path="spec.dataClasses.taxonomy",
                    file=str(taxonomy_path),
                ))

        # Warn if no data classes allowed
        if not dc_config.allowed:
            warnings.append(StructuralError(
                code="NO_DATA_CLASSES_ALLOWED",
                message="No data classes are allowed - may limit functionality",
                path="spec.dataClasses.allowed",
                file=source_file,
                severity="warning",
            ))

    def _validate_placement(
        self,
        manifest: ModelManifest,
        errors: list[StructuralError],
        warnings: list[StructuralError],
        source_file: str | None,
        base_path: Path,
    ) -> None:
        """Validate placement configuration."""
        placement_config = manifest.spec.placement

        # Check policy file exists
        policy_path = base_path / placement_config.policy
        if not policy_path.exists():
            errors.append(StructuralError(
                code="PLACEMENT_POLICY_NOT_FOUND",
                message=f"Placement policy file not found: {placement_config.policy}",
                path="spec.placement.policy",
                file=source_file,
            ))
        else:
            # Try to load and validate policy
            try:
                temp_policy = PlacementPolicy()
                temp_policy.load_from_file(policy_path)

                # Check current placement exists in policy
                if placement_config.current_placement:
                    if not temp_policy.get_placement(placement_config.current_placement):
                        errors.append(StructuralError(
                            code="CURRENT_PLACEMENT_NOT_FOUND",
                            message=f"Current placement '{placement_config.current_placement}' not found in policy",
                            path="spec.placement.currentPlacement",
                            file=source_file,
                        ))
            except Exception as e:
                errors.append(StructuralError(
                    code="PLACEMENT_POLICY_INVALID",
                    message=f"Placement policy validation failed: {e}",
                    path="spec.placement.policy",
                    file=str(policy_path),
                ))

    def _validate_escalation(
        self,
        manifest: ModelManifest,
        errors: list[StructuralError],
        warnings: list[StructuralError],
        source_file: str | None,
    ) -> None:
        """Validate escalation configuration."""
        escalation = manifest.spec.escalation

        # Check escalation conditions
        for i, condition in enumerate(escalation.conditions):
            if condition.trigger not in self.VALID_ESCALATION_TRIGGERS:
                errors.append(StructuralError(
                    code="INVALID_ESCALATION_TRIGGER",
                    message=f"Invalid escalation trigger '{condition.trigger}'. Must be one of: {', '.join(self.VALID_ESCALATION_TRIGGERS)}",
                    path=f"spec.escalation.conditions[{i}].trigger",
                    file=source_file,
                ))

            # Custom triggers require customRule
            if condition.trigger == "custom" and not condition.custom_rule:
                errors.append(StructuralError(
                    code="MISSING_CUSTOM_RULE",
                    message="Custom escalation trigger requires a customRule",
                    path=f"spec.escalation.conditions[{i}].customRule",
                    file=source_file,
                ))

            # confidence_low requires threshold
            if condition.trigger == "confidence_low" and condition.threshold is None:
                errors.append(StructuralError(
                    code="MISSING_THRESHOLD",
                    message="confidence_low trigger requires a threshold value",
                    path=f"spec.escalation.conditions[{i}].threshold",
                    file=source_file,
                ))

        # Check handler configuration
        handler = escalation.handler
        if handler.type == "webhook" and not handler.endpoint:
            errors.append(StructuralError(
                code="MISSING_WEBHOOK_ENDPOINT",
                message="Webhook handler requires an endpoint URL",
                path="spec.escalation.handler.endpoint",
                file=source_file,
            ))

        # Warn if no escalation conditions
        if not escalation.conditions:
            warnings.append(StructuralError(
                code="NO_ESCALATION_CONDITIONS",
                message="No escalation conditions defined",
                path="spec.escalation.conditions",
                file=source_file,
                severity="warning",
            ))

    def _validate_golden_set(
        self,
        manifest: ModelManifest,
        errors: list[StructuralError],
        warnings: list[StructuralError],
        source_file: str | None,
        base_path: Path,
    ) -> None:
        """Validate golden set configuration."""
        golden_set = manifest.spec.golden_set
        if not golden_set:
            return

        if golden_set.path:
            gs_path = base_path / golden_set.path
            if not gs_path.exists():
                errors.append(StructuralError(
                    code="GOLDEN_SET_NOT_FOUND",
                    message=f"Golden set file not found: {golden_set.path}",
                    path="spec.goldenSet.path",
                    file=source_file,
                ))

    def validate_file(self, path: Path | str) -> StructuralValidationResult:
        """
        Load and validate a manifest file.

        Combines loading and structural validation in one step.
        """
        path = Path(path)
        loader = ManifestLoader()

        try:
            manifest = loader.load(path)
        except Exception as e:
            return StructuralValidationResult(
                valid=False,
                errors=[StructuralError(
                    code="MANIFEST_LOAD_FAILED",
                    message=str(e),
                    path="(root)",
                    file=str(path),
                )],
            )

        return self.validate(manifest, base_path=path.parent)
