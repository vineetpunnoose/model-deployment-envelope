"""
Composition Validator (B2)

Validates composition rules to prevent confused-deputy vulnerabilities:
- Tools don't expose data beyond caller permissions
- Data class combinations don't create privilege escalation
- Tool chains don't bypass security boundaries

Returns non-zero exit on validation failure - no override.
"""

from dataclasses import dataclass, field
from typing import Any

from envelope.declaration.manifest import ModelManifest
from envelope.declaration.tools import ToolRegistry, ToolDefinition
from envelope.declaration.taxonomy import DataClassTaxonomy, SensitivityLevel


@dataclass
class CompositionError:
    """
    A composition validation error indicating a security issue.

    Composition errors typically indicate confused-deputy vulnerabilities
    or privilege escalation risks.
    """
    code: str
    message: str
    component1: str
    component2: str | None = None
    severity: str = "error"
    recommendation: str = ""

    def __str__(self) -> str:
        components = self.component1
        if self.component2:
            components = f"{self.component1} <-> {self.component2}"
        return f"{self.severity.upper()}: {self.code} [{components}]: {self.message}"


@dataclass
class CompositionValidationResult:
    """Result of composition validation."""
    valid: bool
    errors: list[CompositionError] = field(default_factory=list)
    warnings: list[CompositionError] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def __bool__(self) -> bool:
        return self.valid


class CompositionValidator:
    """
    Validates composition rules to prevent confused-deputy attacks.

    Ensures that the combination of tools, data classes, and permissions
    does not create security vulnerabilities. A confused-deputy attack
    occurs when a trusted component (the model) is tricked into misusing
    its authority on behalf of an attacker.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        taxonomy: DataClassTaxonomy | None = None,
    ):
        self._tool_registry = tool_registry or ToolRegistry()
        self._taxonomy = taxonomy or DataClassTaxonomy()

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._tool_registry

    @property
    def taxonomy(self) -> DataClassTaxonomy:
        return self._taxonomy

    def validate(self, manifest: ModelManifest) -> CompositionValidationResult:
        """
        Validate a manifest for composition safety.

        Checks for confused-deputy vulnerabilities and privilege escalation.
        """
        errors: list[CompositionError] = []
        warnings: list[CompositionError] = []

        # Check tool data class exposure
        self._check_tool_data_exposure(manifest, errors, warnings)

        # Check cross-tool data flow
        self._check_cross_tool_flow(manifest, errors, warnings)

        # Check sensitivity escalation
        self._check_sensitivity_escalation(manifest, errors, warnings)

        # Check caller scope
        self._check_caller_scope(manifest, errors, warnings)

        # Check tool permission requirements
        self._check_tool_permissions(manifest, errors, warnings)

        return CompositionValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _check_tool_data_exposure(
        self,
        manifest: ModelManifest,
        errors: list[CompositionError],
        warnings: list[CompositionError],
    ) -> None:
        """
        Check if tools expose data classes not allowed by the manifest.

        A tool should not output data classes that the model isn't
        permitted to handle.
        """
        allowed_data_classes = manifest.spec.data_classes.allowed
        allowed_tools = manifest.spec.tools.allowed

        for tool_name in allowed_tools:
            tool = self._tool_registry.get(tool_name)
            if tool is None:
                continue

            # Check output data classes
            for output_dc in tool.data_classes.output:
                if output_dc not in allowed_data_classes:
                    errors.append(CompositionError(
                        code="TOOL_EXPOSES_FORBIDDEN_DATA",
                        message=f"Tool '{tool_name}' can output data class '{output_dc}' which is not in allowed data classes",
                        component1=f"tool:{tool_name}",
                        component2=f"data_class:{output_dc}",
                        recommendation=f"Add '{output_dc}' to allowed data classes or remove tool '{tool_name}'",
                    ))

    def _check_cross_tool_flow(
        self,
        manifest: ModelManifest,
        errors: list[CompositionError],
        warnings: list[CompositionError],
    ) -> None:
        """
        Check for unsafe data flow between tools.

        Identifies cases where one tool's output could flow into
        another tool that shouldn't receive that data class.
        """
        allowed_tools = manifest.spec.tools.allowed
        tools: dict[str, ToolDefinition] = {}

        for tool_name in allowed_tools:
            tool = self._tool_registry.get(tool_name)
            if tool:
                tools[tool_name] = tool

        # Check each pair of tools
        for tool1_name, tool1 in tools.items():
            for tool2_name, tool2 in tools.items():
                if tool1_name == tool2_name:
                    continue

                # Check if tool1 output could flow to tool2 input inappropriately
                output_classes = tool1.data_classes.output
                input_classes = tool2.data_classes.input

                # Get sensitivity of outputs and inputs
                for output_dc in output_classes:
                    output_sensitivity = self._taxonomy.get_effective_sensitivity(output_dc)
                    if output_sensitivity is None:
                        continue

                    for input_dc in input_classes:
                        input_sensitivity = self._taxonomy.get_effective_sensitivity(input_dc)
                        if input_sensitivity is None:
                            continue

                        # Check if sensitive data could flow to less-privileged tool
                        if output_sensitivity > input_sensitivity:
                            # This might be a downgrade attack vector
                            warnings.append(CompositionError(
                                code="POTENTIAL_SENSITIVITY_DOWNGRADE",
                                message=f"Tool '{tool1_name}' outputs {output_dc} (sensitivity: {output_sensitivity.name}) which could flow to tool '{tool2_name}' expecting {input_dc} (sensitivity: {input_sensitivity.name})",
                                component1=f"tool:{tool1_name}",
                                component2=f"tool:{tool2_name}",
                                severity="warning",
                                recommendation="Review if this data flow is intentional",
                            ))

    def _check_sensitivity_escalation(
        self,
        manifest: ModelManifest,
        errors: list[CompositionError],
        warnings: list[CompositionError],
    ) -> None:
        """
        Check for sensitivity escalation through data class combinations.

        Some combinations of data classes, when combined, may create
        data more sensitive than either individually.
        """
        allowed_data_classes = manifest.spec.data_classes.allowed

        # Get max sensitivity of allowed classes
        max_sensitivity: SensitivityLevel | None = None
        for dc_name in allowed_data_classes:
            sensitivity = self._taxonomy.get_effective_sensitivity(dc_name)
            if sensitivity is not None:
                if max_sensitivity is None or sensitivity > max_sensitivity:
                    max_sensitivity = sensitivity

        # Check if RESTRICTED or PROHIBITED data is allowed
        if max_sensitivity is not None and max_sensitivity >= SensitivityLevel.RESTRICTED:
            # Check if there are also lower-sensitivity tools
            has_low_sensitivity_tools = False
            for tool_name in manifest.spec.tools.allowed:
                tool = self._tool_registry.get(tool_name)
                if tool is None:
                    continue
                # Check if tool handles only low-sensitivity data
                all_low = True
                for dc in tool.data_classes.input | tool.data_classes.output:
                    dc_sensitivity = self._taxonomy.get_effective_sensitivity(dc)
                    if dc_sensitivity and dc_sensitivity >= SensitivityLevel.CONFIDENTIAL:
                        all_low = False
                        break
                if all_low and tool.data_classes.input:
                    has_low_sensitivity_tools = True
                    break

            if has_low_sensitivity_tools:
                warnings.append(CompositionError(
                    code="MIXED_SENSITIVITY_RISK",
                    message="Manifest allows both high-sensitivity data classes and tools handling lower sensitivity data",
                    component1="data_classes",
                    component2="tools",
                    severity="warning",
                    recommendation="Ensure data flow controls prevent sensitive data from reaching lower-privilege tools",
                ))

    def _check_caller_scope(
        self,
        manifest: ModelManifest,
        errors: list[CompositionError],
        warnings: list[CompositionError],
    ) -> None:
        """
        Check if caller restrictions are appropriate for data sensitivity.

        If high-sensitivity data is allowed, callers should be restricted.
        """
        allowed_data_classes = manifest.spec.data_classes.allowed
        callers = manifest.spec.callers

        # Get max sensitivity
        max_sensitivity: SensitivityLevel | None = None
        for dc_name in allowed_data_classes:
            sensitivity = self._taxonomy.get_effective_sensitivity(dc_name)
            if sensitivity is not None:
                if max_sensitivity is None or sensitivity > max_sensitivity:
                    max_sensitivity = sensitivity

        # If handling restricted+ data, should have caller restrictions
        if max_sensitivity and max_sensitivity >= SensitivityLevel.RESTRICTED:
            if not callers.allowed_roles and not callers.allowed_caller_ids:
                errors.append(CompositionError(
                    code="UNRESTRICTED_HIGH_SENSITIVITY",
                    message="Manifest allows restricted or higher sensitivity data but has no caller restrictions",
                    component1="data_classes",
                    component2="callers",
                    recommendation="Add allowedRoles or allowedCallerIds to restrict access",
                ))

        # Warn on confidential without restrictions
        elif max_sensitivity == SensitivityLevel.CONFIDENTIAL:
            if not callers.allowed_roles and not callers.allowed_caller_ids:
                warnings.append(CompositionError(
                    code="CONFIDENTIAL_WITHOUT_RESTRICTIONS",
                    message="Manifest allows confidential data without caller restrictions",
                    component1="data_classes",
                    component2="callers",
                    severity="warning",
                    recommendation="Consider adding caller restrictions for confidential data",
                ))

    def _check_tool_permissions(
        self,
        manifest: ModelManifest,
        errors: list[CompositionError],
        warnings: list[CompositionError],
    ) -> None:
        """
        Check if tool permission requirements align with caller permissions.

        Tools with required roles should only be accessible if callers
        with those roles are allowed.
        """
        allowed_roles = manifest.spec.callers.allowed_roles
        if not allowed_roles:
            # No role restrictions, any role is effectively allowed
            return

        for tool_name in manifest.spec.tools.allowed:
            tool = self._tool_registry.get(tool_name)
            if tool is None:
                continue

            required_roles = tool.permissions.required_roles
            if not required_roles:
                continue

            # Check if any required role is in allowed roles
            if not (required_roles & allowed_roles):
                errors.append(CompositionError(
                    code="TOOL_ROLE_MISMATCH",
                    message=f"Tool '{tool_name}' requires roles {required_roles} but manifest only allows roles {allowed_roles}",
                    component1=f"tool:{tool_name}",
                    component2="callers",
                    recommendation="Add required roles to allowedRoles or remove the tool",
                ))

    def check_request_composition(
        self,
        manifest: ModelManifest,
        requested_tools: frozenset[str],
        data_classes_in_request: frozenset[str],
    ) -> CompositionValidationResult:
        """
        Check if a specific request composition is safe.

        This is called at runtime to validate individual requests.
        """
        errors: list[CompositionError] = []
        warnings: list[CompositionError] = []

        allowed_tools = manifest.spec.tools.allowed
        allowed_data_classes = manifest.spec.data_classes.allowed

        # Check requested tools are allowed
        for tool in requested_tools:
            if tool not in allowed_tools:
                errors.append(CompositionError(
                    code="TOOL_NOT_ALLOWED",
                    message=f"Requested tool '{tool}' is not in manifest's allowed tools",
                    component1=f"tool:{tool}",
                ))

        # Check data classes are allowed
        for dc in data_classes_in_request:
            if dc not in allowed_data_classes:
                errors.append(CompositionError(
                    code="DATA_CLASS_NOT_ALLOWED",
                    message=f"Data class '{dc}' in request is not in manifest's allowed data classes",
                    component1=f"data_class:{dc}",
                ))

        # Check tool input compatibility
        for tool_name in requested_tools:
            tool = self._tool_registry.get(tool_name)
            if tool is None:
                continue

            # Check if any request data class is incompatible with tool
            for dc in data_classes_in_request:
                dc_sensitivity = self._taxonomy.get_effective_sensitivity(dc)
                if dc_sensitivity is None:
                    continue

                for tool_input_dc in tool.data_classes.input:
                    input_sensitivity = self._taxonomy.get_effective_sensitivity(tool_input_dc)
                    if input_sensitivity is None:
                        continue

                    if dc_sensitivity > input_sensitivity:
                        warnings.append(CompositionError(
                            code="SENSITIVITY_MISMATCH_IN_REQUEST",
                            message=f"Request contains {dc} (sensitivity: {dc_sensitivity.name}) but tool '{tool_name}' expects lower sensitivity input",
                            component1=f"data_class:{dc}",
                            component2=f"tool:{tool_name}",
                            severity="warning",
                        ))

        return CompositionValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
