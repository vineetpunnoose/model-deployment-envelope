# Model Deployment Envelope - Complete Guide

## What We Built

A **governance layer** that wraps AI models (LLMs, TTS, or any model) with platform-enforced security boundaries. The model cannot bypass these controls because they're enforced externally.

---

## Core Concept

```
Without Envelope:
    User → Model → (anything can happen)

With Envelope:
    User → [Envelope Gates] → Model → [Envelope Gates] → User
              ↓                           ↓
         • Auth check               • PII scan
         • Data class check         • Response filter
         • Rate limit               • Audit log
```

The model is "wrapped" - it only sees requests that pass all gates, and its responses are filtered before reaching users.

---

## What Gets Enforced

### 1. Caller Authorization
```yaml
callers:
  allowedRoles:
    - ivr_system
    - agent_desktop
  denied:
    - public_api
    - external
```
Only approved systems can call the model. Unknown callers are rejected.

### 2. Data Classification
```yaml
dataClasses:
  allowed:
    - general_info
    - greeting
  denied:
    - customer_pii
    - financial_data
```
Model can only process approved data types. Sensitive data classes are blocked at the gate.

### 3. Tool/Voice Permissions (Deny-by-Default)
```yaml
voices:  # For TTS
  allowed:
    - agent-female-1
    - agent-male-1
  restricted:
    - executive-*    # Needs approval
    - celebrity-*    # Blocked
```
Only explicitly allowed tools/voices work. Everything else is denied.

### 4. Content Filtering
```yaml
contentFilters:
  rules:
    - id: redact-pii
      patterns:
        ssn: '\d{3}-\d{2}-\d{4}'
        account: '\b\d{10,16}\b'
      action: redact_and_warn
```
PII is automatically detected and redacted before the model sees it (or speaks it).

### 5. Escalation
```yaml
escalation:
  conditions:
    - trigger: explicit_request
      patterns: ["speak to human", "supervisor"]
    - trigger: low_confidence
      threshold: 0.4
```
Certain conditions trigger human review. The model's response is **withheld** until a human approves.

### 6. Placement-Based Encryption
```yaml
placement:
  rules:
    - dataClasses: [payment_card]
      requiredCertifications: [PCI-DSS]
      allowed: [pci-certified-zone]
```
Sensitive data is encrypted with keys that are **denied** at unauthorized locations. Even if data leaks, it can't be decrypted.

---

## Project Structure

```
model-deployment-envelope/
├── src/envelope/
│   ├── declaration/       # Manifest, tools, taxonomy, placement
│   ├── validation/        # Structural, composition validators
│   ├── enforcement/       # Ingress, tool, egress, escalation gates
│   ├── record/           # Provenance, hash chain, encryption
│   ├── runtime/          # Adapters for Ollama, vLLM, OpenAI, TTS
│   ├── handoff/          # Escalation to human reviewers
│   ├── verification/     # Conformance tests, golden sets
│   ├── api/              # FastAPI endpoints
│   ├── cli/              # Command-line tools
│   └── ui/               # Web dashboard for human-in-the-loop
├── examples/
│   ├── tts-service/      # TTS integration examples
│   └── call-agent-v3/    # LLM agent example
├── starter_packs/
│   ├── bfsi/             # Banking/Finance templates
│   └── retail/           # Retail templates
├── demo/
│   ├── quick_demo.py     # Non-interactive demo
│   ├── tts_demo.py       # TTS-specific demo
│   └── run_demo.py       # Interactive demo
├── schemas/              # JSON schemas for validation
└── delivery_kit/         # Enterprise adoption docs
```

---

## How to Use with Your TTS Model

### Step 1: Pull the Code on Your GPU Server

```bash
git clone https://github.com/vineetpunnoose/model-deployment-envelope.git
cd model-deployment-envelope
pip install -e .
```

### Step 2: Edit the Integration File

```bash
nano examples/tts-service/customer_service_tts.py
```

Find the `YourCustomTTS` class and replace with your model:

```python
class YourCustomTTS:
    def __init__(self):
        # YOUR CODE: Load your model
        import torch
        self.model = torch.load("your_model.pt")
        self.model.to("cuda")
        self.model.eval()

    def synthesize(self, text: str, voice_id: str = "default") -> bytes:
        # YOUR CODE: Generate audio
        with torch.no_grad():
            audio = self.model(text, voice=voice_id)
        return self._to_wav_bytes(audio)
```

### Step 3: Run the Service

```bash
cd examples/tts-service
python customer_service_tts.py
```

### Step 4: Test It

```bash
# Allowed request
curl -X POST http://localhost:8001/v1/speak \
  -H "Content-Type: application/json" \
  -H "X-Caller-Role: ivr_system" \
  -d '{"text": "Thank you for calling", "voice": "agent-female-1"}' \
  --output speech.wav

# Denied (unauthorized caller)
curl -X POST http://localhost:8001/v1/speak \
  -H "X-Caller-Role: external" \
  -d '{"text": "Hello"}'
# Returns 403 Forbidden

# PII gets redacted
curl -X POST http://localhost:8001/v1/speak \
  -H "X-Caller-Role: ivr_system" \
  -d '{"text": "Your SSN is 123-45-6789"}'
# Audio says: "Your SSN is [REDACTED]"

# View audit log
curl http://localhost:8001/v1/audit
```

---

## Run the Dashboard (Human-in-the-Loop UI)

```bash
python run_dashboard.py
# Open: http://localhost:8080/ui/
```

The dashboard shows:
- All interactions (allowed/denied/escalated)
- Pending escalations for human review
- Approval requests for restricted resources
- Audit trail

---

## Run the Demos

```bash
# Quick overview (non-interactive)
python demo/quick_demo.py

# TTS-specific demo
python demo/tts_demo.py

# Interactive step-by-step
python demo/run_demo.py
```

---

## Key Files for TTS Integration

| File | Purpose |
|------|---------|
| `examples/tts-service/customer_service_tts.py` | **Start here** - Customer service TTS with all governance |
| `examples/tts-service/integrate_your_tts.py` | Generic TTS integration template |
| `src/envelope/runtime/adapters/local_tts.py` | The TTS adapter with all gates |
| `examples/tts-service/manifest.yaml` | Example manifest for TTS |

---

## Customer Service Governance (Pre-configured)

The `customer_service_tts.py` includes:

| Gate | What It Does |
|------|--------------|
| **Caller Auth** | Only `ivr_system`, `agent_desktop`, `quality_assurance` allowed |
| **Voice Control** | Only approved agent voices; executive voices need approval |
| **PII Redaction** | Account numbers, SSN, phone, email auto-redacted |
| **Profanity Block** | Blocks profanity from being spoken |
| **Fraud Detection** | "wire transfer", "gift card" → escalated to security |
| **Rate Limiting** | 60 req/min, 20K chars/min per caller |
| **Audit Logging** | Every request logged with caller, text, status |

---

## API Endpoints (TTS Service)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/speak` | POST | Convert text to speech (with governance) |
| `/v1/voices` | GET | List available voices |
| `/v1/audit` | GET | View audit log |
| `/health` | GET | Health check |

### Request Format

```bash
curl -X POST http://localhost:8001/v1/speak \
  -H "Content-Type: application/json" \
  -H "X-Caller-ID: my-app" \
  -H "X-Caller-Role: ivr_system" \
  -d '{
    "text": "Thank you for calling. How can I help you today?",
    "voice": "agent-female-1",
    "data_class": "greeting"
  }' \
  --output speech.wav
```

### Response Headers

```
X-Request-ID: tts-20240101120000123456
X-Duration: 2.5
X-Warnings: none
```

---

## Customizing the Rules

Edit the `CUSTOMER_SERVICE_MANIFEST` in `customer_service_tts.py`:

```python
CUSTOMER_SERVICE_MANIFEST = {
    "spec": {
        "voices": {
            "allowed": ["your-voice-1", "your-voice-2"],
        },
        "callers": {
            "allowedRoles": ["your-app", "your-system"],
        },
        "contentFilters": {
            "rules": [
                # Add your own patterns
            ]
        }
    }
}
```

---

## Architecture Summary

```
┌──────────────────────────────────────────────────────────────┐
│                     YOUR GPU SERVER                          │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                 Envelope Service (:8001)                │ │
│  │                                                         │ │
│  │  Request → [Auth] → [Voice] → [Content] → [Rate Limit] │ │
│  │               │         │          │            │       │ │
│  │              DENY?     DENY?    REDACT?       DENY?     │ │
│  │                                                         │ │
│  │                         ↓ (if all pass)                 │ │
│  │                                                         │ │
│  │              ┌─────────────────────────┐               │ │
│  │              │   YOUR TTS MODEL (GPU)   │               │ │
│  │              └─────────────────────────┘               │ │
│  │                         ↓                               │ │
│  │                                                         │ │
│  │                   [Audit Log]                           │ │
│  │                         ↓                               │ │
│  │                    Response                             │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Dashboard UI (:8080)                       │ │
│  │              - View all requests                        │ │
│  │              - Review escalations                       │ │
│  │              - Audit trail                              │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

---

## Files Created in This Session

1. **TTS Adapter**: `src/envelope/runtime/adapters/local_tts.py`
2. **TTS Example Manifest**: `examples/tts-service/manifest.yaml`
3. **TTS Demo**: `demo/tts_demo.py`
4. **Customer Service Integration**: `examples/tts-service/customer_service_tts.py`
5. **Generic Integration Template**: `examples/tts-service/integrate_your_tts.py`
6. **Web Dashboard**: `src/envelope/ui/dashboard.py`
7. **Dashboard Runner**: `run_dashboard.py`

---

## Next Steps on Your Server

1. `git pull` this repo
2. Edit `YourCustomTTS` class with your model code
3. Run `python examples/tts-service/customer_service_tts.py`
4. Test with curl
5. Integrate with your IVR/agent desktop

---

## Questions?

The key file to edit is:
```
examples/tts-service/customer_service_tts.py
```

Just replace the `YourCustomTTS` class with your actual model loading and synthesis code.
