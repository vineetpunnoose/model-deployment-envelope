"""
Validation Layer (Section B)

Provides validators that REFUSE deployment if rules are violated:
- StructuralValidator (B1): Validates manifest against reality (tools exist, etc.)
- CompositionValidator (B2): Checks for confused-deputy vulnerabilities
- PlacementValidator (B3): Validates data classes against placement constraints

All validators return detailed error messages with file/line citations.
Validation failures are non-recoverable - no override flags.
"""

from envelope.validation.structural import StructuralValidator, StructuralError
from envelope.validation.composition import CompositionValidator, CompositionError
from envelope.validation.placement import PlacementValidator, PlacementValidationError

__all__ = [
    "StructuralValidator",
    "StructuralError",
    "CompositionValidator",
    "CompositionError",
    "PlacementValidator",
    "PlacementValidationError",
]
