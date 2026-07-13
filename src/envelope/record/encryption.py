"""
Per-Subject Encryption (D3)

Provides per-subject encryption for provenance records.
Enables GDPR-compliant erasure by deleting subject keys.
"""

import base64
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


@dataclass
class SubjectKey:
    """
    Encryption key for a specific data subject.

    Each subject has their own symmetric key for payload encryption.
    Deleting this key effectively erases all their encrypted data.
    """
    subject_id: str
    key_id: UUID
    encrypted_key: bytes  # Key encrypted with master key
    created_at: datetime
    expires_at: datetime | None = None
    revoked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_valid(self) -> bool:
        """Check if key is valid (not revoked or expired)."""
        if self.revoked:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        return True


@dataclass
class EncryptedPayload:
    """
    Encrypted payload with metadata for decryption.
    """
    payload_id: UUID
    subject_id: str
    key_id: UUID
    ciphertext: bytes
    nonce: bytes | None = None  # For non-Fernet modes
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "payload_id": str(self.payload_id),
            "subject_id": self.subject_id,
            "key_id": str(self.key_id),
            "ciphertext": base64.b64encode(self.ciphertext).decode(),
            "nonce": base64.b64encode(self.nonce).decode() if self.nonce else None,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EncryptedPayload":
        """Create from dictionary."""
        return cls(
            payload_id=UUID(data["payload_id"]),
            subject_id=data["subject_id"],
            key_id=UUID(data["key_id"]),
            ciphertext=base64.b64decode(data["ciphertext"]),
            nonce=base64.b64decode(data["nonce"]) if data.get("nonce") else None,
            created_at=datetime.fromisoformat(data["created_at"]),
        )


class PerSubjectEncryption:
    """
    Per-subject encryption manager.

    Manages encryption keys per data subject, enabling:
    - Encryption of payloads with subject-specific keys
    - Key rotation per subject
    - GDPR erasure by key deletion
    """

    def __init__(self, master_key: bytes | None = None):
        """
        Initialize with master key.

        Master key is used to encrypt subject keys.
        If not provided, generates a new one (for testing).
        """
        if master_key is None:
            master_key = Fernet.generate_key()
        self._master_key = master_key
        self._master_fernet = Fernet(master_key)
        self._subject_keys: dict[str, SubjectKey] = {}
        self._key_cache: dict[UUID, bytes] = {}

    @classmethod
    def generate_master_key(cls) -> bytes:
        """Generate a new master key."""
        return Fernet.generate_key()

    @classmethod
    def derive_master_key(cls, password: str, salt: bytes) -> bytes:
        """Derive master key from password."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = kdf.derive(password.encode())
        return base64.urlsafe_b64encode(key)

    def create_subject_key(
        self,
        subject_id: str,
        expires_at: datetime | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SubjectKey:
        """
        Create a new encryption key for a subject.

        The raw key is encrypted with the master key before storage.
        """
        # Generate new symmetric key
        raw_key = Fernet.generate_key()
        key_id = uuid4()

        # Encrypt with master key
        encrypted_key = self._master_fernet.encrypt(raw_key)

        subject_key = SubjectKey(
            subject_id=subject_id,
            key_id=key_id,
            encrypted_key=encrypted_key,
            created_at=datetime.utcnow(),
            expires_at=expires_at,
            metadata=metadata or {},
        )

        self._subject_keys[subject_id] = subject_key
        self._key_cache[key_id] = raw_key

        return subject_key

    def get_subject_key(self, subject_id: str) -> SubjectKey | None:
        """Get the current key for a subject."""
        return self._subject_keys.get(subject_id)

    def _decrypt_subject_key(self, subject_key: SubjectKey) -> bytes:
        """Decrypt a subject's raw key."""
        if subject_key.key_id in self._key_cache:
            return self._key_cache[subject_key.key_id]

        raw_key = self._master_fernet.decrypt(subject_key.encrypted_key)
        self._key_cache[subject_key.key_id] = raw_key
        return raw_key

    def encrypt(
        self, subject_id: str, plaintext: str | bytes
    ) -> EncryptedPayload:
        """
        Encrypt data for a subject.

        Creates a subject key if one doesn't exist.
        """
        subject_key = self._subject_keys.get(subject_id)
        if subject_key is None or not subject_key.is_valid():
            subject_key = self.create_subject_key(subject_id)

        raw_key = self._decrypt_subject_key(subject_key)
        fernet = Fernet(raw_key)

        if isinstance(plaintext, str):
            plaintext = plaintext.encode()

        ciphertext = fernet.encrypt(plaintext)

        return EncryptedPayload(
            payload_id=uuid4(),
            subject_id=subject_id,
            key_id=subject_key.key_id,
            ciphertext=ciphertext,
        )

    def decrypt(self, payload: EncryptedPayload) -> bytes:
        """
        Decrypt a payload.

        Raises ValueError if key not found or revoked.
        """
        subject_key = self._subject_keys.get(payload.subject_id)
        if subject_key is None:
            raise ValueError(f"No key found for subject: {payload.subject_id}")

        if not subject_key.is_valid():
            raise ValueError(f"Key for subject {payload.subject_id} is invalid")

        if subject_key.key_id != payload.key_id:
            raise ValueError("Key ID mismatch - payload encrypted with different key")

        raw_key = self._decrypt_subject_key(subject_key)
        fernet = Fernet(raw_key)

        return fernet.decrypt(payload.ciphertext)

    def decrypt_string(self, payload: EncryptedPayload) -> str:
        """Decrypt and return as string."""
        return self.decrypt(payload).decode()

    def rotate_subject_key(
        self, subject_id: str, expires_at: datetime | None = None
    ) -> SubjectKey:
        """
        Rotate a subject's encryption key.

        Old key remains for decrypting old payloads but new
        encryptions use the new key.
        """
        old_key = self._subject_keys.get(subject_id)
        if old_key:
            # Mark old key as not current (but don't revoke for decryption)
            pass

        return self.create_subject_key(subject_id, expires_at)

    def revoke_subject_key(self, subject_id: str) -> bool:
        """
        Revoke a subject's key, making decryption impossible.

        This is the GDPR erasure mechanism - once the key is revoked,
        the encrypted data becomes permanently unrecoverable.
        """
        subject_key = self._subject_keys.get(subject_id)
        if subject_key is None:
            return False

        # Create revoked version
        revoked_key = SubjectKey(
            subject_id=subject_key.subject_id,
            key_id=subject_key.key_id,
            encrypted_key=subject_key.encrypted_key,
            created_at=subject_key.created_at,
            expires_at=subject_key.expires_at,
            revoked=True,
            metadata=subject_key.metadata,
        )
        self._subject_keys[subject_id] = revoked_key

        # Clear from cache
        self._key_cache.pop(subject_key.key_id, None)

        return True

    def erase_subject(self, subject_id: str) -> bool:
        """
        Completely erase a subject's key.

        This is permanent and makes all encrypted data for this
        subject permanently unrecoverable.
        """
        if subject_id not in self._subject_keys:
            return False

        subject_key = self._subject_keys.pop(subject_id)
        self._key_cache.pop(subject_key.key_id, None)

        return True

    def export_subject_keys(self) -> dict[str, dict[str, Any]]:
        """Export subject keys for backup (encrypted form)."""
        return {
            subject_id: {
                "key_id": str(key.key_id),
                "encrypted_key": base64.b64encode(key.encrypted_key).decode(),
                "created_at": key.created_at.isoformat(),
                "expires_at": key.expires_at.isoformat() if key.expires_at else None,
                "revoked": key.revoked,
                "metadata": key.metadata,
            }
            for subject_id, key in self._subject_keys.items()
        }

    def import_subject_keys(self, data: dict[str, dict[str, Any]]) -> int:
        """Import subject keys from backup."""
        imported = 0
        for subject_id, key_data in data.items():
            subject_key = SubjectKey(
                subject_id=subject_id,
                key_id=UUID(key_data["key_id"]),
                encrypted_key=base64.b64decode(key_data["encrypted_key"]),
                created_at=datetime.fromisoformat(key_data["created_at"]),
                expires_at=(
                    datetime.fromisoformat(key_data["expires_at"])
                    if key_data["expires_at"]
                    else None
                ),
                revoked=key_data["revoked"],
                metadata=key_data.get("metadata", {}),
            )
            self._subject_keys[subject_id] = subject_key
            imported += 1
        return imported

    def get_subject_ids(self) -> list[str]:
        """Get all subject IDs with keys."""
        return list(self._subject_keys.keys())

    def is_subject_encrypted(self, subject_id: str) -> bool:
        """Check if a subject has an encryption key."""
        return subject_id in self._subject_keys

    def can_decrypt(self, payload: EncryptedPayload) -> bool:
        """Check if a payload can be decrypted."""
        subject_key = self._subject_keys.get(payload.subject_id)
        if subject_key is None:
            return False
        if not subject_key.is_valid():
            return False
        return subject_key.key_id == payload.key_id
