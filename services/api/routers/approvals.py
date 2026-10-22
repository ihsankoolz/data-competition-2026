"""Approvals inbox, decisions and notifications (M5, D-007). Owner: backend-engineer."""

from fastapi import APIRouter

from services.api.routers._stub import not_built
from services.api.schemas import (
    ApprovalDecisionIn,
    ApprovalInboxItem,
    Notification,
    RequestDetail,
)

router = APIRouter(tags=["approvals"])


@router.get(
    "/approvals/inbox", response_model=list[ApprovalInboxItem], operation_id="approvalInbox"
)
def approval_inbox() -> list[ApprovalInboxItem]:
    """Open tasks assigned to the acting user (including escalated ones)."""
    raise not_built("approval inbox")


@router.post(
    "/approvals/{task_id}/decision", response_model=RequestDetail, operation_id="decideApproval"
)
def decide_approval(task_id: str, body: ApprovalDecisionIn) -> RequestDetail:
    """Approve / reject / ask for info. Maker-checker enforced. A human always decides."""
    raise not_built("approval decision")


@router.get("/notifications", response_model=list[Notification], operation_id="listNotifications")
def list_notifications() -> list[Notification]:
    """Notifications for the acting user, newest first (reminders, escalations, ...)."""
    raise not_built("notifications")
