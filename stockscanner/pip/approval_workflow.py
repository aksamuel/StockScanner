from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class ApprovalStatus(str, Enum):
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    PENDING = "under_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUBMITTED = "submitted"
    CANCELLED = "cancelled"
    ESCALATED = "escalated"


@dataclass
class ApprovalDecision:
    recommendation_id: str | None
    status: ApprovalStatus
    actor: str | None
    reason: str | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] | None = None


def _safe_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"(?i)\b(token|password|secret|api[_-]?key)\s*[:=]\s*\S+", r"\1=[redacted]", str(value))
    return re.sub(r"(?<!\d)\d{6,}(?!\d)", lambda match: f"***{match.group()[-4:]}", text)


class InvalidApprovalTransition(ValueError):
    pass


@dataclass
class ApprovalWorkflow:
    """Validates human-review transitions and records a redacted audit event."""

    audit_sink: Callable[[dict[str, Any]], None] | None = None
    decisions: dict[str, ApprovalDecision] = field(default_factory=dict)
    audit_logs: list[dict[str, Any]] = field(default_factory=list)

    allowed_transitions = {
        ApprovalStatus.PROPOSED: {ApprovalStatus.UNDER_REVIEW, ApprovalStatus.CANCELLED, ApprovalStatus.EXPIRED},
        ApprovalStatus.UNDER_REVIEW: {
            ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.ESCALATED,
            ApprovalStatus.CANCELLED, ApprovalStatus.EXPIRED,
        },
        ApprovalStatus.APPROVED: {ApprovalStatus.SUBMITTED, ApprovalStatus.ESCALATED, ApprovalStatus.CANCELLED},
        ApprovalStatus.ESCALATED: {
            ApprovalStatus.UNDER_REVIEW, ApprovalStatus.APPROVED, ApprovalStatus.REJECTED,
            ApprovalStatus.CANCELLED, ApprovalStatus.EXPIRED,
        },
        ApprovalStatus.REJECTED: set(),
        ApprovalStatus.EXPIRED: set(),
        ApprovalStatus.SUBMITTED: set(),
        ApprovalStatus.CANCELLED: set(),
    }

    def _transition(
        self,
        recommendation_id: str,
        status: ApprovalStatus,
        actor: str | None,
        reason: str | None,
    ) -> ApprovalDecision:
        previous = self.decisions.get(recommendation_id)
        if previous is None or status not in self.allowed_transitions[previous.status]:
            previous_status = previous.status.value if previous else "not_created"
            raise InvalidApprovalTransition(
                f"Cannot transition recommendation from {previous_status} to {status.value}."
            )
        if status is ApprovalStatus.APPROVED and (not actor or not reason or not actor.strip() or not reason.strip()):
            raise ValueError("Explicit human approval requires an actor and a reason.")

        timestamp = datetime.now(timezone.utc)
        safe_actor = _safe_text(actor)
        safe_reason = _safe_text(reason)
        decision = ApprovalDecision(
            recommendation_id=recommendation_id,
            status=status,
            actor=safe_actor,
            reason=safe_reason,
            created_at=timestamp,
            metadata={"approval": status.value},
        )
        event = {
            "entity_type": "sell_recommendation",
            "entity_id": recommendation_id,
            "event_type": "approval_transition",
            "from_status": previous.status.value,
            "to_status": status.value,
            "actor": safe_actor,
            "reason": safe_reason,
            "created_at": timestamp.isoformat(),
        }
        if self.audit_sink is not None:
            self.audit_sink(dict(event))
        self.audit_logs.append(event)
        self.decisions[recommendation_id] = decision
        return decision

    def propose(self, recommendation_id: str) -> ApprovalDecision:
        if not recommendation_id or recommendation_id in self.decisions:
            raise InvalidApprovalTransition("A new recommendation ID is required.")
        timestamp = datetime.now(timezone.utc)
        decision = ApprovalDecision(
            recommendation_id, ApprovalStatus.PROPOSED, None, "Proposed for human review.",
            timestamp, {"approval": ApprovalStatus.PROPOSED.value},
        )
        event = {
            "entity_type": "sell_recommendation",
            "entity_id": recommendation_id,
            "event_type": "approval_transition",
            "from_status": None,
            "to_status": ApprovalStatus.PROPOSED.value,
            "actor": None,
            "reason": decision.reason,
            "created_at": timestamp.isoformat(),
        }
        if self.audit_sink is not None:
            self.audit_sink(dict(event))
        self.audit_logs.append(event)
        self.decisions[recommendation_id] = decision
        return decision

    def begin_review(self, recommendation_id: str, actor: str, reason: str = "Review started.") -> ApprovalDecision:
        return self._transition(recommendation_id, ApprovalStatus.UNDER_REVIEW, actor, reason)

    def submit(self, recommendation_id: str) -> ApprovalDecision:
        """Legacy convenience: create and place the recommendation under review."""
        if recommendation_id in self.decisions:
            return self.begin_review(recommendation_id, "system", "Submitted for review.")
        self.propose(recommendation_id)
        return self.begin_review(recommendation_id, "system", "Submitted for review.")

    def approve(self, recommendation_id: str, actor: str, reason: str) -> ApprovalDecision:
        return self._transition(recommendation_id, ApprovalStatus.APPROVED, actor, reason)

    def reject(self, recommendation_id: str, actor: str, reason: str) -> ApprovalDecision:
        return self._transition(recommendation_id, ApprovalStatus.REJECTED, actor, reason)

    def escalate(self, recommendation_id: str, actor: str, reason: str) -> ApprovalDecision:
        return self._transition(recommendation_id, ApprovalStatus.ESCALATED, actor, reason)

    def expire(self, recommendation_id: str, actor: str = "system", reason: str = "Review window expired.") -> ApprovalDecision:
        return self._transition(recommendation_id, ApprovalStatus.EXPIRED, actor, reason)

    def cancel(self, recommendation_id: str, actor: str, reason: str) -> ApprovalDecision:
        return self._transition(recommendation_id, ApprovalStatus.CANCELLED, actor, reason)

    def mark_submitted(self, recommendation_id: str, actor: str, reason: str) -> ApprovalDecision:
        """Record an externally completed submission; this does not transmit an order."""
        return self._transition(recommendation_id, ApprovalStatus.SUBMITTED, actor, reason)

    def latest(self, recommendation_id: str) -> ApprovalDecision | None:
        return self.decisions.get(recommendation_id)
