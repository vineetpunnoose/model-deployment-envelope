"""
Placement Validator (B3)

Validates that data classes are allowed at specified placements:
- Data sensitivity matches placement security level
- Regulatory requirements are met at the placement
- Encryption requirements are satisfied

Returns non-zero exit on validation failure - no override.
"""

from dataclasses import dataclass, field
from typing import Any

from envelope.declaration.manifest import ModelManifest
from envelope.declaration.taxonomy import DataClassTaxonomy, SensitivityLevel
from envelope.declaration.placement import PlacementPolicy, Placement
from envelope.types import DecisionVerdict, PolicyDecision, CallerIdentity


@dataclass
class PlacementValidationError:
    """
    A placement validation error with rule citation.

    Provides the specific rule that caused the validation failure
    for audit and debugging purposes.
    """
    code: str
    message: str
    placement_id: str
    data_class: str | None = None
    rule_id: str | None = None
    rule_citation: str = ""
    severity: str = "error"

    def __str__(self) -> str:
        citation = f" [Rule: {self.rule_id}]" if self.rule_id else ""
        return f"{self.severity.upper()}: {self.code} at {self.placement_id}{citation}: {self.message}"


@dataclass
class PlacementValidationResult:
    """Result of placement validation."""
    valid: bool
    errors: list[PlacementValidationError] = field(default_factory=list)
    warnings: list[PlacementValidationError] = field(default_factory=list)
    decisions: list[PolicyDecision] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)

    def __bool__(self) -> bool:
        return self.valid


class PlacementValidator:
    """
    Validates data class placement constraints.

    Ensures that data classes are only processed at placements
    that meet their security, regulatory, and technical requirements.
    Validation failures REFUSE deployment.
    """

    # Sensitivity level requirements for placement types
    PLACEMENT_MAX_SENSITIVITY: dict[str, SensitivityLevel] = {
        "public-cloud": SensitivityLevel.CONFIDENTIAL,
        "private-cloud": SensitivityLevel.RESTRICTED,
        "on-premises": SensitivityLevel.PROHIBITED,
        "edge": SensitivityLevel.INTERNAL,
        "hybrid": SensitivityLevel.RESTRICTED,
    }

    def __init__(
        self,
        taxonomy: DataClassTaxonomy | None = None,
        placement_policy: PlacementPolicy | None = None,
    ):
        self._taxonomy = taxonomy or DataClassTaxonomy()
        self._placement_policy = placement_policy or PlacementPolicy()

    @property
    def taxonomy(self) -> DataClassTaxonomy:
        return self._taxonomy

    @property
    def placement_policy(self) -> PlacementPolicy:
        return self._placement_policy

    def validate(
        self,
        manifest: ModelManifest,
        target_placement_id: str | None = None,
    ) -> PlacementValidationResult:
        """
        Validate placement constraints for a manifest.

        If target_placement_id is not provided, uses the manifest's
        currentPlacement.
        """
        errors: list[PlacementValidationError] = []
        warnings: list[PlacementValidationError] = []
        decisions: list[PolicyDecision] = []

        placement_id = target_placement_id or manifest.spec.placement.current_placement
        if not placement_id:
            errors.append(PlacementValidationError(
                code="NO_PLACEMENT_SPECIFIED",
                message="No placement specified and no currentPlacement in manifest",
                placement_id="(none)",
            ))
            return PlacementValidationResult(valid=False, errors=errors)

        # Get placement from policy
        placement = self._placement_policy.get_placement(placement_id)
        if placement is None:
            errors.append(PlacementValidationError(
                code="PLACEMENT_NOT_FOUND",
                message=f"Placement '{placement_id}' not found in policy",
                placement_id=placement_id,
            ))
            return PlacementValidationResult(valid=False, errors=errors)

        # Validate each allowed data class at the placement
        for dc_name in manifest.spec.data_classes.allowed:
            dc_errors, dc_warnings, dc_decisions = self._validate_data_class_at_placement(
                dc_name, placement
            )
            errors.extend(dc_errors)
            warnings.extend(dc_warnings)
            decisions.extend(dc_decisions)

        # Validate tools at the placement
        tool_errors, tool_warnings = self._validate_tools_at_placement(
            manifest, placement
        )
        errors.extend(tool_errors)
        warnings.extend(tool_warnings)

        return PlacementValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            decisions=decisions,
        )

    def _validate_data_class_at_placement(
        self,
        dc_name: str,
        placement: Placement,
    ) -> tuple[list[PlacementValidationError], list[PlacementValidationError], list[PolicyDecision]]:
        """Validate a single data class at a placement."""
        errors: list[PlacementValidationError] = []
        warnings: list[PlacementValidationError] = []
        decisions: list[PolicyDecision] = []

        data_class = self._taxonomy.get_class(dc_name)
        if data_class is None:
            errors.append(PlacementValidationError(
                code="DATA_CLASS_NOT_FOUND",
                message=f"Data class '{dc_name}' not found in taxonomy",
                placement_id=placement.id,
                data_class=dc_name,
            ))
            return errors, warnings, decisions

        # Check explicit placement rules on the data class
        placement_allowed = data_class.requires_placement(placement.id)
        if placement_allowed is False:
            errors.append(PlacementValidationError(
                code="DATA_CLASS_DENIED_AT_PLACEMENT",
                message=f"Data class '{dc_name}' is explicitly denied at placement '{placement.id}'",
                placement_id=placement.id,
                data_class=dc_name,
                rule_citation=f"Data class '{dc_name}' has placement '{placement.id}' in denied list",
            ))

        # Check sensitivity vs placement type
        sensitivity = self._taxonomy.get_effective_sensitivity(dc_name)
        if sensitivity:
            max_sensitivity = self.PLACEMENT_MAX_SENSITIVITY.get(placement.type)
            if max_sensitivity and sensitivity > max_sensitivity:
                errors.append(PlacementValidationError(
                    code="SENSITIVITY_EXCEEDS_PLACEMENT",
                    message=f"Data class '{dc_name}' has sensitivity {sensitivity.name} which exceeds max {max_sensitivity.name} for placement type '{placement.type}'",
                    placement_id=placement.id,
                    data_class=dc_name,
                    rule_citation=f"Placement type '{placement.type}' allows max sensitivity {max_sensitivity.name}",
                ))

        # Check encryption requirements
        if data_class.encryption_required:
            if not placement.encryption_at_rest:
                errors.append(PlacementValidationError(
                    code="ENCRYPTION_AT_REST_REQUIRED",
                    message=f"Data class '{dc_name}' requires encryption at rest but placement '{placement.id}' does not provide it",
                    placement_id=placement.id,
                    data_class=dc_name,
                ))
            if not placement.encryption_in_transit:
                errors.append(PlacementValidationError(
                    code="ENCRYPTION_IN_TRANSIT_REQUIRED",
                    message=f"Data class '{dc_name}' requires encryption in transit but placement '{placement.id}' does not provide it",
                    placement_id=placement.id,
                    data_class=dc_name,
                ))

        # Check regulatory frameworks
        frameworks = self._taxonomy.get_regulatory_frameworks(dc_name)
        self._check_regulatory_compliance(
            dc_name, frameworks, placement, errors, warnings
        )

        # Evaluate placement policy
        decision = self._placement_policy.evaluate(
            placement.id,
            data_class=dc_name,
            taxonomy=self._taxonomy,
        )
        decisions.append(decision)

        if decision.verdict == DecisionVerdict.DENY:
            errors.append(PlacementValidationError(
                code="POLICY_DENIED",
                message=f"Placement policy denied data class '{dc_name}' at placement '{placement.id}'",
                placement_id=placement.id,
                data_class=dc_name,
                rule_id=decision.rule_id,
                rule_citation=decision.rule_citation,
            ))
        elif decision.verdict == DecisionVerdict.ESCALATE:
            warnings.append(PlacementValidationError(
                code="POLICY_ESCALATE",
                message=f"Placement policy requires escalation for data class '{dc_name}' at placement '{placement.id}'",
                placement_id=placement.id,
                data_class=dc_name,
                rule_id=decision.rule_id,
                rule_citation=decision.rule_citation,
                severity="warning",
            ))

        return errors, warnings, decisions

    def _check_regulatory_compliance(
        self,
        dc_name: str,
        frameworks: set[str],
        placement: Placement,
        errors: list[PlacementValidationError],
        warnings: list[PlacementValidationError],
    ) -> None:
        """Check regulatory framework compliance at placement."""
        for framework in frameworks:
            # Check jurisdiction requirements
            if framework == "GDPR":
                if "EU" not in placement.jurisdictions and "EEA" not in placement.jurisdictions:
                    # Check for adequacy decision regions
                    adequate_regions = {"UK", "CH", "JP", "KR", "NZ", "AR", "CA"}
                    if not any(j in adequate_regions for j in placement.jurisdictions):
                        errors.append(PlacementValidationError(
                            code="GDPR_JURISDICTION_VIOLATION",
                            message=f"Data class '{dc_name}' subject to GDPR but placement '{placement.id}' is not in EU/EEA or adequacy-decision region",
                            placement_id=placement.id,
                            data_class=dc_name,
                            rule_citation="GDPR requires data to remain in EU/EEA or regions with adequacy decisions",
                        ))

            elif framework == "PCI-DSS":
                if "PCI-DSS" not in placement.certifications:
                    errors.append(PlacementValidationError(
                        code="PCI_DSS_CERTIFICATION_REQUIRED",
                        message=f"Data class '{dc_name}' subject to PCI-DSS but placement '{placement.id}' lacks PCI-DSS certification",
                        placement_id=placement.id,
                        data_class=dc_name,
                        rule_citation="PCI-DSS data must be processed in PCI-DSS certified environments",
                    ))

            elif framework == "HIPAA":
                if "HIPAA" not in placement.certifications:
                    errors.append(PlacementValidationError(
                        code="HIPAA_CERTIFICATION_REQUIRED",
                        message=f"Data class '{dc_name}' subject to HIPAA but placement '{placement.id}' lacks HIPAA certification",
                        placement_id=placement.id,
                        data_class=dc_name,
                        rule_citation="HIPAA data must be processed in HIPAA-compliant environments",
                    ))

            elif framework == "SOC2":
                if "SOC2" not in placement.certifications:
                    warnings.append(PlacementValidationError(
                        code="SOC2_CERTIFICATION_RECOMMENDED",
                        message=f"Data class '{dc_name}' prefers SOC2 compliance but placement '{placement.id}' lacks SOC2 certification",
                        placement_id=placement.id,
                        data_class=dc_name,
                        severity="warning",
                    ))

    def _validate_tools_at_placement(
        self,
        manifest: ModelManifest,
        placement: Placement,
    ) -> tuple[list[PlacementValidationError], list[PlacementValidationError]]:
        """Validate tool constraints at placement."""
        errors: list[PlacementValidationError] = []
        warnings: list[PlacementValidationError] = []

        # For now, basic validation - tools with external endpoints
        # may have placement restrictions
        if placement.type == "on-premises":
            # On-premises may restrict external API calls
            warnings.append(PlacementValidationError(
                code="ON_PREMISES_EXTERNAL_TOOLS",
                message="On-premises placement may restrict external tool API calls",
                placement_id=placement.id,
                severity="warning",
            ))

        return errors, warnings

    def check_runtime_placement(
        self,
        data_class: str,
        placement_id: str,
        caller: CallerIdentity | None = None,
    ) -> PolicyDecision:
        """
        Check if a data class can be processed at a placement at runtime.

        This is called during request processing to enforce placement constraints.
        """
        placement = self._placement_policy.get_placement(placement_id)
        if placement is None:
            return PolicyDecision(
                verdict=DecisionVerdict.DENY,
                rule_id="placement_not_found",
                rule_citation=f"Placement '{placement_id}' not found",
                reason=f"Unknown placement: {placement_id}",
            )

        # Check explicit data class placement rules
        dc = self._taxonomy.get_class(data_class)
        if dc is not None:
            allowed = dc.requires_placement(placement_id)
            if allowed is False:
                return PolicyDecision(
                    verdict=DecisionVerdict.DENY,
                    rule_id="data_class_placement_denied",
                    rule_citation=f"Data class '{data_class}' denied at placement '{placement_id}'",
                    reason="Data class explicitly denied at this placement",
                )

        # Evaluate full policy
        return self._placement_policy.evaluate(
            placement_id,
            data_class=data_class,
            taxonomy=self._taxonomy,
            caller=caller,
        )

    def get_allowed_placements_for_data_class(
        self, data_class: str
    ) -> list[str]:
        """Get list of placements where a data class is allowed."""
        allowed: list[str] = []

        for placement_id in self._placement_policy.list_placements():
            decision = self.check_runtime_placement(data_class, placement_id)
            if decision.verdict == DecisionVerdict.ALLOW:
                allowed.append(placement_id)

        return allowed

    def get_denied_placements_for_data_class(
        self, data_class: str
    ) -> list[tuple[str, str]]:
        """
        Get list of placements where a data class is denied.

        Returns tuples of (placement_id, denial_reason).
        """
        denied: list[tuple[str, str]] = []

        for placement_id in self._placement_policy.list_placements():
            decision = self.check_runtime_placement(data_class, placement_id)
            if decision.verdict == DecisionVerdict.DENY:
                denied.append((placement_id, decision.reason))

        return denied
