"""
Tool Registry (A2)

Manages tool definitions and enforces deny-by-default policy.
Tools must be explicitly registered and allowed in the manifest
to be invocable by models.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable

import jsonschema
import yaml

from envelope.types import (
    ToolName,
    ToolNotPermittedError,
    ValidationError,
    CallerIdentity,
)


SCHEMA_DIR = Path(__file__).parent.parent.parent.parent / "schemas"


@dataclass(frozen=True)
class ToolPermissions:
    """Tool permission requirements."""
    required_roles: frozenset[str] = frozenset()
    rate_limit_max_calls: int | None = None
    rate_limit_window_seconds: int | None = None


@dataclass(frozen=True)
class ToolAuditConfig:
    """Tool audit configuration."""
    log_inputs: bool = True
    log_outputs: bool = True
    redact_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolDataClasses:
    """Data classes a tool may receive or produce."""
    input: frozenset[str] = frozenset()
    output: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ToolDefinition:
    """
    Complete definition of a tool available to models.

    Tools are external capabilities that models can invoke,
    subject to permission checks and audit logging.
    """
    name: ToolName
    type: str
    description: str
    schema: dict[str, Any]
    return_schema: dict[str, Any] | None = None
    data_classes: ToolDataClasses = field(default_factory=ToolDataClasses)
    permissions: ToolPermissions = field(default_factory=ToolPermissions)
    audit: ToolAuditConfig = field(default_factory=ToolAuditConfig)
    handler: str | None = None
    endpoint: str | None = None
    timeout: int = 30

    def validate_arguments(self, arguments: dict[str, Any]) -> list[str]:
        """Validate tool arguments against schema."""
        errors: list[str] = []
        validator = jsonschema.Draft202012Validator(self.schema)

        for error in validator.iter_errors(arguments):
            path = ".".join(str(p) for p in error.absolute_path) or "(root)"
            errors.append(f"{path}: {error.message}")

        return errors

    def caller_has_permission(self, caller: CallerIdentity) -> bool:
        """Check if caller has permission to invoke this tool."""
        if not self.permissions.required_roles:
            return True
        return bool(caller.roles & self.permissions.required_roles)

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert to OpenAI tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }

    def to_anthropic_tool(self) -> dict[str, Any]:
        """Convert to Anthropic tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema,
        }


class ToolRegistry:
    """
    Registry for tool definitions with deny-by-default policy.

    Tools must be explicitly registered in this registry AND
    allowed in the model manifest to be invocable. Unregistered
    or unallowed tools are rejected at the tool gate.
    """

    def __init__(self):
        self._tools: dict[ToolName, ToolDefinition] = {}
        self._handlers: dict[ToolName, Callable[..., Awaitable[Any]]] = {}
        self._schema: dict[str, Any] | None = None

    @property
    def tool_schema(self) -> dict[str, Any]:
        """Load and cache the tool manifest schema."""
        if self._schema is None:
            schema_path = SCHEMA_DIR / "tool-manifest.schema.json"
            if not schema_path.exists():
                raise FileNotFoundError(f"Schema not found: {schema_path}")
            with open(schema_path) as f:
                import json
                self._schema = json.load(f)
        return self._schema

    def register(self, tool: ToolDefinition) -> None:
        """
        Register a tool definition.

        Overwrites any existing tool with the same name.
        """
        self._tools[tool.name] = tool

    def register_handler(
        self, tool_name: ToolName, handler: Callable[..., Awaitable[Any]]
    ) -> None:
        """Register an async handler function for a tool."""
        if tool_name not in self._tools:
            raise ValueError(f"Tool '{tool_name}' not registered")
        self._handlers[tool_name] = handler

    def unregister(self, tool_name: ToolName) -> bool:
        """
        Unregister a tool.

        Returns True if tool was removed, False if not found.
        """
        if tool_name in self._tools:
            del self._tools[tool_name]
            self._handlers.pop(tool_name, None)
            return True
        return False

    def get(self, tool_name: ToolName) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(tool_name)

    def get_handler(self, tool_name: ToolName) -> Callable[..., Awaitable[Any]] | None:
        """Get a tool's handler function."""
        return self._handlers.get(tool_name)

    def is_registered(self, tool_name: ToolName) -> bool:
        """Check if a tool is registered."""
        return tool_name in self._tools

    def list_tools(self) -> list[ToolName]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_all(self) -> dict[ToolName, ToolDefinition]:
        """Get all registered tools."""
        return dict(self._tools)

    def filter_allowed(self, allowed: frozenset[ToolName]) -> list[ToolDefinition]:
        """Get tools that are both registered and in the allowed set."""
        return [
            tool for name, tool in self._tools.items()
            if name in allowed
        ]

    def check_tool_permitted(
        self,
        tool_name: ToolName,
        allowed_tools: frozenset[ToolName],
        caller: CallerIdentity | None = None,
    ) -> None:
        """
        Check if a tool invocation is permitted.

        Raises ToolNotPermittedError if:
        - Tool is not registered
        - Tool is not in allowed set
        - Caller lacks required permissions

        This implements deny-by-default: all tools are blocked
        unless explicitly registered and allowed.
        """
        # Check registration (deny-by-default)
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ToolNotPermittedError(
                tool_name,
                f"Tool '{tool_name}' is not registered in the tool registry"
            )

        # Check allowlist (deny-by-default)
        if tool_name not in allowed_tools:
            raise ToolNotPermittedError(
                tool_name,
                f"Tool '{tool_name}' is not in the manifest's allowed tools list"
            )

        # Check caller permissions
        if caller is not None and not tool.caller_has_permission(caller):
            raise ToolNotPermittedError(
                tool_name,
                f"Caller lacks required role for tool '{tool_name}'"
            )

    def load_from_manifest(self, path: Path | str) -> ToolDefinition:
        """
        Load a tool definition from a YAML manifest file.

        Validates against JSON schema before loading.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Tool manifest not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        return self.load_from_dict(data)

    def load_from_dict(self, data: dict[str, Any]) -> ToolDefinition:
        """
        Load a tool definition from a dictionary.

        Validates against JSON schema before loading.
        """
        errors = self.validate(data)
        if errors:
            raise ValidationError(
                f"Tool manifest validation failed: {len(errors)} error(s)",
                errors=errors
            )

        return self._parse_tool(data)

    def validate(self, data: dict[str, Any]) -> list[str]:
        """Validate tool manifest data against JSON schema."""
        errors: list[str] = []
        validator = jsonschema.Draft202012Validator(self.tool_schema)

        for error in validator.iter_errors(data):
            path = ".".join(str(p) for p in error.absolute_path) or "(root)"
            errors.append(f"{path}: {error.message}")

        return errors

    def _parse_tool(self, data: dict[str, Any]) -> ToolDefinition:
        """Parse validated data into a ToolDefinition."""
        metadata = data["metadata"]
        spec = data["spec"]

        # Parse data classes
        dc_data = spec.get("dataClasses", {})
        data_classes = ToolDataClasses(
            input=frozenset(dc_data.get("input", [])),
            output=frozenset(dc_data.get("output", [])),
        )

        # Parse permissions
        perm_data = spec.get("permissions", {})
        permissions = ToolPermissions(
            required_roles=frozenset(perm_data.get("requiredRoles", [])),
            rate_limit_max_calls=perm_data.get("rateLimit", {}).get("maxCalls"),
            rate_limit_window_seconds=perm_data.get("rateLimit", {}).get("windowSeconds"),
        )

        # Parse audit config
        audit_data = spec.get("audit", {})
        audit = ToolAuditConfig(
            log_inputs=audit_data.get("logInputs", True),
            log_outputs=audit_data.get("logOutputs", True),
            redact_fields=tuple(audit_data.get("redactFields", [])),
        )

        # Parse implementation
        impl_data = spec.get("implementation", {})

        return ToolDefinition(
            name=metadata["name"],
            type=spec["type"],
            description=metadata.get("description", ""),
            schema=spec["schema"],
            return_schema=spec.get("returnSchema"),
            data_classes=data_classes,
            permissions=permissions,
            audit=audit,
            handler=impl_data.get("handler"),
            endpoint=impl_data.get("endpoint"),
            timeout=impl_data.get("timeout", 30),
        )

    def to_openai_tools(self, allowed: frozenset[ToolName]) -> list[dict[str, Any]]:
        """Convert allowed tools to OpenAI tool format."""
        return [tool.to_openai_tool() for tool in self.filter_allowed(allowed)]

    def to_anthropic_tools(self, allowed: frozenset[ToolName]) -> list[dict[str, Any]]:
        """Convert allowed tools to Anthropic tool format."""
        return [tool.to_anthropic_tool() for tool in self.filter_allowed(allowed)]
