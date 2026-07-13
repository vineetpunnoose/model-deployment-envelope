"""
Core types and interfaces shared across all envelope modules.

This module defines the fundamental data structures and protocols that enable
clean separation between components while maintaining type safety.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Protocol, TypeAlias
from uuid import UUID, uuid4


# Type aliases for clarity
RequestId: TypeAlias = UUID
CallerId: TypeAlias = str
ModelId: TypeAlias = str
ToolName: TypeAlias = str
DataClassName: TypeAlias = str
PlacementId: TypeAlias = str


class Sensitivity(Enum):
    """Data sensitivity levels for classification."""
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"
    PROHIBITED = "prohibited"


class LifecycleState(Enum):
    """Runtime lifecycle states for model instances."""
    INIT = auto()
    LOADING = auto()
    WARMING = auto()
    READY = auto()
    SERVING = auto()
    DRAINING = auto()
    STOPPED = auto()
    FAILED = auto()


class DecisionVerdict(Enum):
    """Verdict for policy decisions."""
    ALLOW = "allow"
    DENY = "deny"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class PolicyDecision:
    """Result of a policy evaluation."""
    verdict: DecisionVerdict
    rule_id: str
    rule_citation: str
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CallerIdentity:
    """Identity of an API caller."""
    caller_id: CallerId
    roles: frozenset[str]
    attributes: dict[str, Any] = field(default_factory=dict)

    def has_role(self, role: str) -> bool:
        return role in self.roles


@dataclass(frozen=True)
class InferenceRequest:
    """A model inference request."""
    request_id: RequestId
    caller: CallerIdentity
    model_id: ModelId
    prompt: str
    tools_requested: frozenset[ToolName] = frozenset()
    data_classes: frozenset[DataClassName] = frozenset()
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @classmethod
    def create(
        cls,
        caller: CallerIdentity,
        model_id: ModelId,
        prompt: str,
        tools_requested: set[ToolName] | None = None,
        data_classes: set[DataClassName] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "InferenceRequest":
        return cls(
            request_id=uuid4(),
            caller=caller,
            model_id=model_id,
            prompt=prompt,
            tools_requested=frozenset(tools_requested or set()),
            data_classes=frozenset(data_classes or set()),
            metadata=metadata or {},
        )


@dataclass(frozen=True)
class InferenceResponse:
    """A model inference response."""
    request_id: RequestId
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    withheld: bool = False
    escalated: bool = False


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation by the model."""
    tool_name: ToolName
    arguments: dict[str, Any]
    call_id: str = field(default_factory=lambda: str(uuid4()))


@dataclass(frozen=True)
class EscalationRecord:
    """Record of an escalation event."""
    request_id: RequestId
    reason: str
    evidence_refs: list[str]
    context: dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    escalation_id: UUID = field(default_factory=uuid4)


# Protocol definitions for dependency injection and modularity

class Validator(Protocol):
    """Protocol for all validators."""

    def validate(self, data: Any) -> list[str]:
        """Validate data, returning list of error messages (empty if valid)."""
        ...


class Gate(Protocol):
    """Protocol for enforcement gates."""

    def check(self, request: InferenceRequest) -> PolicyDecision:
        """Check if request should be allowed through the gate."""
        ...


class RecordStore(Protocol):
    """Protocol for provenance record storage."""

    async def store(self, record: dict[str, Any]) -> str:
        """Store a record and return its ID."""
        ...

    async def retrieve(self, record_id: str) -> dict[str, Any] | None:
        """Retrieve a record by ID."""
        ...

    async def query(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Query records by filters."""
        ...


class RuntimeBackend(Protocol):
    """Protocol for model runtime backends (Ollama, vLLM, OpenAI, etc.)."""

    async def health(self) -> bool:
        """Check if backend is healthy."""
        ...

    async def info(self) -> dict[str, Any]:
        """Get backend information."""
        ...

    async def infer(self, prompt: str, **kwargs: Any) -> str:
        """Run inference on the backend."""
        ...


class EscalationHandler(Protocol):
    """Protocol for escalation handling."""

    async def escalate(
        self,
        request_id: RequestId,
        context: dict[str, Any],
        reason: str,
        evidence_refs: list[str],
    ) -> EscalationRecord:
        """Handle an escalation event."""
        ...


# Exceptions

class EnvelopeError(Exception):
    """Base exception for all envelope errors."""
    pass


class ValidationError(EnvelopeError):
    """Raised when validation fails."""
    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


class PolicyViolationError(EnvelopeError):
    """Raised when a policy is violated."""
    def __init__(self, decision: PolicyDecision):
        super().__init__(f"Policy violation: {decision.reason}")
        self.decision = decision


class EscalationRequiredError(EnvelopeError):
    """Raised when escalation is required."""
    def __init__(self, reason: str, evidence_refs: list[str] | None = None):
        super().__init__(f"Escalation required: {reason}")
        self.reason = reason
        self.evidence_refs = evidence_refs or []


class PlacementDeniedError(EnvelopeError):
    """Raised when placement is denied."""
    def __init__(self, decision: PolicyDecision):
        super().__init__(f"Placement denied: {decision.reason}")
        self.decision = decision


class ToolNotPermittedError(EnvelopeError):
    """Raised when a tool is not permitted."""
    def __init__(self, tool_name: ToolName, reason: str):
        super().__init__(f"Tool '{tool_name}' not permitted: {reason}")
        self.tool_name = tool_name
        self.reason = reason
