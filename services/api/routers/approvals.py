"""Approvals inbox, decisions and notifications (M5, D-007). Owner: backend-engineer."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_, select

from services.api.db import models as m
from services.api.db.session import session_scope
from services.api.deps import CurrentUser
from services.api.schemas import (
    ApprovalDecisionIn,
    ApprovalInboxItem,
    Notification,
    RequestDetail,
)
from services.api.views import (
    detail_model,
    summary_model,
    task_model,
    tasks_for,
    user_countries,
    user_names,
)
from services.api.workflow import engine

router = APIRouter(tags=["approvals"])


@router.get(
    "/approvals/inbox", response_model=list[ApprovalInboxItem], operation_id="approvalInbox"
)
def approval_inbox(actor: CurrentUser) -> list[ApprovalInboxItem]:
    """Open tasks assigned to the acting user (including escalated ones)."""
    engine.run_sla_sweep_safely()
    with session_scope() as session:
        tasks = session.scalars(
            select(m.ApprovalTaskRow)
            .where(
                m.ApprovalTaskRow.status == "pending",
                or_(
                    m.ApprovalTaskRow.assignee_user_id == actor.user_id,
                    m.ApprovalTaskRow.escalated_to_user_id == actor.user_id,
                ),
            )
            .order_by(m.ApprovalTaskRow.due_at, m.ApprovalTaskRow.task_id)
        ).all()
        names = user_names(session)
        countries = user_countries(session)
        out: list[ApprovalInboxItem] = []
        for task in tasks:
            req = session.get(m.Request, task.req_id)
            if req is None:
                continue
            out.append(
                ApprovalInboxItem(
                    task=task_model(task, names, countries),
                    request=summary_model(req, tasks_for(session, req.req_id), names),
                )
            )
        return out


@router.post(
    "/approvals/{task_id}/decision", response_model=RequestDetail, operation_id="decideApproval"
)
def decide_approval(task_id: str, body: ApprovalDecisionIn, actor: CurrentUser) -> RequestDetail:
    """Approve / reject / ask for info. Maker-checker enforced. A human always decides."""
    with session_scope(write=True) as session:
        task = session.get(m.ApprovalTaskRow, task_id)
        if task is None:
            raise HTTPException(404, f"There is no approval task {task_id}.")
        req = session.get(m.Request, task.req_id)
        assert req is not None
        engine.decide(session, req, task, actor, body.action, body.comment)
        session.flush()
        return detail_model(session, req, actor)


@router.get("/notifications", response_model=list[Notification], operation_id="listNotifications")
def list_notifications(actor: CurrentUser) -> list[Notification]:
    """Notifications for the acting user, newest first (reminders, escalations, ...)."""
    engine.run_sla_sweep_safely()
    with session_scope() as session:
        rows = session.scalars(
            select(m.NotificationRow)
            .where(m.NotificationRow.user_id == actor.user_id)
            .order_by(m.NotificationRow.created_at.desc(), m.NotificationRow.notification_id.desc())
            .limit(200)
        ).all()
        return [
            Notification(
                notification_id=r.notification_id,
                user_id=r.user_id,
                kind=r.kind,  # type: ignore[arg-type]
                req_id=r.req_id,
                task_id=r.task_id,
                message=r.message,
                created_at=r.created_at,
            )
            for r in rows
        ]
