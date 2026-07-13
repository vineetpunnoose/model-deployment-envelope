"""
Conformance Test: Escalation and Response Withholding

This test verifies that the envelope correctly triggers escalation
and withholds model responses when escalation conditions are met.
"""

import pytest
from envelope.enforcement.escalation import EscalationEnforcer
from envelope.types import (
    CallerIdentity,
    InferenceRequest,
    InferenceResponse,
    EscalationCondition,
)


@pytest.fixture
def escalation_conditions():
    """Define escalation conditions."""
    return [
        EscalationCondition(
            id="low-confidence",
            trigger="confidence_low",
            threshold=0.4,
            description="Escalate when confidence below threshold",
        ),
        EscalationCondition(
            id="tool-failure",
            trigger="tool_failure",
            description="Escalate on tool execution failure",
        ),
        EscalationCondition(
            id="explicit-request",
            trigger="explicit_request",
            patterns=["speak to human", "supervisor", "manager"],
            description="Escalate on explicit customer request",
        ),
        EscalationCondition(
            id="policy-violation",
            trigger="policy_violation",
            description="Escalate on policy violations",
        ),
        EscalationCondition(
            id="data-class-mismatch",
            trigger="data_class_mismatch",
            data_classes=["payment_card", "credit_data"],
            description="Escalate on forbidden data class access",
        ),
    ]


@pytest.fixture
def escalation_enforcer(escalation_conditions):
    """Create escalation enforcer."""
    return EscalationEnforcer(conditions=escalation_conditions)


@pytest.fixture
def caller():
    """Create valid caller."""
    return CallerIdentity(
        caller_id="test-caller",
        roles=["user"],
        authenticated=True,
    )


class TestEscalationTriggers:
    """Test escalation condition triggers."""

    def test_low_confidence_triggers_escalation(self, escalation_enforcer, caller):
        """Low confidence should trigger escalation."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Complex question"}],
        )
        response = InferenceResponse(
            content="I'm not sure about this...",
            confidence=0.3,  # Below threshold
        )

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.escalate is True
        assert result.condition_id == "low-confidence"

    def test_high_confidence_no_escalation(self, escalation_enforcer, caller):
        """High confidence should not trigger escalation."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Simple question"}],
        )
        response = InferenceResponse(
            content="The answer is 42.",
            confidence=0.95,
        )

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.escalate is False

    def test_tool_failure_triggers_escalation(self, escalation_enforcer, caller):
        """Tool failure should trigger escalation."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Look up my account"}],
        )
        response = InferenceResponse(
            content="I encountered an error looking up your account.",
            tool_failures=[{"tool": "account_lookup", "error": "Connection timeout"}],
        )

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.escalate is True
        assert result.condition_id == "tool-failure"

    def test_explicit_request_triggers_escalation(self, escalation_enforcer, caller):
        """Explicit human request should trigger escalation."""
        patterns = [
            "I want to speak to a human",
            "Let me talk to your supervisor",
            "Get me a manager",
            "I need to speak to human please",
        ]

        for pattern in patterns:
            request = InferenceRequest(
                request_id="req-123",
                messages=[{"role": "user", "content": pattern}],
            )
            response = InferenceResponse(content="")

            result = escalation_enforcer.evaluate(request, response, caller)

            assert result.escalate is True, f"Pattern '{pattern}' should trigger escalation"
            assert result.condition_id == "explicit-request"

    def test_data_class_mismatch_triggers_escalation(self, escalation_enforcer, caller):
        """Accessing forbidden data class should trigger escalation."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Show my credit card"}],
            detected_data_classes=["payment_card"],
        )
        response = InferenceResponse(content="")

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.escalate is True
        assert result.condition_id == "data-class-mismatch"


class TestResponseWithholding:
    """Test response withholding on escalation."""

    def test_response_withheld_on_escalation(self, escalation_enforcer, caller):
        """Model response should be withheld when escalation triggers."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Get me a supervisor"}],
        )
        response = InferenceResponse(
            content="I can help you with that. Here's the information...",
            confidence=0.9,
        )

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.escalate is True
        assert result.withheld is True
        assert result.original_response is not None
        # The withheld response should not be returned to caller
        assert result.replacement_message is not None

    def test_withheld_response_replaced(self, escalation_enforcer, caller):
        """Withheld response should be replaced with escalation message."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Supervisor please"}],
        )
        response = InferenceResponse(content="Original response")

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.replacement_message is not None
        assert "escalat" in result.replacement_message.lower() or \
               "transfer" in result.replacement_message.lower() or \
               "connect" in result.replacement_message.lower()

    def test_original_response_preserved_for_review(self, escalation_enforcer, caller):
        """Original response should be preserved for human review."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Manager now"}],
        )
        original_content = "This was the original model response"
        response = InferenceResponse(content=original_content)

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.original_response == original_content


class TestEscalationHandoff:
    """Test escalation handoff to case system."""

    def test_escalation_creates_case(self, escalation_enforcer, caller):
        """Escalation should create a case for human review."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Speak to human"}],
        )
        response = InferenceResponse(content="Response content")

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.escalate is True
        assert result.case_id is not None

    def test_case_includes_context(self, escalation_enforcer, caller):
        """Escalation case should include full context."""
        request = InferenceRequest(
            request_id="req-context-456",
            messages=[
                {"role": "user", "content": "I have a problem"},
                {"role": "assistant", "content": "How can I help?"},
                {"role": "user", "content": "Get me a manager"},
            ],
            context={"customer_id": "cust-789"},
        )
        response = InferenceResponse(content="Attempting to help...")

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.case_context is not None
        assert result.case_context.get("request_id") == "req-context-456"
        assert result.case_context.get("customer_id") == "cust-789"
        assert len(result.case_context.get("messages", [])) == 3

    def test_escalation_includes_evidence(self, escalation_enforcer, caller):
        """Escalation should include evidence for why it triggered."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "SUPERVISOR NOW!"}],
        )
        response = InferenceResponse(content="")

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.evidence is not None
        assert result.condition_id in str(result.evidence)


class TestMultipleConditions:
    """Test behavior with multiple escalation conditions."""

    def test_first_matching_condition_triggers(self, escalation_enforcer, caller):
        """First matching condition by priority should trigger."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Get supervisor"}],
        )
        response = InferenceResponse(
            content="",
            confidence=0.3,  # Also triggers low-confidence
        )

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.escalate is True
        # Should match whichever condition has higher priority

    def test_all_conditions_logged(self, escalation_enforcer, caller):
        """All matching conditions should be logged even if only one triggers."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Manager please"}],
            detected_data_classes=["payment_card"],
        )
        response = InferenceResponse(
            content="",
            confidence=0.2,
            tool_failures=[{"tool": "lookup", "error": "Failed"}],
        )

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.escalate is True
        # All matching conditions should be in the metadata
        assert len(result.all_matched_conditions) >= 2


class TestEscalationAuditTrail:
    """Verify audit trail for escalations."""

    def test_escalation_is_recorded(self, escalation_enforcer, caller):
        """All escalations should be recorded."""
        request = InferenceRequest(
            request_id="req-audit-999",
            messages=[{"role": "user", "content": "Human please"}],
        )
        response = InferenceResponse(content="Model response")

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.request_id == "req-audit-999"
        # Implementation should record to provenance store

    def test_non_escalation_also_recorded(self, escalation_enforcer, caller):
        """Non-escalation decisions should also be recorded."""
        request = InferenceRequest(
            request_id="req-normal-123",
            messages=[{"role": "user", "content": "What time is it?"}],
        )
        response = InferenceResponse(content="It's 3pm", confidence=0.99)

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.escalate is False
        assert result.request_id == "req-normal-123"


class TestEscalationNoOverride:
    """Verify escalation cannot be bypassed."""

    def test_no_suppress_flag(self, escalation_enforcer, caller):
        """No flag should suppress escalation."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Get me supervisor"}],
            metadata={"suppress_escalation": True, "bypass": True},
        )
        response = InferenceResponse(content="")

        result = escalation_enforcer.evaluate(request, response, caller)

        assert result.escalate is True

    def test_admin_cannot_bypass_escalation(self, escalation_enforcer):
        """Admin roles cannot bypass escalation."""
        admin = CallerIdentity(
            caller_id="admin",
            roles=["admin", "superuser"],
            authenticated=True,
        )

        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Manager now"}],
        )
        response = InferenceResponse(content="")

        result = escalation_enforcer.evaluate(request, response, admin)

        assert result.escalate is True
