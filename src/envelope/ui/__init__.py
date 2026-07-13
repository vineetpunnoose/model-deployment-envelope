"""
Envelope Dashboard UI

Human-in-the-loop interface for:
- Viewing interactions and audit trails
- Handling escalations
- Approving/rejecting requests
- Monitoring system health
"""

from .dashboard import create_dashboard_app

__all__ = ["create_dashboard_app"]
