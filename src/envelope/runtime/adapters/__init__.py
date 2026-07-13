"""
Backend Adapters (E3)

Runtime adapters for different model backends:
- OllamaAdapter: Self-hosted Ollama models
- VLLMAdapter: Self-hosted vLLM models
- OpenAIAdapter: OpenAI API models
- AnthropicAdapter: Anthropic API models

All adapters implement RuntimeContract for consistent behavior.
"""

from envelope.runtime.adapters.base import create_adapter, AdapterConfig
from envelope.runtime.adapters.ollama import OllamaAdapter
from envelope.runtime.adapters.vllm import VLLMAdapter
from envelope.runtime.adapters.openai import OpenAIAdapter

__all__ = [
    "create_adapter",
    "AdapterConfig",
    "OllamaAdapter",
    "VLLMAdapter",
    "OpenAIAdapter",
]
