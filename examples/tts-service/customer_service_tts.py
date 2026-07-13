#!/usr/bin/env python3
"""
Customer Service TTS with Envelope

Wrap your custom-built TTS model with governance for customer service.

EDIT THE SECTION MARKED "YOUR MODEL HERE" WITH YOUR ACTUAL CODE.
"""

import sys
sys.path.insert(0, '../../src')

import asyncio
import io
import wave
import re
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import Response, JSONResponse
from pydantic import BaseModel
import uvicorn


# =============================================================================
# YOUR MODEL HERE - Replace this with your actual TTS model
# =============================================================================

class YourCustomTTS:
    """
    REPLACE THIS CLASS with your actual model.

    Just need two things:
    1. __init__: Load your model
    2. synthesize: Take text, return audio bytes
    """

    def __init__(self):
        # ---- LOAD YOUR MODEL HERE ----
        # self.model = torch.load("your_model.pt")
        # self.model.to("cuda")
        # self.model.eval()
        print("[TTS] Loading your custom model...")
        self.loaded = True

    def synthesize(self, text: str, voice_id: str = "default") -> bytes:
        """
        Generate speech from text.

        Args:
            text: Text to speak
            voice_id: Which voice/agent to use

        Returns:
            WAV audio bytes
        """
        # ---- YOUR SYNTHESIS CODE HERE ----
        # with torch.no_grad():
        #     audio = self.model.generate(text, voice=voice_id)
        # return audio_to_wav(audio)

        # Placeholder for demo
        print(f"[TTS] Generating: '{text[:50]}...'")
        return self._silent_wav(len(text) / 12)

    def _silent_wav(self, duration: float) -> bytes:
        """Generate placeholder WAV."""
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes(b'\x00\x00' * int(22050 * duration))
        return buf.getvalue()


# =============================================================================
# CUSTOMER SERVICE GOVERNANCE RULES
# =============================================================================

CUSTOMER_SERVICE_MANIFEST = {
    "apiVersion": "envelope.ai/v1",
    "metadata": {"name": "customer-service-tts", "version": "v1.0.0"},
    "spec": {
        "voices": {
            # Approved agent voices
            "allowed": [
                "agent-female-1",
                "agent-male-1",
                "agent-female-2",
                "ivr-standard",
            ],
            # Voices that need manager approval
            "restricted": [
                "manager-*",
                "executive-*",
            ],
        },

        "dataClasses": {
            "allowed": [
                "greeting",           # "Thank you for calling..."
                "hold_message",       # "Please hold..."
                "transfer_message",   # "Transferring you to..."
                "closing",            # "Is there anything else..."
                "general_info",       # Product info, hours, etc.
            ],
            "denied": [
                "customer_pii",       # Names, account numbers
                "financial_data",     # Balances, transactions
                "authentication",     # PINs, passwords
                "legal_disclaimer",   # Requires legal approval
            ],
        },

        "callers": {
            "allowedRoles": [
                "ivr_system",         # Automated IVR
                "agent_desktop",      # Agent application
                "quality_assurance",  # QA testing
            ],
            "denied": [
                "public_api",
                "unknown",
            ],
        },

        "contentFilters": {
            "enabled": True,
            "rules": [
                # Redact any PII that slips through
                {
                    "id": "redact-pii",
                    "patterns": {
                        "account_number": r"\b\d{10,16}\b",
                        "ssn": r"\d{3}-\d{2}-\d{4}",
                        "phone": r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
                        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
                        "credit_card": r"\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}",
                    },
                    "action": "redact_and_warn"
                },
                # Block profanity
                {
                    "id": "block-profanity",
                    "patterns": {
                        "profanity": r"\b(damn|shit|fuck|ass)\b",
                    },
                    "action": "reject"
                },
                # Escalate potential fraud scripts
                {
                    "id": "escalate-fraud",
                    "patterns": [
                        r"send money",
                        r"wire transfer",
                        r"gift card",
                        r"do not tell anyone",
                        r"keep this secret",
                    ],
                    "action": "escalate"
                },
            ],
        },

        "rateLimits": {
            "perCaller": {
                "requestsPerMinute": 60,
                "charactersPerMinute": 20000,
            },
        },
    }
}


# =============================================================================
# ENVELOPE ADAPTER
# =============================================================================

from envelope.runtime.adapters.local_tts import LocalTTSAdapter, TTSRequest, TTSResponse


class CustomerServiceTTSBackend:
    """Wraps your model for the envelope."""

    def __init__(self, model: YourCustomTTS):
        self.model = model

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        # Run in thread pool to not block async
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self.model.synthesize, text, voice
        )

    async def list_voices(self) -> List[str]:
        return CUSTOMER_SERVICE_MANIFEST["spec"]["voices"]["allowed"]

    def health_check(self) -> bool:
        return self.model.loaded


# =============================================================================
# AUDIT LOGGING
# =============================================================================

class AuditLog:
    """Simple audit log for customer service compliance."""

    def __init__(self):
        self.entries = []

    def log(self, request_id: str, caller: str, text: str,
            status: str, voice: str, warnings: List[str] = None):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "request_id": request_id,
            "caller": caller,
            "text_preview": text[:100] + "..." if len(text) > 100 else text,
            "voice": voice,
            "status": status,
            "warnings": warnings or [],
        }
        self.entries.append(entry)
        print(f"[AUDIT] {status}: {caller} -> {voice} ({len(text)} chars)")

    def get_recent(self, limit: int = 50) -> List[Dict]:
        return self.entries[-limit:]


audit_log = AuditLog()


# =============================================================================
# API
# =============================================================================

app = FastAPI(
    title="Customer Service TTS",
    description="TTS with governance for customer service applications"
)

# Initialize
tts_model = YourCustomTTS()
backend = CustomerServiceTTSBackend(tts_model)
envelope = LocalTTSAdapter(manifest=CUSTOMER_SERVICE_MANIFEST, backend=backend)


class TTSRequestBody(BaseModel):
    text: str
    voice: str = "agent-female-1"
    data_class: str = "general_info"


@app.post("/v1/speak")
async def speak(
    body: TTSRequestBody,
    x_caller_id: str = Header(default="unknown"),
    x_caller_role: str = Header(default="unknown"),
    x_request_id: str = Header(default=None),
):
    """
    Convert text to speech for customer service.

    Headers:
        X-Caller-ID: Identifier of calling system
        X-Caller-Role: Role (ivr_system, agent_desktop, etc.)
        X-Request-ID: Optional request tracking ID
    """
    request_id = x_request_id or f"tts-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"

    # Create envelope request
    request = TTSRequest(
        request_id=request_id,
        text=body.text,
        voice=body.voice,
        caller_id=x_caller_id,
        caller_roles=[x_caller_role],
        data_class=body.data_class,
    )

    # Process through envelope
    response = await envelope.synthesize(request)

    # Audit log
    audit_log.log(
        request_id=request_id,
        caller=f"{x_caller_id}:{x_caller_role}",
        text=body.text,
        status="ALLOWED" if response.allowed else "DENIED",
        voice=body.voice,
        warnings=response.warnings,
    )

    # Handle denial
    if not response.allowed:
        return JSONResponse(
            status_code=403,
            content={
                "error": "Request denied by governance policy",
                "reason": response.denied_reason,
                "request_id": request_id,
            }
        )

    # Handle escalation
    if response.metadata.get("escalated"):
        return JSONResponse(
            status_code=202,
            content={
                "status": "escalated",
                "message": "Request requires human review",
                "request_id": request_id,
                "reason": response.metadata.get("escalation_reason"),
            }
        )

    # Return audio
    return Response(
        content=response.audio_data,
        media_type="audio/wav",
        headers={
            "X-Request-ID": request_id,
            "X-Duration": str(response.duration_seconds),
            "X-Warnings": "; ".join(response.warnings) if response.warnings else "none",
        }
    )


@app.get("/v1/voices")
async def list_voices(x_caller_role: str = Header(default="ivr_system")):
    """List available voices for the caller."""
    result = await envelope.list_voices([x_caller_role])
    return result


@app.get("/v1/audit")
async def get_audit(limit: int = 50):
    """Get recent audit log entries."""
    return {"entries": audit_log.get_recent(limit)}


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "model_loaded": tts_model.loaded,
        "timestamp": datetime.now().isoformat(),
    }


# =============================================================================
# RUN
# =============================================================================

if __name__ == "__main__":
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║       🎧 Customer Service TTS with Governance            ║
    ╠══════════════════════════════════════════════════════════╣
    ║                                                          ║
    ║  Your TTS model is protected by:                         ║
    ║                                                          ║
    ║  ✓ Caller authorization (IVR, Agent Desktop only)        ║
    ║  ✓ Approved voices only (no exec impersonation)          ║
    ║  ✓ PII auto-redaction (SSN, account #, phone)            ║
    ║  ✓ Profanity blocking                                    ║
    ║  ✓ Fraud script detection → escalation                   ║
    ║  ✓ Full audit logging                                    ║
    ║                                                          ║
    ║  API: http://localhost:8001                              ║
    ║  Audit: http://localhost:8001/v1/audit                   ║
    ║                                                          ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    print("\nExample requests:\n")
    print('  # Allowed - IVR greeting')
    print('  curl -X POST http://localhost:8001/v1/speak \\')
    print('    -H "Content-Type: application/json" \\')
    print('    -H "X-Caller-Role: ivr_system" \\')
    print('    -d \'{"text": "Thank you for calling. How can I help?"}\' \\')
    print('    --output greeting.wav')
    print()
    print('  # Denied - unauthorized caller')
    print('  curl -X POST http://localhost:8001/v1/speak \\')
    print('    -H "X-Caller-Role: public_api" \\')
    print('    -d \'{"text": "Hello"}\'')
    print()
    print('  # PII redacted automatically')
    print('  curl -X POST http://localhost:8001/v1/speak \\')
    print('    -H "X-Caller-Role: ivr_system" \\')
    print('    -d \'{"text": "Your account 1234567890 balance is..."}\' \\')
    print('    --output redacted.wav')
    print()

    uvicorn.run(app, host="0.0.0.0", port=8001)
