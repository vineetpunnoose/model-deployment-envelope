"""
Escalation Enforcer (C4)

Enforces escalation conditions and withholds responses when triggered.
Ensures model responses are blocked until human review when required.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from envelope.types import (
    InferenceRequest,
    InferenceResponse,
    PolicyDecision,
    DecisionVerdict,
    EscalationRecord,
)
from envelope.declaration.manifest import ModelManifest


class EscalationTrigger(Enum):
    """Types of escalation triggers."""
    CONFIDENCE_LOW = "confidence_low"
    TOOL_FAILURE = "tool_failure"
    POLICY_VIOLATION = "policy_violation"
    EXPLICIT_REQUEST = "explicit_request"
    DATA_CLASS_MISMATCH = "data_class_mismatch"
    CUSTOM = "custom"


@dataclass
class EscalationCondition:
    """Evaluated escalation condition."""
    condition_id: str
    trigger: EscalationTrigger
    met: bool
    threshold: float | None = None
    actual_value: float | None = None
    reason: str = ""


@dataclass
class EscalationDecision:
    """Result of escalation evaluation."""
    should_escalate: bool
    conditions_met: list[EscalationCondition] = field(default_factory=list)
    reason: str = ""
    evidence_refs: list[str] = field(default_factory=list)


class EscalationEnforcer:
    """
    Enforces escalation conditions for model responses.

    When escalation is triggered:
    - Response is withheld from the caller
    - Escalation is recorded for human review
    - Handoff is initiated to case management

    The model never sees that escalation happened - it's
    enforced at the platform level.
    """

    def __init__(self, manifest: ModelManifest):
        self._manifest = manifest
        self._escalation_history: list[EscalationRecord] = []
        self._custom_evaluators: dict[str, Any] = {}

    @property
    def manifest(self) -> ModelManifest:
        return self._manifest

    def register_custom_evaluator(
        self,
        condition_id: str,
        evaluator: Any,  # Callable that returns (met: bool, reason: str)
    ) -> None:
        """Register a custom condition evaluator."""
        self._custom_evaluators[condition_id] = evaluator

    def evaluate(
        self,
        request: InferenceRequest,
        response: InferenceResponse,
        context: dict[str, Any] | None = None,
    ) -> EscalationDecision:
        """
        Evaluate whether escalation is required.

        Checks all configured escalation conditions against
        the request and response.
        """
        context = context or {}
        conditions_met: list[EscalationCondition] = []
        evidence_refs: list[str] = []

        for condition in self._manifest.spec.escalation.conditions:
            trigger = EscalationTrigger(condition.trigger)
            result = self._evaluate_condition(
                condition_id=condition.id,
                trigger=trigger,
                threshold=condition.threshold,
                custom_rule=condition.custom_rule,
                request=request,
                response=response,
                context=context,
            )

            if result.met:
                conditions_met.append(result)
                evidence_refs.append(f"condition:{condition.id}")

        should_escalate = len(conditions_met) > 0

        return EscalationDecision(
            should_escalate=should_escalate,
            conditions_met=conditions_met,
            reason=conditions_met[0].reason if conditions_met else "",
            evidence_refs=evidence_refs,
        )

    def _evaluate_condition(
        self,
        condition_id: str,
        trigger: EscalationTrigger,
        threshold: float | None,
        custom_rule: str | None,
        request: InferenceRequest,
        response: InferenceResponse,
        context: dict[str, Any],
    ) -> EscalationCondition:
        """Evaluate a single escalation condition."""

        if trigger == EscalationTrigger.CONFIDENCE_LOW:
            return self._evaluate_confidence(condition_id, threshold, response, context)

        elif trigger == EscalationTrigger.TOOL_FAILURE:
            return self._evaluate_tool_failure(condition_id, response, context)

        elif trigger == EscalationTrigger.POLICY_VIOLATION:
            return self._evaluate_policy_violation(condition_id, context)

        elif trigger == EscalationTrigger.EXPLICIT_REQUEST:
            return self._evaluate_explicit_request(condition_id, request, response)

        elif trigger == EscalationTrigger.DATA_CLASS_MISMATCH:
            return self._evaluate_data_class_mismatch(condition_id, request, context)

        elif trigger == EscalationTrigger.CUSTOM:
            return self._evaluate_custom(condition_id, custom_rule, request, response, context)

        return EscalationCondition(
            condition_id=condition_id,
            trigger=trigger,
            met=False,
            reason="Unknown trigger type",
        )

    def _evaluate_confidence(
        self,
        condition_id: str,
        threshold: float | None,
        response: InferenceResponse,
        context: dict[str, Any],
    ) -> EscalationCondition:
        """Evaluate low confidence condition."""
        confidence = context.get("confidence", 1.0)
        threshold = threshold or 0.5

        met = confidence < threshold

        return EscalationCondition(
            condition_id=condition_id,
            trigger=EscalationTrigger.CONFIDENCE_LOW,
            met=met,
            threshold=threshold,
            actual_value=confidence,
            reason=f"Confidence {confidence:.2f} below threshold {threshold:.2f}" if met else "",
        )

    def _evaluate_tool_failure(
        self,
        condition_id: str,
        response: InferenceResponse,
        context: dict[str, Any],
    ) -> EscalationCondition:
        """Evaluate tool failure condition."""
        tool_failures = context.get("tool_failures", [])
        met = len(tool_failures) > 0

        return EscalationCondition(
            condition_id=condition_id,
            trigger=EscalationTrigger.TOOL_FAILURE,
            met=met,
            reason=f"Tool failures detected: {tool_failures}" if met else "",
        )

    def _evaluate_policy_violation(
        self,
        condition_id: str,
        context: dict[str, Any],
    ) -> EscalationCondition:
        """Evaluate policy violation condition."""
        violations = context.get("policy_violations", [])
        met = len(violations) > 0

        return EscalationCondition(
            condition_id=condition_id,
            trigger=EscalationTrigger.POLICY_VIOLATION,
            met=met,
            reason=f"Policy violations: {violations}" if met else "",
        )

    def _evaluate_explicit_request(
        self,
        condition_id: str,
        request: InferenceRequest,
        response: InferenceResponse,
    ) -> EscalationCondition:
        """Evaluate explicit escalation request."""
        # Check for escalation keywords in response
        escalation_phrases = [
            "i need to escalate",
            "please escalate",
            "transfer to human",
            "speak to a human",
            "human agent",
            "i'm not able to help",
            "cannot assist",
        ]

        content_lower = response.content.lower()
        met = any(phrase in content_lower for phrase in escalation_phrases)

        return EscalationCondition(
            condition_id=condition_id,
            trigger=EscalationTrigger.EXPLICIT_REQUEST,
            met=met,
            reason="Model explicitly requested escalation" if met else "",
        )

    def _evaluate_data_class_mismatch(
        self,
        condition_id: str,
        request: InferenceRequest,
        context: dict[str, Any],
    ) -> EscalationCondition:
        """Evaluate data class mismatch condition."""
        detected_classes = set(context.get("detected_data_classes", []))
        allowed_classes = set(request.data_classes)

        # Check for detected classes not in allowed
        unexpected = detected_classes - allowed_classes if allowed_classes else set()

        met = len(unexpected) > 0

        return EscalationCondition(
            condition_id=condition_id,
            trigger=EscalationTrigger.DATA_CLASS_MISMATCH,
            met=met,
            reason=f"Unexpected data classes detected: {unexpected}" if met else "",
        )

    def _evaluate_custom(
        self,
        condition_id: str,
        custom_rule: str | None,
        request: InferenceRequest,
        response: InferenceResponse,
        context: dict[str, Any],
    ) -> EscalationCondition:
        """Evaluate custom condition."""
        evaluator = self._custom_evaluators.get(condition_id)

        if evaluator:
            try:
                met, reason = evaluator(request, response, context)
                return EscalationCondition(
                    condition_id=condition_id,
                    trigger=EscalationTrigger.CUSTOM,
                    met=met,
                    reason=reason,
                )
            except Exception as e:
                return EscalationCondition(
                    condition_id=condition_id,
                    trigger=EscalationTrigger.CUSTOM,
                    met=False,
                    reason=f"Custom evaluator error: {e}",
                )

        return EscalationCondition(
            condition_id=condition_id,
            trigger=EscalationTrigger.CUSTOM,
            met=False,
            reason="No custom evaluator registered",
        )

    def create_escalation_record(
        self,
        request: InferenceRequest,
        decision: EscalationDecision,
        context: dict[str, Any] | None = None,
    ) -> EscalationRecord:
        """Create an escalation record for handoff."""
        from uuid import uuid4

        record = EscalationRecord(
            request_id=request.request_id,
            reason=decision.reason,
            evidence_refs=decision.evidence_refs,
            context={
                "caller_id": request.caller.caller_id,
                "model_id": request.model_id,
                "conditions_met": [
                    {
                        "id": c.condition_id,
                        "trigger": c.trigger.value,
                        "reason": c.reason,
                    }
                    for c in decision.conditions_met
                ],
                **(context or {}),
            },
        )

        self._escalation_history.append(record)
        return record

    def create_withheld_response(
        self,
        response: InferenceResponse,
        decision: EscalationDecision,
    ) -> InferenceResponse:
        """
        Create a withheld response for when escalation is triggered.

        The original content is not returned to the caller.
        """
        return InferenceResponse(
            request_id=response.request_id,
            content="[Response withheld pending human review]",
            metadata={
                "withheld": True,
                "escalated": True,
                "escalation_reason": decision.reason,
            },
            timestamp=response.timestamp,
            withheld=True,
            escalated=True,
        )

    def get_escalation_history(
        self,
        limit: int = 100,
    ) -> list[EscalationRecord]:
        """Get recent escalation records."""
        return self._escalation_history[-limit:]

    def get_escalation_stats(self) -> dict[str, Any]:
        """Get escalation statistics."""
        total = len(self._escalation_history)
        if total == 0:
            return {"total": 0}

        by_trigger: dict[str, int] = {}
        for record in self._escalation_history:
            for condition in record.context.get("conditions_met", []):
                trigger = condition.get("trigger", "unknown")
                by_trigger[trigger] = by_trigger.get(trigger, 0) + 1

        return {
            "total": total,
            "by_trigger": by_trigger,
        }
