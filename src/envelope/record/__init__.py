"""
Record System (Section D)

Provides structured provenance records with integrity guarantees:
- ProvenanceRecord (D1): Structured provenance records for each request
- HashChain (D2): Hash chain with tamper detection
- PerSubjectEncryption (D3): Per-subject encryption with erasure support
- ReproductionEngine (D4): Request replay capability

All records are immutable and form a tamper-evident chain.
"""

from envelope.record.provenance import (
    ProvenanceRecord,
    ProvenanceStore,
    InMemoryProvenanceStore,
    SQLiteProvenanceStore,
)
from envelope.record.hashchain import HashChain, ChainEntry, ChainIntegrityError
from envelope.record.encryption import (
    PerSubjectEncryption,
    SubjectKey,
    EncryptedPayload,
)
from envelope.record.reproduction import ReproductionEngine, ReplayResult

__all__ = [
    "ProvenanceRecord",
    "ProvenanceStore",
    "InMemoryProvenanceStore",
    "SQLiteProvenanceStore",
    "HashChain",
    "ChainEntry",
    "ChainIntegrityError",
    "PerSubjectEncryption",
    "SubjectKey",
    "EncryptedPayload",
    "ReproductionEngine",
    "ReplayResult",
]
