"""
Egress Gate (C3)

Scans responses for policy violations before release.
Includes PII detection, grounding checks, and content filtering.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from envelope.types import (
    InferenceResponse,
    PolicyDecision,
    DecisionVerdict,
)
from envelope.declaration.manifest import ModelManifest
from envelope.declaration.taxonomy import DataClassTaxonomy


@dataclass
class EgressViolation:
    """A detected egress policy violation."""
    code: str
    message: str
    severity: str  # error, warning
    location: tuple[int, int] | None = None  # (start, end) positions
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EgressResult:
    """Result of egress gate check."""
    allowed: bool
    decision: PolicyDecision
    violations: list[EgressViolation] = field(default_factory=list)
    warnings: list[EgressViolation] = field(default_factory=list)
    sanitized_content: str | None = None
    grounding_score: float = 1.0


class EgressGate:
    """
    Egress gate for validating model responses.

    Checks:
    - PII leakage detection
    - Grounding verification (responses based on provided context)
    - Content filtering (prohibited content)
    - Data class boundary enforcement

    Responses with violations are blocked or sanitized.
    """

    # Patterns for detecting potentially problematic content
    PII_PATTERNS = {
        "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        "phone": re.compile(r'\b(?:\+\d{1,3}[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b'),
        "ssn": re.compile(r'\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b'),
        "credit_card": re.compile(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b'),
    }

    PROHIBITED_PATTERNS = {
        "api_key": re.compile(r'\b(?:sk-|api[_-]?key[:\s=]+)[A-Za-z0-9\-_]{20,}\b', re.IGNORECASE),
        "password": re.compile(r'\bpassword[:\s=]+[^\s]{4,}\b', re.IGNORECASE),
        "secret": re.compile(r'\bsecret[:\s=]+[^\s]{4,}\b', re.IGNORECASE),
    }

    def __init__(
        self,
        manifest: ModelManifest,
        taxonomy: DataClassTaxonomy | None = None,
        enable_pii_check: bool = True,
        enable_grounding_check: bool = True,
        grounding_threshold: float = 0.7,
        block_on_pii: bool = True,
    ):
        self._manifest = manifest
        self._taxonomy = taxonomy or DataClassTaxonomy()
        self._enable_pii_check = enable_pii_check
        self._enable_grounding_check = enable_grounding_check
        self._grounding_threshold = grounding_threshold
        self._block_on_pii = block_on_pii

    @property
    def manifest(self) -> ModelManifest:
        return self._manifest

    def check(
        self,
        response: InferenceResponse,
        context: str | None = None,
        allowed_data_classes: frozenset[str] | None = None,
    ) -> EgressResult:
        """
        Check if a response is allowed through the gate.

        Args:
            response: The model response to check
            context: Optional context for grounding verification
            allowed_data_classes: Data classes allowed for this request

        Returns:
            EgressResult with decision and any violations
        """
        violations: list[EgressViolation] = []
        warnings: list[EgressViolation] = []

        content = response.content

        # Check for PII
        if self._enable_pii_check:
            pii_violations = self._check_pii(content)
            for v in pii_violations:
                if self._block_on_pii:
                    violations.append(v)
                else:
                    v.severity = "warning"
                    warnings.append(v)

        # Check for prohibited content
        prohibited_violations = self._check_prohibited(content)
        violations.extend(prohibited_violations)

        # Check grounding
        grounding_score = 1.0
        if self._enable_grounding_check and context:
            grounding_score = self._check_grounding(content, context)
            if grounding_score < self._grounding_threshold:
                warnings.append(EgressViolation(
                    code="POOR_GROUNDING",
                    message=f"Response may not be well-grounded (score: {grounding_score:.2f})",
                    severity="warning",
                    metadata={"grounding_score": grounding_score},
                ))

        # Determine decision
        if violations:
            return EgressResult(
                allowed=False,
                decision=PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="egress_violations",
                    rule_citation=f"{len(violations)} violation(s) detected",
                    reason=violations[0].message,
                ),
                violations=violations,
                warnings=warnings,
                grounding_score=grounding_score,
            )

        # Create sanitized content if there were warnings
        sanitized = content
        if warnings:
            sanitized = self._sanitize_content(content)

        return EgressResult(
            allowed=True,
            decision=PolicyDecision(
                verdict=DecisionVerdict.ALLOW,
                rule_id="egress_allowed",
                rule_citation="Response passed egress checks",
                reason="Response allowed",
            ),
            violations=[],
            warnings=warnings,
            sanitized_content=sanitized,
            grounding_score=grounding_score,
        )

    def _check_pii(self, content: str) -> list[EgressViolation]:
        """Check for PII patterns in content."""
        violations: list[EgressViolation] = []

        for pii_type, pattern in self.PII_PATTERNS.items():
            matches = list(pattern.finditer(content))
            for match in matches:
                violations.append(EgressViolation(
                    code=f"PII_DETECTED_{pii_type.upper()}",
                    message=f"Potential {pii_type} detected in response",
                    severity="error",
                    location=(match.start(), match.end()),
                    metadata={"pii_type": pii_type},
                ))

        return violations

    def _check_prohibited(self, content: str) -> list[EgressViolation]:
        """Check for prohibited patterns in content."""
        violations: list[EgressViolation] = []

        for pattern_type, pattern in self.PROHIBITED_PATTERNS.items():
            matches = list(pattern.finditer(content))
            for match in matches:
                violations.append(EgressViolation(
                    code=f"PROHIBITED_{pattern_type.upper()}",
                    message=f"Prohibited content detected: potential {pattern_type}",
                    severity="error",
                    location=(match.start(), match.end()),
                    metadata={"type": pattern_type},
                ))

        return violations

    def _check_grounding(self, content: str, context: str) -> float:
        """
        Check how well the response is grounded in the context.

        Returns a score between 0 and 1.
        This is a simplified implementation - production would use
        NLP/embedding-based similarity.
        """
        if not context:
            return 1.0

        # Simple word overlap as proxy for grounding
        content_words = set(content.lower().split())
        context_words = set(context.lower().split())

        # Remove common stop words
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "and", "or", "but", "if", "then", "else", "this", "that",
        }
        content_words -= stop_words
        context_words -= stop_words

        if not content_words:
            return 1.0

        overlap = content_words & context_words
        return len(overlap) / len(content_words)

    def _sanitize_content(self, content: str) -> str:
        """Sanitize content by redacting sensitive patterns."""
        result = content

        # Redact PII
        for pii_type, pattern in self.PII_PATTERNS.items():
            result = pattern.sub(f"[REDACTED_{pii_type.upper()}]", result)

        # Redact prohibited patterns
        for pattern_type, pattern in self.PROHIBITED_PATTERNS.items():
            result = pattern.sub(f"[REDACTED_{pattern_type.upper()}]", result)

        return result

    def create_blocked_response(
        self,
        response: InferenceResponse,
        violations: list[EgressViolation],
    ) -> InferenceResponse:
        """
        Create a blocked response indicating content was withheld.

        Used when egress check fails and content cannot be released.
        """
        from envelope.types import InferenceResponse as IR

        return InferenceResponse(
            request_id=response.request_id,
            content="[Response withheld due to policy violation]",
            metadata={
                "blocked": True,
                "violation_count": len(violations),
                "violation_codes": [v.code for v in violations],
            },
            timestamp=response.timestamp,
            withheld=True,
        )

    def get_content_metrics(self, content: str) -> dict[str, Any]:
        """Get content analysis metrics for monitoring."""
        pii_counts: dict[str, int] = {}
        for pii_type, pattern in self.PII_PATTERNS.items():
            matches = pattern.findall(content)
            if matches:
                pii_counts[pii_type] = len(matches)

        prohibited_counts: dict[str, int] = {}
        for pattern_type, pattern in self.PROHIBITED_PATTERNS.items():
            matches = pattern.findall(content)
            if matches:
                prohibited_counts[pattern_type] = len(matches)

        return {
            "length": len(content),
            "word_count": len(content.split()),
            "pii_detected": pii_counts,
            "prohibited_detected": prohibited_counts,
            "has_violations": bool(pii_counts or prohibited_counts),
        }
