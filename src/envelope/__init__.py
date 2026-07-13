"""
Model Deployment Envelope - A declarative envelope around deployed AI models.

This package provides platform-enforced boundaries and machine-checkable proofs
for AI model deployments, ensuring security, compliance, and auditability.

Core Modules:
- declaration: Manifest loading, tool registry, data taxonomy, placement policies
- validation: Structural, composition, and placement validators
- enforcement: Ingress/egress gates, tool gates, escalation, key broker
- record: Provenance records, hash chains, encryption, reproduction
- runtime: Runtime contracts, lifecycle management, backend adapters
- handoff: Escalation handling and case system integration
- verification: Conformance testing, golden sets, canaries
- api: FastAPI application for model inference
- cli: Command-line interface for operations
"""

__version__ = "0.1.0"
__author__ = "Model Deployment Envelope Team"

from envelope.declaration.manifest import ModelManifest
from envelope.declaration.tools import ToolRegistry
from envelope.declaration.taxonomy import DataClassTaxonomy
from envelope.declaration.placement import PlacementPolicy

__all__ = [
    "__version__",
    "ModelManifest",
    "ToolRegistry",
    "DataClassTaxonomy",
    "PlacementPolicy",
]
