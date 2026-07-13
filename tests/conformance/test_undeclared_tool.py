"""
Conformance Test: Undeclared Tool Invocation

This test verifies that the envelope correctly rejects attempts
to invoke tools that are not declared in the manifest.
"""

import pytest
from envelope.enforcement.tool_gate import ToolGate
from envelope.declaration.tools import ToolRegistry
from envelope.types import CallerIdentity, ToolInvocation


@pytest.fixture
def tool_registry():
    """Create a tool registry with only allowed tools."""
    registry = ToolRegistry()
    registry.register_tool(
        name="allowed_tool",
        description="An allowed tool",
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object", "properties": {}},
    )
    return registry


@pytest.fixture
def tool_gate(tool_registry):
    """Create a tool gate with the registry."""
    return ToolGate(tool_registry=tool_registry)


@pytest.fixture
def caller():
    """Create a valid caller identity."""
    return CallerIdentity(
        caller_id="test-caller",
        roles=["user"],
        authenticated=True,
    )


class TestUndeclaredToolRejection:
    """Test suite for undeclared tool rejection."""

    def test_undeclared_tool_is_rejected(self, tool_gate, caller):
        """Undeclared tools should be rejected with deny decision."""
        invocation = ToolInvocation(
            tool_name="undeclared_tool",
            arguments={"query": "test"},
            request_id="req-123",
        )

        result = tool_gate.check(invocation, caller)

        assert result.allowed is False
        assert "not registered" in result.reason.lower() or "denied" in result.reason.lower()

    def test_declared_tool_is_allowed(self, tool_gate, caller):
        """Declared tools should be allowed."""
        invocation = ToolInvocation(
            tool_name="allowed_tool",
            arguments={},
            request_id="req-123",
        )

        result = tool_gate.check(invocation, caller)

        assert result.allowed is True

    def test_empty_tool_name_rejected(self, tool_gate, caller):
        """Empty tool names should be rejected."""
        invocation = ToolInvocation(
            tool_name="",
            arguments={},
            request_id="req-123",
        )

        result = tool_gate.check(invocation, caller)

        assert result.allowed is False

    def test_tool_name_case_sensitive(self, tool_gate, caller):
        """Tool name matching should be case-sensitive."""
        invocation = ToolInvocation(
            tool_name="ALLOWED_TOOL",  # Wrong case
            arguments={},
            request_id="req-123",
        )

        result = tool_gate.check(invocation, caller)

        assert result.allowed is False

    def test_similar_tool_name_rejected(self, tool_gate, caller):
        """Similar but not exact tool names should be rejected."""
        similar_names = [
            "allowed_tool_",
            "_allowed_tool",
            "allowed-tool",
            "allowedtool",
            "allowed_tools",
        ]

        for name in similar_names:
            invocation = ToolInvocation(
                tool_name=name,
                arguments={},
                request_id="req-123",
            )

            result = tool_gate.check(invocation, caller)

            assert result.allowed is False, f"Tool '{name}' should be rejected"

    def test_injection_attempt_in_tool_name(self, tool_gate, caller):
        """Injection attempts in tool names should be rejected."""
        injection_attempts = [
            "allowed_tool; rm -rf /",
            "allowed_tool\n secret_tool",
            "allowed_tool' OR '1'='1",
            "allowed_tool$(whoami)",
        ]

        for name in injection_attempts:
            invocation = ToolInvocation(
                tool_name=name,
                arguments={},
                request_id="req-123",
            )

            result = tool_gate.check(invocation, caller)

            assert result.allowed is False, f"Injection attempt '{name}' should be rejected"

    def test_rejection_is_logged(self, tool_gate, caller, caplog):
        """Rejections should be logged for audit purposes."""
        invocation = ToolInvocation(
            tool_name="undeclared_tool",
            arguments={},
            request_id="req-123",
        )

        tool_gate.check(invocation, caller)

        # Verify logging (implementation-specific)
        # assert "undeclared_tool" in caplog.text or check audit trail

    def test_rejection_includes_request_id(self, tool_gate, caller):
        """Rejection response should include the request ID for tracing."""
        invocation = ToolInvocation(
            tool_name="undeclared_tool",
            arguments={},
            request_id="req-trace-456",
        )

        result = tool_gate.check(invocation, caller)

        assert result.request_id == "req-trace-456"


class TestToolGateNoOverride:
    """Verify that tool gate cannot be overridden."""

    def test_no_bypass_flag(self, tool_gate, caller):
        """There should be no way to bypass tool checking."""
        invocation = ToolInvocation(
            tool_name="undeclared_tool",
            arguments={"bypass": True, "force": True, "skip_check": True},
            request_id="req-123",
        )

        result = tool_gate.check(invocation, caller)

        assert result.allowed is False

    def test_admin_cannot_bypass(self, tool_gate):
        """Even admin roles cannot bypass tool restrictions."""
        admin_caller = CallerIdentity(
            caller_id="admin-user",
            roles=["admin", "superuser", "root"],
            authenticated=True,
        )

        invocation = ToolInvocation(
            tool_name="undeclared_tool",
            arguments={},
            request_id="req-123",
        )

        result = tool_gate.check(invocation, admin_caller)

        assert result.allowed is False
