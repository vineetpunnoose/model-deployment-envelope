"""
vLLM Adapter (E3)

Runtime adapter for self-hosted vLLM models.
Uses OpenAI-compatible API provided by vLLM.
"""

import json
import time
from typing import Any, AsyncIterator
from uuid import uuid4

import httpx

from envelope.types import LifecycleState, ToolCall
from envelope.runtime.contract import (
    BaseRuntimeAdapter,
    ModelInfo,
    InferenceResult,
    StreamChunk,
)


class VLLMAdapter(BaseRuntimeAdapter):
    """
    Runtime adapter for vLLM models.

    Connects to a local vLLM server using OpenAI-compatible API.
    """

    def __init__(
        self,
        model_id: str,
        endpoint: str = "http://localhost:8000",
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
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def backend_name(self) -> str:
        return "vllm"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._endpoint,
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    async def health(self) -> bool:
        """Check if vLLM server is healthy."""
        try:
            client = await self._get_client()
            response = await client.get("/health")
            return response.status_code == 200
        except Exception:
            # Try models endpoint as fallback
            try:
                client = await self._get_client()
                response = await client.get("/v1/models")
                return response.status_code == 200
            except Exception:
                return False

    async def info(self) -> ModelInfo:
        """Get model information from vLLM."""
        try:
            client = await self._get_client()
            response = await client.get("/v1/models")

            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])

                for model in models:
                    if model.get("id") == self._model_id:
                        return ModelInfo(
                            model_id=self._model_id,
                            version=model.get("created", "unknown"),
                            backend="vllm",
                            capabilities=["chat", "completion"],
                            context_length=model.get("max_model_len", 4096),
                            metadata=model,
                        )
        except Exception:
            pass

        return ModelInfo(
            model_id=self._model_id,
            version="unknown",
            backend="vllm",
        )

    async def load(self) -> bool:
        """
        Load model in vLLM.

        Note: vLLM typically has models loaded at server startup.
        This method verifies the model is available.
        """
        self._set_state(LifecycleState.LOADING)

        try:
            client = await self._get_client()
            response = await client.get("/v1/models")

            if response.status_code == 200:
                data = response.json()
                models = data.get("data", [])
                model_ids = [m.get("id") for m in models]

                if self._model_id in model_ids:
                    self._set_state(LifecycleState.WARMING)
                    return True
                else:
                    raise ValueError(
                        f"Model {self._model_id} not found in vLLM. "
                        f"Available: {model_ids}"
                    )

        except Exception as e:
            self._set_state(LifecycleState.FAILED)
            raise

        return False

    async def unload(self) -> bool:
        """Unload model (close client connection)."""
        self._set_state(LifecycleState.STOPPED)
        if self._client:
            await self._client.aclose()
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
        """Run inference with vLLM using OpenAI-compatible API."""
        start_time = time.perf_counter()
        client = await self._get_client()

        # Build request (OpenAI format)
        request_body: dict[str, Any] = {
            "model": self._model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._get_temperature(temperature),
            "max_tokens": self._get_max_tokens(max_tokens),
            "stream": False,
        }

        if stop_sequences:
            request_body["stop"] = stop_sequences

        if tools:
            request_body["tools"] = tools

        response = await client.post("/v1/chat/completions", json=request_body)
        response.raise_for_status()
        data = response.json()

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Parse response
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")

        # Parse tool calls
        tool_calls: list[ToolCall] = []
        for tc in message.get("tool_calls", []):
            func = tc.get("function", {})
            args = func.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(ToolCall(
                tool_name=func.get("name", ""),
                arguments=args,
                call_id=tc.get("id", ""),
            ))

        # Parse usage
        usage_data = data.get("usage", {})

        return InferenceResult(
            request_id=uuid4(),
            content=content,
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            usage={
                "input_tokens": usage_data.get("prompt_tokens", 0),
                "output_tokens": usage_data.get("completion_tokens", 0),
            },
            duration_ms=duration_ms,
            metadata={
                "model": data.get("model", self._model_id),
                "id": data.get("id", ""),
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
        """Run streaming inference with vLLM."""
        client = await self._get_client()

        # Build request
        request_body: dict[str, Any] = {
            "model": self._model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._get_temperature(temperature),
            "max_tokens": self._get_max_tokens(max_tokens),
            "stream": True,
        }

        if stop_sequences:
            request_body["stop"] = stop_sequences

        async with client.stream(
            "POST", "/v1/chat/completions", json=request_body
        ) as response:
            async for line in response.aiter_lines():
                if not line or line.startswith(":"):
                    continue

                if line.startswith("data: "):
                    line = line[6:]

                if line == "[DONE]":
                    yield StreamChunk(content="", is_final=True)
                    break

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                choices = data.get("choices", [])
                if not choices:
                    continue

                delta = choices[0].get("delta", {})
                content = delta.get("content", "")
                finish_reason = choices[0].get("finish_reason")

                yield StreamChunk(
                    content=content,
                    is_final=finish_reason is not None,
                    metadata={
                        "model": data.get("model", self._model_id),
                    },
                )
