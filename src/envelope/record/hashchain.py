"""
Hash Chain System (D2)

Provides tamper-evident hash chain for provenance records.
Each record carries the hash of its predecessor, enabling
integrity verification of the entire chain.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from envelope.record.provenance import ProvenanceRecord, ProvenanceStore


class ChainIntegrityError(Exception):
    """Raised when hash chain integrity verification fails."""

    def __init__(
        self,
        message: str,
        record_id: UUID | None = None,
        expected_hash: str | None = None,
        actual_hash: str | None = None,
    ):
        super().__init__(message)
        self.record_id = record_id
        self.expected_hash = expected_hash
        self.actual_hash = actual_hash


@dataclass(frozen=True)
class ChainEntry:
    """
    An entry in the hash chain.

    Contains the record ID, content hash, and link to previous entry.
    """
    record_id: UUID
    content_hash: str
    previous_hash: str | None
    chain_hash: str
    timestamp: datetime
    sequence: int

    def verify_chain_hash(self) -> bool:
        """Verify that chain_hash is correctly computed."""
        expected = self._compute_chain_hash()
        return expected == self.chain_hash

    def _compute_chain_hash(self) -> str:
        """Compute the chain hash from content and previous hash."""
        data = {
            "content_hash": self.content_hash,
            "previous_hash": self.previous_hash or "",
            "sequence": self.sequence,
        }
        content = json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()


class HashChain:
    """
    Tamper-evident hash chain for provenance records.

    Each record's chain_hash is computed from:
    - The record's content hash
    - The previous record's chain hash
    - The sequence number

    This creates an unbroken chain where any tampering
    is detectable through hash verification.
    """

    GENESIS_HASH = "0" * 64  # Genesis block hash

    def __init__(self, store: ProvenanceStore):
        self._store = store
        self._head: ChainEntry | None = None
        self._sequence = 0

    @property
    def head(self) -> ChainEntry | None:
        """Get the current chain head."""
        return self._head

    @property
    def sequence(self) -> int:
        """Get current sequence number."""
        return self._sequence

    async def initialize(self) -> None:
        """Initialize chain state from store."""
        # Get the latest record to determine chain state
        if isinstance(self._store, ProvenanceStore):
            records = await self._store.query(limit=1)
            if records:
                latest = records[0]
                self._sequence = latest.metadata.get("sequence", 0)
                if latest.chain_hash:
                    self._head = ChainEntry(
                        record_id=latest.request_id,
                        content_hash=latest.compute_hash(),
                        previous_hash=latest.previous_hash,
                        chain_hash=latest.chain_hash,
                        timestamp=latest.timestamp,
                        sequence=self._sequence,
                    )

    def compute_chain_hash(
        self, content_hash: str, previous_hash: str | None, sequence: int
    ) -> str:
        """Compute the chain hash for a new entry."""
        data = {
            "content_hash": content_hash,
            "previous_hash": previous_hash or "",
            "sequence": sequence,
        }
        content = json.dumps(data, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()

    async def append(self, record: ProvenanceRecord) -> ChainEntry:
        """
        Append a record to the chain.

        Computes content hash and chain hash, then stores the record.
        Returns the new chain entry.
        """
        content_hash = record.compute_hash()
        previous_hash = self._head.chain_hash if self._head else self.GENESIS_HASH
        self._sequence += 1

        chain_hash = self.compute_chain_hash(
            content_hash, previous_hash, self._sequence
        )

        # Update record with chain information
        record.chain_hash = chain_hash
        record.previous_hash = previous_hash
        record.metadata["sequence"] = self._sequence

        # Store the record
        await self._store.store(record)

        # Update head
        entry = ChainEntry(
            record_id=record.request_id,
            content_hash=content_hash,
            previous_hash=previous_hash,
            chain_hash=chain_hash,
            timestamp=record.timestamp,
            sequence=self._sequence,
        )
        self._head = entry

        return entry

    async def verify_entry(self, record: ProvenanceRecord) -> bool:
        """
        Verify a single entry's chain hash.

        Returns True if the chain hash is valid.
        """
        if not record.chain_hash:
            return False

        content_hash = record.compute_hash()
        sequence = record.metadata.get("sequence", 0)
        expected_hash = self.compute_chain_hash(
            content_hash, record.previous_hash, sequence
        )

        return expected_hash == record.chain_hash

    async def verify_chain(
        self,
        start_id: UUID | None = None,
        count: int = 100,
    ) -> tuple[bool, list[ChainEntry], ChainIntegrityError | None]:
        """
        Verify chain integrity from a starting point.

        Returns:
            - valid: True if chain is valid
            - entries: List of verified chain entries
            - error: ChainIntegrityError if verification failed
        """
        entries: list[ChainEntry] = []
        error: ChainIntegrityError | None = None

        # Get records to verify
        if start_id:
            records = await self._store.get_chain(start_id, count)
        else:
            records = await self._store.query(limit=count)
            records = sorted(records, key=lambda r: r.metadata.get("sequence", 0))

        if not records:
            return True, entries, None

        previous_hash: str | None = None

        for record in records:
            # Verify content hash
            content_hash = record.compute_hash()
            sequence = record.metadata.get("sequence", 0)

            # Verify chain hash
            expected_chain_hash = self.compute_chain_hash(
                content_hash, record.previous_hash, sequence
            )

            if record.chain_hash != expected_chain_hash:
                error = ChainIntegrityError(
                    f"Chain hash mismatch at record {record.request_id}",
                    record_id=record.request_id,
                    expected_hash=expected_chain_hash,
                    actual_hash=record.chain_hash,
                )
                return False, entries, error

            # Verify chain continuity
            if previous_hash is not None and record.previous_hash != previous_hash:
                error = ChainIntegrityError(
                    f"Chain continuity broken at record {record.request_id}",
                    record_id=record.request_id,
                    expected_hash=previous_hash,
                    actual_hash=record.previous_hash,
                )
                return False, entries, error

            entry = ChainEntry(
                record_id=record.request_id,
                content_hash=content_hash,
                previous_hash=record.previous_hash,
                chain_hash=record.chain_hash,
                timestamp=record.timestamp,
                sequence=sequence,
            )
            entries.append(entry)
            previous_hash = record.chain_hash

        return True, entries, None

    async def find_tampering(
        self, count: int = 1000
    ) -> list[tuple[ProvenanceRecord, str]]:
        """
        Scan for tampered records.

        Returns list of (record, reason) tuples for tampered records.
        """
        tampered: list[tuple[ProvenanceRecord, str]] = []

        records = await self._store.query(limit=count)
        records = sorted(records, key=lambda r: r.metadata.get("sequence", 0))

        previous_hash: str | None = None

        for record in records:
            # Check content hash
            content_hash = record.compute_hash()
            sequence = record.metadata.get("sequence", 0)
            expected_chain_hash = self.compute_chain_hash(
                content_hash, record.previous_hash, sequence
            )

            if record.chain_hash != expected_chain_hash:
                tampered.append((record, "Chain hash mismatch - content modified"))
                continue

            # Check chain continuity
            if previous_hash is not None and record.previous_hash != previous_hash:
                tampered.append((record, "Chain continuity broken - record inserted/removed"))

            previous_hash = record.chain_hash

        return tampered

    async def get_entry_at_sequence(self, sequence: int) -> ChainEntry | None:
        """Get chain entry at a specific sequence number."""
        records = await self._store.query(limit=1000)

        for record in records:
            if record.metadata.get("sequence") == sequence:
                return ChainEntry(
                    record_id=record.request_id,
                    content_hash=record.compute_hash(),
                    previous_hash=record.previous_hash,
                    chain_hash=record.chain_hash or "",
                    timestamp=record.timestamp,
                    sequence=sequence,
                )

        return None

    def get_merkle_root(self, entries: list[ChainEntry]) -> str:
        """
        Compute Merkle root of a set of entries.

        Useful for compact verification of large chains.
        """
        if not entries:
            return self.GENESIS_HASH

        hashes = [e.chain_hash for e in entries]

        while len(hashes) > 1:
            if len(hashes) % 2 == 1:
                hashes.append(hashes[-1])

            new_hashes = []
            for i in range(0, len(hashes), 2):
                combined = hashes[i] + hashes[i + 1]
                new_hash = hashlib.sha256(combined.encode()).hexdigest()
                new_hashes.append(new_hash)

            hashes = new_hashes

        return hashes[0]
