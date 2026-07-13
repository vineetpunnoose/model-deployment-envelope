"""
Reproduction Engine (D4)

Enables replay of historical requests for debugging,
audit, and verification purposes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from envelope.record.provenance import ProvenanceRecord, ProvenanceStore


class InferenceEngine(Protocol):
    """Protocol for inference engines that can replay requests."""

    async def infer(
        self,
        prompt: str,
        model_id: str,
        **kwargs: Any,
    ) -> str:
        """Run inference with the given prompt."""
        ...


@dataclass
class ReplayResult:
    """
    Result of replaying a historical request.

    Compares original and replayed responses for verification.
    """
    request_id: UUID
    original_record: ProvenanceRecord
    replayed_response: str
    replayed_response_hash: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    duration_ms: float = 0.0
    exact_match: bool = False
    similarity_score: float = 0.0
    differences: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_reproduced(self) -> bool:
        """Check if the response was exactly reproduced."""
        return self.exact_match

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": str(self.request_id),
            "original_response_hash": self.original_record.response_hash,
            "replayed_response_hash": self.replayed_response_hash,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.duration_ms,
            "exact_match": self.exact_match,
            "similarity_score": self.similarity_score,
            "differences": self.differences,
            "metadata": self.metadata,
        }


class ReproductionEngine:
    """
    Engine for replaying historical inference requests.

    Enables:
    - Debugging by re-running problematic requests
    - Audit verification by reproducing decisions
    - Regression testing against historical requests
    """

    def __init__(
        self,
        store: ProvenanceStore,
        inference_engine: InferenceEngine | None = None,
    ):
        self._store = store
        self._inference_engine = inference_engine

    def set_inference_engine(self, engine: InferenceEngine) -> None:
        """Set the inference engine for replay."""
        self._inference_engine = engine

    async def get_record(self, request_id: UUID) -> ProvenanceRecord | None:
        """Retrieve a record for replay."""
        return await self._store.retrieve(request_id)

    async def replay(
        self,
        request_id: UUID,
        use_same_model: bool = True,
        override_model_id: str | None = None,
        **inference_kwargs: Any,
    ) -> ReplayResult:
        """
        Replay a historical request.

        Args:
            request_id: ID of the request to replay
            use_same_model: If True, use the same model as original
            override_model_id: Override model ID if not using same model
            **inference_kwargs: Additional arguments for inference

        Returns:
            ReplayResult with comparison to original
        """
        import hashlib
        import time

        if self._inference_engine is None:
            raise RuntimeError("No inference engine configured for replay")

        # Get original record
        record = await self._store.retrieve(request_id)
        if record is None:
            raise ValueError(f"Record not found: {request_id}")

        # Determine model to use
        model_id = record.model_id if use_same_model else (override_model_id or record.model_id)

        # Replay the request
        start_time = time.perf_counter()
        replayed_response = await self._inference_engine.infer(
            prompt=record.prompt,
            model_id=model_id,
            **inference_kwargs,
        )
        duration_ms = (time.perf_counter() - start_time) * 1000

        # Compute hash
        replayed_hash = hashlib.sha256(replayed_response.encode()).hexdigest()

        # Compare responses
        exact_match = replayed_hash == record.response_hash
        similarity = self._compute_similarity(record.response, replayed_response)
        differences = self._find_differences(record.response, replayed_response)

        return ReplayResult(
            request_id=request_id,
            original_record=record,
            replayed_response=replayed_response,
            replayed_response_hash=replayed_hash,
            duration_ms=duration_ms,
            exact_match=exact_match,
            similarity_score=similarity,
            differences=differences,
            metadata={
                "model_id": model_id,
                "original_model_id": record.model_id,
                "same_model": model_id == record.model_id,
            },
        )

    async def replay_batch(
        self,
        request_ids: list[UUID],
        **kwargs: Any,
    ) -> list[ReplayResult]:
        """Replay multiple requests."""
        results: list[ReplayResult] = []
        for request_id in request_ids:
            try:
                result = await self.replay(request_id, **kwargs)
                results.append(result)
            except Exception as e:
                # Create error result
                record = await self._store.retrieve(request_id)
                if record:
                    results.append(ReplayResult(
                        request_id=request_id,
                        original_record=record,
                        replayed_response="",
                        replayed_response_hash="",
                        exact_match=False,
                        similarity_score=0.0,
                        differences=[f"Replay failed: {e}"],
                        metadata={"error": str(e)},
                    ))
        return results

    async def verify_reproduction(
        self,
        request_id: UUID,
        expected_response: str | None = None,
    ) -> tuple[bool, ReplayResult | None, str]:
        """
        Verify that a request can be exactly reproduced.

        Returns:
            - success: True if reproduced exactly
            - result: ReplayResult if replay succeeded
            - message: Description of outcome
        """
        try:
            result = await self.replay(request_id)

            if expected_response:
                import hashlib
                expected_hash = hashlib.sha256(expected_response.encode()).hexdigest()
                if result.replayed_response_hash == expected_hash:
                    return True, result, "Response matches expected output"
                return False, result, "Response does not match expected output"

            if result.exact_match:
                return True, result, "Response exactly matches original"

            return False, result, f"Response differs (similarity: {result.similarity_score:.2%})"

        except Exception as e:
            return False, None, f"Replay failed: {e}"

    async def find_similar_requests(
        self,
        prompt: str,
        model_id: str | None = None,
        limit: int = 10,
    ) -> list[ProvenanceRecord]:
        """
        Find historical requests similar to a given prompt.

        Useful for finding comparable cases for testing.
        """
        records = await self._store.query(model_id=model_id, limit=100)

        # Score by similarity to prompt
        scored: list[tuple[float, ProvenanceRecord]] = []
        for record in records:
            similarity = self._compute_similarity(prompt, record.prompt)
            scored.append((similarity, record))

        # Sort by similarity (descending)
        scored.sort(key=lambda x: x[0], reverse=True)

        return [record for _, record in scored[:limit]]

    def _compute_similarity(self, text1: str, text2: str) -> float:
        """
        Compute similarity between two texts.

        Uses simple token-based Jaccard similarity.
        """
        if not text1 or not text2:
            return 0.0

        tokens1 = set(text1.lower().split())
        tokens2 = set(text2.lower().split())

        if not tokens1 or not tokens2:
            return 0.0

        intersection = tokens1 & tokens2
        union = tokens1 | tokens2

        return len(intersection) / len(union)

    def _find_differences(self, original: str, replayed: str) -> list[str]:
        """
        Find differences between original and replayed responses.

        Returns list of difference descriptions.
        """
        differences: list[str] = []

        # Length difference
        len_diff = len(replayed) - len(original)
        if len_diff != 0:
            differences.append(f"Length difference: {len_diff:+d} characters")

        # Line count difference
        orig_lines = original.count("\n") + 1
        replay_lines = replayed.count("\n") + 1
        if orig_lines != replay_lines:
            differences.append(f"Line count: {orig_lines} → {replay_lines}")

        # Word count difference
        orig_words = len(original.split())
        replay_words = len(replayed.split())
        if orig_words != replay_words:
            differences.append(f"Word count: {orig_words} → {replay_words}")

        # First difference location
        for i, (c1, c2) in enumerate(zip(original, replayed)):
            if c1 != c2:
                context_start = max(0, i - 10)
                context_end = min(len(original), i + 10)
                differences.append(
                    f"First difference at position {i}: "
                    f"'{original[context_start:context_end]}' → "
                    f"'{replayed[context_start:min(len(replayed), context_end)]}'"
                )
                break

        return differences

    async def create_golden_test(
        self, request_id: UUID
    ) -> dict[str, Any]:
        """
        Create a golden test case from a historical request.

        Returns a test case that can be used for regression testing.
        """
        record = await self._store.retrieve(request_id)
        if record is None:
            raise ValueError(f"Record not found: {request_id}")

        return {
            "id": str(request_id),
            "name": f"Golden test from {record.timestamp.isoformat()}",
            "model_id": record.model_id,
            "prompt": record.prompt,
            "expected_response": record.response,
            "expected_response_hash": record.response_hash,
            "data_classes": record.data_classes,
            "metadata": {
                "source": "reproduction_engine",
                "original_timestamp": record.timestamp.isoformat(),
                "original_caller": record.caller_id,
            },
        }

    async def export_for_debug(
        self, request_id: UUID
    ) -> dict[str, Any]:
        """
        Export complete debug information for a request.

        Includes all context needed to investigate issues.
        """
        record = await self._store.retrieve(request_id)
        if record is None:
            raise ValueError(f"Record not found: {request_id}")

        return {
            "request_id": str(request_id),
            "timestamp": record.timestamp.isoformat(),
            "caller": {
                "id": record.caller_id,
                "roles": record.caller_roles,
            },
            "model": {
                "id": record.model_id,
                "version": record.model_version,
            },
            "placement_id": record.placement_id,
            "prompt": record.prompt,
            "prompt_hash": record.prompt_hash,
            "response": record.response,
            "response_hash": record.response_hash,
            "tool_invocations": [
                {
                    "tool": t.tool_name,
                    "arguments": t.arguments,
                    "result": t.result,
                    "success": t.success,
                    "duration_ms": t.duration_ms,
                    "error": t.error,
                }
                for t in record.tool_invocations
            ],
            "data_classes": record.data_classes,
            "escalation": {
                "escalated": record.escalated,
                "reason": record.escalation_reason,
                "withheld": record.withheld,
            },
            "timing": {
                "duration_ms": record.duration_ms,
            },
            "chain": {
                "hash": record.chain_hash,
                "previous_hash": record.previous_hash,
            },
            "metadata": record.metadata,
        }
