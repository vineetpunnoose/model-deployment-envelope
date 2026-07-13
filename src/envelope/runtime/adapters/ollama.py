"""
Ollama Adapter (E3)

Runtime adapter for self-hosted Ollama models.
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


class OllamaAdapter(BaseRuntimeAdapter):
    """
    Runtime adapter for Ollama models.

    Connects to a local Ollama server for inference.
    Supports both chat and completion endpoints.
    """

    def __init__(
        self,
        model_id: str,
        endpoint: str = "http://localhost:11434",
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
        return "ollama"

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._endpoint,
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    async def health(self) -> bool:
        """Check if Ollama server is healthy."""
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    async def info(self) -> ModelInfo:
        """Get model information from Ollama."""
        try:
            client = await self._get_client()
            response = await client.post(
                "/api/show",
                json={"name": self._model_id},
            )

            if response.status_code == 200:
                data = response.json()
                return ModelInfo(
                    model_id=self._model_id,
                    version=data.get("digest", "unknown")[:12],
                    backend="ollama",
                    parameters=data.get("parameters", {}),
                    capabilities=["chat", "completion"],
                    context_length=data.get("context_length", 4096),
                    metadata=data,
                )
        except Exception:
            pass

        return ModelInfo(
            model_id=self._model_id,
            version="unknown",
            backend="ollama",
        )

    async def load(self) -> bool:
        """Load model into Ollama memory."""
        self._set_state(LifecycleState.LOADING)

        try:
            client = await self._get_client()

            # Pull model if not available
            response = await client.post(
                "/api/pull",
                json={"name": self._model_id, "stream": False},
                timeout=httpx.Timeout(600.0),  # Long timeout for pull
            )

            if response.status_code == 200:
                # Warm up the model with a simple request
                await client.post(
                    "/api/generate",
                    json={
                        "model": self._model_id,
                        "prompt": "Hello",
                        "stream": False,
                    },
                )
                self._set_state(LifecycleState.WARMING)
                return True

        except Exception as e:
            self._set_state(LifecycleState.FAILED)
            raise

        return False

    async def unload(self) -> bool:
        """Unload model from memory."""
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
        """Run inference with Ollama."""
        start_time = time.perf_counter()
        client = await self._get_client()

        # Build request
        request_body: dict[str, Any] = {
            "model": self._model_id,
            "stream": False,
            "options": {
                "temperature": self._get_temperature(temperature),
                "num_predict": self._get_max_tokens(max_tokens),
            },
        }

        if stop_sequences:
            request_body["options"]["stop"] = stop_sequences

        # Use chat API for tool support
        if tools:
            request_body["messages"] = [{"role": "user", "content": prompt}]
            request_body["tools"] = tools
            endpoint = "/api/chat"
        else:
            request_body["prompt"] = prompt
            endpoint = "/api/generate"

        response = await client.post(endpoint, json=request_body)
        response.raise_for_status()
        data = response.json()

        duration_ms = (time.perf_counter() - start_time) * 1000

        # Parse response based on endpoint
        if tools:
            content = data.get("message", {}).get("content", "")
            tool_calls_data = data.get("message", {}).get("tool_calls", [])
        else:
            content = data.get("response", "")
            tool_calls_data = []

        # Parse tool calls
        tool_calls: list[ToolCall] = []
        for tc in tool_calls_data:
            tool_calls.append(ToolCall(
                tool_name=tc.get("function", {}).get("name", ""),
                arguments=tc.get("function", {}).get("arguments", {}),
            ))

        return InferenceResult(
            request_id=uuid4(),
            content=content,
            tool_calls=tool_calls,
            finish_reason=data.get("done_reason", "stop"),
            usage={
                "input_tokens": data.get("prompt_eval_count", 0),
                "output_tokens": data.get("eval_count", 0),
            },
            duration_ms=duration_ms,
            metadata={
                "model": data.get("model", self._model_id),
                "total_duration": data.get("total_duration", 0),
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
        """Run streaming inference with Ollama."""
        client = await self._get_client()

        # Build request
        request_body: dict[str, Any] = {
            "model": self._model_id,
            "stream": True,
            "options": {
                "temperature": self._get_temperature(temperature),
                "num_predict": self._get_max_tokens(max_tokens),
            },
        }

        if stop_sequences:
            request_body["options"]["stop"] = stop_sequences

        # Use generate API for streaming
        request_body["prompt"] = prompt
        endpoint = "/api/generate"

        async with client.stream("POST", endpoint, json=request_body) as response:
            async for line in response.aiter_lines():
                if not line:
                    continue

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                content = data.get("response", "")
                is_final = data.get("done", False)

                yield StreamChunk(
                    content=content,
                    is_final=is_final,
                    metadata={
                        "model": data.get("model", self._model_id),
                    },
                )

                if is_final:
                    break
