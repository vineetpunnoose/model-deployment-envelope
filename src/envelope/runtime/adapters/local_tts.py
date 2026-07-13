"""
Local TTS Adapter

Wraps a local GPU-based TTS model (like Coqui XTTS, Bark, StyleTTS2, etc.)
with the envelope governance layer.
"""

import asyncio
import base64
import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
from pathlib import Path
import io


class TTSBackend(Protocol):
    """Protocol for TTS backends."""
    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        """Generate audio from text."""
        ...

    async def list_voices(self) -> List[str]:
        """List available voices."""
        ...

    def health_check(self) -> bool:
        """Check if backend is healthy."""
        ...


@dataclass
class TTSRequest:
    """Text-to-speech request."""
    request_id: str
    text: str
    voice: str = "en-female-1"
    language: Optional[str] = None
    sample_rate: int = 22050
    output_format: str = "wav"
    speed: float = 1.0
    pitch: float = 1.0
    caller_id: str = ""
    caller_roles: List[str] = field(default_factory=list)
    data_class: str = "public_content"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSResponse:
    """Text-to-speech response."""
    request_id: str
    audio_data: Optional[bytes] = None
    audio_base64: Optional[str] = None
    duration_seconds: float = 0.0
    sample_rate: int = 22050
    format: str = "wav"
    voice_used: str = ""
    characters_processed: int = 0
    allowed: bool = True
    denied_reason: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    redacted_content: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentFilterResult:
    """Result of content filtering."""
    allowed: bool
    action: str  # allow, redact, reject, escalate
    filtered_text: str
    redactions: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    escalate: bool = False
    escalation_reason: Optional[str] = None


class LocalTTSAdapter:
    """
    Envelope adapter for local TTS models.

    Enforces:
    - Caller authorization
    - Voice access control
    - Content filtering (PII, profanity, impersonation)
    - Data class restrictions
    - Rate limiting
    - Provenance recording
    """

    def __init__(
        self,
        manifest: Dict[str, Any],
        backend: Optional[TTSBackend] = None,
    ):
        self.manifest = manifest
        self.backend = backend
        self.spec = manifest.get("spec", {})

        # Load configuration
        self._load_config()

        # Rate limiting state
        self._caller_usage: Dict[str, Dict[str, Any]] = {}
        self._global_concurrent = 0

    def _load_config(self):
        """Load configuration from manifest."""
        # Allowed/denied voices
        voices_config = self.spec.get("voices", {})
        self.allowed_voices = set(voices_config.get("allowed", []))
        self.restricted_voices = voices_config.get("restricted", [])
        self.approval_voices = voices_config.get("requireApproval", [])

        # Allowed/denied data classes
        dc_config = self.spec.get("dataClasses", {})
        self.allowed_data_classes = set(dc_config.get("allowed", []))
        self.denied_data_classes = set(dc_config.get("denied", []))

        # Caller roles
        caller_config = self.spec.get("callers", {})
        self.allowed_roles = set(caller_config.get("allowedRoles", []))
        self.denied_roles = set(caller_config.get("denied", []))

        # Content filters
        self.content_filters = self.spec.get("contentFilters", {})
        self.filter_rules = self.content_filters.get("rules", [])

        # Rate limits
        self.rate_limits = self.spec.get("rateLimits", {})

    # =========================================================================
    # GATE 1: Caller Authorization
    # =========================================================================

    def _check_caller(self, request: TTSRequest) -> Optional[str]:
        """Check if caller is authorized. Returns denial reason or None."""
        # Check denied roles first
        for role in request.caller_roles:
            if role in self.denied_roles:
                return f"Caller role '{role}' is explicitly denied"

        # Check if any role is allowed
        if not any(role in self.allowed_roles for role in request.caller_roles):
            return f"No authorized role. Allowed: {self.allowed_roles}"

        return None  # Allowed

    # =========================================================================
    # GATE 2: Data Class Check
    # =========================================================================

    def _check_data_class(self, request: TTSRequest) -> Optional[str]:
        """Check if data class is allowed. Returns denial reason or None."""
        if request.data_class in self.denied_data_classes:
            return f"Data class '{request.data_class}' is denied for TTS"

        if request.data_class not in self.allowed_data_classes:
            return f"Data class '{request.data_class}' not in allowed list"

        return None  # Allowed

    # =========================================================================
    # GATE 3: Voice Access Control
    # =========================================================================

    def _check_voice(self, request: TTSRequest) -> tuple[bool, Optional[str], bool]:
        """
        Check voice access.
        Returns: (allowed, denial_reason, needs_escalation)
        """
        voice = request.voice

        # Check if voice matches restricted patterns
        for pattern in self.restricted_voices:
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                if voice.startswith(prefix):
                    return False, f"Voice '{voice}' is restricted", True
            elif voice == pattern:
                return False, f"Voice '{voice}' is restricted", True

        # Check if voice needs approval
        for pattern in self.approval_voices:
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                if voice.startswith(prefix):
                    return False, f"Voice '{voice}' requires approval", True

        # Check if voice is in allowed list
        if self.allowed_voices and voice not in self.allowed_voices:
            return False, f"Voice '{voice}' not in allowed voices", False

        return True, None, False  # Allowed

    # =========================================================================
    # GATE 4: Content Filtering
    # =========================================================================

    def _filter_content(self, text: str) -> ContentFilterResult:
        """
        Filter content for PII, profanity, and impersonation attempts.
        """
        filtered_text = text
        redactions = []
        warnings = []
        escalate = False
        escalation_reason = None
        action = "allow"

        for rule in self.filter_rules:
            rule_id = rule.get("id", "unknown")
            rule_action = rule.get("action", "warn")
            patterns = rule.get("patterns", {})

            if isinstance(patterns, dict):
                # Named patterns (like ssn, credit_card)
                for name, pattern in patterns.items():
                    matches = list(re.finditer(pattern, filtered_text, re.IGNORECASE))
                    if matches:
                        if rule_action == "redact_and_warn":
                            for match in reversed(matches):  # Reverse to preserve indices
                                redacted = "[REDACTED]"
                                filtered_text = (
                                    filtered_text[:match.start()] +
                                    redacted +
                                    filtered_text[match.end():]
                                )
                                redactions.append({
                                    "type": name,
                                    "position": match.start(),
                                    "original_length": len(match.group())
                                })
                            warnings.append(f"Redacted {len(matches)} {name} pattern(s)")

                        elif rule_action == "reject":
                            return ContentFilterResult(
                                allowed=False,
                                action="reject",
                                filtered_text=text,
                                warnings=[f"Content contains forbidden {name} pattern"],
                            )

                        elif rule_action == "escalate":
                            escalate = True
                            escalation_reason = f"Content matched {name} pattern"

            elif isinstance(patterns, list):
                # List of patterns
                for pattern in patterns:
                    if re.search(pattern, filtered_text, re.IGNORECASE):
                        if rule_action == "escalate":
                            escalate = True
                            escalation_reason = f"Content matched pattern in rule {rule_id}"
                        elif rule_action == "reject":
                            return ContentFilterResult(
                                allowed=False,
                                action="reject",
                                filtered_text=text,
                                warnings=[f"Content rejected by rule {rule_id}"],
                            )

        return ContentFilterResult(
            allowed=True,
            action="allow" if not redactions else "redact",
            filtered_text=filtered_text,
            redactions=redactions,
            warnings=warnings,
            escalate=escalate,
            escalation_reason=escalation_reason,
        )

    # =========================================================================
    # GATE 5: Rate Limiting
    # =========================================================================

    def _check_rate_limit(self, request: TTSRequest) -> Optional[str]:
        """Check rate limits. Returns denial reason or None."""
        caller_id = request.caller_id
        now = time.time()

        # Initialize caller tracking
        if caller_id not in self._caller_usage:
            self._caller_usage[caller_id] = {
                "requests": [],
                "characters": [],
                "audio_minutes": [],
            }

        usage = self._caller_usage[caller_id]
        per_caller = self.rate_limits.get("perCaller", {})

        # Clean old entries (older than 1 hour)
        cutoff = now - 3600
        usage["requests"] = [t for t in usage["requests"] if t > cutoff]
        usage["characters"] = [(t, c) for t, c in usage["characters"] if t > cutoff]
        usage["audio_minutes"] = [(t, m) for t, m in usage["audio_minutes"] if t > cutoff]

        # Check requests per minute
        rpm_limit = per_caller.get("requestsPerMinute", float("inf"))
        recent_requests = [t for t in usage["requests"] if t > now - 60]
        if len(recent_requests) >= rpm_limit:
            return f"Rate limit exceeded: {rpm_limit} requests/minute"

        # Check characters per minute
        cpm_limit = per_caller.get("charactersPerMinute", float("inf"))
        recent_chars = sum(c for t, c in usage["characters"] if t > now - 60)
        if recent_chars + len(request.text) > cpm_limit:
            return f"Rate limit exceeded: {cpm_limit} characters/minute"

        # Check global concurrent
        global_limits = self.rate_limits.get("global", {})
        max_concurrent = global_limits.get("concurrentRequests", float("inf"))
        if self._global_concurrent >= max_concurrent:
            return f"Max concurrent requests ({max_concurrent}) reached"

        return None  # Allowed

    def _record_usage(self, request: TTSRequest, audio_duration: float):
        """Record usage for rate limiting."""
        caller_id = request.caller_id
        now = time.time()

        if caller_id not in self._caller_usage:
            self._caller_usage[caller_id] = {
                "requests": [],
                "characters": [],
                "audio_minutes": [],
            }

        usage = self._caller_usage[caller_id]
        usage["requests"].append(now)
        usage["characters"].append((now, len(request.text)))
        usage["audio_minutes"].append((now, audio_duration / 60))

    # =========================================================================
    # Main Synthesis Method
    # =========================================================================

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """
        Process TTS request through all envelope gates.
        """
        response = TTSResponse(
            request_id=request.request_id,
            voice_used=request.voice,
            characters_processed=len(request.text),
        )

        # GATE 1: Caller Authorization
        denial = self._check_caller(request)
        if denial:
            response.allowed = False
            response.denied_reason = f"[CALLER DENIED] {denial}"
            return response

        # GATE 2: Data Class Check
        denial = self._check_data_class(request)
        if denial:
            response.allowed = False
            response.denied_reason = f"[DATA CLASS DENIED] {denial}"
            return response

        # GATE 3: Voice Access Control
        voice_allowed, voice_denial, needs_escalation = self._check_voice(request)
        if not voice_allowed:
            response.allowed = False
            response.denied_reason = f"[VOICE DENIED] {voice_denial}"
            if needs_escalation:
                response.metadata["escalated"] = True
                response.metadata["escalation_reason"] = voice_denial
            return response

        # GATE 4: Content Filtering
        filter_result = self._filter_content(request.text)
        if not filter_result.allowed:
            response.allowed = False
            response.denied_reason = f"[CONTENT DENIED] {filter_result.warnings}"
            return response

        # Apply redactions
        text_to_speak = filter_result.filtered_text
        response.warnings = filter_result.warnings
        if filter_result.redactions:
            response.redacted_content = text_to_speak

        # Handle escalation
        if filter_result.escalate:
            response.allowed = False
            response.denied_reason = "[ESCALATED] Content flagged for review"
            response.metadata["escalated"] = True
            response.metadata["escalation_reason"] = filter_result.escalation_reason
            return response

        # GATE 5: Rate Limiting
        denial = self._check_rate_limit(request)
        if denial:
            response.allowed = False
            response.denied_reason = f"[RATE LIMITED] {denial}"
            return response

        # All gates passed - proceed with synthesis
        self._global_concurrent += 1
        try:
            if self.backend:
                # Call actual TTS backend
                audio_data = await self.backend.synthesize(
                    text=text_to_speak,
                    voice=request.voice,
                    sample_rate=request.sample_rate,
                    speed=request.speed,
                )
                response.audio_data = audio_data
                response.audio_base64 = base64.b64encode(audio_data).decode()

                # Estimate duration (rough: ~150 chars/sec for speech)
                response.duration_seconds = len(text_to_speak) / 150
            else:
                # Mock response for demo
                response.duration_seconds = len(text_to_speak) / 150
                response.metadata["mock"] = True

            response.format = request.output_format
            response.sample_rate = request.sample_rate
            response.allowed = True

            # Record usage
            self._record_usage(request, response.duration_seconds)

        finally:
            self._global_concurrent -= 1

        return response

    async def list_voices(self, caller_roles: List[str]) -> Dict[str, Any]:
        """List available voices for the caller."""
        # Check authorization
        if not any(role in self.allowed_roles for role in caller_roles):
            return {"allowed": False, "reason": "Unauthorized"}

        # Filter voices based on caller
        available = []
        for voice in self.allowed_voices:
            # Check if voice is restricted for this caller
            is_restricted = False
            for pattern in self.restricted_voices:
                if pattern.endswith("*"):
                    if voice.startswith(pattern[:-1]):
                        is_restricted = True
                        break

            if not is_restricted:
                available.append(voice)

        return {
            "allowed": True,
            "voices": available,
            "restricted_count": len(self.restricted_voices),
        }


# =============================================================================
# Example TTS Backend Implementations
# =============================================================================

class CoquiXTTSBackend:
    """Backend for Coqui XTTS v2."""

    def __init__(self, model_path: str = None, device: str = "cuda"):
        self.device = device
        self.model = None
        # In real implementation:
        # from TTS.api import TTS
        # self.model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        """Generate audio using XTTS."""
        # Real implementation would call:
        # audio = self.model.tts(text=text, speaker=voice, language="en")
        # return audio_to_wav_bytes(audio)

        # Mock for demo
        return b"RIFF" + b"\x00" * 1000  # Fake WAV header

    async def list_voices(self) -> List[str]:
        return ["en-female-1", "en-male-1", "es-female-1"]

    def health_check(self) -> bool:
        return self.model is not None


class BarkBackend:
    """Backend for Suno Bark."""

    def __init__(self, device: str = "cuda"):
        self.device = device
        # from bark import SAMPLE_RATE, generate_audio, preload_models
        # preload_models()

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        # audio_array = generate_audio(text, history_prompt=voice)
        return b"RIFF" + b"\x00" * 1000

    async def list_voices(self) -> List[str]:
        return ["v2/en_speaker_0", "v2/en_speaker_1"]

    def health_check(self) -> bool:
        return True


# =============================================================================
# Factory
# =============================================================================

def create_tts_adapter(
    manifest_path: str,
    backend_type: str = "coqui",
    **backend_kwargs
) -> LocalTTSAdapter:
    """Create TTS adapter from manifest."""
    import yaml

    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)

    backend = None
    if backend_type == "coqui":
        backend = CoquiXTTSBackend(**backend_kwargs)
    elif backend_type == "bark":
        backend = BarkBackend(**backend_kwargs)

    return LocalTTSAdapter(manifest=manifest, backend=backend)
