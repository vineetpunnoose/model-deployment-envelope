"""
Ingress Gate (C1)

Validates callers and payloads at entry point.
Implements deny-by-default for unauthorized requests.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from envelope.types import (
    CallerIdentity,
    InferenceRequest,
    PolicyDecision,
    DecisionVerdict,
    DataClassName,
)
from envelope.declaration.manifest import ModelManifest
from envelope.declaration.taxonomy import DataClassTaxonomy, SensitivityLevel


@dataclass
class IngressResult:
    """Result of ingress gate check."""
    allowed: bool
    decision: PolicyDecision
    sanitized_prompt: str | None = None
    detected_data_classes: list[DataClassName] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class IngressGate:
    """
    Ingress gate for validating incoming requests.

    Checks:
    - Caller identity and authorization
    - Data class detection and validation
    - Payload sanitization
    - Rate limiting (optional)

    Implements deny-by-default: requests are blocked unless
    explicitly allowed by policy.
    """

    # Common PII patterns for detection
    PII_PATTERNS = {
        "email": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        "phone_us": re.compile(r'\b(?:\+1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b'),
        "ssn": re.compile(r'\b[0-9]{3}-[0-9]{2}-[0-9]{4}\b'),
        "credit_card": re.compile(r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13})\b'),
        "ip_address": re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'),
    }

    def __init__(
        self,
        manifest: ModelManifest,
        taxonomy: DataClassTaxonomy | None = None,
        enable_pii_detection: bool = True,
        max_prompt_length: int = 100000,
    ):
        self._manifest = manifest
        self._taxonomy = taxonomy or DataClassTaxonomy()
        self._enable_pii_detection = enable_pii_detection
        self._max_prompt_length = max_prompt_length

    @property
    def manifest(self) -> ModelManifest:
        return self._manifest

    @property
    def taxonomy(self) -> DataClassTaxonomy:
        return self._taxonomy

    def check(self, request: InferenceRequest) -> IngressResult:
        """
        Check if a request is allowed through the gate.

        Returns IngressResult with decision and any modifications.
        """
        warnings: list[str] = []

        # Check caller authorization
        caller_decision = self._check_caller(request.caller)
        if caller_decision.verdict != DecisionVerdict.ALLOW:
            return IngressResult(
                allowed=False,
                decision=caller_decision,
            )

        # Check prompt length
        if len(request.prompt) > self._max_prompt_length:
            return IngressResult(
                allowed=False,
                decision=PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="prompt_too_long",
                    rule_citation="Prompt exceeds maximum length",
                    reason=f"Prompt length {len(request.prompt)} exceeds maximum {self._max_prompt_length}",
                ),
            )

        # Detect data classes in prompt
        detected_data_classes = self._detect_data_classes(request.prompt)

        # Check data class authorization
        dc_decision = self._check_data_classes(
            detected_data_classes,
            request.data_classes,
        )
        if dc_decision.verdict != DecisionVerdict.ALLOW:
            return IngressResult(
                allowed=False,
                decision=dc_decision,
                detected_data_classes=detected_data_classes,
            )

        # Check requested tools
        if request.tools_requested:
            tool_decision = self._check_requested_tools(request.tools_requested)
            if tool_decision.verdict != DecisionVerdict.ALLOW:
                return IngressResult(
                    allowed=False,
                    decision=tool_decision,
                    detected_data_classes=detected_data_classes,
                )

        # Detect PII and add warnings
        if self._enable_pii_detection:
            pii_findings = self._detect_pii(request.prompt)
            for pii_type, count in pii_findings.items():
                warnings.append(f"Detected {count} potential {pii_type} pattern(s) in prompt")

        return IngressResult(
            allowed=True,
            decision=PolicyDecision(
                verdict=DecisionVerdict.ALLOW,
                rule_id="ingress_allowed",
                rule_citation="Request passed all ingress checks",
                reason="Request authorized",
            ),
            sanitized_prompt=request.prompt,  # Could sanitize here
            detected_data_classes=detected_data_classes,
            warnings=warnings,
        )

    def _check_caller(self, caller: CallerIdentity) -> PolicyDecision:
        """Check if caller is authorized."""
        # Check caller ID allowlist
        if self._manifest.spec.callers.allowed_caller_ids:
            if not self._manifest.allows_caller_id(caller.caller_id):
                return PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="caller_not_allowed",
                    rule_citation="Caller ID not in allowlist",
                    reason=f"Caller '{caller.caller_id}' not in allowed caller IDs",
                )

        # Check roles
        if self._manifest.spec.callers.allowed_roles:
            has_allowed_role = any(
                self._manifest.allows_caller_role(role)
                for role in caller.roles
            )
            if not has_allowed_role:
                return PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="caller_role_not_allowed",
                    rule_citation="Caller has no allowed role",
                    reason=f"Caller roles {caller.roles} not in allowed roles",
                )

        return PolicyDecision(
            verdict=DecisionVerdict.ALLOW,
            rule_id="caller_authorized",
            rule_citation="Caller passed authorization checks",
            reason="Caller authorized",
        )

    def _check_data_classes(
        self,
        detected: list[DataClassName],
        declared: frozenset[DataClassName],
    ) -> PolicyDecision:
        """Check if data classes are allowed."""
        allowed = self._manifest.spec.data_classes.allowed

        # Check declared data classes
        for dc in declared:
            if dc not in allowed:
                return PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="data_class_not_allowed",
                    rule_citation=f"Data class '{dc}' not in manifest",
                    reason=f"Data class '{dc}' is not allowed by manifest",
                )

        # Check detected data classes (from content analysis)
        for dc in detected:
            if dc not in allowed:
                return PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="detected_data_class_not_allowed",
                    rule_citation=f"Detected data class '{dc}' not in manifest",
                    reason=f"Detected data class '{dc}' is not allowed by manifest",
                )

        return PolicyDecision(
            verdict=DecisionVerdict.ALLOW,
            rule_id="data_classes_allowed",
            rule_citation="All data classes are allowed",
            reason="Data classes authorized",
        )

    def _check_requested_tools(
        self, tools_requested: frozenset[str]
    ) -> PolicyDecision:
        """Check if requested tools are allowed."""
        allowed = self._manifest.spec.tools.allowed

        for tool in tools_requested:
            if tool not in allowed:
                return PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="tool_not_allowed",
                    rule_citation=f"Tool '{tool}' not in manifest",
                    reason=f"Tool '{tool}' is not allowed by manifest",
                )

        return PolicyDecision(
            verdict=DecisionVerdict.ALLOW,
            rule_id="tools_allowed",
            rule_citation="All requested tools are allowed",
            reason="Tools authorized",
        )

    def _detect_data_classes(self, text: str) -> list[DataClassName]:
        """
        Detect data classes present in text.

        This is a simplified implementation - production would use
        more sophisticated NLP/ML classification.
        """
        detected: list[DataClassName] = []

        # Check for PII indicators
        pii = self._detect_pii(text)
        if pii.get("ssn") or pii.get("credit_card"):
            # Check if we have a PII data class
            if self._taxonomy.has_class("pii"):
                detected.append("pii")
            if self._taxonomy.has_class("financial_pii"):
                detected.append("financial_pii")

        if pii.get("email") or pii.get("phone_us"):
            if self._taxonomy.has_class("contact_info"):
                detected.append("contact_info")

        return detected

    def _detect_pii(self, text: str) -> dict[str, int]:
        """Detect PII patterns in text."""
        findings: dict[str, int] = {}

        for pii_type, pattern in self.PII_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                findings[pii_type] = len(matches)

        return findings

    def sanitize_prompt(self, prompt: str, redact_pii: bool = False) -> str:
        """
        Sanitize a prompt by removing or redacting sensitive content.

        Args:
            prompt: The input prompt
            redact_pii: If True, redact detected PII

        Returns:
            Sanitized prompt
        """
        result = prompt

        if redact_pii:
            for pii_type, pattern in self.PII_PATTERNS.items():
                result = pattern.sub(f"[REDACTED_{pii_type.upper()}]", result)

        return result

    def get_data_class_requirements(
        self, data_classes: list[DataClassName]
    ) -> dict[str, Any]:
        """Get combined requirements for a set of data classes."""
        requirements: dict[str, Any] = {
            "max_sensitivity": SensitivityLevel.PUBLIC,
            "encryption_required": False,
            "regulatory_frameworks": set(),
        }

        for dc_name in data_classes:
            dc = self._taxonomy.get_class(dc_name)
            if dc is None:
                continue

            sensitivity = self._taxonomy.get_effective_sensitivity(dc_name)
            if sensitivity and sensitivity > requirements["max_sensitivity"]:
                requirements["max_sensitivity"] = sensitivity

            if dc.encryption_required:
                requirements["encryption_required"] = True

            frameworks = self._taxonomy.get_regulatory_frameworks(dc_name)
            requirements["regulatory_frameworks"].update(frameworks)

        requirements["regulatory_frameworks"] = list(requirements["regulatory_frameworks"])
        return requirements
