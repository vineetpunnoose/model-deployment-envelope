"""
Runtime Contract (E1)

Defines the unified interface that all backend adapters must implement.
Ensures consistent behavior regardless of underlying runtime.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator
from uuid import UUID, uuid4

from envelope.types import ToolCall, LifecycleState


@dataclass
class ModelInfo:
    """Information about a loaded model."""
    model_id: str
    version: str
    backend: str
    parameters: dict[str, Any] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)
    context_length: int = 4096
    loaded_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InferenceResult:
    """Result of a model inference call."""
    request_id: UUID
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    duration_ms: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def input_tokens(self) -> int:
        return self.usage.get("input_tokens", 0)

    @property
    def output_tokens(self) -> int:
        return self.usage.get("output_tokens", 0)


@dataclass
class StreamChunk:
    """A chunk of streaming inference output."""
    content: str
    is_final: bool = False
    tool_call: ToolCall | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class RuntimeContract(ABC):
    """
    Unified contract for all model runtime backends.

    Every backend (Ollama, vLLM, OpenAI, Anthropic) must implement
    this interface to ensure consistent behavior across deployments.
    """

    @abstractmethod
    async def health(self) -> bool:
        """
        Check if the backend is healthy and ready to serve.

        Returns True if healthy, False otherwise.
        """
        pass

    @abstractmethod
    async def info(self) -> ModelInfo:
        """
        Get information about the loaded model.

        Returns ModelInfo with model details.
        """
        pass

    @abstractmethod
    async def infer(
        self,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop_sequences: list[str] | None = None,
        **kwargs: Any,
    ) -> InferenceResult:
        """
        Run inference with the model.

        Args:
            prompt: The input prompt
            tools: Optional list of tools in provider format
            temperature: Optional temperature override
            max_tokens: Optional max tokens override
            stop_sequences: Optional stop sequences
            **kwargs: Additional provider-specific arguments

        Returns:
            InferenceResult with response and metadata
        """
        pass

    @abstractmethod
    async def infer_stream(
        self,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop_sequences: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """
        Run streaming inference.

        Yields StreamChunk objects as content is generated.
        """
        pass

    @abstractmethod
    async def load(self) -> bool:
        """
        Load the model into memory.

        Returns True if successful.
        """
        pass

    @abstractmethod
    async def unload(self) -> bool:
        """
        Unload the model from memory.

        Returns True if successful.
        """
        pass

    @abstractmethod
    def get_state(self) -> LifecycleState:
        """Get current lifecycle state."""
        pass

    @property
    @abstractmethod
    def model_id(self) -> str:
        """Get the model ID."""
        pass

    @property
    @abstractmethod
    def backend_name(self) -> str:
        """Get the backend name (e.g., 'ollama', 'openai')."""
        pass


class BaseRuntimeAdapter(RuntimeContract):
    """
    Base implementation with common functionality.

    Concrete adapters extend this and implement abstract methods.
    """

    def __init__(
        self,
        model_id: str,
        endpoint: str | None = None,
        default_temperature: float = 0.7,
        default_max_tokens: int = 1024,
        **kwargs: Any,
    ):
        self._model_id = model_id
        self._endpoint = endpoint
        self._default_temperature = default_temperature
        self._default_max_tokens = default_max_tokens
        self._state = LifecycleState.INIT
        self._config = kwargs
        self._model_info: ModelInfo | None = None

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def endpoint(self) -> str | None:
        return self._endpoint

    @property
    def config(self) -> dict[str, Any]:
        return self._config

    def get_state(self) -> LifecycleState:
        return self._state

    def _set_state(self, state: LifecycleState) -> None:
        self._state = state

    def _get_temperature(self, override: float | None) -> float:
        return override if override is not None else self._default_temperature

    def _get_max_tokens(self, override: int | None) -> int:
        return override if override is not None else self._default_max_tokens

    async def health(self) -> bool:
        """Default health check - override in subclass."""
        return self._state == LifecycleState.READY or self._state == LifecycleState.SERVING

    async def info(self) -> ModelInfo:
        """Return cached model info or fetch it."""
        if self._model_info is None:
            self._model_info = ModelInfo(
                model_id=self._model_id,
                version="unknown",
                backend=self.backend_name,
            )
        return self._model_info

    async def load(self) -> bool:
        """Default load - set state to loading."""
        self._set_state(LifecycleState.LOADING)
        return True

    async def unload(self) -> bool:
        """Default unload - set state to stopped."""
        self._set_state(LifecycleState.STOPPED)
        return True


class MockRuntimeAdapter(BaseRuntimeAdapter):
    """Mock runtime adapter for testing."""

    def __init__(
        self,
        model_id: str = "mock-model",
        responses: list[str] | None = None,
        **kwargs: Any,
    ):
        super().__init__(model_id, **kwargs)
        self._responses = responses or ["Mock response"]
        self._response_index = 0

    @property
    def backend_name(self) -> str:
        return "mock"

    async def health(self) -> bool:
        return True

    async def info(self) -> ModelInfo:
        return ModelInfo(
            model_id=self._model_id,
            version="1.0.0",
            backend="mock",
            capabilities=["chat", "tools"],
        )

    async def infer(
        self,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop_sequences: list[str] | None = None,
        **kwargs: Any,
    ) -> InferenceResult:
        response = self._responses[self._response_index % len(self._responses)]
        self._response_index += 1

        return InferenceResult(
            request_id=uuid4(),
            content=response,
            finish_reason="stop",
            usage={"input_tokens": len(prompt.split()), "output_tokens": len(response.split())},
        )

    async def infer_stream(
        self,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop_sequences: list[str] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        response = self._responses[self._response_index % len(self._responses)]
        self._response_index += 1

        words = response.split()
        for i, word in enumerate(words):
            is_final = i == len(words) - 1
            yield StreamChunk(content=word + (" " if not is_final else ""), is_final=is_final)

    async def load(self) -> bool:
        self._set_state(LifecycleState.READY)
        return True

    async def unload(self) -> bool:
        self._set_state(LifecycleState.STOPPED)
        return True

    def add_response(self, response: str) -> None:
        """Add a canned response for testing."""
        self._responses.append(response)

    def set_responses(self, responses: list[str]) -> None:
        """Set the list of canned responses."""
        self._responses = responses
        self._response_index = 0
