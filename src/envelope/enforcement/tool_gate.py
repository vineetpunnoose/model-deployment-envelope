"""
Tool Gate (C2)

Controls tool invocations with deny-by-default policy.
Makes unmanifested tools completely unreachable.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable

from envelope.types import (
    CallerIdentity,
    ToolCall,
    PolicyDecision,
    DecisionVerdict,
    ToolNotPermittedError,
)
from envelope.declaration.manifest import ModelManifest
from envelope.declaration.tools import ToolRegistry, ToolDefinition


@dataclass
class ToolGateResult:
    """Result of tool gate check."""
    allowed: bool
    decision: PolicyDecision
    tool_definition: ToolDefinition | None = None
    sanitized_arguments: dict[str, Any] | None = None


@dataclass
class ToolInvocationRecord:
    """Record of a tool invocation."""
    tool_name: str
    arguments: dict[str, Any]
    result: Any
    success: bool
    duration_ms: float
    caller_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    error: str | None = None


class ToolGate:
    """
    Tool invocation gate with deny-by-default policy.

    Controls which tools can be invoked and validates arguments.
    Unmanifested tools are completely unreachable - they cannot
    be invoked even if the model requests them.
    """

    def __init__(
        self,
        manifest: ModelManifest,
        registry: ToolRegistry,
    ):
        self._manifest = manifest
        self._registry = registry
        self._invocation_log: list[ToolInvocationRecord] = []

    @property
    def manifest(self) -> ModelManifest:
        return self._manifest

    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    def check(
        self,
        tool_call: ToolCall,
        caller: CallerIdentity,
    ) -> ToolGateResult:
        """
        Check if a tool invocation is permitted.

        Implements deny-by-default: tool must be both registered
        and explicitly allowed in the manifest.
        """
        tool_name = tool_call.tool_name

        # Check 1: Is tool registered?
        tool = self._registry.get(tool_name)
        if tool is None:
            return ToolGateResult(
                allowed=False,
                decision=PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="tool_not_registered",
                    rule_citation="Tool not registered in registry",
                    reason=f"Tool '{tool_name}' is not registered (deny-by-default)",
                ),
            )

        # Check 2: Is tool in manifest allowlist?
        allowed_tools = self._manifest.spec.tools.allowed
        if tool_name not in allowed_tools:
            return ToolGateResult(
                allowed=False,
                decision=PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="tool_not_in_manifest",
                    rule_citation="Tool not in manifest allowlist",
                    reason=f"Tool '{tool_name}' is not allowed by manifest (deny-by-default)",
                ),
            )

        # Check 3: Does caller have required roles?
        if not tool.caller_has_permission(caller):
            return ToolGateResult(
                allowed=False,
                decision=PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="tool_role_denied",
                    rule_citation="Caller lacks required role",
                    reason=f"Caller lacks required roles for tool '{tool_name}'",
                ),
            )

        # Check 4: Validate arguments
        arg_errors = tool.validate_arguments(tool_call.arguments)
        if arg_errors:
            return ToolGateResult(
                allowed=False,
                decision=PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="tool_invalid_arguments",
                    rule_citation="Invalid tool arguments",
                    reason=f"Invalid arguments: {'; '.join(arg_errors)}",
                ),
            )

        return ToolGateResult(
            allowed=True,
            decision=PolicyDecision(
                verdict=DecisionVerdict.ALLOW,
                rule_id="tool_allowed",
                rule_citation="Tool passed all checks",
                reason=f"Tool '{tool_name}' invocation permitted",
            ),
            tool_definition=tool,
            sanitized_arguments=tool_call.arguments,
        )

    async def execute(
        self,
        tool_call: ToolCall,
        caller: CallerIdentity,
    ) -> tuple[Any, ToolInvocationRecord]:
        """
        Execute a tool invocation after checking permissions.

        Returns (result, record) tuple.
        Raises ToolNotPermittedError if not allowed.
        """
        import time

        # Check permissions
        check_result = self.check(tool_call, caller)
        if not check_result.allowed:
            raise ToolNotPermittedError(
                tool_call.tool_name,
                check_result.decision.reason,
            )

        tool = check_result.tool_definition
        if tool is None:
            raise ToolNotPermittedError(
                tool_call.tool_name,
                "Tool definition not found",
            )

        # Get handler
        handler = self._registry.get_handler(tool_call.tool_name)
        if handler is None:
            raise ToolNotPermittedError(
                tool_call.tool_name,
                "Tool handler not registered",
            )

        # Execute
        start_time = time.perf_counter()
        try:
            result = await handler(**tool_call.arguments)
            duration_ms = (time.perf_counter() - start_time) * 1000

            record = ToolInvocationRecord(
                tool_name=tool_call.tool_name,
                arguments=self._redact_arguments(tool, tool_call.arguments),
                result=self._redact_result(tool, result),
                success=True,
                duration_ms=duration_ms,
                caller_id=caller.caller_id,
            )
            self._invocation_log.append(record)

            return result, record

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000

            record = ToolInvocationRecord(
                tool_name=tool_call.tool_name,
                arguments=self._redact_arguments(tool, tool_call.arguments),
                result=None,
                success=False,
                duration_ms=duration_ms,
                caller_id=caller.caller_id,
                error=str(e),
            )
            self._invocation_log.append(record)

            raise

    def _redact_arguments(
        self, tool: ToolDefinition, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Redact sensitive fields from arguments for logging."""
        if not tool.audit.log_inputs:
            return {"_redacted": True}

        result = dict(arguments)
        for field_path in tool.audit.redact_fields:
            self._redact_field(result, field_path)

        return result

    def _redact_result(
        self, tool: ToolDefinition, result: Any
    ) -> Any:
        """Redact sensitive fields from result for logging."""
        if not tool.audit.log_outputs:
            return {"_redacted": True}

        if isinstance(result, dict):
            result_copy = dict(result)
            for field_path in tool.audit.redact_fields:
                self._redact_field(result_copy, field_path)
            return result_copy

        return result

    def _redact_field(self, data: dict[str, Any], field_path: str) -> None:
        """Redact a field at a given path in nested dict."""
        parts = field_path.split(".")
        current = data

        for part in parts[:-1]:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return

        if isinstance(current, dict) and parts[-1] in current:
            current[parts[-1]] = "[REDACTED]"

    def get_allowed_tools(self) -> list[ToolDefinition]:
        """Get list of tools allowed by the manifest."""
        return self._registry.filter_allowed(self._manifest.spec.tools.allowed)

    def get_tool_schema(self, format: str = "openai") -> list[dict[str, Any]]:
        """
        Get tool schemas in provider format.

        Args:
            format: 'openai' or 'anthropic'
        """
        allowed = self._manifest.spec.tools.allowed

        if format == "anthropic":
            return self._registry.to_anthropic_tools(allowed)
        else:
            return self._registry.to_openai_tools(allowed)

    def get_invocation_log(
        self,
        limit: int = 100,
        tool_name: str | None = None,
    ) -> list[ToolInvocationRecord]:
        """Get recent tool invocations."""
        logs = self._invocation_log

        if tool_name:
            logs = [l for l in logs if l.tool_name == tool_name]

        return logs[-limit:]

    def clear_invocation_log(self) -> int:
        """Clear invocation log. Returns count of cleared entries."""
        count = len(self._invocation_log)
        self._invocation_log.clear()
        return count

    def is_tool_available(self, tool_name: str) -> bool:
        """Check if a tool is available (registered and allowed)."""
        if not self._registry.is_registered(tool_name):
            return False
        return tool_name in self._manifest.spec.tools.allowed

    def list_available_tools(self) -> list[str]:
        """List all available tool names."""
        registered = set(self._registry.list_tools())
        allowed = self._manifest.spec.tools.allowed
        return list(registered & allowed)
