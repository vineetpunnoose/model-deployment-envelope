"""
Golden Set Runner (G2)

Runs golden set tests at release, load, and on schedule.
Golden tests verify model behavior against expected outputs.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import yaml

from envelope.runtime.contract import RuntimeContract


@dataclass
class GoldenTestCase:
    """
    A single golden test case.

    Defines an expected input/output pair for verification.
    """
    test_id: str
    name: str
    prompt: str
    expected_response: str | None = None
    expected_response_hash: str | None = None
    expected_contains: list[str] = field(default_factory=list)
    expected_not_contains: list[str] = field(default_factory=list)
    model_id: str | None = None
    timeout: float = 30.0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate_response(self, actual: str) -> tuple[bool, str]:
        """
        Validate actual response against expectations.

        Returns (passed, message) tuple.
        """
        # Check exact match if expected_response provided
        if self.expected_response:
            if actual.strip() == self.expected_response.strip():
                return True, "Exact match"
            return False, "Response does not match expected"

        # Check hash match
        if self.expected_response_hash:
            actual_hash = hashlib.sha256(actual.encode()).hexdigest()
            if actual_hash == self.expected_response_hash:
                return True, "Hash match"
            return False, f"Hash mismatch: expected {self.expected_response_hash[:16]}..., got {actual_hash[:16]}..."

        # Check contains patterns
        for pattern in self.expected_contains:
            if pattern.lower() not in actual.lower():
                return False, f"Missing expected pattern: {pattern}"

        # Check not-contains patterns
        for pattern in self.expected_not_contains:
            if pattern.lower() in actual.lower():
                return False, f"Contains forbidden pattern: {pattern}"

        return True, "All patterns matched"


@dataclass
class GoldenTestExecution:
    """Record of a golden test execution."""
    test_id: str
    passed: bool
    message: str
    actual_response: str
    actual_response_hash: str
    duration_ms: float
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class GoldenSetResult:
    """Result of running a golden set."""
    run_id: UUID
    set_name: str
    executions: list[GoldenTestExecution]
    passed: int
    failed: int
    duration_ms: float
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def success(self) -> bool:
        return self.failed == 0

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total


class GoldenSetRunner:
    """
    Runner for golden set tests.

    Executes golden tests against a runtime and validates
    responses against expected outputs.
    """

    def __init__(
        self,
        runtime: RuntimeContract | None = None,
        set_name: str = "default",
    ):
        self._runtime = runtime
        self._set_name = set_name
        self._test_cases: dict[str, GoldenTestCase] = {}
        self._history: list[GoldenSetResult] = []

    def set_runtime(self, runtime: RuntimeContract) -> None:
        """Set the runtime to test against."""
        self._runtime = runtime

    def add_test(self, test: GoldenTestCase) -> None:
        """Add a test case."""
        self._test_cases[test.test_id] = test

    def add_tests(self, tests: list[GoldenTestCase]) -> None:
        """Add multiple test cases."""
        for test in tests:
            self.add_test(test)

    def remove_test(self, test_id: str) -> bool:
        """Remove a test case."""
        if test_id in self._test_cases:
            del self._test_cases[test_id]
            return True
        return False

    def get_test(self, test_id: str) -> GoldenTestCase | None:
        """Get a test by ID."""
        return self._test_cases.get(test_id)

    def list_tests(self, tag: str | None = None) -> list[GoldenTestCase]:
        """List tests with optional tag filtering."""
        tests = list(self._test_cases.values())

        if tag:
            tests = [t for t in tests if tag in t.tags]

        return tests

    def load_from_yaml(self, path: Path | str) -> int:
        """
        Load test cases from a YAML file.

        Returns count of tests loaded.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Golden set file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        self._set_name = data.get("name", self._set_name)
        tests_data = data.get("tests", [])

        count = 0
        for test_data in tests_data:
            test = GoldenTestCase(
                test_id=test_data["id"],
                name=test_data.get("name", test_data["id"]),
                prompt=test_data["prompt"],
                expected_response=test_data.get("expected_response"),
                expected_response_hash=test_data.get("expected_response_hash"),
                expected_contains=test_data.get("expected_contains", []),
                expected_not_contains=test_data.get("expected_not_contains", []),
                model_id=test_data.get("model_id"),
                timeout=test_data.get("timeout", 30.0),
                tags=test_data.get("tags", []),
                metadata=test_data.get("metadata", {}),
            )
            self.add_test(test)
            count += 1

        return count

    def save_to_yaml(self, path: Path | str) -> None:
        """Save test cases to a YAML file."""
        path = Path(path)

        data = {
            "name": self._set_name,
            "tests": [
                {
                    "id": test.test_id,
                    "name": test.name,
                    "prompt": test.prompt,
                    "expected_response": test.expected_response,
                    "expected_response_hash": test.expected_response_hash,
                    "expected_contains": test.expected_contains,
                    "expected_not_contains": test.expected_not_contains,
                    "model_id": test.model_id,
                    "timeout": test.timeout,
                    "tags": test.tags,
                    "metadata": test.metadata,
                }
                for test in self._test_cases.values()
            ],
        }

        with open(path, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False)

    async def run_test(self, test_id: str) -> GoldenTestExecution | None:
        """Run a single test."""
        import time

        if self._runtime is None:
            raise RuntimeError("No runtime configured")

        test = self._test_cases.get(test_id)
        if test is None:
            return None

        start_time = time.perf_counter()

        try:
            result = await self._runtime.infer(
                prompt=test.prompt,
                temperature=0.0,  # Deterministic for golden tests
            )
            actual_response = result.content

        except Exception as e:
            return GoldenTestExecution(
                test_id=test_id,
                passed=False,
                message=f"Runtime error: {e}",
                actual_response="",
                actual_response_hash="",
                duration_ms=(time.perf_counter() - start_time) * 1000,
            )

        duration_ms = (time.perf_counter() - start_time) * 1000
        actual_hash = hashlib.sha256(actual_response.encode()).hexdigest()

        passed, message = test.validate_response(actual_response)

        return GoldenTestExecution(
            test_id=test_id,
            passed=passed,
            message=message,
            actual_response=actual_response,
            actual_response_hash=actual_hash,
            duration_ms=duration_ms,
        )

    async def run_all(
        self,
        tags: list[str] | None = None,
    ) -> GoldenSetResult:
        """Run all tests (optionally filtered by tags)."""
        import time

        if self._runtime is None:
            raise RuntimeError("No runtime configured")

        tests = self.list_tests()
        if tags:
            tests = [t for t in tests if any(tag in t.tags for tag in tags)]

        executions: list[GoldenTestExecution] = []
        start_time = time.perf_counter()

        for test in tests:
            execution = await self.run_test(test.test_id)
            if execution:
                executions.append(execution)

        duration_ms = (time.perf_counter() - start_time) * 1000

        result = GoldenSetResult(
            run_id=uuid4(),
            set_name=self._set_name,
            executions=executions,
            passed=sum(1 for e in executions if e.passed),
            failed=sum(1 for e in executions if not e.passed),
            duration_ms=duration_ms,
        )

        self._history.append(result)
        return result

    def get_history(self, limit: int = 10) -> list[GoldenSetResult]:
        """Get recent run history."""
        return self._history[-limit:]

    def create_test_from_response(
        self,
        test_id: str,
        name: str,
        prompt: str,
        response: str,
        tags: list[str] | None = None,
    ) -> GoldenTestCase:
        """
        Create a golden test from an actual response.

        Useful for capturing good responses as baseline tests.
        """
        response_hash = hashlib.sha256(response.encode()).hexdigest()

        test = GoldenTestCase(
            test_id=test_id,
            name=name,
            prompt=prompt,
            expected_response_hash=response_hash,
            tags=tags or [],
            metadata={
                "created_from_response": True,
                "created_at": datetime.utcnow().isoformat(),
            },
        )

        self.add_test(test)
        return test

    def clear_tests(self) -> int:
        """Clear all tests. Returns count cleared."""
        count = len(self._test_cases)
        self._test_cases.clear()
        return count
