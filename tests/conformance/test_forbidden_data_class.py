"""
Conformance Test: Forbidden Data Class Rejection

This test verifies that the envelope correctly rejects requests
containing data classes that are not allowed in the manifest.
"""

import pytest
from envelope.enforcement.ingress import IngressGate
from envelope.declaration.taxonomy import DataClassTaxonomy, SensitivityLevel
from envelope.types import CallerIdentity, InferenceRequest


@pytest.fixture
def taxonomy():
    """Create a taxonomy with various data classes."""
    taxonomy = DataClassTaxonomy()

    # Add sensitivity levels
    taxonomy.add_sensitivity_level("public", 0)
    taxonomy.add_sensitivity_level("internal", 1)
    taxonomy.add_sensitivity_level("confidential", 2)
    taxonomy.add_sensitivity_level("restricted", 3)

    # Add data classes
    taxonomy.add_data_class(
        name="general_inquiry",
        sensitivity=SensitivityLevel.PUBLIC,
    )
    taxonomy.add_data_class(
        name="account_info",
        sensitivity=SensitivityLevel.INTERNAL,
    )
    taxonomy.add_data_class(
        name="customer_profile",
        sensitivity=SensitivityLevel.CONFIDENTIAL,
        pii_fields=["name", "email", "phone"],
    )
    taxonomy.add_data_class(
        name="payment_card",
        sensitivity=SensitivityLevel.RESTRICTED,
        pii_fields=["card_number", "cvv"],
    )

    return taxonomy


@pytest.fixture
def ingress_gate(taxonomy):
    """Create ingress gate with allowed data classes."""
    allowed_classes = ["general_inquiry", "account_info"]
    return IngressGate(
        taxonomy=taxonomy,
        allowed_data_classes=allowed_classes,
    )


@pytest.fixture
def caller():
    """Create a valid caller identity."""
    return CallerIdentity(
        caller_id="test-caller",
        roles=["user"],
        authenticated=True,
    )


class TestForbiddenDataClassRejection:
    """Test suite for forbidden data class rejection."""

    def test_allowed_data_class_passes(self, ingress_gate, caller):
        """Requests with allowed data classes should pass."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "What are your hours?"}],
            data_class="general_inquiry",
        )

        result = ingress_gate.check(request, caller)

        assert result.allowed is True

    def test_forbidden_data_class_rejected(self, ingress_gate, caller):
        """Requests with forbidden data classes should be rejected."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Show me card details"}],
            data_class="payment_card",
        )

        result = ingress_gate.check(request, caller)

        assert result.allowed is False
        assert "payment_card" in result.reason or "denied" in result.reason.lower()

    def test_confidential_when_not_allowed(self, ingress_gate, caller):
        """Confidential data should be rejected if not in allowed list."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Update my profile"}],
            data_class="customer_profile",
        )

        result = ingress_gate.check(request, caller)

        assert result.allowed is False

    def test_unknown_data_class_rejected(self, ingress_gate, caller):
        """Unknown data classes should be rejected (deny-by-default)."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Access secret data"}],
            data_class="unknown_class",
        )

        result = ingress_gate.check(request, caller)

        assert result.allowed is False

    def test_empty_data_class_rejected(self, ingress_gate, caller):
        """Empty data class should be rejected."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Hello"}],
            data_class="",
        )

        result = ingress_gate.check(request, caller)

        assert result.allowed is False

    def test_pii_detection_triggers_classification(self, ingress_gate, caller):
        """PII in content should trigger higher classification."""
        # Request claims to be general inquiry but contains PII
        request = InferenceRequest(
            request_id="req-123",
            messages=[{
                "role": "user",
                "content": "My card number is 4111-1111-1111-1111"
            }],
            data_class="general_inquiry",
        )

        result = ingress_gate.check(request, caller)

        # Should detect PII and either reject or escalate
        assert result.allowed is False or result.escalate is True


class TestDataClassBoundaryEnforcement:
    """Test data class boundary enforcement scenarios."""

    def test_multiple_data_classes_all_allowed(self, ingress_gate, caller):
        """Request with multiple allowed data classes should pass."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Account inquiry"}],
            data_classes=["general_inquiry", "account_info"],
        )

        result = ingress_gate.check(request, caller)

        assert result.allowed is True

    def test_multiple_data_classes_one_forbidden(self, ingress_gate, caller):
        """Request with any forbidden data class should be rejected."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Mixed inquiry"}],
            data_classes=["general_inquiry", "payment_card"],
        )

        result = ingress_gate.check(request, caller)

        assert result.allowed is False

    def test_sensitivity_level_boundary(self, taxonomy, caller):
        """Requests exceeding max sensitivity should be rejected."""
        gate = IngressGate(
            taxonomy=taxonomy,
            allowed_data_classes=["general_inquiry", "account_info"],
            max_sensitivity=SensitivityLevel.INTERNAL,
        )

        # Confidential exceeds internal
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Profile data"}],
            data_class="customer_profile",
        )

        result = gate.check(request, caller)

        assert result.allowed is False


class TestDataClassNoOverride:
    """Verify that data class restrictions cannot be overridden."""

    def test_no_bypass_parameter(self, ingress_gate, caller):
        """No parameter should bypass data class checks."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Access payment"}],
            data_class="payment_card",
            metadata={"bypass": True, "force": True},
        )

        result = ingress_gate.check(request, caller)

        assert result.allowed is False

    def test_admin_cannot_bypass_data_class(self, ingress_gate):
        """Admin roles cannot bypass data class restrictions."""
        admin = CallerIdentity(
            caller_id="admin",
            roles=["admin", "superuser"],
            authenticated=True,
        )

        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Payment access"}],
            data_class="payment_card",
        )

        result = ingress_gate.check(request, admin)

        assert result.allowed is False


class TestDataClassAuditTrail:
    """Verify audit trail for data class decisions."""

    def test_rejection_is_recorded(self, ingress_gate, caller):
        """Data class rejections should be recorded."""
        request = InferenceRequest(
            request_id="req-audit-123",
            messages=[{"role": "user", "content": "Payment data"}],
            data_class="payment_card",
        )

        result = ingress_gate.check(request, caller)

        assert result.request_id == "req-audit-123"
        # Implementation should record to provenance store

    def test_rejection_includes_reason(self, ingress_gate, caller):
        """Rejections should include specific reason."""
        request = InferenceRequest(
            request_id="req-123",
            messages=[{"role": "user", "content": "Payment"}],
            data_class="payment_card",
        )

        result = ingress_gate.check(request, caller)

        assert result.reason is not None
        assert len(result.reason) > 0
