# Model Deployment Envelope - Gap Assessment Checklist

This structured assessment helps organizations identify gaps between their current AI deployment practices and the requirements for a governed Model Deployment Envelope.

---

## 1. Declaration Layer Assessment

### 1.1 Model Manifests
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| All deployed models have written manifests | ☐ Yes ☐ Partial ☐ No | | |
| Manifests are machine-readable (YAML/JSON) | ☐ Yes ☐ Partial ☐ No | | |
| Manifests include version information | ☐ Yes ☐ Partial ☐ No | | |
| Manifests are stored in version control | ☐ Yes ☐ Partial ☐ No | | |
| Schema validation is performed on manifests | ☐ Yes ☐ Partial ☐ No | | |

### 1.2 Tool Registration
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| All model-accessible tools are documented | ☐ Yes ☐ Partial ☐ No | | |
| Tools have defined input/output schemas | ☐ Yes ☐ Partial ☐ No | | |
| Tool permissions are explicit (deny-by-default) | ☐ Yes ☐ Partial ☐ No | | |
| Unregistered tools are blocked at runtime | ☐ Yes ☐ Partial ☐ No | | |

### 1.3 Data Classification
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Data classification taxonomy exists | ☐ Yes ☐ Partial ☐ No | | |
| Sensitivity levels are defined | ☐ Yes ☐ Partial ☐ No | | |
| PII fields are identified per data class | ☐ Yes ☐ Partial ☐ No | | |
| Regulatory frameworks are mapped to data classes | ☐ Yes ☐ Partial ☐ No | | |
| Retention policies are defined | ☐ Yes ☐ Partial ☐ No | | |

### 1.4 Placement Policy
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Deployment environments are documented | ☐ Yes ☐ Partial ☐ No | | |
| Certification requirements are defined per environment | ☐ Yes ☐ Partial ☐ No | | |
| Data residency rules are documented | ☐ Yes ☐ Partial ☐ No | | |
| Placement rules are machine-enforceable | ☐ Yes ☐ Partial ☐ No | | |

---

## 2. Validation Layer Assessment

### 2.1 Structural Validation
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Manifests are validated before deployment | ☐ Yes ☐ Partial ☐ No | | |
| Validation failures block deployment | ☐ Yes ☐ Partial ☐ No | | |
| No override flags exist for validation | ☐ Yes ☐ Partial ☐ No | | |
| Validation errors cite specific violations | ☐ Yes ☐ Partial ☐ No | | |

### 2.2 Composition Validation
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Tool-data class relationships are validated | ☐ Yes ☐ Partial ☐ No | | |
| Confused deputy patterns are detected | ☐ Yes ☐ Partial ☐ No | | |
| Privilege escalation paths are blocked | ☐ Yes ☐ Partial ☐ No | | |

### 2.3 Placement Validation
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Placement-data class compatibility is checked | ☐ Yes ☐ Partial ☐ No | | |
| Forbidden placements are enforced | ☐ Yes ☐ Partial ☐ No | | |
| Certification requirements are verified | ☐ Yes ☐ Partial ☐ No | | |

---

## 3. Enforcement Layer Assessment

### 3.1 Ingress Gate
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Caller identity is verified on every request | ☐ Yes ☐ Partial ☐ No | | |
| Unauthorized callers are rejected | ☐ Yes ☐ Partial ☐ No | | |
| Input data classes are validated | ☐ Yes ☐ Partial ☐ No | | |
| PII is detected in payloads | ☐ Yes ☐ Partial ☐ No | | |

### 3.2 Tool Gate
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Tool invocations are intercepted | ☐ Yes ☐ Partial ☐ No | | |
| Model never has direct tool credentials | ☐ Yes ☐ Partial ☐ No | | |
| Unmanifested tools return empty results | ☐ Yes ☐ Partial ☐ No | | |
| Tool usage is logged | ☐ Yes ☐ Partial ☐ No | | |

### 3.3 Egress Gate
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Responses are scanned before delivery | ☐ Yes ☐ Partial ☐ No | | |
| PII leakage is detected and blocked | ☐ Yes ☐ Partial ☐ No | | |
| Grounding requirements are enforced | ☐ Yes ☐ Partial ☐ No | | |
| Response modifications are logged | ☐ Yes ☐ Partial ☐ No | | |

### 3.4 Escalation Enforcement
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Escalation conditions are defined | ☐ Yes ☐ Partial ☐ No | | |
| Low confidence triggers escalation | ☐ Yes ☐ Partial ☐ No | | |
| Escalation withholds model response | ☐ Yes ☐ Partial ☐ No | | |
| Escalations are handed to case systems | ☐ Yes ☐ Partial ☐ No | | |

### 3.5 Key Management
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Encryption keys are managed externally | ☐ Yes ☐ Partial ☐ No | | |
| Key access is placement-aware | ☐ Yes ☐ Partial ☐ No | | |
| Forbidden placements are denied keys | ☐ Yes ☐ Partial ☐ No | | |
| Key grants are audited | ☐ Yes ☐ Partial ☐ No | | |

---

## 4. Record System Assessment

### 4.1 Provenance Records
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| All inferences are recorded | ☐ Yes ☐ Partial ☐ No | | |
| Records include full context | ☐ Yes ☐ Partial ☐ No | | |
| Records are structured (not just logs) | ☐ Yes ☐ Partial ☐ No | | |
| Records are immutable | ☐ Yes ☐ Partial ☐ No | | |

### 4.2 Integrity Verification
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Hash chain links records | ☐ Yes ☐ Partial ☐ No | | |
| Tamper detection is possible | ☐ Yes ☐ Partial ☐ No | | |
| Chain integrity is periodically verified | ☐ Yes ☐ Partial ☐ No | | |

### 4.3 Per-Subject Encryption
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Payloads are encrypted per-subject | ☐ Yes ☐ Partial ☐ No | | |
| GDPR erasure is supported via key deletion | ☐ Yes ☐ Partial ☐ No | | |
| Key rotation is supported | ☐ Yes ☐ Partial ☐ No | | |

### 4.4 Reproduction
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Historical requests can be replayed | ☐ Yes ☐ Partial ☐ No | | |
| Replay uses original model version | ☐ Yes ☐ Partial ☐ No | | |
| Results can be compared | ☐ Yes ☐ Partial ☐ No | | |

---

## 5. Runtime Assessment

### 5.1 Lifecycle Management
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Defined lifecycle states exist | ☐ Yes ☐ Partial ☐ No | | |
| State transitions are enforced | ☐ Yes ☐ Partial ☐ No | | |
| Warmup gate exists before serving | ☐ Yes ☐ Partial ☐ No | | |
| Graceful shutdown is supported | ☐ Yes ☐ Partial ☐ No | | |

### 5.2 Backend Abstraction
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Unified runtime interface exists | ☐ Yes ☐ Partial ☐ No | | |
| Backend switching is config-driven | ☐ Yes ☐ Partial ☐ No | | |
| Multiple backends are supported | ☐ Yes ☐ Partial ☐ No | | |

---

## 6. Verification Assessment

### 6.1 Golden Set Testing
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Golden set tests are defined | ☐ Yes ☐ Partial ☐ No | | |
| Tests run before model goes live | ☐ Yes ☐ Partial ☐ No | | |
| Tests run on schedule | ☐ Yes ☐ Partial ☐ No | | |
| Test failures block deployment | ☐ Yes ☐ Partial ☐ No | | |

### 6.2 Conformance Testing
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Adversarial tests exist | ☐ Yes ☐ Partial ☐ No | | |
| Conformance harness runs regularly | ☐ Yes ☐ Partial ☐ No | | |
| Conformance reports are generated | ☐ Yes ☐ Partial ☐ No | | |

### 6.3 Canary Testing
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Canary tests run in production | ☐ Yes ☐ Partial ☐ No | | |
| Alerting is configured for failures | ☐ Yes ☐ Partial ☐ No | | |

---

## 7. Handoff Assessment

### 7.1 Escalation Handling
| Requirement | Current State | Gap | Priority |
|-------------|---------------|-----|----------|
| Escalation interface is defined | ☐ Yes ☐ Partial ☐ No | | |
| Case systems receive escalations | ☐ Yes ☐ Partial ☐ No | | |
| Context is preserved in handoff | ☐ Yes ☐ Partial ☐ No | | |
| Human reviewers can access evidence | ☐ Yes ☐ Partial ☐ No | | |

---

## Summary Scoring

| Section | Items | Compliant | Partial | Non-Compliant | Score |
|---------|-------|-----------|---------|---------------|-------|
| 1. Declaration | | | | | /100 |
| 2. Validation | | | | | /100 |
| 3. Enforcement | | | | | /100 |
| 4. Records | | | | | /100 |
| 5. Runtime | | | | | /100 |
| 6. Verification | | | | | /100 |
| 7. Handoff | | | | | /100 |
| **Overall** | | | | | **/100** |

---

## Next Steps

1. **Critical Gaps** (Priority 1): Items that must be addressed before deployment
2. **High Priority** (Priority 2): Items to address within 30 days
3. **Medium Priority** (Priority 3): Items to address within 90 days
4. **Low Priority** (Priority 4): Items for long-term roadmap

### Recommended Actions
| Gap | Recommended Action | Owner | Target Date |
|-----|-------------------|-------|-------------|
| | | | |
| | | | |
| | | | |
