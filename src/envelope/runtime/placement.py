"""
Resource Placement (E4)

Static resource allocation for model deployments.
Manages resource assignment and placement constraints.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ResourceType(Enum):
    """Types of compute resources."""
    CPU = "cpu"
    MEMORY = "memory"
    GPU = "gpu"
    GPU_MEMORY = "gpu_memory"
    STORAGE = "storage"
    NETWORK = "network"


@dataclass
class ResourceRequirement:
    """Resource requirement specification."""
    resource_type: ResourceType
    minimum: float
    requested: float
    maximum: float | None = None
    unit: str = ""

    def is_satisfied_by(self, available: float) -> bool:
        """Check if available resources satisfy the requirement."""
        return available >= self.minimum

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.resource_type.value,
            "minimum": self.minimum,
            "requested": self.requested,
            "maximum": self.maximum,
            "unit": self.unit,
        }


@dataclass
class ResourceAllocation:
    """
    Resource allocation for a model deployment.

    Tracks allocated resources at a specific placement.
    """
    allocation_id: str
    placement_id: str
    model_id: str
    resources: dict[ResourceType, float] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_resource(self, resource_type: ResourceType) -> float:
        """Get allocated amount for a resource type."""
        return self.resources.get(resource_type, 0.0)

    def is_expired(self) -> bool:
        """Check if allocation has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocation_id": self.allocation_id,
            "placement_id": self.placement_id,
            "model_id": self.model_id,
            "resources": {
                rt.value: amount for rt, amount in self.resources.items()
            },
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata,
        }


@dataclass
class PlacementCapacity:
    """Capacity of a placement location."""
    placement_id: str
    total: dict[ResourceType, float] = field(default_factory=dict)
    allocated: dict[ResourceType, float] = field(default_factory=dict)
    reserved: dict[ResourceType, float] = field(default_factory=dict)

    def available(self, resource_type: ResourceType) -> float:
        """Get available capacity for a resource type."""
        total = self.total.get(resource_type, 0.0)
        alloc = self.allocated.get(resource_type, 0.0)
        resv = self.reserved.get(resource_type, 0.0)
        return max(0.0, total - alloc - resv)

    def utilization(self, resource_type: ResourceType) -> float:
        """Get utilization percentage for a resource type."""
        total = self.total.get(resource_type, 0.0)
        if total == 0:
            return 0.0
        alloc = self.allocated.get(resource_type, 0.0)
        return alloc / total

    def can_allocate(self, requirements: list[ResourceRequirement]) -> bool:
        """Check if all requirements can be satisfied."""
        for req in requirements:
            if self.available(req.resource_type) < req.minimum:
                return False
        return True


class ResourcePlacement:
    """
    Resource placement manager.

    Handles static resource allocation across placements.
    Ensures models get resources meeting their requirements.
    """

    def __init__(self):
        self._capacities: dict[str, PlacementCapacity] = {}
        self._allocations: dict[str, ResourceAllocation] = {}
        self._model_requirements: dict[str, list[ResourceRequirement]] = {}

    def register_placement(
        self,
        placement_id: str,
        capacity: dict[ResourceType, float],
        reserved: dict[ResourceType, float] | None = None,
    ) -> PlacementCapacity:
        """Register a placement with its capacity."""
        placement_capacity = PlacementCapacity(
            placement_id=placement_id,
            total=capacity,
            reserved=reserved or {},
        )
        self._capacities[placement_id] = placement_capacity
        return placement_capacity

    def register_model_requirements(
        self,
        model_id: str,
        requirements: list[ResourceRequirement],
    ) -> None:
        """Register resource requirements for a model."""
        self._model_requirements[model_id] = requirements

    def get_placement_capacity(
        self, placement_id: str
    ) -> PlacementCapacity | None:
        """Get capacity information for a placement."""
        return self._capacities.get(placement_id)

    def get_model_requirements(
        self, model_id: str
    ) -> list[ResourceRequirement]:
        """Get requirements for a model."""
        return self._model_requirements.get(model_id, [])

    def find_suitable_placements(
        self,
        model_id: str,
    ) -> list[str]:
        """Find placements that can accommodate a model's requirements."""
        requirements = self._model_requirements.get(model_id, [])
        if not requirements:
            return list(self._capacities.keys())

        suitable: list[str] = []
        for placement_id, capacity in self._capacities.items():
            if capacity.can_allocate(requirements):
                suitable.append(placement_id)

        return suitable

    def allocate(
        self,
        model_id: str,
        placement_id: str,
        allocation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ResourceAllocation | None:
        """
        Allocate resources for a model at a placement.

        Returns ResourceAllocation if successful, None if insufficient resources.
        """
        import uuid

        capacity = self._capacities.get(placement_id)
        if capacity is None:
            return None

        requirements = self._model_requirements.get(model_id, [])
        if requirements and not capacity.can_allocate(requirements):
            return None

        # Allocate resources
        allocated: dict[ResourceType, float] = {}
        for req in requirements:
            amount = min(req.requested, capacity.available(req.resource_type))
            allocated[req.resource_type] = amount
            capacity.allocated[req.resource_type] = (
                capacity.allocated.get(req.resource_type, 0.0) + amount
            )

        allocation = ResourceAllocation(
            allocation_id=allocation_id or str(uuid.uuid4()),
            placement_id=placement_id,
            model_id=model_id,
            resources=allocated,
            metadata=metadata or {},
        )

        self._allocations[allocation.allocation_id] = allocation
        return allocation

    def release(self, allocation_id: str) -> bool:
        """Release an allocation."""
        allocation = self._allocations.get(allocation_id)
        if allocation is None:
            return False

        capacity = self._capacities.get(allocation.placement_id)
        if capacity:
            for rt, amount in allocation.resources.items():
                capacity.allocated[rt] = max(
                    0.0, capacity.allocated.get(rt, 0.0) - amount
                )

        del self._allocations[allocation_id]
        return True

    def get_allocation(self, allocation_id: str) -> ResourceAllocation | None:
        """Get an allocation by ID."""
        return self._allocations.get(allocation_id)

    def get_allocations_for_model(
        self, model_id: str
    ) -> list[ResourceAllocation]:
        """Get all allocations for a model."""
        return [
            a for a in self._allocations.values()
            if a.model_id == model_id
        ]

    def get_allocations_at_placement(
        self, placement_id: str
    ) -> list[ResourceAllocation]:
        """Get all allocations at a placement."""
        return [
            a for a in self._allocations.values()
            if a.placement_id == placement_id
        ]

    def cleanup_expired(self) -> list[str]:
        """Release all expired allocations. Returns list of released IDs."""
        expired: list[str] = []
        for allocation_id, allocation in list(self._allocations.items()):
            if allocation.is_expired():
                self.release(allocation_id)
                expired.append(allocation_id)
        return expired

    def get_utilization_report(self) -> dict[str, dict[str, float]]:
        """Get utilization report for all placements."""
        report: dict[str, dict[str, float]] = {}

        for placement_id, capacity in self._capacities.items():
            report[placement_id] = {}
            for rt in capacity.total.keys():
                report[placement_id][rt.value] = capacity.utilization(rt)

        return report

    def to_dict(self) -> dict[str, Any]:
        """Serialize state to dictionary."""
        return {
            "capacities": {
                pid: {
                    "total": {rt.value: v for rt, v in cap.total.items()},
                    "allocated": {rt.value: v for rt, v in cap.allocated.items()},
                    "reserved": {rt.value: v for rt, v in cap.reserved.items()},
                }
                for pid, cap in self._capacities.items()
            },
            "allocations": {
                aid: alloc.to_dict()
                for aid, alloc in self._allocations.items()
            },
            "model_requirements": {
                mid: [req.to_dict() for req in reqs]
                for mid, reqs in self._model_requirements.items()
            },
        }
