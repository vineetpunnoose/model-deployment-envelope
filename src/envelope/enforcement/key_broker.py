"""
Key Broker (C5)

Manages encryption key grants based on placement and data class.
Denies keys at forbidden placements to enforce data residency.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from envelope.types import (
    CallerIdentity,
    PolicyDecision,
    DecisionVerdict,
    PlacementDeniedError,
)
from envelope.declaration.manifest import ModelManifest
from envelope.declaration.taxonomy import DataClassTaxonomy
from envelope.declaration.placement import PlacementPolicy
from envelope.record.encryption import PerSubjectEncryption


@dataclass
class KeyGrant:
    """
    A grant for access to encryption keys.

    Grants are time-limited and placement-specific.
    """
    grant_id: UUID
    subject_id: str
    placement_id: str
    caller_id: str
    data_classes: frozenset[str]
    granted_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    revoked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_valid(self) -> bool:
        """Check if grant is currently valid."""
        if self.revoked:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "grant_id": str(self.grant_id),
            "subject_id": self.subject_id,
            "placement_id": self.placement_id,
            "caller_id": self.caller_id,
            "data_classes": list(self.data_classes),
            "granted_at": self.granted_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "revoked": self.revoked,
            "metadata": self.metadata,
        }


class KeyBroker:
    """
    Key broker for managing encryption key access.

    Controls access to encryption keys based on:
    - Data class permissions
    - Placement constraints
    - Caller authorization

    Keys are denied at forbidden placements, enforcing
    data residency requirements at the cryptographic level.
    """

    def __init__(
        self,
        manifest: ModelManifest,
        taxonomy: DataClassTaxonomy,
        placement_policy: PlacementPolicy,
        encryption: PerSubjectEncryption | None = None,
        default_grant_ttl: timedelta = timedelta(hours=1),
    ):
        self._manifest = manifest
        self._taxonomy = taxonomy
        self._placement_policy = placement_policy
        self._encryption = encryption or PerSubjectEncryption()
        self._default_ttl = default_grant_ttl
        self._grants: dict[UUID, KeyGrant] = {}
        self._active_grants_by_subject: dict[str, list[UUID]] = {}

    @property
    def manifest(self) -> ModelManifest:
        return self._manifest

    @property
    def encryption(self) -> PerSubjectEncryption:
        return self._encryption

    def request_grant(
        self,
        subject_id: str,
        placement_id: str,
        caller: CallerIdentity,
        data_classes: set[str],
        ttl: timedelta | None = None,
    ) -> tuple[KeyGrant | None, PolicyDecision]:
        """
        Request a key grant for a subject at a placement.

        Returns (grant, decision) tuple. Grant is None if denied.
        """
        # Check 1: Caller authorization
        caller_decision = self._check_caller(caller)
        if caller_decision.verdict != DecisionVerdict.ALLOW:
            return None, caller_decision

        # Check 2: Data class authorization
        dc_decision = self._check_data_classes(data_classes)
        if dc_decision.verdict != DecisionVerdict.ALLOW:
            return None, dc_decision

        # Check 3: Placement policy for each data class
        for dc in data_classes:
            placement_decision = self._placement_policy.evaluate(
                placement_id,
                data_class=dc,
                taxonomy=self._taxonomy,
                caller=caller,
            )
            if placement_decision.verdict != DecisionVerdict.ALLOW:
                return None, PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="placement_denied_for_data_class",
                    rule_citation=placement_decision.rule_citation,
                    reason=f"Placement denied for data class '{dc}': {placement_decision.reason}",
                )

        # Check 4: Verify placement exists
        placement = self._placement_policy.get_placement(placement_id)
        if placement is None:
            return None, PolicyDecision(
                verdict=DecisionVerdict.DENY,
                rule_id="placement_not_found",
                rule_citation="Placement not registered",
                reason=f"Placement '{placement_id}' not found",
            )

        # Create grant
        grant = KeyGrant(
            grant_id=uuid4(),
            subject_id=subject_id,
            placement_id=placement_id,
            caller_id=caller.caller_id,
            data_classes=frozenset(data_classes),
            expires_at=datetime.utcnow() + (ttl or self._default_ttl),
        )

        self._grants[grant.grant_id] = grant

        # Track active grants by subject
        if subject_id not in self._active_grants_by_subject:
            self._active_grants_by_subject[subject_id] = []
        self._active_grants_by_subject[subject_id].append(grant.grant_id)

        return grant, PolicyDecision(
            verdict=DecisionVerdict.ALLOW,
            rule_id="grant_approved",
            rule_citation="Key grant approved",
            reason="Grant approved for all data classes at placement",
        )

    def _check_caller(self, caller: CallerIdentity) -> PolicyDecision:
        """Check if caller is authorized for key access."""
        if self._manifest.spec.callers.allowed_roles:
            has_role = any(
                self._manifest.allows_caller_role(role)
                for role in caller.roles
            )
            if not has_role:
                return PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="caller_role_denied",
                    rule_citation="Caller lacks required role",
                    reason="Caller not authorized for key access",
                )

        return PolicyDecision(
            verdict=DecisionVerdict.ALLOW,
            rule_id="caller_authorized",
            rule_citation="Caller authorized",
            reason="Caller authorized",
        )

    def _check_data_classes(
        self, data_classes: set[str]
    ) -> PolicyDecision:
        """Check if data classes are allowed."""
        allowed = self._manifest.spec.data_classes.allowed

        for dc in data_classes:
            if dc not in allowed:
                return PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="data_class_not_allowed",
                    rule_citation=f"Data class '{dc}' not in manifest",
                    reason=f"Data class '{dc}' not allowed by manifest",
                )

        return PolicyDecision(
            verdict=DecisionVerdict.ALLOW,
            rule_id="data_classes_allowed",
            rule_citation="All data classes allowed",
            reason="Data classes authorized",
        )

    def get_grant(self, grant_id: UUID) -> KeyGrant | None:
        """Get a grant by ID."""
        return self._grants.get(grant_id)

    def validate_grant(
        self,
        grant_id: UUID,
        placement_id: str,
        data_class: str,
    ) -> bool:
        """
        Validate a grant for a specific operation.

        Checks that grant is valid, placement matches, and
        data class is covered.
        """
        grant = self._grants.get(grant_id)
        if grant is None:
            return False

        if not grant.is_valid():
            return False

        if grant.placement_id != placement_id:
            return False

        if data_class not in grant.data_classes:
            return False

        return True

    def revoke_grant(self, grant_id: UUID) -> bool:
        """Revoke a grant."""
        grant = self._grants.get(grant_id)
        if grant is None:
            return False

        # Create revoked version
        revoked = KeyGrant(
            grant_id=grant.grant_id,
            subject_id=grant.subject_id,
            placement_id=grant.placement_id,
            caller_id=grant.caller_id,
            data_classes=grant.data_classes,
            granted_at=grant.granted_at,
            expires_at=grant.expires_at,
            revoked=True,
            metadata=grant.metadata,
        )
        self._grants[grant_id] = revoked

        return True

    def revoke_all_for_subject(self, subject_id: str) -> int:
        """Revoke all grants for a subject. Returns count revoked."""
        grant_ids = self._active_grants_by_subject.get(subject_id, [])
        revoked = 0

        for grant_id in grant_ids:
            if self.revoke_grant(grant_id):
                revoked += 1

        return revoked

    def get_encryption_key(
        self,
        grant_id: UUID,
        placement_id: str,
    ) -> bytes | None:
        """
        Get encryption key if grant is valid.

        This is the enforcement point - keys are denied if
        the grant is invalid or placement doesn't match.
        """
        grant = self._grants.get(grant_id)
        if grant is None:
            return None

        if not grant.is_valid():
            return None

        if grant.placement_id != placement_id:
            # Key denied at this placement!
            return None

        # Get subject's key
        subject_key = self._encryption.get_subject_key(grant.subject_id)
        if subject_key is None:
            # Create key if doesn't exist
            self._encryption.create_subject_key(grant.subject_id)
            subject_key = self._encryption.get_subject_key(grant.subject_id)

        if subject_key is None or not subject_key.is_valid():
            return None

        # Decrypt and return the raw key
        return self._encryption._decrypt_subject_key(subject_key)

    def encrypt_for_subject(
        self,
        grant_id: UUID,
        placement_id: str,
        data: str | bytes,
    ) -> bytes | None:
        """
        Encrypt data for a subject if grant is valid.

        Returns encrypted data or None if denied.
        """
        grant = self._grants.get(grant_id)
        if grant is None or not grant.is_valid():
            return None

        if grant.placement_id != placement_id:
            return None

        payload = self._encryption.encrypt(grant.subject_id, data)
        return payload.ciphertext

    def decrypt_for_subject(
        self,
        grant_id: UUID,
        placement_id: str,
        ciphertext: bytes,
    ) -> bytes | None:
        """
        Decrypt data for a subject if grant is valid.

        Returns decrypted data or None if denied.
        """
        grant = self._grants.get(grant_id)
        if grant is None or not grant.is_valid():
            return None

        if grant.placement_id != placement_id:
            # Key denied at forbidden placement!
            return None

        subject_key = self._encryption.get_subject_key(grant.subject_id)
        if subject_key is None or not subject_key.is_valid():
            return None

        from envelope.record.encryption import EncryptedPayload

        payload = EncryptedPayload(
            payload_id=uuid4(),
            subject_id=grant.subject_id,
            key_id=subject_key.key_id,
            ciphertext=ciphertext,
        )

        try:
            return self._encryption.decrypt(payload)
        except Exception:
            return None

    def cleanup_expired(self) -> int:
        """Remove expired grants. Returns count removed."""
        expired_ids: list[UUID] = []

        for grant_id, grant in self._grants.items():
            if grant.expires_at and datetime.utcnow() > grant.expires_at:
                expired_ids.append(grant_id)

        for grant_id in expired_ids:
            del self._grants[grant_id]

        return len(expired_ids)

    def get_active_grants(
        self,
        subject_id: str | None = None,
        placement_id: str | None = None,
    ) -> list[KeyGrant]:
        """Get active (valid) grants."""
        grants: list[KeyGrant] = []

        for grant in self._grants.values():
            if not grant.is_valid():
                continue

            if subject_id and grant.subject_id != subject_id:
                continue

            if placement_id and grant.placement_id != placement_id:
                continue

            grants.append(grant)

        return grants

    def get_grant_stats(self) -> dict[str, Any]:
        """Get grant statistics."""
        total = len(self._grants)
        active = sum(1 for g in self._grants.values() if g.is_valid())
        revoked = sum(1 for g in self._grants.values() if g.revoked)
        expired = total - active - revoked

        return {
            "total": total,
            "active": active,
            "revoked": revoked,
            "expired": expired,
            "subjects": len(self._active_grants_by_subject),
        }
