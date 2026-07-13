"""
Provenance Record System (D1)

Structured provenance records for audit and reproduction.
Records capture complete context of each inference request.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


@dataclass(frozen=True)
class ToolInvocation:
    """Record of a single tool invocation."""
    tool_name: str
    arguments: dict[str, Any]
    result: Any
    duration_ms: float
    success: bool
    error: str | None = None


@dataclass
class ProvenanceRecord:
    """
    Complete provenance record for an inference request.

    Captures all context needed to reproduce the request and
    audit the decision process.
    """
    request_id: UUID
    timestamp: datetime
    caller_id: str
    caller_roles: list[str]
    model_id: str
    model_version: str
    placement_id: str
    prompt: str
    prompt_hash: str
    response: str
    response_hash: str
    tool_invocations: list[ToolInvocation] = field(default_factory=list)
    data_classes: list[str] = field(default_factory=list)
    escalated: bool = False
    escalation_reason: str | None = None
    withheld: bool = False
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    chain_hash: str | None = None
    previous_hash: str | None = None

    @classmethod
    def create(
        cls,
        caller_id: str,
        caller_roles: list[str],
        model_id: str,
        model_version: str,
        placement_id: str,
        prompt: str,
        response: str,
        **kwargs: Any,
    ) -> "ProvenanceRecord":
        """Create a new provenance record with auto-generated fields."""
        import hashlib

        return cls(
            request_id=uuid4(),
            timestamp=datetime.utcnow(),
            caller_id=caller_id,
            caller_roles=caller_roles,
            model_id=model_id,
            model_version=model_version,
            placement_id=placement_id,
            prompt=prompt,
            prompt_hash=hashlib.sha256(prompt.encode()).hexdigest(),
            response=response,
            response_hash=hashlib.sha256(response.encode()).hexdigest(),
            **kwargs,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["request_id"] = str(self.request_id)
        data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProvenanceRecord":
        """Create from dictionary."""
        data = data.copy()
        data["request_id"] = UUID(data["request_id"])
        data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        data["tool_invocations"] = [
            ToolInvocation(**t) for t in data.get("tool_invocations", [])
        ]
        return cls(**data)

    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_json(cls, json_str: str) -> "ProvenanceRecord":
        """Create from JSON string."""
        return cls.from_dict(json.loads(json_str))

    def compute_hash(self) -> str:
        """Compute hash of record content (excluding chain hashes)."""
        import hashlib

        content = {
            "request_id": str(self.request_id),
            "timestamp": self.timestamp.isoformat(),
            "caller_id": self.caller_id,
            "caller_roles": sorted(self.caller_roles),
            "model_id": self.model_id,
            "model_version": self.model_version,
            "placement_id": self.placement_id,
            "prompt_hash": self.prompt_hash,
            "response_hash": self.response_hash,
            "data_classes": sorted(self.data_classes),
            "escalated": self.escalated,
            "withheld": self.withheld,
        }
        content_str = json.dumps(content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()


class ProvenanceStore(ABC):
    """Abstract base for provenance storage backends."""

    @abstractmethod
    async def store(self, record: ProvenanceRecord) -> str:
        """Store a record and return its ID."""
        pass

    @abstractmethod
    async def retrieve(self, request_id: UUID) -> ProvenanceRecord | None:
        """Retrieve a record by request ID."""
        pass

    @abstractmethod
    async def query(
        self,
        caller_id: str | None = None,
        model_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[ProvenanceRecord]:
        """Query records by filters."""
        pass

    @abstractmethod
    async def get_chain(
        self, start_id: UUID, count: int = 10
    ) -> list[ProvenanceRecord]:
        """Get a chain of records starting from a given ID."""
        pass


class InMemoryProvenanceStore(ProvenanceStore):
    """In-memory provenance store for testing."""

    def __init__(self):
        self._records: dict[UUID, ProvenanceRecord] = {}
        self._chain: list[UUID] = []

    async def store(self, record: ProvenanceRecord) -> str:
        """Store a record."""
        self._records[record.request_id] = record
        self._chain.append(record.request_id)
        return str(record.request_id)

    async def retrieve(self, request_id: UUID) -> ProvenanceRecord | None:
        """Retrieve a record by ID."""
        return self._records.get(request_id)

    async def query(
        self,
        caller_id: str | None = None,
        model_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[ProvenanceRecord]:
        """Query records by filters."""
        results: list[ProvenanceRecord] = []

        for record in self._records.values():
            if caller_id and record.caller_id != caller_id:
                continue
            if model_id and record.model_id != model_id:
                continue
            if start_time and record.timestamp < start_time:
                continue
            if end_time and record.timestamp > end_time:
                continue
            results.append(record)

            if len(results) >= limit:
                break

        return sorted(results, key=lambda r: r.timestamp, reverse=True)

    async def get_chain(
        self, start_id: UUID, count: int = 10
    ) -> list[ProvenanceRecord]:
        """Get chain of records."""
        try:
            start_idx = self._chain.index(start_id)
        except ValueError:
            return []

        end_idx = min(start_idx + count, len(self._chain))
        chain_ids = self._chain[start_idx:end_idx]

        return [self._records[rid] for rid in chain_ids]

    def clear(self) -> None:
        """Clear all records."""
        self._records.clear()
        self._chain.clear()


class SQLiteProvenanceStore(ProvenanceStore):
    """SQLite-based provenance store for persistence."""

    def __init__(self, db_path: Path | str):
        self._db_path = Path(db_path)
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Ensure database is initialized."""
        if self._initialized:
            return

        import aiosqlite

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS provenance (
                    request_id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    caller_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    placement_id TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    chain_hash TEXT,
                    previous_hash TEXT
                )
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp
                ON provenance(timestamp DESC)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_caller
                ON provenance(caller_id)
            """)
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_model
                ON provenance(model_id)
            """)
            await db.commit()

        self._initialized = True

    async def store(self, record: ProvenanceRecord) -> str:
        """Store a record."""
        import aiosqlite

        await self._ensure_initialized()

        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                INSERT INTO provenance
                (request_id, timestamp, caller_id, model_id, placement_id,
                 data_json, chain_hash, previous_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(record.request_id),
                    record.timestamp.isoformat(),
                    record.caller_id,
                    record.model_id,
                    record.placement_id,
                    record.to_json(),
                    record.chain_hash,
                    record.previous_hash,
                ),
            )
            await db.commit()

        return str(record.request_id)

    async def retrieve(self, request_id: UUID) -> ProvenanceRecord | None:
        """Retrieve a record by ID."""
        import aiosqlite

        await self._ensure_initialized()

        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT data_json FROM provenance WHERE request_id = ?",
                (str(request_id),),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return ProvenanceRecord.from_json(row[0])
        return None

    async def query(
        self,
        caller_id: str | None = None,
        model_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
    ) -> list[ProvenanceRecord]:
        """Query records by filters."""
        import aiosqlite

        await self._ensure_initialized()

        conditions: list[str] = []
        params: list[Any] = []

        if caller_id:
            conditions.append("caller_id = ?")
            params.append(caller_id)
        if model_id:
            conditions.append("model_id = ?")
            params.append(model_id)
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time.isoformat())
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time.isoformat())

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        query = f"""
            SELECT data_json FROM provenance
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
        """
        params.append(limit)

        results: list[ProvenanceRecord] = []
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(query, params) as cursor:
                async for row in cursor:
                    results.append(ProvenanceRecord.from_json(row[0]))

        return results

    async def get_chain(
        self, start_id: UUID, count: int = 10
    ) -> list[ProvenanceRecord]:
        """Get chain of records starting from a given ID."""
        import aiosqlite

        await self._ensure_initialized()

        results: list[ProvenanceRecord] = []
        current_id = str(start_id)

        async with aiosqlite.connect(self._db_path) as db:
            for _ in range(count):
                async with db.execute(
                    "SELECT data_json FROM provenance WHERE request_id = ?",
                    (current_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        break

                    record = ProvenanceRecord.from_json(row[0])
                    results.append(record)

                    # Follow chain
                    async with db.execute(
                        """
                        SELECT request_id FROM provenance
                        WHERE previous_hash = ?
                        ORDER BY timestamp ASC
                        LIMIT 1
                        """,
                        (record.chain_hash,),
                    ) as next_cursor:
                        next_row = await next_cursor.fetchone()
                        if not next_row:
                            break
                        current_id = next_row[0]

        return results

    async def get_latest(self) -> ProvenanceRecord | None:
        """Get the most recent record."""
        import aiosqlite

        await self._ensure_initialized()

        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                "SELECT data_json FROM provenance ORDER BY timestamp DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return ProvenanceRecord.from_json(row[0])
        return None
