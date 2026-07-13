"""
Declaration Layer (Section A)

This module provides the declarative components for model deployment envelopes:
- ModelManifest (A1): YAML manifest loader with JSON schema validation
- ToolRegistry (A2): Tool registry with deny-by-default policy
- DataClassTaxonomy (A3): Data classification taxonomy with sensitivity levels
- PlacementPolicy (A4): Placement policy evaluator

All declarations are immutable once loaded and serve as the source of truth
for what a model deployment is permitted to do.
"""

from envelope.declaration.manifest import ModelManifest, ManifestLoader
from envelope.declaration.tools import ToolRegistry, ToolDefinition
from envelope.declaration.taxonomy import DataClassTaxonomy, DataClass, SensitivityLevel
from envelope.declaration.placement import PlacementPolicy, Placement, PlacementRule

__all__ = [
    "ModelManifest",
    "ManifestLoader",
    "ToolRegistry",
    "ToolDefinition",
    "DataClassTaxonomy",
    "DataClass",
    "SensitivityLevel",
    "PlacementPolicy",
    "Placement",
    "PlacementRule",
]
