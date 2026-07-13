"""
API Layer

FastAPI application for model inference with envelope enforcement.
"""

from envelope.api.main import create_app, EnvelopeAPI

__all__ = [
    "create_app",
    "EnvelopeAPI",
]
