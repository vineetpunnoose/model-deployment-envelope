"""
Enforcement Layer (Section C)

Platform-enforced gates that control all interactions:
- IngressGate (C1): Validates callers and payloads at entry
- ToolGate (C2): Controls tool invocations (deny-by-default)
- EgressGate (C3): Scans responses for policy violations
- EscalationEnforcer (C4): Enforces escalation conditions
- KeyBroker (C5): Manages encryption key grants

All gates implement deny-by-default semantics.
"""

from envelope.enforcement.ingress import IngressGate, IngressResult
from envelope.enforcement.tool_gate import ToolGate, ToolGateResult
from envelope.enforcement.egress import EgressGate, EgressResult
from envelope.enforcement.escalation import EscalationEnforcer, EscalationTrigger
from envelope.enforcement.key_broker import KeyBroker, KeyGrant

__all__ = [
    "IngressGate",
    "IngressResult",
    "ToolGate",
    "ToolGateResult",
    "EgressGate",
    "EgressResult",
    "EscalationEnforcer",
    "EscalationTrigger",
    "KeyBroker",
    "KeyGrant",
]
