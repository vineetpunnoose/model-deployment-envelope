#!/usr/bin/env python3
"""
TTS Envelope Demo

Shows how the Model Deployment Envelope protects a local TTS model.
Run: python demo/tts_demo.py
"""

import asyncio
import sys
sys.path.insert(0, 'src')

from envelope.runtime.adapters.local_tts import (
    LocalTTSAdapter, TTSRequest, TTSResponse
)

# Colors
G = '\033[92m'  # Green
R = '\033[91m'  # Red
Y = '\033[93m'  # Yellow
B = '\033[94m'  # Blue
C = '\033[96m'  # Cyan
E = '\033[0m'   # End
BOLD = '\033[1m'

def header(t): print(f"\n{BOLD}{C}{'='*60}\n{t:^60}\n{'='*60}{E}\n")
def ok(t): print(f"  {G}✓ {t}{E}")
def fail(t): print(f"  {R}✗ {t}{E}")
def info(t): print(f"  {B}ℹ {t}{E}")
def warn(t): print(f"  {Y}⚠ {t}{E}")

# Sample manifest (normally loaded from YAML)
MANIFEST = {
    "apiVersion": "envelope.ai/v1",
    "kind": "ModelManifest",
    "metadata": {
        "name": "tts-service",
        "version": "v1.0.0"
    },
    "spec": {
        "model": {
            "id": "coqui-xtts-v2",
            "backend": "local-tts"
        },
        "voices": {
            "allowed": ["en-female-1", "en-male-1", "es-female-1"],
            "restricted": ["executive-*", "celebrity-*"],
            "requireApproval": ["custom-*"]
        },
        "dataClasses": {
            "allowed": ["public_content", "notification_text", "accessibility_content"],
            "denied": ["customer_pii", "financial_data", "credentials"]
        },
        "callers": {
            "allowedRoles": ["app_service", "notification_service", "accessibility_service"],
            "denied": ["public_api", "external_partner"]
        },
        "contentFilters": {
            "enabled": True,
            "rules": [
                {
                    "id": "no-pii-speech",
                    "patterns": {
                        "ssn": r"\d{3}-\d{2}-\d{4}",
                        "credit_card": r"\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}",
                        "phone": r"\(\d{3}\)\s*\d{3}-\d{4}",
                        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
                    },
                    "action": "redact_and_warn"
                },
                {
                    "id": "no-impersonation",
                    "patterns": [
                        r"I am the CEO",
                        r"This is .+ speaking",
                        r"I am President"
                    ],
                    "action": "escalate"
                }
            ]
        },
        "rateLimits": {
            "perCaller": {
                "requestsPerMinute": 10,
                "charactersPerMinute": 5000
            },
            "global": {
                "concurrentRequests": 5
            }
        }
    }
}


async def main():
    print(f"\n{BOLD}{C}TTS ENVELOPE DEMO{E}")
    print(f"{B}Demonstrating AI governance for Text-to-Speech{E}\n")

    # Create adapter
    adapter = LocalTTSAdapter(manifest=MANIFEST)

    # ==========================================================================
    header("1. AUTHORIZED TTS REQUEST")
    # ==========================================================================

    request = TTSRequest(
        request_id="tts-001",
        text="Welcome to our service. How can I help you today?",
        voice="en-female-1",
        caller_id="app-123",
        caller_roles=["app_service"],
        data_class="public_content"
    )

    info(f"Text: '{request.text}'")
    info(f"Voice: {request.voice}")
    info(f"Caller: {request.caller_roles}")

    response = await adapter.synthesize(request)

    if response.allowed:
        ok(f"TTS ALLOWED - {response.characters_processed} chars processed")
        ok(f"Estimated duration: {response.duration_seconds:.1f}s")
    else:
        fail(f"DENIED: {response.denied_reason}")

    # ==========================================================================
    header("2. UNAUTHORIZED CALLER")
    # ==========================================================================

    request = TTSRequest(
        request_id="tts-002",
        text="Hello world",
        voice="en-female-1",
        caller_id="external-456",
        caller_roles=["external_partner"],  # DENIED role
        data_class="public_content"
    )

    info(f"Caller role: 'external_partner'")

    response = await adapter.synthesize(request)

    if not response.allowed:
        fail(f"DENIED: {response.denied_reason}")
        warn("External partners cannot use TTS service")
    else:
        ok("Allowed")

    # ==========================================================================
    header("3. RESTRICTED VOICE ACCESS")
    # ==========================================================================

    request = TTSRequest(
        request_id="tts-003",
        text="Important announcement from leadership.",
        voice="executive-ceo",  # Restricted voice
        caller_id="app-123",
        caller_roles=["app_service"],
        data_class="public_content"
    )

    info(f"Requesting voice: 'executive-ceo' (cloned executive voice)")

    response = await adapter.synthesize(request)

    if not response.allowed:
        fail(f"DENIED: {response.denied_reason}")
        warn("Cloned executive voices require special approval")
        if response.metadata.get("escalated"):
            warn(f"Request ESCALATED for review")
    else:
        ok("Allowed")

    # ==========================================================================
    header("4. PII REDACTION IN SPEECH")
    # ==========================================================================

    request = TTSRequest(
        request_id="tts-004",
        text="Your SSN is 123-45-6789 and your card is 4111-1111-1111-1111",
        voice="en-female-1",
        caller_id="app-123",
        caller_roles=["app_service"],
        data_class="public_content"
    )

    info(f"Text with PII: '{request.text}'")

    response = await adapter.synthesize(request)

    if response.allowed:
        ok("TTS ALLOWED (with redactions)")
        if response.redacted_content:
            ok(f"Redacted text: '{response.redacted_content}'")
        for warning in response.warnings:
            warn(warning)
    else:
        fail(f"DENIED: {response.denied_reason}")

    # ==========================================================================
    header("5. FORBIDDEN DATA CLASS")
    # ==========================================================================

    request = TTSRequest(
        request_id="tts-005",
        text="Your account balance is $50,000",
        voice="en-female-1",
        caller_id="app-123",
        caller_roles=["app_service"],
        data_class="financial_data"  # DENIED data class
    )

    info(f"Data class: 'financial_data'")

    response = await adapter.synthesize(request)

    if not response.allowed:
        fail(f"DENIED: {response.denied_reason}")
        warn("Financial data cannot be converted to speech")
    else:
        ok("Allowed")

    # ==========================================================================
    header("6. IMPERSONATION ATTEMPT")
    # ==========================================================================

    request = TTSRequest(
        request_id="tts-006",
        text="I am the CEO and I approve this transfer of $1 million.",
        voice="en-male-1",
        caller_id="app-123",
        caller_roles=["app_service"],
        data_class="public_content"
    )

    info(f"Text: '{request.text}'")
    warn("Potential impersonation/fraud attempt")

    response = await adapter.synthesize(request)

    if not response.allowed:
        fail(f"DENIED: {response.denied_reason}")
        if response.metadata.get("escalated"):
            fail("ESCALATED to security team")
    else:
        ok("Allowed")

    # ==========================================================================
    header("7. RATE LIMITING")
    # ==========================================================================

    info("Sending 12 rapid requests (limit: 10/minute)")

    allowed_count = 0
    denied_count = 0

    for i in range(12):
        request = TTSRequest(
            request_id=f"tts-rate-{i}",
            text=f"Test message {i}",
            voice="en-female-1",
            caller_id="rate-test-caller",
            caller_roles=["app_service"],
            data_class="public_content"
        )
        response = await adapter.synthesize(request)

        if response.allowed:
            allowed_count += 1
        else:
            denied_count += 1
            if "RATE" in str(response.denied_reason):
                break

    ok(f"Allowed: {allowed_count} requests")
    if denied_count > 0:
        fail(f"Rate limited: {denied_count} requests")
        warn("Rate limiting prevents abuse")

    # ==========================================================================
    header("8. VOICE LISTING (FILTERED)")
    # ==========================================================================

    info("Listing available voices for 'app_service' role")

    result = await adapter.list_voices(caller_roles=["app_service"])

    if result["allowed"]:
        ok(f"Available voices: {result['voices']}")
        info(f"Restricted voices hidden: {result['restricted_count']}")
    else:
        fail(f"DENIED: {result['reason']}")

    # ==========================================================================
    header("SUMMARY: TTS ENVELOPE GATES")
    # ==========================================================================

    gates = [
        ("Caller Authorization", "Who can use TTS"),
        ("Data Class Check", "What content types allowed"),
        ("Voice Access Control", "Which voices available"),
        ("Content Filtering", "PII redaction, profanity, impersonation"),
        ("Rate Limiting", "Prevent abuse/overuse"),
    ]

    for gate, desc in gates:
        ok(f"{gate}: {desc}")

    print(f"""
  {BOLD}The TTS model is wrapped in an envelope that:{E}

  • Blocks unauthorized callers from generating speech
  • Prevents speaking of PII (SSNs, credit cards, phones)
  • Restricts access to cloned/celebrity voices
  • Escalates impersonation attempts to security
  • Rate limits to prevent abuse
  • Logs all synthesis requests for audit

  All enforced by the {BOLD}platform{E}, not the TTS model.
""")


if __name__ == "__main__":
    asyncio.run(main())
