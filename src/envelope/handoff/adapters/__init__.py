"""
Handoff Adapters (F3)

Adapters for integrating with external case management systems.
"""

from envelope.handoff.adapters.webhook import WebhookAdapter, WebhookConfig

__all__ = [
    "WebhookAdapter",
    "WebhookConfig",
]
