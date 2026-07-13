# Reference Topology: On-Premises Deployment

This document describes the reference architecture for deploying the Model Deployment Envelope in an on-premises environment.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        On-Premises Data Center                          │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │                     Security Perimeter                          │    │
│  │                                                                  │    │
│  │  ┌─────────────┐    ┌─────────────────────────────────────┐    │    │
│  │  │   Clients   │───▶│         Load Balancer               │    │    │
│  │  │  (Internal) │    │        (HAProxy/NGINX)              │    │    │
│  │  └─────────────┘    └───────────────┬─────────────────────┘    │    │
│  │                                     │                          │    │
│  │                    ┌────────────────┴────────────────┐         │    │
│  │                    ▼                                 ▼         │    │
│  │  ┌─────────────────────────────┐ ┌─────────────────────────────┐   │
│  │  │   Envelope Instance 1       │ │   Envelope Instance 2       │   │
│  │  │  ┌─────────────────────┐   │ │  ┌─────────────────────┐   │   │
│  │  │  │    FastAPI App      │   │ │  │    FastAPI App      │   │   │
│  │  │  │  ┌───────────────┐  │   │ │  │  ┌───────────────┐  │   │   │
│  │  │  │  │ Ingress Gate  │  │   │ │  │  │ Ingress Gate  │  │   │   │
│  │  │  │  ├───────────────┤  │   │ │  │  ├───────────────┤  │   │   │
│  │  │  │  │  Tool Gate    │  │   │ │  │  │  Tool Gate    │  │   │   │
│  │  │  │  ├───────────────┤  │   │ │  │  ├───────────────┤  │   │   │
│  │  │  │  │ Egress Gate   │  │   │ │  │  │ Egress Gate   │  │   │   │
│  │  │  │  └───────────────┘  │   │ │  │  └───────────────┘  │   │   │
│  │  │  └─────────────────────┘   │ │  └─────────────────────┘   │   │
│  │  └─────────────┬───────────────┘ └───────────────┬───────────────┘   │
│  │                │                                 │              │    │
│  │                └────────────────┬────────────────┘              │    │
│  │                                 ▼                               │    │
│  │  ┌─────────────────────────────────────────────────────────┐   │    │
│  │  │              Model Backend (Isolated Network)            │   │    │
│  │  │  ┌─────────────────┐  ┌─────────────────┐               │   │    │
│  │  │  │   Ollama/vLLM   │  │   Ollama/vLLM   │               │   │    │
│  │  │  │   (GPU Node 1)  │  │   (GPU Node 2)  │               │   │    │
│  │  │  └─────────────────┘  └─────────────────┘               │   │    │
│  │  └─────────────────────────────────────────────────────────┘   │    │
│  │                                                                  │    │
│  └──────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Supporting Services                           │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │   │
│  │  │  PostgreSQL │  │    Vault    │  │    Redis    │              │   │
│  │  │ (Provenance)│  │   (Keys)    │  │   (Cache)   │              │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. Load Balancer
- **Technology:** HAProxy or NGINX
- **Purpose:** Distribute requests across envelope instances
- **Configuration:**
  - Health check endpoint: `/health`
  - Session affinity: Not required (stateless)
  - TLS termination: At load balancer

### 2. Envelope Instances
- **Deployment:** Multiple instances for HA
- **Scaling:** Horizontal scaling based on request volume
- **Resources:**
  - CPU: 4-8 cores per instance
  - Memory: 8-16 GB per instance
  - Storage: Minimal (stateless)

### 3. Model Backend
- **Technology:** Ollama or vLLM
- **Isolation:** Separate network segment
- **Access:** Only envelope instances can reach backend
- **Resources:**
  - GPU: NVIDIA A100/H100 or equivalent
  - Memory: 80+ GB GPU memory recommended
  - Storage: SSD for model weights

### 4. Provenance Store
- **Technology:** PostgreSQL
- **Purpose:** Store provenance records with hash chain
- **Configuration:**
  - Replication: Primary-replica for HA
  - Backup: Daily with point-in-time recovery
  - Encryption: TDE enabled

### 5. Key Management
- **Technology:** HashiCorp Vault
- **Purpose:** Store subject encryption keys
- **Configuration:**
  - Auto-unseal with HSM
  - Audit logging enabled
  - Key rotation policies

### 6. Cache (Optional)
- **Technology:** Redis
- **Purpose:** Session cache, rate limiting
- **Configuration:**
  - Cluster mode for HA
  - Persistence: AOF for durability

---

## Network Segmentation

```
┌─────────────────────────────────────────────────────────────────┐
│                         Network Zones                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐    ┌─────────────────┐                    │
│  │   DMZ Zone      │───▶│   App Zone      │                    │
│  │                 │    │                 │                    │
│  │  Load Balancer  │    │  Envelope Apps  │                    │
│  │                 │    │  Tool Services  │                    │
│  └─────────────────┘    └────────┬────────┘                    │
│                                  │                              │
│                    ┌─────────────┴─────────────┐               │
│                    ▼                           ▼               │
│  ┌─────────────────────┐    ┌─────────────────────┐           │
│  │   Model Zone        │    │   Data Zone         │           │
│  │   (GPU Network)     │    │                     │           │
│  │                     │    │  PostgreSQL         │           │
│  │  Ollama/vLLM        │    │  Vault              │           │
│  │  Nodes              │    │  Redis              │           │
│  └─────────────────────┘    └─────────────────────┘           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Firewall Rules

| Source | Destination | Port | Protocol | Purpose |
|--------|-------------|------|----------|---------|
| External | Load Balancer | 443 | HTTPS | Client requests |
| Load Balancer | Envelope | 8000 | HTTP | Internal routing |
| Envelope | Model Backend | 11434 | HTTP | Ollama API |
| Envelope | PostgreSQL | 5432 | TCP | Provenance store |
| Envelope | Vault | 8200 | HTTPS | Key management |
| Envelope | Redis | 6379 | TCP | Caching |
| Envelope | Tool Services | varies | HTTPS | Tool execution |

---

## Deployment Steps

### 1. Infrastructure Preparation
```bash
# Provision servers
# - 2+ envelope application servers
# - 2+ GPU nodes for model backend
# - Database cluster
# - Vault cluster

# Configure network segmentation
# Configure firewall rules
# Install TLS certificates
```

### 2. Database Setup
```bash
# Initialize PostgreSQL
createdb envelope_provenance

# Run migrations
envelope db migrate

# Configure replication
# Configure backups
```

### 3. Vault Setup
```bash
# Initialize Vault
vault operator init

# Configure authentication
vault auth enable kubernetes

# Create policies for envelope
vault policy write envelope-policy envelope-policy.hcl

# Enable secrets engine
vault secrets enable -path=envelope kv-v2
```

### 4. Model Backend Setup
```bash
# Install Ollama on GPU nodes
curl -fsSL https://ollama.ai/install.sh | sh

# Pull required models
ollama pull llama3.1:8b

# Configure model backend network
# - Bind to internal interface only
# - Configure firewall rules
```

### 5. Envelope Deployment
```bash
# Deploy envelope application
docker pull envelope:latest

docker run -d \
  --name envelope \
  -e DATABASE_URL=postgresql://... \
  -e VAULT_ADDR=https://vault:8200 \
  -e MODEL_BACKEND=ollama \
  -e MODEL_ENDPOINT=http://gpu-node:11434 \
  -p 8000:8000 \
  envelope:latest

# Validate deployment
envelope validate --manifest /path/to/manifest.yaml

# Run golden set tests
envelope verify --golden-set /path/to/golden_set.yaml
```

### 6. Load Balancer Configuration
```nginx
# NGINX example
upstream envelope {
    server envelope-1:8000;
    server envelope-2:8000;
}

server {
    listen 443 ssl;
    server_name ai.internal.example.com;

    ssl_certificate /etc/nginx/certs/server.crt;
    ssl_certificate_key /etc/nginx/certs/server.key;

    location / {
        proxy_pass http://envelope;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /health {
        proxy_pass http://envelope/health;
    }
}
```

---

## Security Considerations

### 1. Network Isolation
- Model backend on isolated network segment
- No direct external access to model
- All traffic through envelope gates

### 2. Encryption
- TLS 1.3 for all network traffic
- Encryption at rest for databases
- Per-subject payload encryption

### 3. Authentication
- mTLS between components
- JWT for client authentication
- Vault tokens for key access

### 4. Audit Logging
- All requests logged with provenance
- Vault audit log enabled
- Centralized log aggregation

---

## Monitoring

### Health Checks
```bash
# Envelope health
curl https://ai.internal/health

# Model backend health
curl http://gpu-node:11434/api/version

# Database health
pg_isready -h postgres -p 5432
```

### Metrics
- Request latency (P50, P95, P99)
- Request throughput
- Error rates by type
- Model inference time
- Queue depth

### Alerts
- Envelope instance down
- Model backend unhealthy
- Database connection failures
- High error rate (>1%)
- Conformance test failures

---

## Disaster Recovery

### Backup Strategy
| Component | Method | Frequency | Retention |
|-----------|--------|-----------|-----------|
| PostgreSQL | pg_dump + WAL | Continuous | 30 days |
| Vault | Snapshot | Daily | 90 days |
| Manifests | Git | Continuous | Forever |
| Model weights | Artifact store | Per version | Forever |

### Recovery Procedure
1. Restore database from backup
2. Unseal Vault
3. Deploy envelope instances
4. Run conformance tests
5. Resume traffic

### RTO/RPO
- **RTO:** 4 hours
- **RPO:** 1 hour (with continuous WAL archiving)

---

## Capacity Planning

### Sizing Guidelines

| Workload | Envelope Instances | GPU Nodes | Database |
|----------|-------------------|-----------|----------|
| Small (100 req/min) | 2 | 1 | 2 vCPU, 8 GB |
| Medium (1K req/min) | 4 | 2 | 4 vCPU, 16 GB |
| Large (10K req/min) | 8 | 4 | 8 vCPU, 32 GB |

### Scaling Triggers
- Scale envelope: CPU > 70% or latency P95 > 500ms
- Scale model backend: GPU utilization > 80%
- Scale database: Connection count > 80% of max
