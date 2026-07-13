# Reference Topology: API-Backed Deployment

This document describes the reference architecture for deploying the Model Deployment Envelope using external API-backed model providers (OpenAI, Anthropic, etc.) as the inference backend.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         API-Backed Architecture                              │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                           Cloud Platform                                 ││
│  │                                                                          ││
│  │   ┌─────────────┐      ┌─────────────────────────────────────────┐      ││
│  │   │   Clients   │─────▶│           API Gateway                   │      ││
│  │   │             │      │    (Kong / AWS API Gateway / Apigee)    │      ││
│  │   └─────────────┘      └──────────────────┬──────────────────────┘      ││
│  │                                           │                              ││
│  │                          ┌────────────────┴────────────────┐             ││
│  │                          ▼                                 ▼             ││
│  │   ┌───────────────────────────────┐   ┌───────────────────────────────┐ ││
│  │   │     Envelope Instance 1       │   │     Envelope Instance 2       │ ││
│  │   │  ┌─────────────────────────┐  │   │  ┌─────────────────────────┐  │ ││
│  │   │  │      Ingress Gate       │  │   │  │      Ingress Gate       │  │ ││
│  │   │  │  - Caller auth          │  │   │  │  - Caller auth          │  │ ││
│  │   │  │  - Data classification  │  │   │  │  - Data classification  │  │ ││
│  │   │  │  - PII detection        │  │   │  │  - PII detection        │  │ ││
│  │   │  ├─────────────────────────┤  │   │  ├─────────────────────────┤  │ ││
│  │   │  │       Tool Gate         │  │   │  │       Tool Gate         │  │ ││
│  │   │  │  - Tool permissions     │  │   │  │  - Tool permissions     │  │ ││
│  │   │  │  - Credential injection │  │   │  │  - Credential injection │  │ ││
│  │   │  ├─────────────────────────┤  │   │  ├─────────────────────────┤  │ ││
│  │   │  │      Egress Gate        │  │   │  │      Egress Gate        │  │ ││
│  │   │  │  - Response scan        │  │   │  │  - Response scan        │  │ ││
│  │   │  │  - Grounding check      │  │   │  │  - Grounding check      │  │ ││
│  │   │  │  - PII redaction        │  │   │  │  - PII redaction        │  │ ││
│  │   │  └─────────────────────────┘  │   │  └─────────────────────────┘  │ ││
│  │   └───────────────┬───────────────┘   └───────────────┬───────────────┘ ││
│  │                   │                                   │                  ││
│  │                   └───────────────┬───────────────────┘                  ││
│  │                                   │                                      ││
│  │   ┌───────────────────────────────┴───────────────────────────────────┐ ││
│  │   │                      API Router / Proxy                            │ ││
│  │   │            (Rate limiting, retries, circuit breaker)               │ ││
│  │   └───────────────────────────────┬───────────────────────────────────┘ ││
│  │                                   │                                      ││
│  │   ┌───────────────────────────────┴───────────────────────────────────┐ ││
│  │   │                     Supporting Services                            │ ││
│  │   │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐    │ ││
│  │   │  │    PostgreSQL   │  │  Secrets Mgr    │  │      Redis      │    │ ││
│  │   │  │   (Provenance)  │  │  (API Keys)     │  │    (Cache)      │    │ ││
│  │   │  └─────────────────┘  └─────────────────┘  └─────────────────┘    │ ││
│  │   └───────────────────────────────────────────────────────────────────┘ ││
│  │                                                                          ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
│                                      │                                       │
│                                      │ HTTPS                                 │
│                                      ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                       External API Providers                             ││
│  │                                                                          ││
│  │   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐         ││
│  │   │    OpenAI       │  │   Anthropic     │  │  Azure OpenAI   │         ││
│  │   │   api.openai.   │  │   api.anthropic │  │  .openai.azure  │         ││
│  │   │     com         │  │      .com       │  │      .com       │         ││
│  │   └─────────────────┘  └─────────────────┘  └─────────────────┘         ││
│  │                                                                          ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Key Characteristics

### Advantages
- No GPU infrastructure to manage
- Rapid deployment
- Access to latest models
- Pay-per-use pricing
- Automatic scaling

### Constraints
- Data leaves organizational boundary
- Dependent on provider availability
- Limited to provider's data retention policies
- May not meet regulatory requirements for sensitive data

### Best Suited For
- Public and internal data only
- Development and testing
- Non-regulated workloads
- Organizations without GPU infrastructure

---

## Components

### 1. API Gateway
- **Technology:** Kong, AWS API Gateway, Apigee, or Azure API Management
- **Purpose:** External entry point with rate limiting
- **Features:**
  - Authentication (API keys, OAuth)
  - Rate limiting per client
  - Request/response logging
  - Usage analytics

### 2. Envelope Instances
- **Deployment:** Kubernetes, ECS, Cloud Run, or serverless
- **Purpose:** Enforce all envelope policies before reaching API provider
- **Scaling:** Horizontal based on request volume
- **Resources:** Lightweight (no GPU required)

### 3. API Router/Proxy
- **Technology:** Custom proxy or service mesh
- **Purpose:** Route requests to appropriate API provider
- **Features:**
  - Circuit breaker for provider outages
  - Automatic retries with backoff
  - Request queuing
  - Provider failover

### 4. Provenance Store
- **Technology:** PostgreSQL (RDS, Cloud SQL, etc.)
- **Purpose:** Store all inference records
- **Note:** Full request/response stored (not sent to provider)

### 5. Secrets Manager
- **Technology:** AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault
- **Purpose:** Store API provider credentials securely
- **Features:**
  - Automatic rotation
  - Access auditing
  - Version history

### 6. Cache
- **Technology:** Redis or Memcached
- **Purpose:** Cache common responses (when appropriate)
- **Configuration:** Respect cache headers, TTL policies

---

## API Provider Configuration

### Manifest Example

```yaml
apiVersion: envelope.ai/v1
kind: ModelManifest
metadata:
  name: api-backed-assistant
  version: v1.0.0
spec:
  model:
    id: gpt-4o
    backend: openai
    endpoint: https://api.openai.com/v1
    parameters:
      temperature: 0.7
      maxTokens: 2048

    # Fallback provider
    fallback:
      backend: anthropic
      endpoint: https://api.anthropic.com/v1
      modelId: claude-sonnet-4-20250514

  # API-backed specific settings
  apiSettings:
    timeout: 30000
    retries: 3
    circuitBreaker:
      failureThreshold: 5
      resetTimeout: 60000

  placement:
    policy: placement.yaml
    currentPlacement: cloud-api

  dataClasses:
    allowed:
      - general_inquiry
      - product_catalog
      - pricing_info
    # Note: Restricted data classes NOT allowed
    taxonomy: taxonomy.yaml
```

### Placement Policy for API-Backed

```yaml
apiVersion: envelope.ai/v1
kind: PlacementPolicy
metadata:
  name: api-backed-placement
spec:
  placements:
    - id: cloud-api
      type: api-backed
      provider: openai
      region: external
      jurisdiction:
        - US  # OpenAI data processing
      certifications:
        - SOC2
      encryptionAtRest: true
      encryptionInTransit: true
      dataResidency: false  # Data leaves org boundary

  rules:
    # Only public/internal data allowed
    - id: public-internal-only
      description: Only low-sensitivity data allowed
      priority: 10
      conditions:
        sensitivity:
          max: internal
      action: allow
      reason: API-backed deployment for low-sensitivity data

    # Deny confidential and above
    - id: deny-confidential
      description: Confidential+ data denied
      priority: 5
      conditions:
        sensitivity:
          min: confidential
      action: deny
      reason: Confidential data cannot leave organizational boundary

    # Deny specific data classes
    - id: deny-pii-heavy
      description: PII-heavy classes denied
      priority: 3
      conditions:
        dataClasses:
          - customer_profile
          - payment_info
          - credit_data
          - kyc_data
      action: deny
      reason: PII-heavy data classes not allowed in API-backed deployment

  defaultAction: deny
```

---

## Request Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            Request Processing                                │
│                                                                              │
│   1. Client Request                                                          │
│      │                                                                       │
│      ▼                                                                       │
│   2. API Gateway                                                             │
│      ├── Authenticate client                                                 │
│      ├── Rate limit check                                                    │
│      └── Route to envelope                                                   │
│      │                                                                       │
│      ▼                                                                       │
│   3. Ingress Gate                                                            │
│      ├── Verify caller identity                                              │
│      ├── Classify data in request                                            │
│      ├── Check placement policy                                              │
│      │   └── DENY if confidential+ data detected                             │
│      ├── Detect PII patterns                                                 │
│      │   └── DENY if forbidden PII found                                     │
│      └── Create provenance record                                            │
│      │                                                                       │
│      ▼                                                                       │
│   4. Tool Gate (if tool call)                                                │
│      ├── Verify tool is manifested                                           │
│      ├── Inject tool credentials                                             │
│      └── Execute tool locally                                                │
│      │                                                                       │
│      ▼                                                                       │
│   5. API Proxy                                                               │
│      ├── Retrieve API key from secrets manager                               │
│      ├── Apply circuit breaker logic                                         │
│      ├── Send request to provider                                            │
│      │   └── Failover to backup provider if needed                           │
│      └── Wait for response                                                   │
│      │                                                                       │
│      ▼                                                                       │
│   6. Egress Gate                                                             │
│      ├── Scan response for PII leakage                                       │
│      ├── Check grounding requirements                                        │
│      ├── Apply any redactions                                                │
│      └── Update provenance record                                            │
│      │                                                                       │
│      ▼                                                                       │
│   7. Response to Client                                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Provider Adapter Implementation

### OpenAI Adapter

```python
# src/envelope/runtime/adapters/openai.py (simplified)

class OpenAIAdapter(RuntimeBackend):
    def __init__(self, config: Dict[str, Any]):
        self.endpoint = config.get("endpoint", "https://api.openai.com/v1")
        self.model_id = config.get("model_id", "gpt-4o")
        self.timeout = config.get("timeout", 30)

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        # API key injected at runtime, never stored in model
        api_key = await self.secrets_manager.get("openai_api_key")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.endpoint}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": self.model_id,
                    "messages": request.messages,
                    "temperature": request.parameters.get("temperature", 0.7),
                    "max_tokens": request.parameters.get("maxTokens", 2048),
                },
                timeout=self.timeout,
            )

        return InferenceResponse(
            content=response.json()["choices"][0]["message"]["content"],
            metadata={"provider": "openai", "model": self.model_id},
        )
```

### Anthropic Adapter

```python
# src/envelope/runtime/adapters/anthropic.py (simplified)

class AnthropicAdapter(RuntimeBackend):
    def __init__(self, config: Dict[str, Any]):
        self.endpoint = config.get("endpoint", "https://api.anthropic.com/v1")
        self.model_id = config.get("model_id", "claude-sonnet-4-20250514")

    async def infer(self, request: InferenceRequest) -> InferenceResponse:
        api_key = await self.secrets_manager.get("anthropic_api_key")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.endpoint}/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": self.model_id,
                    "messages": request.messages,
                    "max_tokens": request.parameters.get("maxTokens", 2048),
                },
            )

        return InferenceResponse(
            content=response.json()["content"][0]["text"],
            metadata={"provider": "anthropic", "model": self.model_id},
        )
```

---

## Circuit Breaker Configuration

```yaml
# Circuit breaker for provider resilience
circuitBreaker:
  # Open circuit after 5 consecutive failures
  failureThreshold: 5

  # Time to wait before trying again (ms)
  resetTimeout: 60000

  # Success threshold to close circuit
  successThreshold: 3

  # Timeout for individual requests (ms)
  requestTimeout: 30000

  # Fallback behavior when circuit is open
  fallbackBehavior: "use_secondary_provider"

  # Secondary provider configuration
  secondaryProvider:
    backend: anthropic
    modelId: claude-sonnet-4-20250514
```

---

## Security Considerations

### 1. API Key Security
- Store keys in secrets manager (never in config files)
- Rotate keys regularly
- Use separate keys per environment
- Monitor key usage for anomalies

### 2. Data Classification
- Strict enforcement of data classification at ingress
- No confidential or restricted data to API providers
- PII detection must catch all patterns before sending

### 3. Request/Response Logging
- Full provenance stored locally
- Do not log to external services
- Encrypt sensitive fields in provenance

### 4. Provider Compliance
- Review provider's SOC2 report
- Understand data retention policies
- Configure data processing options (if available)
- Consider regional endpoints for data residency

---

## Deployment Steps

### 1. Infrastructure Setup

```bash
# Deploy cloud infrastructure
terraform apply -var-file=api-backed.tfvars

# Create secrets
aws secretsmanager create-secret \
  --name envelope/openai-api-key \
  --secret-string "sk-..."

aws secretsmanager create-secret \
  --name envelope/anthropic-api-key \
  --secret-string "sk-ant-..."
```

### 2. Deploy Envelope

```bash
# Build and push container
docker build -t envelope:latest .
docker push registry/envelope:latest

# Deploy to Kubernetes
kubectl apply -f k8s/envelope-deployment.yaml

# Or deploy to serverless
gcloud run deploy envelope \
  --image registry/envelope:latest \
  --set-env-vars "MODEL_BACKEND=openai,MODEL_ENDPOINT=https://api.openai.com/v1"
```

### 3. Configure API Gateway

```yaml
# Kong configuration example
services:
  - name: envelope
    url: http://envelope-service:8000

routes:
  - name: envelope-route
    service: envelope
    paths:
      - /v1/infer

plugins:
  - name: rate-limiting
    config:
      minute: 100
      policy: local

  - name: key-auth
    config:
      key_names:
        - X-API-Key
```

### 4. Validate Deployment

```bash
# Run conformance tests
envelope verify --target https://api.example.com

# Test placement enforcement
envelope test-placement --data-class confidential
# Expected: DENIED

envelope test-placement --data-class general_inquiry
# Expected: ALLOWED

# Generate report
envelope report --output api-backed-conformance.html
```

---

## Monitoring

### Provider Metrics
| Metric | Alert Threshold |
|--------|-----------------|
| Provider latency P95 | > 5s |
| Provider error rate | > 1% |
| Circuit breaker open | Any |
| Failover activated | Any |

### Cost Monitoring
- Track token usage per client
- Alert on unusual spikes
- Daily/weekly cost reports

### Compliance Monitoring
- Data classification violations
- Placement denials
- PII detection hits

---

## Cost Optimization

### Strategies
1. **Caching:** Cache common responses (when appropriate)
2. **Request optimization:** Compress prompts, limit max tokens
3. **Provider selection:** Use cheaper models for simple tasks
4. **Batching:** Batch similar requests when latency allows

### Token Budgets

```yaml
# Per-request token limits
tokenLimits:
  input: 4000
  output: 2048

# Per-client daily limits
clientLimits:
  default:
    dailyTokens: 100000
  premium:
    dailyTokens: 1000000
```

---

## Limitations

### Cannot Use API-Backed For
- Restricted or confidential data
- Data subject to strict residency requirements
- PCI-DSS cardholder data
- HIPAA PHI without BAA
- Financial data requiring on-premises processing

### Mitigation
- Use hybrid topology for sensitive data
- Route sensitive requests to on-premises backend
- Clear data classification at ingress gate
