"""
Verification Routes

Conformance testing and verification endpoints.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Depends, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from envelope.verification.conformance import ConformanceHarness, create_standard_tests
from envelope.verification.golden_set import GoldenSetRunner
from envelope.verification.report import ReportGenerator


router = APIRouter()


# Module-level harness for demonstration
_harness: ConformanceHarness | None = None
_golden_runner: GoldenSetRunner | None = None


def get_harness() -> ConformanceHarness:
    """Get or create conformance harness."""
    global _harness
    if _harness is None:
        _harness = ConformanceHarness()
        _harness.register_tests(create_standard_tests())
    return _harness


def get_golden_runner() -> GoldenSetRunner:
    """Get or create golden set runner."""
    global _golden_runner
    if _golden_runner is None:
        _golden_runner = GoldenSetRunner()
    return _golden_runner


def get_envelope(request: Request):
    """Dependency to get envelope from request state."""
    return request.state.envelope


@router.get("/conformance/tests")
async def list_conformance_tests(
    category: str | None = None,
    tag: str | None = None,
):
    """List available conformance tests."""
    harness = get_harness()
    tests = harness.list_tests(category=category, tag=tag)

    return {
        "count": len(tests),
        "tests": [
            {
                "id": t.test_id,
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "tags": t.tags,
                "enabled": t.enabled,
            }
            for t in tests
        ],
    }


@router.post("/conformance/run")
async def run_conformance_tests(
    request: Request,
    categories: list[str] = Query(default=[]),
    tags: list[str] = Query(default=[]),
    envelope=Depends(get_envelope),
):
    """Run conformance tests."""
    harness = get_harness()

    # Build context with envelope components if available
    context: dict[str, Any] = {}
    if envelope:
        context["ingress_gate"] = envelope.ingress_gate
        context["tool_gate"] = envelope.tool_gate
        context["egress_gate"] = envelope.egress_gate
        context["escalation_enforcer"] = envelope.escalation_enforcer
        context["key_broker"] = envelope.key_broker

    result = await harness.run_all(
        context=context,
        categories=categories if categories else None,
        tags=tags if tags else None,
    )

    return {
        "run_id": str(result.run_id),
        "success": result.success,
        "passed": result.passed,
        "failed": result.failed,
        "skipped": result.skipped,
        "errors": result.errors,
        "pass_rate": result.pass_rate,
        "duration_ms": result.duration_ms,
        "executions": [
            {
                "test_id": e.test_id,
                "result": e.result.value,
                "message": e.message,
                "duration_ms": e.duration_ms,
            }
            for e in result.executions
        ],
    }


@router.post("/conformance/run/{test_id}")
async def run_single_test(
    test_id: str,
    request: Request,
    envelope=Depends(get_envelope),
):
    """Run a single conformance test."""
    harness = get_harness()

    context: dict[str, Any] = {}
    if envelope:
        context["ingress_gate"] = envelope.ingress_gate
        context["tool_gate"] = envelope.tool_gate
        context["egress_gate"] = envelope.egress_gate
        context["escalation_enforcer"] = envelope.escalation_enforcer
        context["key_broker"] = envelope.key_broker

    execution = await harness.run_test(test_id, context)

    return {
        "test_id": execution.test_id,
        "result": execution.result.value,
        "message": execution.message,
        "duration_ms": execution.duration_ms,
    }


@router.get("/conformance/history")
async def get_conformance_history(
    limit: int = 10,
):
    """Get conformance test history."""
    harness = get_harness()
    history = harness.get_history(limit=limit)

    return {
        "count": len(history),
        "runs": [
            {
                "run_id": str(r.run_id),
                "timestamp": r.timestamp.isoformat(),
                "success": r.success,
                "passed": r.passed,
                "failed": r.failed,
                "pass_rate": r.pass_rate,
            }
            for r in history
        ],
    }


@router.get("/golden/tests")
async def list_golden_tests(
    tag: str | None = None,
):
    """List golden set tests."""
    runner = get_golden_runner()
    tests = runner.list_tests(tag=tag)

    return {
        "count": len(tests),
        "tests": [
            {
                "id": t.test_id,
                "name": t.name,
                "tags": t.tags,
                "has_expected_response": t.expected_response is not None,
                "has_expected_hash": t.expected_response_hash is not None,
            }
            for t in tests
        ],
    }


class AddGoldenTestRequest(BaseModel):
    """Request to add a golden test."""
    test_id: str
    name: str
    prompt: str
    expected_response: str | None = None
    expected_contains: list[str] = []
    expected_not_contains: list[str] = []
    tags: list[str] = []


@router.post("/golden/tests")
async def add_golden_test(
    body: AddGoldenTestRequest,
):
    """Add a golden test."""
    from envelope.verification.golden_set import GoldenTestCase
    import hashlib

    runner = get_golden_runner()

    expected_hash = None
    if body.expected_response:
        expected_hash = hashlib.sha256(body.expected_response.encode()).hexdigest()

    test = GoldenTestCase(
        test_id=body.test_id,
        name=body.name,
        prompt=body.prompt,
        expected_response=body.expected_response,
        expected_response_hash=expected_hash,
        expected_contains=body.expected_contains,
        expected_not_contains=body.expected_not_contains,
        tags=body.tags,
    )

    runner.add_test(test)

    return {"message": "Test added", "test_id": body.test_id}


@router.post("/golden/run")
async def run_golden_tests(
    request: Request,
    tags: list[str] = Query(default=[]),
    envelope=Depends(get_envelope),
):
    """Run golden set tests."""
    runner = get_golden_runner()

    if envelope and envelope.runtime:
        runner.set_runtime(envelope.runtime)
    else:
        raise HTTPException(
            status_code=503,
            detail="Runtime not available for golden tests",
        )

    result = await runner.run_all(tags=tags if tags else None)

    return {
        "run_id": str(result.run_id),
        "set_name": result.set_name,
        "success": result.success,
        "passed": result.passed,
        "failed": result.failed,
        "pass_rate": result.pass_rate,
        "duration_ms": result.duration_ms,
        "executions": [
            {
                "test_id": e.test_id,
                "passed": e.passed,
                "message": e.message,
                "duration_ms": e.duration_ms,
            }
            for e in result.executions
        ],
    }


@router.get("/report", response_class=HTMLResponse)
async def get_conformance_report(
    request: Request,
    format: str = "html",
    envelope=Depends(get_envelope),
):
    """
    Generate conformance report.

    Format: html, json, or markdown
    """
    harness = get_harness()
    golden_runner = get_golden_runner()

    manifest_name = ""
    manifest_version = ""
    if envelope:
        manifest_name = envelope.manifest.metadata.name
        manifest_version = envelope.manifest.metadata.version

    generator = ReportGenerator(
        manifest_name=manifest_name,
        manifest_version=manifest_version,
    )

    # Get latest results
    conformance_history = harness.get_history(limit=1)
    golden_history = golden_runner.get_history(limit=5)

    system_status = {}
    if envelope:
        system_status = {
            "lifecycle": envelope.lifecycle.state_machine.state.name,
            "runtime_healthy": await envelope.runtime.health() if envelope.runtime else False,
        }

    report = generator.generate(
        conformance_results=conformance_history[0] if conformance_history else None,
        golden_set_results=golden_history,
        system_status=system_status,
    )

    if format == "json":
        from fastapi.responses import JSONResponse
        return JSONResponse(content=report.to_dict())

    elif format == "markdown":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            content=generator.render_markdown(report),
            media_type="text/markdown",
        )

    else:
        return HTMLResponse(content=generator.render_html(report))


@router.get("/replay/{request_id}")
async def replay_request(
    request_id: str,
    request: Request,
    envelope=Depends(get_envelope),
):
    """
    Replay a historical request.

    Fetches the original request from provenance and re-runs it.
    """
    if envelope is None:
        raise HTTPException(status_code=503, detail="Envelope not initialized")

    from envelope.record.reproduction import ReproductionEngine

    try:
        rid = UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID")

    engine = ReproductionEngine(
        store=envelope.provenance_store,
        inference_engine=envelope.runtime,
    )

    try:
        result = await engine.replay(rid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return {
        "request_id": str(result.request_id),
        "exact_match": result.exact_match,
        "similarity_score": result.similarity_score,
        "duration_ms": result.duration_ms,
        "differences": result.differences,
        "original_response_hash": result.original_record.response_hash,
        "replayed_response_hash": result.replayed_response_hash,
    }
