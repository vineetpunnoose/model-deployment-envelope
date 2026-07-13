"""
Runtime Layer (Section E)

Provides the runtime infrastructure for model inference:
- RuntimeContract (E1): Unified interface for all backends
- LifecycleStateMachine (E2): Model lifecycle management
- Backend Adapters (E3): Ollama, vLLM, OpenAI, Anthropic adapters
- ResourcePlacement (E4): Static resource allocation

All backends implement the same contract for consistent behavior.
"""

from envelope.runtime.contract import RuntimeContract, InferenceResult, ModelInfo
from envelope.runtime.lifecycle import LifecycleStateMachine, LifecycleEvent
from envelope.runtime.placement import ResourcePlacement, ResourceAllocation

__all__ = [
    "RuntimeContract",
    "InferenceResult",
    "ModelInfo",
    "LifecycleStateMachine",
    "LifecycleEvent",
    "ResourcePlacement",
    "ResourceAllocation",
]
