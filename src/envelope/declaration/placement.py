"""
Placement Policy Evaluator (A4)

Evaluates placement policies to determine if data can be processed
at specific deployment locations. Returns yes/no with rule citation.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from envelope.types import (
    PolicyDecision,
    DecisionVerdict,
    CallerIdentity,
    ValidationError,
)
from envelope.declaration.taxonomy import SensitivityLevel, DataClassTaxonomy


SCHEMA_DIR = Path(__file__).parent.parent.parent.parent / "schemas"


@dataclass(frozen=True)
class Placement:
    """
    Definition of a deployment placement location.

    Placements represent physical or logical locations where
    models can be deployed, with associated security properties.
    """
    id: str
    type: str  # on-premises, private-cloud, public-cloud, edge, hybrid
    provider: str = ""
    region: str = ""
    jurisdictions: tuple[str, ...] = ()
    certifications: tuple[str, ...] = ()
    encryption_at_rest: bool = True
    encryption_in_transit: bool = True
    attributes: dict[str, Any] = field(default_factory=dict)

    def has_certification(self, cert: str) -> bool:
        """Check if placement has a specific certification."""
        return cert in self.certifications

    def in_jurisdiction(self, jurisdiction: str) -> bool:
        """Check if placement is in a specific jurisdiction."""
        return jurisdiction in self.jurisdictions


@dataclass(frozen=True)
class RuleConditions:
    """Conditions for a placement rule."""
    data_classes: frozenset[str] = frozenset()
    sensitivity_min: SensitivityLevel | None = None
    sensitivity_max: SensitivityLevel | None = None
    placement_types: frozenset[str] = frozenset()
    jurisdictions: frozenset[str] = frozenset()
    required_certifications: frozenset[str] = frozenset()
    caller_roles: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PlacementRule:
    """
    A placement policy rule.

    Rules are evaluated in priority order (lower number = higher priority).
    First matching rule determines the decision.
    """
    id: str
    conditions: RuleConditions
    action: DecisionVerdict
    description: str = ""
    priority: int = 100
    reason: str = ""

    def matches(
        self,
        data_class: str | None,
        sensitivity: SensitivityLevel | None,
        placement: Placement,
        caller: CallerIdentity | None,
    ) -> bool:
        """Check if rule conditions match the request context."""
        conditions = self.conditions

        # Check data class
        if conditions.data_classes and data_class not in conditions.data_classes:
            return False

        # Check sensitivity range
        if sensitivity is not None:
            if conditions.sensitivity_min is not None:
                if sensitivity < conditions.sensitivity_min:
                    return False
            if conditions.sensitivity_max is not None:
                if sensitivity > conditions.sensitivity_max:
                    return False

        # Check placement type
        if conditions.placement_types:
            if placement.type not in conditions.placement_types:
                return False

        # Check jurisdictions
        if conditions.jurisdictions:
            if not any(j in placement.jurisdictions for j in conditions.jurisdictions):
                return False

        # Check required certifications (all must be present)
        if conditions.required_certifications:
            for cert in conditions.required_certifications:
                if not placement.has_certification(cert):
                    return False

        # Check caller roles
        if conditions.caller_roles and caller is not None:
            if not (caller.roles & conditions.caller_roles):
                return False

        return True


class PlacementPolicy:
    """
    Placement policy evaluator.

    Evaluates rules to determine if data can be processed at a specific
    placement. Implements deny-by-default semantics.
    """

    def __init__(
        self,
        name: str = "",
        version: str = "",
        description: str = "",
        default_action: DecisionVerdict = DecisionVerdict.DENY,
    ):
        self._name = name
        self._version = version
        self._description = description
        self._default_action = default_action
        self._placements: dict[str, Placement] = {}
        self._rules: list[PlacementRule] = []
        self._schema: dict[str, Any] | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def description(self) -> str:
        return self._description

    @property
    def default_action(self) -> DecisionVerdict:
        return self._default_action

    @property
    def policy_schema(self) -> dict[str, Any]:
        """Load and cache the placement policy schema."""
        if self._schema is None:
            schema_path = SCHEMA_DIR / "placement-policy.schema.json"
            if not schema_path.exists():
                raise FileNotFoundError(f"Schema not found: {schema_path}")
            with open(schema_path) as f:
                import json
                self._schema = json.load(f)
        return self._schema

    def add_placement(self, placement: Placement) -> None:
        """Add a placement to the policy."""
        self._placements[placement.id] = placement

    def get_placement(self, placement_id: str) -> Placement | None:
        """Get a placement by ID."""
        return self._placements.get(placement_id)

    def list_placements(self) -> list[str]:
        """List all placement IDs."""
        return list(self._placements.keys())

    def add_rule(self, rule: PlacementRule) -> None:
        """Add a rule to the policy."""
        self._rules.append(rule)
        # Keep rules sorted by priority
        self._rules.sort(key=lambda r: r.priority)

    def get_rules(self) -> list[PlacementRule]:
        """Get all rules in priority order."""
        return list(self._rules)

    def evaluate(
        self,
        placement_id: str,
        data_class: str | None = None,
        taxonomy: DataClassTaxonomy | None = None,
        caller: CallerIdentity | None = None,
    ) -> PolicyDecision:
        """
        Evaluate if a request is allowed at a placement.

        Args:
            placement_id: Target placement identifier
            data_class: Optional data class being processed
            taxonomy: Optional taxonomy for sensitivity lookup
            caller: Optional caller identity

        Returns:
            PolicyDecision with verdict and rule citation
        """
        # Get placement
        placement = self._placements.get(placement_id)
        if placement is None:
            return PolicyDecision(
                verdict=DecisionVerdict.DENY,
                rule_id="placement_not_found",
                rule_citation="Placement not registered in policy",
                reason=f"Placement '{placement_id}' not found in policy",
            )

        # Get sensitivity if data class and taxonomy provided
        sensitivity = None
        if data_class and taxonomy:
            sensitivity = taxonomy.get_effective_sensitivity(data_class)

        # Evaluate rules in priority order
        for rule in self._rules:
            if rule.matches(data_class, sensitivity, placement, caller):
                return PolicyDecision(
                    verdict=rule.action,
                    rule_id=rule.id,
                    rule_citation=f"Rule '{rule.id}' (priority {rule.priority}): {rule.description}",
                    reason=rule.reason or f"Matched rule: {rule.id}",
                    metadata={
                        "placement_id": placement_id,
                        "data_class": data_class,
                        "sensitivity": sensitivity.name if sensitivity else None,
                    },
                )

        # No rule matched - apply default action
        return PolicyDecision(
            verdict=self._default_action,
            rule_id="default",
            rule_citation="No matching rule found - applying default action",
            reason=f"Default policy action: {self._default_action.value}",
            metadata={
                "placement_id": placement_id,
                "data_class": data_class,
            },
        )

    def check_placement_allowed(
        self,
        placement_id: str,
        data_class: str | None = None,
        taxonomy: DataClassTaxonomy | None = None,
        caller: CallerIdentity | None = None,
    ) -> bool:
        """Convenience method to check if placement is allowed."""
        decision = self.evaluate(placement_id, data_class, taxonomy, caller)
        return decision.verdict == DecisionVerdict.ALLOW

    def load_from_file(self, path: Path | str) -> None:
        """Load policy from a YAML file."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Policy file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        self.load_from_dict(data)

    def load_from_dict(self, data: dict[str, Any]) -> None:
        """Load policy from a dictionary."""
        errors = self.validate(data)
        if errors:
            raise ValidationError(
                f"Placement policy validation failed: {len(errors)} error(s)",
                errors=errors
            )

        self._parse_policy(data)

    def validate(self, data: dict[str, Any]) -> list[str]:
        """Validate policy data against JSON schema."""
        errors: list[str] = []
        validator = jsonschema.Draft202012Validator(self.policy_schema)

        for error in validator.iter_errors(data):
            path = ".".join(str(p) for p in error.absolute_path) or "(root)"
            errors.append(f"{path}: {error.message}")

        return errors

    def _parse_policy(self, data: dict[str, Any]) -> None:
        """Parse validated data into the policy."""
        metadata = data["metadata"]
        spec = data["spec"]

        self._name = metadata["name"]
        self._version = metadata.get("version", "")
        self._description = metadata.get("description", "")

        # Parse default action
        default = spec.get("defaultAction", "deny")
        self._default_action = (
            DecisionVerdict.ALLOW if default == "allow" else DecisionVerdict.DENY
        )

        # Parse placements
        self._placements = {}
        for p_data in spec.get("placements", []):
            placement = Placement(
                id=p_data["id"],
                type=p_data["type"],
                provider=p_data.get("provider", ""),
                region=p_data.get("region", ""),
                jurisdictions=tuple(p_data.get("jurisdiction", [])),
                certifications=tuple(p_data.get("certifications", [])),
                encryption_at_rest=p_data.get("encryptionAtRest", True),
                encryption_in_transit=p_data.get("encryptionInTransit", True),
                attributes=p_data.get("attributes", {}),
            )
            self._placements[placement.id] = placement

        # Parse rules
        self._rules = []
        for r_data in spec.get("rules", []):
            cond_data = r_data.get("conditions", {})

            # Parse sensitivity range
            sensitivity_min = None
            sensitivity_max = None
            sens_data = cond_data.get("sensitivity", {})
            if "min" in sens_data:
                sensitivity_min = SensitivityLevel.from_string(sens_data["min"])
            if "max" in sens_data:
                sensitivity_max = SensitivityLevel.from_string(sens_data["max"])

            conditions = RuleConditions(
                data_classes=frozenset(cond_data.get("dataClasses", [])),
                sensitivity_min=sensitivity_min,
                sensitivity_max=sensitivity_max,
                placement_types=frozenset(cond_data.get("placementType", [])),
                jurisdictions=frozenset(cond_data.get("jurisdiction", [])),
                required_certifications=frozenset(cond_data.get("requiredCertifications", [])),
                caller_roles=frozenset(cond_data.get("callerRoles", [])),
            )

            # Parse action
            action_str = r_data["action"]
            action = {
                "allow": DecisionVerdict.ALLOW,
                "deny": DecisionVerdict.DENY,
                "escalate": DecisionVerdict.ESCALATE,
            }[action_str]

            rule = PlacementRule(
                id=r_data["id"],
                conditions=conditions,
                action=action,
                description=r_data.get("description", ""),
                priority=r_data.get("priority", 100),
                reason=r_data.get("reason", ""),
            )
            self._rules.append(rule)

        # Sort rules by priority
        self._rules.sort(key=lambda r: r.priority)

    def to_dict(self) -> dict[str, Any]:
        """Convert policy to dictionary representation."""
        return {
            "apiVersion": "envelope.ai/v1",
            "kind": "PlacementPolicy",
            "metadata": {
                "name": self._name,
                "version": self._version,
                "description": self._description,
            },
            "spec": {
                "placements": [
                    {
                        "id": p.id,
                        "type": p.type,
                        "provider": p.provider,
                        "region": p.region,
                        "jurisdiction": list(p.jurisdictions),
                        "certifications": list(p.certifications),
                        "encryptionAtRest": p.encryption_at_rest,
                        "encryptionInTransit": p.encryption_in_transit,
                        "attributes": p.attributes,
                    }
                    for p in self._placements.values()
                ],
                "rules": [
                    {
                        "id": r.id,
                        "description": r.description,
                        "priority": r.priority,
                        "conditions": {
                            "dataClasses": list(r.conditions.data_classes),
                            "sensitivity": {
                                "min": r.conditions.sensitivity_min.name.lower()
                                if r.conditions.sensitivity_min else None,
                                "max": r.conditions.sensitivity_max.name.lower()
                                if r.conditions.sensitivity_max else None,
                            },
                            "placementType": list(r.conditions.placement_types),
                            "jurisdiction": list(r.conditions.jurisdictions),
                            "requiredCertifications": list(r.conditions.required_certifications),
                            "callerRoles": list(r.conditions.caller_roles),
                        },
                        "action": r.action.value,
                        "reason": r.reason,
                    }
                    for r in self._rules
                ],
                "defaultAction": self._default_action.value,
            },
        }
