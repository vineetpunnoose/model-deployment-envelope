"""
Webhook Adapter (F3)

Generic webhook adapter for integrating with external case systems.
Sends escalation events as HTTP POST requests.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx

from envelope.handoff.escalation import (
    EscalationInterface,
    EscalationCase,
    CaseStatus,
    CasePriority,
)


@dataclass
class WebhookConfig:
    """Configuration for webhook adapter."""
    endpoint: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0
    retry_count: int = 3
    retry_delay: float = 1.0
    auth_type: str | None = None  # 'bearer', 'basic', 'api_key'
    auth_value: str | None = None
    verify_ssl: bool = True

    def get_auth_headers(self) -> dict[str, str]:
        """Get authentication headers."""
        if not self.auth_type or not self.auth_value:
            return {}

        if self.auth_type == "bearer":
            return {"Authorization": f"Bearer {self.auth_value}"}
        elif self.auth_type == "basic":
            import base64
            encoded = base64.b64encode(self.auth_value.encode()).decode()
            return {"Authorization": f"Basic {encoded}"}
        elif self.auth_type == "api_key":
            return {"X-API-Key": self.auth_value}

        return {}


@dataclass
class WebhookDelivery:
    """Record of a webhook delivery attempt."""
    delivery_id: str
    case_id: UUID
    endpoint: str
    status_code: int | None
    success: bool
    response_body: str | None = None
    error: str | None = None
    attempt: int = 1
    timestamp: datetime = field(default_factory=datetime.utcnow)


class WebhookAdapter(EscalationInterface):
    """
    Webhook adapter for external case system integration.

    Sends escalation events to a configured webhook endpoint.
    Supports retries, authentication, and delivery tracking.
    """

    def __init__(
        self,
        config: WebhookConfig,
        fallback_sink: EscalationInterface | None = None,
    ):
        self._config = config
        self._fallback = fallback_sink
        self._cases: dict[UUID, EscalationCase] = {}
        self._deliveries: list[WebhookDelivery] = []
        self._client: httpx.AsyncClient | None = None

    @property
    def config(self) -> WebhookConfig:
        return self._config

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._config.timeout),
                verify=self._config.verify_ssl,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def escalate(
        self,
        request_id: UUID,
        context: dict[str, Any],
        reason: str,
        evidence_refs: list[str],
    ) -> EscalationCase:
        """Send escalation to webhook endpoint."""
        case = EscalationCase.create(
            request_id=request_id,
            reason=reason,
            evidence_refs=evidence_refs,
            context=context,
        )

        # Store locally
        self._cases[case.case_id] = case

        # Attempt delivery
        delivery = await self._deliver(case)

        if not delivery.success:
            # Try fallback if configured
            if self._fallback:
                await self._fallback.escalate(
                    request_id, context, reason, evidence_refs
                )

        return case

    async def _deliver(
        self,
        case: EscalationCase,
        attempt: int = 1,
    ) -> WebhookDelivery:
        """Deliver case to webhook endpoint."""
        import asyncio
        from uuid import uuid4

        client = await self._get_client()

        # Build payload
        payload = self._build_payload(case)

        # Build headers
        headers = {
            "Content-Type": "application/json",
            **self._config.headers,
            **self._config.get_auth_headers(),
        }

        delivery_id = str(uuid4())

        try:
            response = await client.request(
                method=self._config.method,
                url=self._config.endpoint,
                json=payload,
                headers=headers,
            )

            delivery = WebhookDelivery(
                delivery_id=delivery_id,
                case_id=case.case_id,
                endpoint=self._config.endpoint,
                status_code=response.status_code,
                success=200 <= response.status_code < 300,
                response_body=response.text[:1000],
                attempt=attempt,
            )

            self._deliveries.append(delivery)

            # Retry if needed
            if not delivery.success and attempt < self._config.retry_count:
                await asyncio.sleep(self._config.retry_delay * attempt)
                return await self._deliver(case, attempt + 1)

            return delivery

        except Exception as e:
            delivery = WebhookDelivery(
                delivery_id=delivery_id,
                case_id=case.case_id,
                endpoint=self._config.endpoint,
                status_code=None,
                success=False,
                error=str(e),
                attempt=attempt,
            )

            self._deliveries.append(delivery)

            # Retry if needed
            if attempt < self._config.retry_count:
                await asyncio.sleep(self._config.retry_delay * attempt)
                return await self._deliver(case, attempt + 1)

            return delivery

    def _build_payload(self, case: EscalationCase) -> dict[str, Any]:
        """Build webhook payload."""
        return {
            "event_type": "escalation.created",
            "timestamp": datetime.utcnow().isoformat(),
            "case": case.to_dict(),
        }

    async def get_case(self, case_id: UUID) -> EscalationCase | None:
        """Get a case by ID."""
        return self._cases.get(case_id)

    async def update_case(
        self,
        case_id: UUID,
        status: CaseStatus | None = None,
        assignee: str | None = None,
        notes: str | None = None,
    ) -> EscalationCase | None:
        """Update a case (local only - external updates require callback)."""
        case = self._cases.get(case_id)
        if case is None:
            return None

        if status:
            case.status = status
        if assignee:
            case.assign(assignee)
        if notes:
            case.add_note("webhook_user", notes)

        case.updated_at = datetime.utcnow()

        # Optionally send update to webhook
        await self._send_update(case)

        return case

    async def _send_update(self, case: EscalationCase) -> WebhookDelivery | None:
        """Send case update to webhook."""
        client = await self._get_client()

        payload = {
            "event_type": "escalation.updated",
            "timestamp": datetime.utcnow().isoformat(),
            "case": case.to_dict(),
        }

        headers = {
            "Content-Type": "application/json",
            **self._config.headers,
            **self._config.get_auth_headers(),
        }

        try:
            response = await client.request(
                method=self._config.method,
                url=self._config.endpoint,
                json=payload,
                headers=headers,
            )

            from uuid import uuid4
            delivery = WebhookDelivery(
                delivery_id=str(uuid4()),
                case_id=case.case_id,
                endpoint=self._config.endpoint,
                status_code=response.status_code,
                success=200 <= response.status_code < 300,
            )
            self._deliveries.append(delivery)
            return delivery

        except Exception:
            return None

    async def list_cases(
        self,
        status: CaseStatus | None = None,
        limit: int = 100,
    ) -> list[EscalationCase]:
        """List cases."""
        cases = list(self._cases.values())

        if status:
            cases = [c for c in cases if c.status == status]

        return sorted(cases, key=lambda c: c.created_at, reverse=True)[:limit]

    async def resolve_case(
        self,
        case_id: UUID,
        resolution: str,
    ) -> EscalationCase | None:
        """Resolve a case."""
        case = self._cases.get(case_id)
        if case is None:
            return None

        case.resolve(resolution)

        # Send resolution to webhook
        await self._send_update(case)

        return case

    def get_deliveries(
        self,
        case_id: UUID | None = None,
        limit: int = 100,
    ) -> list[WebhookDelivery]:
        """Get delivery history."""
        deliveries = self._deliveries

        if case_id:
            deliveries = [d for d in deliveries if d.case_id == case_id]

        return deliveries[-limit:]

    def get_failed_deliveries(self) -> list[WebhookDelivery]:
        """Get failed deliveries."""
        return [d for d in self._deliveries if not d.success]

    def get_stats(self) -> dict[str, Any]:
        """Get adapter statistics."""
        total_deliveries = len(self._deliveries)
        successful = sum(1 for d in self._deliveries if d.success)
        failed = total_deliveries - successful

        return {
            "cases": len(self._cases),
            "total_deliveries": total_deliveries,
            "successful_deliveries": successful,
            "failed_deliveries": failed,
            "success_rate": (successful / total_deliveries * 100) if total_deliveries else 0,
        }

    async def process_callback(
        self, data: dict[str, Any]
    ) -> EscalationCase | None:
        """
        Process a callback from the external system.

        This allows the external case system to update case status.
        """
        case_id_str = data.get("case_id")
        if not case_id_str:
            return None

        try:
            case_id = UUID(case_id_str)
        except ValueError:
            return None

        case = self._cases.get(case_id)
        if case is None:
            return None

        # Apply updates from callback
        if "status" in data:
            try:
                case.status = CaseStatus(data["status"])
            except ValueError:
                pass

        if "assignee" in data:
            case.assignee = data["assignee"]

        if "resolution" in data:
            case.resolve(data["resolution"])

        if "notes" in data:
            case.add_note("external_system", data["notes"])

        case.updated_at = datetime.utcnow()
        return case
