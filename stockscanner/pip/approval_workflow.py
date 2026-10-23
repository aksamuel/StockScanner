from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class ApprovalStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"


@dataclass
class ApprovalDecision:
    recommendation_id: Optional[str]
    status: ApprovalStatus
    actor: Optional[str]
    reason: Optional[str] = None
    created_at: Optional[datetime] = None
    metadata: Dict[str, Any] | None = None


@dataclass
class ApprovalWorkflow:
    """Simple workflow for review and approval of sell recommendations."""

    decisions: Dict[str, ApprovalDecision] = field(default_factory=dict)

    def submit(self, recommendation_id: str) -> ApprovalDecision:
        decision = ApprovalDecision(
            recommendation_id=recommendation_id,
            status=ApprovalStatus.PENDING,
            actor=None,
            reason="Submitted for review.",
            created_at=datetime.utcnow(),
            metadata={"approval": "pending"},
        )
        self.decisions[recommendation_id] = decision
        return decision

    def approve(self, recommendation_id: str, actor: str, reason: str) -> ApprovalDecision:
        decision = ApprovalDecision(
            recommendation_id=recommendation_id,
            status=ApprovalStatus.APPROVED,
            actor=actor,
            reason=reason,
            created_at=datetime.utcnow(),
            metadata={"approval": "approved"},
        )
        self.decisions[recommendation_id] = decision
        return decision

    def reject(self, recommendation_id: str, actor: str, reason: str) -> ApprovalDecision:
        decision = ApprovalDecision(
            recommendation_id=recommendation_id,
            status=ApprovalStatus.REJECTED,
            actor=actor,
            reason=reason,
            created_at=datetime.utcnow(),
            metadata={"approval": "rejected"},
        )
        self.decisions[recommendation_id] = decision
        return decision

    def escalate(self, recommendation_id: str, actor: str, reason: str) -> ApprovalDecision:
        decision = ApprovalDecision(
            recommendation_id=recommendation_id,
            status=ApprovalStatus.ESCALATED,
            actor=actor,
            reason=reason,
            created_at=datetime.utcnow(),
            metadata={"approval": "escalated"},
        )
        self.decisions[recommendation_id] = decision
        return decision

    def latest(self, recommendation_id: str) -> Optional[ApprovalDecision]:
        return self.decisions.get(recommendation_id)
