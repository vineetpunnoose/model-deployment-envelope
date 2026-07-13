"""
Handoff System (Section F)

Manages escalation handoffs to human reviewers:
- EscalationInterface (F1): Standard escalation interface
- ReferenceSink (F2): Minimal escalation receiver for demo
- WebhookAdapter (F3): Integration with external case systems

The handoff system ensures escalated cases reach human reviewers
with all necessary context for resolution.
"""

from envelope.handoff.escalation import EscalationInterface, EscalationCase
from envelope.handoff.reference_sink import ReferenceSink, SinkEntry
from envelope.handoff.adapters.webhook import WebhookAdapter

__all__ = [
    "EscalationInterface",
    "EscalationCase",
    "ReferenceSink",
    "SinkEntry",
    "WebhookAdapter",
]
