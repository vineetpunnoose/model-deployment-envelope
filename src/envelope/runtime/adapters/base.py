"""
Base Adapter and Factory (E3)

Provides the base functionality and factory for creating adapters.
Backend switching is achieved by changing one configuration value.
"""

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from envelope.runtime.contract import RuntimeContract

if TYPE_CHECKING:
    from envelope.runtime.adapters.ollama import OllamaAdapter
    from envelope.runtime.adapters.vllm import VLLMAdapter
    from envelope.runtime.adapters.openai import OpenAIAdapter


@dataclass
class AdapterConfig:
    """
    Configuration for creating a runtime adapter.

    Backend switching is achieved by changing the 'backend' field.
    All other configuration flows through to the specific adapter.
    """
    backend: str  # ollama, vllm, openai, anthropic
    model_id: str
    endpoint: str | None = None
    api_key: str | None = None
    temperature: float = 0.7
    max_tokens: int = 1024
    timeout: float = 60.0
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AdapterConfig":
        """Create config from dictionary."""
        return cls(
            backend=data["backend"],
            model_id=data["model_id"],
            endpoint=data.get("endpoint"),
            api_key=data.get("api_key"),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 1024),
            timeout=data.get("timeout", 60.0),
            extra=data.get("extra", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "backend": self.backend,
            "model_id": self.model_id,
            "endpoint": self.endpoint,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "extra": self.extra,
        }


def create_adapter(config: AdapterConfig) -> RuntimeContract:
    """
    Factory function to create the appropriate adapter.

    Backend switching is achieved by changing config.backend:
    - 'ollama': Creates OllamaAdapter for local Ollama server
    - 'vllm': Creates VLLMAdapter for local vLLM server
    - 'openai': Creates OpenAIAdapter for OpenAI API
    - 'anthropic': Creates AnthropicAdapter for Anthropic API

    This is the single point of configuration for switching backends.

    Args:
        config: Adapter configuration

    Returns:
        RuntimeContract implementation for the specified backend

    Raises:
        ValueError: If backend is not recognized
    """
    backend = config.backend.lower()

    if backend == "ollama":
        from envelope.runtime.adapters.ollama import OllamaAdapter
        return OllamaAdapter(
            model_id=config.model_id,
            endpoint=config.endpoint or "http://localhost:11434",
            default_temperature=config.temperature,
            default_max_tokens=config.max_tokens,
            timeout=config.timeout,
            **config.extra,
        )

    elif backend == "vllm":
        from envelope.runtime.adapters.vllm import VLLMAdapter
        return VLLMAdapter(
            model_id=config.model_id,
            endpoint=config.endpoint or "http://localhost:8000",
            default_temperature=config.temperature,
            default_max_tokens=config.max_tokens,
            timeout=config.timeout,
            **config.extra,
        )

    elif backend == "openai":
        from envelope.runtime.adapters.openai import OpenAIAdapter
        return OpenAIAdapter(
            model_id=config.model_id,
            api_key=config.api_key,
            endpoint=config.endpoint,
            default_temperature=config.temperature,
            default_max_tokens=config.max_tokens,
            timeout=config.timeout,
            **config.extra,
        )

    elif backend == "anthropic":
        # Anthropic adapter uses OpenAI adapter with different base
        # For now, placeholder - would need anthropic SDK
        raise NotImplementedError("Anthropic adapter not yet implemented")

    elif backend == "mock":
        from envelope.runtime.contract import MockRuntimeAdapter
        return MockRuntimeAdapter(
            model_id=config.model_id,
            **config.extra,
        )

    else:
        raise ValueError(
            f"Unknown backend: {backend}. "
            f"Supported: ollama, vllm, openai, anthropic, mock"
        )


def get_default_endpoint(backend: str) -> str:
    """Get default endpoint for a backend."""
    defaults = {
        "ollama": "http://localhost:11434",
        "vllm": "http://localhost:8000",
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com",
    }
    return defaults.get(backend.lower(), "")
