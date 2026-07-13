# Reference Topology: Hybrid Deployment

This document describes the reference architecture for deploying the Model Deployment Envelope in a hybrid environment spanning on-premises and cloud infrastructure.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Hybrid Architecture                             │
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         Cloud Region (AWS/GCP/Azure)                    │ │
│  │                                                                         │ │
│  │   ┌─────────────┐     ┌─────────────────────────────────────────┐      │ │
│  │   │   Internet  │────▶│            Cloud Load Balancer          │      │ │
│  │   │   Clients   │     │           (ALB/Cloud LB/App GW)         │      │ │
│  │   └─────────────┘     └────────────────┬────────────────────────┘      │ │
│  │                                        │                                │ │
│  │                       ┌────────────────┴────────────────┐              │ │
│  │                       ▼                                 ▼              │ │
│  │   ┌───────────────────────────┐   ┌───────────────────────────┐       │ │
│  │   │  Envelope (Cloud) - AZ1   │   │  Envelope (Cloud) - AZ2   │       │ │
│  │   │  ┌─────────────────────┐  │   │  ┌─────────────────────┐  │       │ │
│  │   │  │   Ingress Gate      │  │   │  │   Ingress Gate      │  │       │ │
│  │   │  │   Tool Gate         │  │   │  │   Tool Gate         │  │       │ │
│  │   │  │   Egress Gate       │  │   │  │   Egress Gate       │  │       │ │
│  │   │  └─────────────────────┘  │   │  └─────────────────────┘  │       │ │
│  │   └───────────┬───────────────┘   └───────────────┬───────────┘       │ │
│  │               │                                   │                    │ │
│  │               └───────────────┬───────────────────┘                    │ │
│  │                               │                                        │ │
│  │   ┌───────────────────────────┴───────────────────────────────┐       │ │
│  │   │                Cloud Backend (Public Data Only)            │       │ │
│  │   │   ┌─────────────────┐    ┌─────────────────┐              │       │ │
│  │   │   │  OpenAI API     │    │  Cloud Database │              │       │ │
│  │   │   │  (via Gateway)  │    │  (Provenance)   │              │       │ │
│  │   │   └─────────────────┘    └─────────────────┘              │       │ │
│  │   └───────────────────────────────────────────────────────────┘       │ │
│  │                                                                         │ │
│  └────────────────────────────────────────┬───────────────────────────────┘ │
│                                           │                                  │
│                                   VPN / Direct Connect                       │
│                                           │                                  │
│  ┌────────────────────────────────────────┴───────────────────────────────┐ │
│  │                         On-Premises Data Center                         │ │
│  │                                                                         │ │
│  │   ┌─────────────┐     ┌─────────────────────────────────────────┐      │ │
│  │   │  Internal   │────▶│            Internal Load Balancer       │      │ │
│  │   │  Clients    │     │              (HAProxy)                  │      │ │
│  │   └─────────────┘     └────────────────┬────────────────────────┘      │ │
│  │                                        │                                │ │
│  │   ┌───────────────────────────────────┴───────────────────────────┐    │ │
│  │   │              Envelope (On-Prem) - Restricted Data              │    │ │
│  │   │   ┌─────────────────────┐    ┌─────────────────────────┐      │    │ │
│  │   │   │   Ingress Gate      │    │   Key Broker            │      │    │ │
│  │   │   │   Tool Gate         │    │   (Placement-aware)     │      │    │ │
│  │   │   │   Egress Gate       │    │                         │      │    │ │
│  │   │   └─────────────────────┘    └─────────────────────────┘      │    │ │
│  │   └───────────────────────────────────┬───────────────────────────┘    │ │
│  │                                       │                                 │ │
│  │   ┌───────────────────────────────────┴───────────────────────────┐    │ │
│  │   │              On-Prem Backend (Restricted Data)                 │    │ │
│  │   │   ┌─────────────────┐    ┌─────────────────┐                  │    │ │
│  │   │   │   Ollama/vLLM   │    │   PostgreSQL    │                  │    │ │
│  │   │   │   (GPU Nodes)   │    │   (Provenance)  │                  │    │ │
│  │   │   └─────────────────┘    └─────────────────┘                  │    │ │
│  │   │                                                                │    │ │
│  │   │   ┌─────────────────┐    ┌─────────────────┐                  │    │ │
│  │   │   │   Vault (HSM)   │    │   PCI Zone      │                  │    │ │
│  │   │   │                 │    │   (Isolated)    │                  │    │ │
│  │   │   └─────────────────┘    └─────────────────┘                  │    │ │
│  │   └───────────────────────────────────────────────────────────────┘    │ │
│  │                                                                         │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## Deployment Strategy

### Data Classification Routing

| Data Class | Sensitivity | Placement | Rationale |
|------------|-------------|-----------|-----------|
| general_inquiry | Public | Cloud | No restrictions |
| product_catalog | Public | Cloud | Public data |
| account_info | Internal | Cloud or On-Prem | Standard controls |
| transaction_data | Confidential | On-Prem preferred | Regulatory |
| credit_data | Restricted | On-Prem only | Cannot leave premises |
| payment_card | Restricted | PCI Zone only | PCI-DSS requirement |
| kyc_data | Restricted | On-Prem only | Regulatory |

### Request Routing Logic

```
┌─────────────────────────────────────────────────────────────────┐
│                        Request Router                           │
│                                                                 │
│   ┌─────────────┐                                              │
│   │  Incoming   │                                              │
│   │  Request    │                                              │
│   └──────┬──────┘                                              │
│          │                                                      │
│          ▼                                                      │
│   ┌─────────────────┐                                          │
│   │ Classify Data   │                                          │
│   │ (Ingress Gate)  │                                          │
│   └────────┬────────┘                                          │
│            │                                                    │
│    ┌───────┴───────┐                                           │
│    ▼               ▼                                           │
│  Public/        Confidential/                                   │
│  Internal       Restricted                                      │
│    │               │                                            │
│    ▼               ▼                                            │
│  Cloud          On-Prem                                         │
│  Envelope       Envelope                                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Components

### Cloud Components

#### 1. Cloud Load Balancer
- **Technology:** AWS ALB / GCP Cloud Load Balancer / Azure Application Gateway
- **Purpose:** Public-facing entry point
- **Features:**
  - TLS termination
  - WAF integration
  - DDoS protection
  - Geographic routing (optional)

#### 2. Cloud Envelope Instances
- **Deployment:** Kubernetes (EKS/GKE/AKS) or ECS/Cloud Run
- **Purpose:** Handle public and internal data requests
- **Configuration:**
  - Cannot access restricted data
  - Key broker denies keys for restricted placements
  - Routes restricted requests to on-prem

#### 3. Cloud Database
- **Technology:** RDS PostgreSQL / Cloud SQL / Azure Database
- **Purpose:** Provenance for cloud-processed requests
- **Isolation:** Separate from on-prem provenance

### On-Premises Components

#### 4. On-Prem Envelope Instances
- **Purpose:** Handle restricted and confidential data
- **Features:**
  - Full key access for all data classes
  - Direct access to on-prem model backend
  - PCI zone access when required

#### 5. On-Prem Model Backend
- **Technology:** Ollama or vLLM
- **Purpose:** Run inference on restricted data
- **Isolation:** Network isolated, no cloud access

#### 6. Key Management (Vault with HSM)
- **Technology:** HashiCorp Vault with HSM backend
- **Purpose:** Master key storage, per-subject keys
- **Features:**
  - HSM-backed seal
  - On-prem only
  - No cloud access to keys

### Connectivity

#### 7. VPN / Direct Connect
- **Technology:** AWS Direct Connect / Azure ExpressRoute / GCP Interconnect
- **Purpose:** Secure connectivity between cloud and on-prem
- **Configuration:**
  - Encrypted tunnel
  - Private IP addressing
  - Dedicated bandwidth

---

## Placement Policy Example

```yaml
apiVersion: envelope.ai/v1
kind: PlacementPolicy
metadata:
  name: hybrid-placement
spec:
  placements:
    - id: cloud-primary
      type: public-cloud
      provider: aws
      region: us-east-1
      certifications:
        - SOC2
        - ISO27001
      encryptionAtRest: true
      encryptionInTransit: true

    - id: on-prem-secure
      type: on-premises
      provider: internal
      region: dc-east
      certifications:
        - SOC2
        - ISO27001
        - HIPAA
      encryptionAtRest: true
      encryptionInTransit: true

    - id: pci-zone
      type: on-premises
      provider: internal
      region: dc-east
      certifications:
        - PCI-DSS
        - SOC2
      encryptionAtRest: true
      encryptionInTransit: true

  rules:
    # Restricted data must stay on-prem
    - id: restricted-on-prem
      priority: 10
      conditions:
        sensitivity:
          min: restricted
        placementType:
          - on-premises
      action: allow

    - id: restricted-deny-cloud
      priority: 11
      conditions:
        sensitivity:
          min: restricted
        placementType:
          - public-cloud
      action: deny
      reason: Restricted data cannot be processed in cloud

    # PCI data in PCI zone only
    - id: pci-zone-only
      priority: 5
      conditions:
        dataClasses:
          - payment_card
        requiredCertifications:
          - PCI-DSS
      action: allow

    # Confidential prefers on-prem but can use cloud
    - id: confidential-anywhere
      priority: 30
      conditions:
        sensitivity:
          min: confidential
          max: confidential
      action: allow

    # Public/internal anywhere
    - id: low-sensitivity
      priority: 50
      conditions:
        sensitivity:
          max: internal
      action: allow

  defaultAction: deny
```

---

## Request Flow Examples

### Example 1: Public Data Request (Cloud Path)

```
1. Client → Cloud LB → Cloud Envelope
2. Ingress Gate: Classify as "public"
3. Placement Check: Cloud allowed
4. Model Backend: OpenAI API
5. Egress Gate: Scan response
6. Response → Client
```

### Example 2: Restricted Data Request (On-Prem Path)

```
1. Client → Cloud LB → Cloud Envelope
2. Ingress Gate: Classify as "restricted"
3. Placement Check: Cloud denied, route to on-prem
4. Request → VPN → On-Prem Envelope
5. Key Broker: Grant decryption key
6. Model Backend: On-prem Ollama
7. Egress Gate: Scan response
8. Response → VPN → Cloud Envelope → Client
```

### Example 3: PCI Data Request (PCI Zone Path)

```
1. Internal Client → On-Prem LB → On-Prem Envelope
2. Ingress Gate: Classify as "payment_card"
3. Placement Check: PCI zone required
4. Route to PCI Zone Envelope
5. Key Broker: Verify PCI certification
6. Model Backend: PCI-isolated Ollama
7. Egress Gate: PII redaction
8. Response → Client
```

---

## Security Considerations

### 1. Data Residency
- Restricted data never leaves on-prem
- Provenance records split by placement
- Key material never leaves on-prem Vault

### 2. Network Security
- VPN/Direct Connect encrypted
- Firewall rules enforce placement
- Cloud instances cannot access on-prem backend

### 3. Key Isolation
- Cloud envelope has no access to restricted keys
- Key broker enforces placement before key grant
- HSM-backed master keys

### 4. Audit Trail
- Separate provenance stores per placement
- Cross-reference by request ID
- Unified reporting

---

## Deployment Steps

### Phase 1: On-Premises Foundation
```bash
# Deploy on-prem infrastructure
# - GPU nodes with Ollama/vLLM
# - PostgreSQL cluster
# - Vault with HSM

# Configure networking
# - Internal load balancer
# - PCI zone isolation
# - Firewall rules

# Deploy on-prem envelope
envelope deploy --manifest manifest.yaml --placement on-prem-secure
```

### Phase 2: Cloud Infrastructure
```bash
# Deploy cloud infrastructure
# - Kubernetes cluster
# - RDS PostgreSQL
# - Cloud secrets manager (for non-sensitive secrets)

# Configure networking
# - Cloud load balancer
# - VPC configuration
# - Security groups

# Deploy cloud envelope
envelope deploy --manifest manifest.yaml --placement cloud-primary
```

### Phase 3: Connectivity
```bash
# Establish VPN/Direct Connect
# - Configure tunnel
# - Set up routing tables
# - Test connectivity

# Configure cross-environment routing
# - Update placement policy
# - Configure request routing
# - Test data flow
```

### Phase 4: Validation
```bash
# Run conformance tests
envelope verify --target cloud-primary
envelope verify --target on-prem-secure

# Test placement enforcement
envelope test-placement --data-class restricted --target cloud-primary
# Expected: DENIED

envelope test-placement --data-class restricted --target on-prem-secure
# Expected: ALLOWED

# Generate conformance report
envelope report --output hybrid-conformance.html
```

---

## Monitoring

### Unified Monitoring
- Aggregate metrics from both environments
- Centralized logging (with data classification awareness)
- Cross-environment request tracing

### Key Metrics
| Metric | Cloud | On-Prem | Alert Threshold |
|--------|-------|---------|-----------------|
| Request latency P95 | < 200ms | < 100ms | > 500ms |
| Error rate | < 0.1% | < 0.1% | > 1% |
| Placement denials | N/A | N/A | > 10/min |
| VPN latency | < 50ms | < 50ms | > 100ms |

### Cross-Environment Alerts
- VPN tunnel down
- Placement routing failures
- Key synchronization failures
- Conformance test failures

---

## Disaster Recovery

### Failover Scenarios

| Scenario | Impact | Recovery |
|----------|--------|----------|
| Cloud region failure | Public data processing | Failover to backup region |
| On-prem DC failure | Restricted data processing | Failover to DR site |
| VPN failure | Cross-env routing | Fallback to backup VPN |
| Vault failure | Key access | Unseal from DR |

### RTO/RPO by Placement

| Placement | RTO | RPO |
|-----------|-----|-----|
| Cloud | 15 min | 5 min |
| On-Prem | 4 hours | 1 hour |
| PCI Zone | 8 hours | 0 (no data loss) |
