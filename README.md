# Model Deployment Envelope

A declarative envelope around deployed AI models with platform-enforced boundaries and machine-checkable proofs.

## Overview

The Model Deployment Envelope provides a governance layer for AI model deployments that enforces:

- **Deny-by-default permissions** for tools, data classes, and callers
- **Placement policies** that control where data can be processed
- **Structured provenance** with tamper-evident hash chains
- **Per-subject encryption** for GDPR-compliant data erasure
- **Escalation handling** with response withholding
- **Golden-set verification** before models serve production traffic

## Installation

```bash
# From source
pip install -e .

# Or with all dependencies
pip install -e ".[all]"
```

## Quick Start

### 1. Create a Manifest

```yaml
# manifest.yaml
apiVersion: envelope.ai/v1
kind: ModelManifest
metadata:
  name: my-assistant
  version: v1.0.0
spec:
  model:
    id: llama3.1:8b
    backend: ollama
    endpoint: http://localhost:11434

  tools:
    allowed:
      - search_docs
      - get_time
    manifests:
      - tools/search_docs.yaml
      - tools/get_time.yaml

  dataClasses:
    allowed:
      - general_inquiry
      - product_info
    taxonomy: taxonomy.yaml

  placement:
    policy: placement.yaml
    currentPlacement: on-premises

  callers:
    allowedRoles:
      - user
      - admin
```

### 2. Validate the Manifest

```bash
envelope validate --manifest manifest.yaml
```

### 3. Deploy

```bash
envelope deploy --manifest manifest.yaml
```

### 4. Run Verification

```bash
envelope verify --golden-set golden_set.yaml
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Model Deployment Envelope                │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    Declaration Layer                  │   │
│  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐  │   │
│  │  │Manifest │  │  Tools  │  │Taxonomy │  │Placement│  │   │
│  │  └─────────┘  └─────────┘  └─────────┘  └─────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                              │                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    Validation Layer                   │   │
│  │  ┌──────────────┐  ┌───────────────┐  ┌───────────┐  │   │
│  │  │  Structural  │  │  Composition  │  │ Placement │  │   │
│  │  └──────────────┘  └───────────────┘  └───────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                              │                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                   Enforcement Layer                   │   │
│  │  ┌───────┐  ┌──────┐  ┌───────┐  ┌──────┐  ┌──────┐  │   │
│  │  │Ingress│  │ Tool │  │Egress │  │ Esc. │  │ Key  │  │   │
│  │  │ Gate  │  │ Gate │  │ Gate  │  │Enforc│  │Broker│  │   │
│  │  └───────┘  └──────┘  └───────┘  └──────┘  └──────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                              │                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    Runtime Layer                      │   │
│  │  ┌──────────┐  ┌───────────┐  ┌───────────────────┐  │   │
│  │  │ Contract │  │ Lifecycle │  │     Adapters      │  │   │
│  │  │          │  │           │  │ Ollama│vLLM|OpenAI│  │   │
│  │  └──────────┘  └───────────┘  └───────────────────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                              │                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │                    Record System                      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐  │   │
│  │  │Provenance│  │HashChain │  │Encryption│  │Replay│  │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────┘  │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

## Key Concepts

### Deny-by-Default

All registries default to rejection. Tools, data classes, and callers must be explicitly allowed:

```yaml
tools:
  allowed:
    - search_docs  # Only this tool is accessible
    # All other tools are blocked
```

### External Enforcement

The model never sees credentials or has direct tool access. The envelope:

1. Intercepts tool requests
2. Validates permissions
3. Injects credentials
4. Executes the tool
5. Returns results to model

### Placement Policies

Data can only be processed in allowed environments:

```yaml
placements:
  - id: on-premises
    certifications: [SOC2, ISO27001]

rules:
  - conditions:
      dataClasses: [payment_info]
      requiredCertifications: [PCI-DSS]
    action: allow
```

### Provenance Records

Every inference is recorded with:

- Request ID
- Caller identity
- Model version
- Input/output hashes
- Tool calls
- Processing location
- Timestamp

### Hash Chain Integrity

Records are linked in a tamper-evident chain:

```
Record N: hash = SHA256(content + prev_hash)
Record N+1: hash = SHA256(content + hash_N)
```

### Per-Subject Encryption

Payloads are encrypted with per-subject keys, enabling GDPR erasure:

```python
# Erase all data for a subject by deleting their key
encryption.delete_key(subject_id="user-123")
# All encrypted payloads become unreadable
```

## CLI Commands

### Validate

Validate manifest and supporting files:

```bash
envelope validate --manifest manifest.yaml
envelope validate --manifest manifest.yaml --strict
```

### Deploy

Deploy a model with envelope:

```bash
envelope deploy --manifest manifest.yaml
envelope deploy --manifest manifest.yaml --placement on-premises
```

### Verify

Run verification tests:

```bash
envelope verify --golden-set golden_set.yaml
envelope verify --conformance
envelope verify --canary
```

### Replay

Reproduce a historical decision:

```bash
envelope replay --request-id <uuid>
envelope replay --request-id <uuid> --compare
```

### Report

Generate conformance report:

```bash
envelope report --output report.html
envelope report --format json --output report.json
```

## API Endpoints

### Inference

```
POST /v1/infer
Content-Type: application/json
Authorization: Bearer <token>

{
  "messages": [{"role": "user", "content": "Hello"}],
  "parameters": {"temperature": 0.7}
}
```

### Health

```
GET /health
GET /health/ready
GET /health/live
```

### Admin

```
GET /admin/provenance/{request_id}
GET /admin/escalations
POST /admin/escalations/{id}/resolve
GET /admin/lifecycle/state
```

### Verification

```
POST /verify/conformance
POST /verify/golden-set
GET /verify/report
```

## Starter Packs

Pre-built configurations for common industries:

### BFSI (Banking, Financial Services, Insurance)

```bash
cp -r starter_packs/bfsi/* my-deployment/
```

Includes:
- Data taxonomy (payment_card, kyc_data, credit_data, etc.)
- Placement policies (PCI-DSS requirements)
- Example manifest

### Retail

```bash
cp -r starter_packs/retail/* my-deployment/
```

Includes:
- Data taxonomy (customer_profile, order_history, payment_info)
- Placement policies (GDPR, edge deployment)
- Example manifest

## Delivery Kit

Resources for enterprise adoption:

- **Gap Assessment**: Checklist for evaluating current state
- **Decision Register**: 20 key decisions to document
- **Reference Topologies**:
  - On-premises deployment
  - Hybrid (cloud + on-prem)
  - API-backed (OpenAI, Anthropic)

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `ENVELOPE_CONFIG` | Path to config file | `envelope.yaml` |
| `DATABASE_URL` | Provenance store connection | `sqlite:///envelope.db` |
| `MODEL_BACKEND` | Backend type | `ollama` |
| `MODEL_ENDPOINT` | Backend URL | `http://localhost:11434` |
| `VAULT_ADDR` | Key management URL | (none) |
| `LOG_LEVEL` | Logging level | `INFO` |

### Configuration File

```yaml
# envelope.yaml
database:
  url: postgresql://localhost/envelope
  pool_size: 10

model:
  backend: ollama
  endpoint: http://localhost:11434

encryption:
  key_backend: vault
  vault_addr: https://vault:8200

logging:
  level: INFO
  format: json
```

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/org/model-deployment-envelope.git
cd model-deployment-envelope

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install in development mode
pip install -e ".[dev]"
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=envelope

# Run specific test categories
pytest tests/unit/
pytest tests/integration/
pytest tests/conformance/
```

### Code Quality

```bash
# Format code
black src/ tests/
isort src/ tests/

# Type checking
mypy src/

# Linting
ruff check src/ tests/
```

## License

MIT License - See LICENSE file for details.

## Contributing

See CONTRIBUTING.md for contribution guidelines.
