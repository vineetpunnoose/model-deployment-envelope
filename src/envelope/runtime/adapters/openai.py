"""
OpenAI Adapter (E3)

Runtime adapter for OpenAI API models.
"""

import json
import os
import time
from typing import Any, AsyncIterator
from uuid import uuid4

from envelope.types import LifecycleState, ToolCall
from envelope.runtime.contract import (
    BaseRuntimeAdapter,
    ModelInfo,
    InferenceResult,
    StreamChunk,
)


class OpenAIAdapter(BaseRuntimeAdapter):
    """
    Runtime adapter for OpenAI API models.

    Uses the official OpenAI Python SDK for API calls.
    """

    def __init__(
        self,
        model_id: str,
        api_key: str | None = None,
        endpoint: str | None = None,
        organization: str | None = None,
        default_temperature: float = 0.7,
        default_max_tokens: int = 1024,
        timeout: float = 60.0,
        **kwargs: Any,
    ):
        super().__init__(
            model_id=model_id,
            endpoint=endpoint,
            default_temperature=default_temperature,
            default_max_tokens=default_max_tokens,
            **kwargs,
        )
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._organization = organization
        self._timeout = timeout
        self._client: Any = None

    @property
    def backend_name(self) -> str:
        return "openai"

    def _get_client(self) -> Any:
        """Get or create OpenAI client."""
        if self._client is None:
            from openai import AsyncOpenAI

            kwargs: dict[str, Any] = {
                "api_key": self._api_key,
                "timeout": self._timeout,
            }

            if self._endpoint:
                kwargs["base_url"] = self._endpoint

            if self._organization:
                kwargs["organization"] = self._organization

            self._client = AsyncOpenAI(**kwargs)

        return self._client

    async def health(self) -> bool:
        """Check if OpenAI API is accessible."""
        try:
            client = self._get_client()
            # Simple models list call to verify connectivity
            await client.models.list()
            return True
        except Exception:
            return False

    async def info(self) -> ModelInfo:
        """Get model information from OpenAI."""
        try:
            client = self._get_client()
            model = await client.models.retrieve(self._model_id)

            return ModelInfo(
                model_id=self._model_id,
                version=str(model.created),
                backend="openai",
                capabilities=["chat", "tools"],
                context_length=self._get_context_length(self._model_id),
                metadata={
                    "owned_by": model.owned_by,
                    "object": model.object,
                },
            )
        except Exception:
            pass

        return ModelInfo(
            model_id=self._model_id,
            version="unknown",
            backend="openai",
            context_length=self._get_context_length(self._model_id),
        )

    def _get_context_length(self, model_id: str) -> int:
        """Get approximate context length for known models."""
        context_lengths = {
            "gpt-4": 8192,
            "gpt-4-32k": 32768,
            "gpt-4-turbo": 128000,
            "gpt-4o": 128000,
            "gpt-4o-mini": 128000,
            "gpt-3.5-turbo": 16385,
            "gpt-3.5-turbo-16k": 16385,
        }

        for key, length in context_lengths.items():
            if model_id.startswith(key):
                return length

        return 4096

    async def load(self) -> bool:
        """Verify model is accessible."""
        self._set_state(LifecycleState.LOADING)

        try:
            # Verify API key and model access
            client = self._get_client()
            await client.models.retrieve(self._model_id)
            self._set_state(LifecycleState.WARMING)
            return True

        except Exception as e:
            self._set_state(LifecycleState.FAILED)
            raise

    async def unload(self) -> bool:
        """Close client connection."""
        self._set_state(LifecycleState.STOPPED)
        if self._client:
            await self._client.close()
            self._client = None
        return True

    async def infer(
        self,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop_sequences: list[str] | None = None,
        **kwargs: Any,
    ) -> InferenceResult:
        """Run inference with OpenAI API."""
        start_time = time.perf_counter()
        client = self._get_client()

        # Build request
        request_kwargs: dict[str, Any] = {
            "model": self._model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._get_temperature(temperature),
            "max_tokens": self._get_max_tokens(max_tokens),
        }

        if stop_sequences:
            request_kwargs["stop"] = stop_sequences

        if tools:
            request_kwargs["tools"] = tools

        # Add any extra kwargs
        request_kwargs.update(kwargs)

        response = await client.chat.completions.create(**request_kwargs)

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Parse response
        choice = response.choices[0]
        message = choice.message
        content = message.content or ""

        # Parse tool calls
        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                tool_calls.append(ToolCall(
                    tool_name=tc.function.name,
                    arguments=args,
                    call_id=tc.id,
                ))

        return InferenceResult(
            request_id=uuid4(),
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            usage={
                "input_tokens": response.usage.prompt_tokens if response.usage else 0,
                "output_tokens": response.usage.completion_tokens if response.usage else 0,
            },
            duration_ms=duration_ms,
            metadata={
                "model": response.model,
                "id": response.id,
                "system_fingerprint": getattr(response, "system_fingerprint", None),
            },
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
        """Run streaming inference with OpenAI API."""
        client = self._get_client()

        # Build request
        request_kwargs: dict[str, Any] = {
            "model": self._model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._get_temperature(temperature),
            "max_tokens": self._get_max_tokens(max_tokens),
            "stream": True,
        }

        if stop_sequences:
            request_kwargs["stop"] = stop_sequences

        # Note: tools with streaming requires special handling
        # For simplicity, we don't support tools in streaming mode here

        request_kwargs.update(kwargs)

        stream = await client.chat.completions.create(**request_kwargs)

        async for chunk in stream:
            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            content = delta.content or ""
            finish_reason = chunk.choices[0].finish_reason

            yield StreamChunk(
                content=content,
                is_final=finish_reason is not None,
                metadata={
                    "model": chunk.model,
                    "id": chunk.id,
                },
            )

            if finish_reason:
                break
