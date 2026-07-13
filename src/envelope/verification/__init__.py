"""
Verification Suite (Section G)

Provides conformance testing and verification:
- ConformanceHarness (G1): Adversarial test harness
- GoldenSetRunner (G2): Golden-set test runner
- CanaryRunner (G3): Scheduled canary tests
- ConformanceReport (G4): Report generation

Ensures the envelope enforces all declared constraints.
"""

from envelope.verification.conformance import ConformanceHarness, ConformanceTest
from envelope.verification.golden_set import GoldenSetRunner, GoldenTestCase, GoldenSetResult
from envelope.verification.canary import CanaryRunner, CanaryConfig
from envelope.verification.report import ConformanceReport, ReportGenerator

__all__ = [
    "ConformanceHarness",
    "ConformanceTest",
    "GoldenSetRunner",
    "GoldenTestCase",
    "GoldenSetResult",
    "CanaryRunner",
    "CanaryConfig",
    "ConformanceReport",
    "ReportGenerator",
]
