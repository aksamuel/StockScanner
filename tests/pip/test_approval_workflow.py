from __future__ import annotations

from stockscanner.pip.approval_workflow import ApprovalStatus, ApprovalWorkflow


def test_approval_workflow_tracks_recommendation_status():
    workflow = ApprovalWorkflow()

    submitted = workflow.submit("rec-123")
    approved = workflow.approve("rec-123", "analyst-a", "Score and replacement candidates justify action.")
    escalated = workflow.escalate("rec-123", "lead-a", "Escalated for final portfolio review.")

    assert submitted.status == ApprovalStatus.PENDING
    assert approved.status == ApprovalStatus.APPROVED
    assert escalated.status == ApprovalStatus.ESCALATED
    assert workflow.latest("rec-123").status == ApprovalStatus.ESCALATED
