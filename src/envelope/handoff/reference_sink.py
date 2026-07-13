"""
Reference Sink (F2)

Minimal escalation receiver for demonstration and testing.
Provides a simple UI for viewing and managing escalations.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from envelope.handoff.escalation import (
    EscalationInterface,
    EscalationCase,
    CaseStatus,
    CasePriority,
)


@dataclass
class SinkEntry:
    """
    An entry in the reference sink.

    Wraps an escalation case with sink-specific metadata.
    """
    entry_id: int
    case: EscalationCase
    received_at: datetime = field(default_factory=datetime.utcnow)
    viewed: bool = False
    viewed_at: datetime | None = None
    tags: list[str] = field(default_factory=list)

    def mark_viewed(self) -> None:
        """Mark entry as viewed."""
        self.viewed = True
        self.viewed_at = datetime.utcnow()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "entry_id": self.entry_id,
            "case": self.case.to_dict(),
            "received_at": self.received_at.isoformat(),
            "viewed": self.viewed,
            "viewed_at": self.viewed_at.isoformat() if self.viewed_at else None,
            "tags": self.tags,
        }


class ReferenceSink(EscalationInterface):
    """
    Reference implementation of an escalation sink.

    Provides a minimal receiver for escalations with basic
    viewing and management capabilities. Suitable for
    demonstration and testing.
    """

    def __init__(self, max_entries: int = 1000):
        self._entries: dict[UUID, SinkEntry] = {}
        self._entry_counter = 0
        self._max_entries = max_entries

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    async def escalate(
        self,
        request_id: UUID,
        context: dict[str, Any],
        reason: str,
        evidence_refs: list[str],
    ) -> EscalationCase:
        """Receive an escalation."""
        # Determine priority based on context
        priority = self._determine_priority(context, reason)

        case = EscalationCase.create(
            request_id=request_id,
            reason=reason,
            evidence_refs=evidence_refs,
            context=context,
            priority=priority,
        )

        self._entry_counter += 1
        entry = SinkEntry(
            entry_id=self._entry_counter,
            case=case,
            tags=self._generate_tags(context, reason),
        )

        self._entries[case.case_id] = entry

        # Prune old entries if needed
        self._prune_if_needed()

        return case

    def _determine_priority(
        self, context: dict[str, Any], reason: str
    ) -> CasePriority:
        """Determine case priority based on context."""
        # Check for critical indicators
        critical_keywords = ["urgent", "critical", "emergency", "security"]
        if any(kw in reason.lower() for kw in critical_keywords):
            return CasePriority.CRITICAL

        high_keywords = ["error", "failure", "violation"]
        if any(kw in reason.lower() for kw in high_keywords):
            return CasePriority.HIGH

        return CasePriority.MEDIUM

    def _generate_tags(
        self, context: dict[str, Any], reason: str
    ) -> list[str]:
        """Generate tags for categorization."""
        tags: list[str] = []

        # Add trigger-based tags
        conditions = context.get("conditions_met", [])
        for cond in conditions:
            trigger = cond.get("trigger", "")
            if trigger:
                tags.append(f"trigger:{trigger}")

        # Add model tag
        model_id = context.get("model_id", "")
        if model_id:
            tags.append(f"model:{model_id}")

        return tags

    def _prune_if_needed(self) -> int:
        """Prune old entries if over limit. Returns count pruned."""
        if len(self._entries) <= self._max_entries:
            return 0

        # Remove oldest resolved cases first
        resolved = [
            (cid, e) for cid, e in self._entries.items()
            if e.case.status == CaseStatus.RESOLVED
        ]
        resolved.sort(key=lambda x: x[1].received_at)

        pruned = 0
        while len(self._entries) > self._max_entries and resolved:
            case_id, _ = resolved.pop(0)
            del self._entries[case_id]
            pruned += 1

        return pruned

    async def get_case(self, case_id: UUID) -> EscalationCase | None:
        """Get a case by ID."""
        entry = self._entries.get(case_id)
        if entry is None:
            return None

        # Mark as viewed
        entry.mark_viewed()
        return entry.case

    async def update_case(
        self,
        case_id: UUID,
        status: CaseStatus | None = None,
        assignee: str | None = None,
        notes: str | None = None,
    ) -> EscalationCase | None:
        """Update a case."""
        entry = self._entries.get(case_id)
        if entry is None:
            return None

        case = entry.case
        if status:
            case.status = status
        if assignee:
            case.assign(assignee)
        if notes:
            case.add_note("sink_user", notes)

        case.updated_at = datetime.utcnow()
        return case

    async def list_cases(
        self,
        status: CaseStatus | None = None,
        limit: int = 100,
    ) -> list[EscalationCase]:
        """List cases with optional filtering."""
        cases = [e.case for e in self._entries.values()]

        if status:
            cases = [c for c in cases if c.status == status]

        return sorted(cases, key=lambda c: c.created_at, reverse=True)[:limit]

    async def resolve_case(
        self,
        case_id: UUID,
        resolution: str,
    ) -> EscalationCase | None:
        """Resolve a case."""
        entry = self._entries.get(case_id)
        if entry is None:
            return None

        entry.case.resolve(resolution)
        return entry.case

    # Reference sink specific methods

    def get_entry(self, case_id: UUID) -> SinkEntry | None:
        """Get a sink entry by case ID."""
        return self._entries.get(case_id)

    def list_entries(
        self,
        unviewed_only: bool = False,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[SinkEntry]:
        """List sink entries with filtering."""
        entries = list(self._entries.values())

        if unviewed_only:
            entries = [e for e in entries if not e.viewed]

        if tag:
            entries = [e for e in entries if tag in e.tags]

        return sorted(entries, key=lambda e: e.received_at, reverse=True)[:limit]

    def get_unviewed_count(self) -> int:
        """Get count of unviewed entries."""
        return sum(1 for e in self._entries.values() if not e.viewed)

    def get_stats(self) -> dict[str, Any]:
        """Get sink statistics."""
        total = len(self._entries)
        unviewed = self.get_unviewed_count()

        by_status: dict[str, int] = {}
        by_priority: dict[str, int] = {}

        for entry in self._entries.values():
            status = entry.case.status.value
            by_status[status] = by_status.get(status, 0) + 1

            priority = entry.case.priority.value
            by_priority[priority] = by_priority.get(priority, 0) + 1

        return {
            "total": total,
            "unviewed": unviewed,
            "by_status": by_status,
            "by_priority": by_priority,
            "max_entries": self._max_entries,
        }

    def render_list_html(self) -> str:
        """
        Render a simple HTML listing of cases.

        Provides a minimal UI for viewing escalations.
        """
        entries = self.list_entries(limit=50)

        rows = []
        for entry in entries:
            case = entry.case
            status_class = "pending" if case.status == CaseStatus.PENDING else "resolved"
            viewed_mark = "" if entry.viewed else "●"

            rows.append(f"""
            <tr class="{status_class}">
                <td>{viewed_mark}</td>
                <td>{entry.entry_id}</td>
                <td>{case.case_id}</td>
                <td>{case.priority.value}</td>
                <td>{case.status.value}</td>
                <td>{case.reason[:50]}...</td>
                <td>{case.created_at.strftime('%Y-%m-%d %H:%M')}</td>
            </tr>
            """)

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Escalation Sink</title>
            <style>
                body {{ font-family: monospace; margin: 20px; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
                th {{ background-color: #f5f5f5; }}
                .pending {{ background-color: #fff3cd; }}
                .resolved {{ background-color: #d4edda; }}
                .stats {{ margin-bottom: 20px; padding: 10px; background: #f8f9fa; }}
            </style>
        </head>
        <body>
            <h1>Escalation Reference Sink</h1>
            <div class="stats">
                <strong>Total:</strong> {len(self._entries)} |
                <strong>Unviewed:</strong> {self.get_unviewed_count()}
            </div>
            <table>
                <tr>
                    <th></th>
                    <th>#</th>
                    <th>Case ID</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Reason</th>
                    <th>Created</th>
                </tr>
                {''.join(rows)}
            </table>
        </body>
        </html>
        """
        return html

    def clear(self) -> int:
        """Clear all entries. Returns count cleared."""
        count = len(self._entries)
        self._entries.clear()
        return count
