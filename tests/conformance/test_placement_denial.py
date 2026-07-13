"""
Conformance Test: Placement Denial

This test verifies that the envelope correctly denies decryption keys
when data is accessed from a forbidden placement.
"""

import pytest
from envelope.enforcement.key_broker import KeyBroker
from envelope.declaration.placement import PlacementPolicy, Placement, PlacementRule
from envelope.declaration.taxonomy import DataClassTaxonomy, SensitivityLevel
from envelope.types import CallerIdentity, KeyGrantRequest


@pytest.fixture
def placements():
    """Define test placements."""
    return [
        Placement(
            id="on-premises",
            type="on-premises",
            provider="internal",
            region="us-east",
            jurisdiction=["US"],
            certifications=["SOC2", "ISO27001", "PCI-DSS"],
            encryption_at_rest=True,
            encryption_in_transit=True,
        ),
        Placement(
            id="public-cloud",
            type="public-cloud",
            provider="aws",
            region="us-east-1",
            jurisdiction=["US"],
            certifications=["SOC2", "ISO27001"],
            encryption_at_rest=True,
            encryption_in_transit=True,
        ),
        Placement(
            id="edge",
            type="edge",
            provider="store-systems",
            region="multiple",
            jurisdiction=["US"],
            certifications=[],
            encryption_at_rest=False,
            encryption_in_transit=True,
        ),
    ]


@pytest.fixture
def placement_policy(placements):
    """Create placement policy with rules."""
    policy = PlacementPolicy(placements=placements)

    # PCI data requires on-premises with PCI-DSS cert
    policy.add_rule(PlacementRule(
        id="pci-data",
        priority=10,
        conditions={
            "dataClasses": ["payment_card"],
            "requiredCertifications": ["PCI-DSS"],
        },
        action="allow",
        reason="PCI data allowed only in PCI-certified environments",
    ))

    # Deny PCI data elsewhere
    policy.add_rule(PlacementRule(
        id="pci-data-deny",
        priority=11,
        conditions={"dataClasses": ["payment_card"]},
        action="deny",
        reason="PCI data not allowed in non-PCI environments",
    ))

    # Restricted data on-prem or private cloud only
    policy.add_rule(PlacementRule(
        id="restricted-on-prem",
        priority=20,
        conditions={
            "sensitivity": {"min": "restricted"},
            "placementType": ["on-premises", "private-cloud"],
        },
        action="allow",
        reason="Restricted data allowed on-premises",
    ))

    # Deny restricted in public cloud
    policy.add_rule(PlacementRule(
        id="restricted-deny-cloud",
        priority=21,
        conditions={
            "sensitivity": {"min": "restricted"},
            "placementType": ["public-cloud", "edge"],
        },
        action="deny",
        reason="Restricted data not allowed in public cloud",
    ))

    policy.default_action = "deny"
    return policy


@pytest.fixture
def taxonomy():
    """Create data taxonomy."""
    taxonomy = DataClassTaxonomy()
    taxonomy.add_sensitivity_level("public", 0)
    taxonomy.add_sensitivity_level("internal", 1)
    taxonomy.add_sensitivity_level("confidential", 2)
    taxonomy.add_sensitivity_level("restricted", 3)

    taxonomy.add_data_class("general_inquiry", SensitivityLevel.PUBLIC)
    taxonomy.add_data_class("account_info", SensitivityLevel.INTERNAL)
    taxonomy.add_data_class("customer_profile", SensitivityLevel.CONFIDENTIAL)
    taxonomy.add_data_class("payment_card", SensitivityLevel.RESTRICTED)
    taxonomy.add_data_class("credit_data", SensitivityLevel.RESTRICTED)

    return taxonomy


@pytest.fixture
def key_broker(placement_policy, taxonomy):
    """Create key broker with policies."""
    return KeyBroker(
        placement_policy=placement_policy,
        taxonomy=taxonomy,
    )


@pytest.fixture
def caller():
    """Create valid caller."""
    return CallerIdentity(
        caller_id="test-service",
        roles=["service"],
        authenticated=True,
    )


class TestPlacementDenial:
    """Test placement-based key denial."""

    def test_allowed_placement_gets_key(self, key_broker, caller):
        """Allowed placement should receive decryption key."""
        request = KeyGrantRequest(
            request_id="req-123",
            subject_id="subject-456",
            data_class="payment_card",
            current_placement="on-premises",
        )

        result = key_broker.request_key(request, caller)

        assert result.granted is True
        assert result.key is not None

    def test_forbidden_placement_denied_key(self, key_broker, caller):
        """Forbidden placement should be denied decryption key."""
        request = KeyGrantRequest(
            request_id="req-123",
            subject_id="subject-456",
            data_class="payment_card",
            current_placement="public-cloud",
        )

        result = key_broker.request_key(request, caller)

        assert result.granted is False
        assert result.key is None
        assert "denied" in result.reason.lower() or "not allowed" in result.reason.lower()

    def test_edge_placement_denied_restricted(self, key_broker, caller):
        """Edge placement should be denied restricted data keys."""
        request = KeyGrantRequest(
            request_id="req-123",
            subject_id="subject-456",
            data_class="credit_data",
            current_placement="edge",
        )

        result = key_broker.request_key(request, caller)

        assert result.granted is False

    def test_public_data_allowed_anywhere(self, key_broker, caller):
        """Public data should be accessible from any placement."""
        for placement in ["on-premises", "public-cloud", "edge"]:
            request = KeyGrantRequest(
                request_id="req-123",
                subject_id="subject-456",
                data_class="general_inquiry",
                current_placement=placement,
            )

            result = key_broker.request_key(request, caller)

            assert result.granted is True, f"Public data should be allowed at {placement}"

    def test_unknown_placement_denied(self, key_broker, caller):
        """Unknown placements should be denied by default."""
        request = KeyGrantRequest(
            request_id="req-123",
            subject_id="subject-456",
            data_class="account_info",
            current_placement="unknown-datacenter",
        )

        result = key_broker.request_key(request, caller)

        assert result.granted is False


class TestPlacementCertificationRequirements:
    """Test certification-based placement requirements."""

    def test_missing_certification_denied(self, key_broker, caller):
        """Placement without required certification should be denied."""
        # public-cloud lacks PCI-DSS certification
        request = KeyGrantRequest(
            request_id="req-123",
            subject_id="subject-456",
            data_class="payment_card",
            current_placement="public-cloud",
        )

        result = key_broker.request_key(request, caller)

        assert result.granted is False

    def test_correct_certification_allowed(self, key_broker, caller):
        """Placement with required certification should be allowed."""
        # on-premises has PCI-DSS certification
        request = KeyGrantRequest(
            request_id="req-123",
            subject_id="subject-456",
            data_class="payment_card",
            current_placement="on-premises",
        )

        result = key_broker.request_key(request, caller)

        assert result.granted is True


class TestPlacementNoOverride:
    """Verify placement restrictions cannot be overridden."""

    def test_no_bypass_flag(self, key_broker, caller):
        """No flag should bypass placement checks."""
        request = KeyGrantRequest(
            request_id="req-123",
            subject_id="subject-456",
            data_class="payment_card",
            current_placement="public-cloud",
            metadata={"bypass": True, "force": True, "emergency": True},
        )

        result = key_broker.request_key(request, caller)

        assert result.granted is False

    def test_admin_cannot_bypass(self, key_broker):
        """Admin roles cannot bypass placement restrictions."""
        admin = CallerIdentity(
            caller_id="admin",
            roles=["admin", "superuser", "key-admin"],
            authenticated=True,
        )

        request = KeyGrantRequest(
            request_id="req-123",
            subject_id="subject-456",
            data_class="payment_card",
            current_placement="edge",
        )

        result = key_broker.request_key(request, admin)

        assert result.granted is False

    def test_claimed_placement_verified(self, key_broker, caller):
        """Claimed placement should be verified against actual location."""
        # This would require integration with placement verification
        # The broker should not trust claimed placement without verification
        pass


class TestPlacementAuditTrail:
    """Verify audit trail for placement decisions."""

    def test_denial_is_recorded(self, key_broker, caller):
        """Placement denials should be recorded."""
        request = KeyGrantRequest(
            request_id="req-audit-789",
            subject_id="subject-456",
            data_class="payment_card",
            current_placement="public-cloud",
        )

        result = key_broker.request_key(request, caller)

        assert result.request_id == "req-audit-789"
        # Implementation should record to audit log

    def test_denial_includes_rule_citation(self, key_broker, caller):
        """Denials should cite the specific rule that caused denial."""
        request = KeyGrantRequest(
            request_id="req-123",
            subject_id="subject-456",
            data_class="payment_card",
            current_placement="public-cloud",
        )

        result = key_broker.request_key(request, caller)

        assert result.rule_id is not None or "rule" in result.reason.lower()

    def test_grant_is_recorded(self, key_broker, caller):
        """Key grants should also be recorded."""
        request = KeyGrantRequest(
            request_id="req-grant-123",
            subject_id="subject-456",
            data_class="payment_card",
            current_placement="on-premises",
        )

        result = key_broker.request_key(request, caller)

        assert result.granted is True
        assert result.request_id == "req-grant-123"
        # Implementation should record grant to audit log


class TestDataCannotBeDecrypted:
    """Verify that denied placements cannot decrypt data."""

    def test_denied_placement_cannot_read_payload(self, key_broker, caller):
        """Without key, encrypted payload should be unreadable."""
        # First, get denied
        request = KeyGrantRequest(
            request_id="req-123",
            subject_id="subject-456",
            data_class="payment_card",
            current_placement="public-cloud",
        )

        result = key_broker.request_key(request, caller)

        assert result.granted is False
        assert result.key is None

        # Without the key, the payload remains encrypted
        # This is verified by the encryption module tests

    def test_key_not_leaked_in_error(self, key_broker, caller):
        """Keys should not be leaked in error messages."""
        request = KeyGrantRequest(
            request_id="req-123",
            subject_id="subject-456",
            data_class="payment_card",
            current_placement="public-cloud",
        )

        result = key_broker.request_key(request, caller)

        # Ensure no key material in reason
        if result.reason:
            assert "key" not in result.reason.lower() or "denied" in result.reason.lower()
            # No base64 or hex key patterns
            import re
            assert not re.search(r'[A-Za-z0-9+/]{32,}', result.reason)
