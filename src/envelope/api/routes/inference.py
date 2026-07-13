"""
Inference Routes

Model inference endpoints with full envelope enforcement.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field

from envelope.types import CallerIdentity, InferenceRequest, InferenceResponse


router = APIRouter()


class InferenceRequestModel(BaseModel):
    """Request model for inference."""
    prompt: str = Field(..., description="The input prompt")
    model_id: str | None = Field(None, description="Optional model ID override")
    tools: list[str] | None = Field(None, description="Tools to enable")
    data_classes: list[str] | None = Field(None, description="Data classes in request")
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int | None = Field(None, ge=1)
    caller_id: str | None = Field(None, description="Caller identifier")
    caller_roles: list[str] | None = Field(None, description="Caller roles")


class InferenceResponseModel(BaseModel):
    """Response model for inference."""
    request_id: str
    content: str
    tool_calls: list[dict[str, Any]] = []
    finish_reason: str = "stop"
    usage: dict[str, int] = {}
    withheld: bool = False
    escalated: bool = False
    metadata: dict[str, Any] = {}


class ToolCallRequestModel(BaseModel):
    """Request model for tool invocation."""
    tool_name: str
    arguments: dict[str, Any]
    caller_id: str | None = None
    caller_roles: list[str] | None = None


class ToolCallResponseModel(BaseModel):
    """Response model for tool invocation."""
    tool_name: str
    result: Any
    success: bool
    duration_ms: float
    error: str | None = None


def get_envelope(request: Request):
    """Dependency to get envelope from request state."""
    envelope = request.state.envelope
    if envelope is None:
        raise HTTPException(status_code=503, detail="Envelope not initialized")
    return envelope


@router.post("/infer", response_model=InferenceResponseModel)
async def infer(
    request_body: InferenceRequestModel,
    request: Request,
    envelope=Depends(get_envelope),
):
    """
    Run model inference with full envelope enforcement.

    This endpoint:
    1. Validates the request through ingress gate
    2. Runs inference through the runtime
    3. Validates response through egress gate
    4. Checks escalation conditions
    5. Records provenance

    Returns InferenceResponseModel with results or withheld indication.
    """
    import time

    start_time = time.perf_counter()

    # Build caller identity
    caller = CallerIdentity(
        caller_id=request_body.caller_id or "anonymous",
        roles=frozenset(request_body.caller_roles or []),
    )

    # Build inference request
    inf_request = InferenceRequest.create(
        caller=caller,
        model_id=request_body.model_id or envelope.manifest.model_id,
        prompt=request_body.prompt,
        tools_requested=frozenset(request_body.tools or []),
        data_classes=frozenset(request_body.data_classes or []),
    )

    # Ingress gate check
    ingress_result = envelope.ingress_gate.check(inf_request)
    if not ingress_result.allowed:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Ingress denied",
                "reason": ingress_result.decision.reason,
                "rule": ingress_result.decision.rule_id,
            },
        )

    # Run inference
    if envelope.runtime is None:
        raise HTTPException(status_code=503, detail="Runtime not available")

    # Get tool schemas if tools requested
    tools = None
    if request_body.tools:
        tools = envelope.tool_gate.get_tool_schema(format="openai")

    result = await envelope.runtime.infer(
        prompt=request_body.prompt,
        tools=tools,
        temperature=request_body.temperature,
        max_tokens=request_body.max_tokens,
    )

    # Build response
    inf_response = InferenceResponse(
        request_id=inf_request.request_id,
        content=result.content,
        tool_calls=[
            {"name": tc.tool_name, "arguments": tc.arguments}
            for tc in result.tool_calls
        ],
    )

    # Egress gate check
    egress_result = envelope.egress_gate.check(
        inf_response,
        context=request_body.prompt,
        allowed_data_classes=frozenset(request_body.data_classes or []),
    )

    if not egress_result.allowed:
        # Create blocked response
        inf_response = envelope.egress_gate.create_blocked_response(
            inf_response, egress_result.violations
        )

    # Check escalation
    escalation_decision = envelope.escalation_enforcer.evaluate(
        inf_request,
        inf_response,
        context={"detected_data_classes": ingress_result.detected_data_classes},
    )

    if escalation_decision.should_escalate:
        # Withhold response and escalate
        inf_response = envelope.escalation_enforcer.create_withheld_response(
            inf_response, escalation_decision
        )

        # Create escalation record
        await envelope.escalation_sink.escalate(
            request_id=inf_request.request_id,
            context={
                "caller": caller.caller_id,
                "model_id": inf_request.model_id,
            },
            reason=escalation_decision.reason,
            evidence_refs=escalation_decision.evidence_refs,
        )

    # Record provenance
    from envelope.record.provenance import ProvenanceRecord

    duration_ms = (time.perf_counter() - start_time) * 1000

    provenance = ProvenanceRecord.create(
        caller_id=caller.caller_id,
        caller_roles=list(caller.roles),
        model_id=inf_request.model_id,
        model_version=envelope.manifest.metadata.version,
        placement_id=envelope.manifest.spec.placement.current_placement or "default",
        prompt=request_body.prompt,
        response=inf_response.content,
        data_classes=list(inf_request.data_classes),
        escalated=inf_response.escalated,
        withheld=inf_response.withheld,
        duration_ms=duration_ms,
    )

    if envelope.hashchain:
        await envelope.hashchain.append(provenance)

    return InferenceResponseModel(
        request_id=str(inf_response.request_id),
        content=inf_response.content,
        tool_calls=inf_response.tool_calls,
        finish_reason=result.finish_reason,
        usage=result.usage,
        withheld=inf_response.withheld,
        escalated=inf_response.escalated,
        metadata={
            "duration_ms": duration_ms,
            "warnings": ingress_result.warnings,
        },
    )


@router.post("/tools/{tool_name}", response_model=ToolCallResponseModel)
async def invoke_tool(
    tool_name: str,
    request_body: ToolCallRequestModel,
    request: Request,
    envelope=Depends(get_envelope),
):
    """
    Invoke a tool with envelope enforcement.

    Tool must be registered and allowed in manifest.
    """
    from envelope.types import ToolCall

    caller = CallerIdentity(
        caller_id=request_body.caller_id or "anonymous",
        roles=frozenset(request_body.caller_roles or []),
    )

    tool_call = ToolCall(
        tool_name=tool_name,
        arguments=request_body.arguments,
    )

    try:
        result, record = await envelope.tool_gate.execute(tool_call, caller)

        return ToolCallResponseModel(
            tool_name=tool_name,
            result=result,
            success=True,
            duration_ms=record.duration_ms,
        )

    except Exception as e:
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Tool invocation failed",
                "reason": str(e),
            },
        )


@router.get("/tools")
async def list_tools(
    request: Request,
    envelope=Depends(get_envelope),
):
    """List available tools."""
    tools = envelope.tool_gate.get_allowed_tools()

    return {
        "tools": [
            {
                "name": t.name,
                "type": t.type,
                "description": t.description,
                "schema": t.schema,
            }
            for t in tools
        ]
    }


@router.get("/model")
async def get_model_info(
    request: Request,
    envelope=Depends(get_envelope),
):
    """Get model information."""
    if envelope.runtime is None:
        return {
            "model_id": envelope.manifest.model_id,
            "backend": envelope.manifest.backend,
            "status": "not_loaded",
        }

    info = await envelope.runtime.info()

    return {
        "model_id": info.model_id,
        "version": info.version,
        "backend": info.backend,
        "capabilities": info.capabilities,
        "context_length": info.context_length,
        "status": envelope.lifecycle.state.name,
    }
