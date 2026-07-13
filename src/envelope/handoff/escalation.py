"""
Escalation Interface (F1)

Provides the standard interface for escalation handling.
All escalation handlers must implement this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4


class CaseStatus(Enum):
    """Status of an escalation case."""
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class CasePriority(Enum):
    """Priority level for escalation cases."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class EscalationCase:
    """
    An escalation case for human review.

    Contains all context needed for a human reviewer to
    understand and resolve the escalated issue.
    """
    case_id: UUID
    request_id: UUID
    reason: str
    evidence_refs: list[str]
    status: CaseStatus = CaseStatus.PENDING
    priority: CasePriority = CasePriority.MEDIUM
    context: dict[str, Any] = field(default_factory=dict)
    assignee: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None
    resolution: str | None = None
    notes: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        request_id: UUID,
        reason: str,
        evidence_refs: list[str],
        context: dict[str, Any] | None = None,
        priority: CasePriority = CasePriority.MEDIUM,
    ) -> "EscalationCase":
        """Create a new escalation case."""
        return cls(
            case_id=uuid4(),
            request_id=request_id,
            reason=reason,
            evidence_refs=evidence_refs,
            context=context or {},
            priority=priority,
        )

    def add_note(
        self, author: str, content: str, note_type: str = "comment"
    ) -> None:
        """Add a note to the case."""
        self.notes.append({
            "author": author,
            "content": content,
            "type": note_type,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.updated_at = datetime.utcnow()

    def assign(self, assignee: str) -> None:
        """Assign the case to a reviewer."""
        self.assignee = assignee
        self.status = CaseStatus.ASSIGNED
        self.updated_at = datetime.utcnow()

    def start_progress(self) -> None:
        """Mark case as in progress."""
        self.status = CaseStatus.IN_PROGRESS
        self.updated_at = datetime.utcnow()

    def resolve(self, resolution: str) -> None:
        """Resolve the case."""
        self.resolution = resolution
        self.status = CaseStatus.RESOLVED
        self.resolved_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def close(self) -> None:
        """Close the case."""
        self.status = CaseStatus.CLOSED
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "case_id": str(self.case_id),
            "request_id": str(self.request_id),
            "reason": self.reason,
            "evidence_refs": self.evidence_refs,
            "status": self.status.value,
            "priority": self.priority.value,
            "context": self.context,
            "assignee": self.assignee,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution": self.resolution,
            "notes": self.notes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EscalationCase":
        """Create from dictionary."""
        return cls(
            case_id=UUID(data["case_id"]),
            request_id=UUID(data["request_id"]),
            reason=data["reason"],
            evidence_refs=data["evidence_refs"],
            status=CaseStatus(data["status"]),
            priority=CasePriority(data["priority"]),
            context=data.get("context", {}),
            assignee=data.get("assignee"),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            resolved_at=(
                datetime.fromisoformat(data["resolved_at"])
                if data.get("resolved_at")
                else None
            ),
            resolution=data.get("resolution"),
            notes=data.get("notes", []),
            metadata=data.get("metadata", {}),
        )


class EscalationInterface(ABC):
    """
    Abstract interface for escalation handlers.

    All escalation handlers (webhook, reference sink, case systems)
    must implement this interface.
    """

    @abstractmethod
    async def escalate(
        self,
        request_id: UUID,
        context: dict[str, Any],
        reason: str,
        evidence_refs: list[str],
    ) -> EscalationCase:
        """
        Handle an escalation event.

        Args:
            request_id: ID of the original request
            context: Context information for the escalation
            reason: Human-readable reason for escalation
            evidence_refs: References to evidence supporting escalation

        Returns:
            EscalationCase created for this escalation
        """
        pass

    @abstractmethod
    async def get_case(self, case_id: UUID) -> EscalationCase | None:
        """Get a case by ID."""
        pass

    @abstractmethod
    async def update_case(
        self,
        case_id: UUID,
        status: CaseStatus | None = None,
        assignee: str | None = None,
        notes: str | None = None,
    ) -> EscalationCase | None:
        """Update a case."""
        pass

    @abstractmethod
    async def list_cases(
        self,
        status: CaseStatus | None = None,
        limit: int = 100,
    ) -> list[EscalationCase]:
        """List cases with optional filtering."""
        pass

    @abstractmethod
    async def resolve_case(
        self,
        case_id: UUID,
        resolution: str,
    ) -> EscalationCase | None:
        """Resolve a case."""
        pass


class InMemoryEscalationHandler(EscalationInterface):
    """In-memory implementation for testing."""

    def __init__(self):
        self._cases: dict[UUID, EscalationCase] = {}

    async def escalate(
        self,
        request_id: UUID,
        context: dict[str, Any],
        reason: str,
        evidence_refs: list[str],
    ) -> EscalationCase:
        """Handle escalation."""
        case = EscalationCase.create(
            request_id=request_id,
            reason=reason,
            evidence_refs=evidence_refs,
            context=context,
        )
        self._cases[case.case_id] = case
        return case

    async def get_case(self, case_id: UUID) -> EscalationCase | None:
        """Get case by ID."""
        return self._cases.get(case_id)

    async def update_case(
        self,
        case_id: UUID,
        status: CaseStatus | None = None,
        assignee: str | None = None,
        notes: str | None = None,
    ) -> EscalationCase | None:
        """Update case."""
        case = self._cases.get(case_id)
        if case is None:
            return None

        if status:
            case.status = status
        if assignee:
            case.assign(assignee)
        if notes:
            case.add_note("system", notes)

        case.updated_at = datetime.utcnow()
        return case

    async def list_cases(
        self,
        status: CaseStatus | None = None,
        limit: int = 100,
    ) -> list[EscalationCase]:
        """List cases."""
        cases = list(self._cases.values())

        if status:
            cases = [c for c in cases if c.status == status]

        return sorted(cases, key=lambda c: c.created_at, reverse=True)[:limit]

    async def resolve_case(
        self,
        case_id: UUID,
        resolution: str,
    ) -> EscalationCase | None:
        """Resolve case."""
        case = self._cases.get(case_id)
        if case is None:
            return None

        case.resolve(resolution)
        return case

    def clear(self) -> int:
        """Clear all cases. Returns count cleared."""
        count = len(self._cases)
        self._cases.clear()
        return count
