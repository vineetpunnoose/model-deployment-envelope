"""
Admin Routes

Administration and monitoring endpoints.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel


router = APIRouter()


def get_envelope(request: Request):
    """Dependency to get envelope from request state."""
    envelope = request.state.envelope
    if envelope is None:
        raise HTTPException(status_code=503, detail="Envelope not initialized")
    return envelope


@router.get("/manifest")
async def get_manifest(
    request: Request,
    envelope=Depends(get_envelope),
):
    """Get the current manifest."""
    return envelope.manifest.to_dict()


@router.get("/status")
async def get_status(
    request: Request,
    envelope=Depends(get_envelope),
):
    """Get system status."""
    runtime_healthy = False
    if envelope.runtime:
        runtime_healthy = await envelope.runtime.health()

    return {
        "lifecycle": envelope.lifecycle.state_machine.to_dict(),
        "runtime_healthy": runtime_healthy,
        "manifest": {
            "name": envelope.manifest.metadata.name,
            "version": envelope.manifest.metadata.version,
        },
        "gates": {
            "ingress": "active",
            "tool": "active",
            "egress": "active",
            "escalation": "active",
        },
    }


@router.get("/provenance")
async def list_provenance(
    request: Request,
    limit: int = 20,
    caller_id: str | None = None,
    model_id: str | None = None,
    envelope=Depends(get_envelope),
):
    """List provenance records."""
    records = await envelope.provenance_store.query(
        caller_id=caller_id,
        model_id=model_id,
        limit=limit,
    )

    return {
        "count": len(records),
        "records": [r.to_dict() for r in records],
    }


@router.get("/provenance/{request_id}")
async def get_provenance(
    request_id: str,
    request: Request,
    envelope=Depends(get_envelope),
):
    """Get a specific provenance record."""
    try:
        rid = UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid request ID")

    record = await envelope.provenance_store.retrieve(rid)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")

    return record.to_dict()


@router.get("/escalations")
async def list_escalations(
    request: Request,
    status: str | None = None,
    limit: int = 50,
    envelope=Depends(get_envelope),
):
    """List escalation cases."""
    from envelope.handoff.escalation import CaseStatus

    status_filter = None
    if status:
        try:
            status_filter = CaseStatus(status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

    cases = await envelope.escalation_sink.list_cases(
        status=status_filter,
        limit=limit,
    )

    return {
        "count": len(cases),
        "cases": [c.to_dict() for c in cases],
    }


@router.get("/escalations/{case_id}")
async def get_escalation(
    case_id: str,
    request: Request,
    envelope=Depends(get_envelope),
):
    """Get a specific escalation case."""
    try:
        cid = UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID")

    case = await envelope.escalation_sink.get_case(cid)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    return case.to_dict()


class ResolveEscalationRequest(BaseModel):
    """Request to resolve an escalation."""
    resolution: str


@router.post("/escalations/{case_id}/resolve")
async def resolve_escalation(
    case_id: str,
    body: ResolveEscalationRequest,
    request: Request,
    envelope=Depends(get_envelope),
):
    """Resolve an escalation case."""
    try:
        cid = UUID(case_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid case ID")

    case = await envelope.escalation_sink.resolve_case(cid, body.resolution)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    return case.to_dict()


@router.get("/hashchain/verify")
async def verify_hashchain(
    request: Request,
    count: int = 100,
    envelope=Depends(get_envelope),
):
    """Verify hash chain integrity."""
    if envelope.hashchain is None:
        raise HTTPException(status_code=503, detail="Hash chain not initialized")

    valid, entries, error = await envelope.hashchain.verify_chain(count=count)

    return {
        "valid": valid,
        "entries_verified": len(entries),
        "error": str(error) if error else None,
    }


@router.get("/encryption/subjects")
async def list_encrypted_subjects(
    request: Request,
    envelope=Depends(get_envelope),
):
    """List subjects with encryption keys."""
    subjects = envelope.encryption.get_subject_ids()

    return {
        "count": len(subjects),
        "subjects": subjects,
    }


@router.delete("/encryption/subjects/{subject_id}")
async def erase_subject(
    subject_id: str,
    request: Request,
    envelope=Depends(get_envelope),
):
    """
    Erase a subject's encryption key.

    This is the GDPR erasure endpoint - permanently removes
    the ability to decrypt the subject's data.
    """
    success = envelope.encryption.erase_subject(subject_id)

    if not success:
        raise HTTPException(status_code=404, detail="Subject not found")

    # Also revoke any key grants
    envelope.key_broker.revoke_all_for_subject(subject_id)

    return {"message": f"Subject {subject_id} erased", "success": True}


@router.get("/lifecycle")
async def get_lifecycle(
    request: Request,
    envelope=Depends(get_envelope),
):
    """Get lifecycle state machine status."""
    return envelope.lifecycle.state_machine.to_dict()


@router.post("/lifecycle/drain")
async def drain_lifecycle(
    request: Request,
    envelope=Depends(get_envelope),
):
    """Initiate graceful shutdown (drain)."""
    success = await envelope.lifecycle.drain()

    if not success:
        raise HTTPException(
            status_code=400,
            detail="Cannot drain from current state",
        )

    return {"message": "Drain initiated", "state": envelope.lifecycle.state.name}


@router.get("/key-broker/grants")
async def list_grants(
    request: Request,
    subject_id: str | None = None,
    placement_id: str | None = None,
    envelope=Depends(get_envelope),
):
    """List active key grants."""
    grants = envelope.key_broker.get_active_grants(
        subject_id=subject_id,
        placement_id=placement_id,
    )

    return {
        "count": len(grants),
        "grants": [g.to_dict() for g in grants],
    }


@router.get("/key-broker/stats")
async def get_grant_stats(
    request: Request,
    envelope=Depends(get_envelope),
):
    """Get key grant statistics."""
    return envelope.key_broker.get_grant_stats()
