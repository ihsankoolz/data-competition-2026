"""The request state machine (PRD §7, D-007). Plain Python: no LLM, no workflow library.

    DRAFT -> SUBMITTED -> IN_APPROVAL -> APPROVED -> PUBLISHED_INACTIVE -> ACTIVE
                              |  ^
                              |  +-- INFO_REQUESTED (requestor edits and resubmits)
                              +-- REJECTED
    DRAFT -> LINKED_TO_EXISTING (a human confirmed the duplicate; no approvals)

Every function takes the caller's session and writes inside the caller's transaction. Every
state change, decision, reminder and escalation writes an audit row; time comes from the
simulated clock.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from services.api import bankfields, clock
from services.api.audit import AuditAction, append_audit
from services.api.db import models as m
from services.api.db.session import default_db_path, session_scope
from services.api.deps import Actor
from services.api.formfields import title_of
from services.api.ids import next_id
from services.api.views import finance_approvers, role_label, tasks_for, user_names
from services.api.workflow import sla
from services.api.workflow.rules import assign, directory, load_rules, plan_tasks

log = logging.getLogger(__name__)
S = m.RequestState


# ---------------------------------------------------------------- small helpers


def audit_state(
    session: Session, req: m.Request, actor_id: str, new: m.RequestState, summary: str
) -> None:
    old = req.state
    req.state = new
    req.updated_at = clock.now()
    append_audit(
        session,
        actor=actor_id,
        action=AuditAction.state_change,
        entity_type="request",
        entity_id=req.req_id,
        request_id=req.req_id,
        payload={"from": old.value, "to": new.value, "summary": summary},
    )


def notify(
    session: Session,
    user_id: str,
    kind: str,
    req: m.Request,
    message: str,
    task: m.ApprovalTaskRow | None = None,
) -> None:
    session.add(
        m.NotificationRow(
            notification_id=next_id(session, "notification", "NTF", 5),
            user_id=user_id,
            kind=kind,
            req_id=req.req_id,
            task_id=task.task_id if task else None,
            message=message,
            created_at=clock.now(),
        )
    )


def _describe(req: m.Request, names: dict[str, str]) -> str:
    title = title_of(req.domain.value, bankfields.unseal(req.payload))
    who = names.get(req.requestor_user_id, req.requestor_user_id)
    return f"{who}'s {req.domain.value.replace('_', ' ')} request '{title}' ({req.req_id})"


def _open_task(task: m.ApprovalTaskRow) -> None:
    rules = load_rules()
    now = clock.now()
    task.status = "pending"
    task.assigned_at = now
    task.due_at = sla.due_time(now, rules)
    task.reminded_at = None
    task.escalated_at = None
    task.escalated_to_user_id = None


def _audit_task(
    session: Session, actor_id: str, req: m.Request, task: m.ApprovalTaskRow, summary: str, **extra
) -> None:
    append_audit(
        session,
        actor=actor_id,
        action=AuditAction.approval,
        entity_type="approval_task",
        entity_id=task.task_id,
        request_id=req.req_id,
        payload={
            "task_id": task.task_id,
            "role": task.role,
            "country": task.country,
            "summary": summary,
            **extra,
        },
    )


# ---------------------------------------------------------------- submit and routing


def route(session: Session, req: m.Request, actor: Actor) -> list[m.ApprovalTaskRow]:
    """Build stages and tasks from the rule table. Stage 1 opens now; later stages wait."""
    plain = bankfields.unseal(req.payload)
    plans = plan_tasks(req.domain.value, plain)
    dir_ = directory(session)
    names = user_names(session)
    taken: set[tuple[int, str, str]] = set()
    tasks: list[m.ApprovalTaskRow] = []
    for plan in plans:
        try:
            person = assign(plan, req.entity, dir_, taken)
        except ValueError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from None
        task = m.ApprovalTaskRow(
            task_id=next_id(session, "task", "TSK", 4),
            req_id=req.req_id,
            stage=plan.stage,
            stage_name=plan.stage_name,
            role=plan.role,
            country=plan.country,
            assignee_user_id=person.user_id,
            status="waiting",
        )
        if plan.stage == 1:
            _open_task(task)
        session.add(task)
        tasks.append(task)
    session.flush()
    for task in tasks:
        _audit_task(
            session,
            actor.user_id,
            req,
            task,
            f"{role_label(task)} approval assigned to {names.get(task.assignee_user_id)}",
            assignee=task.assignee_user_id,
            stage=task.stage,
        )
        if task.status == "pending":
            notify(
                session,
                task.assignee_user_id,
                "task_assigned",
                req,
                f"New request to approve: {_describe(req, names)}. Your part: {role_label(task)}. "
                f"Please decide by {task.due_at:%a %d %b %H:%M}.",
                task,
            )
    return tasks


def submit(session: Session, req: m.Request, actor: Actor) -> None:
    """DRAFT -> SUBMITTED -> IN_APPROVAL, or INFO_REQUESTED -> IN_APPROVAL (tasks reopen)."""
    names = user_names(session)
    if req.state == S.INFO_REQUESTED:
        tasks = tasks_for(session, req.req_id)
        for task in tasks:
            if task.status == "info_requested":
                _open_task(task)
                _audit_task(
                    session, actor.user_id, req, task, f"{role_label(task)} approval reopened"
                )
                notify(
                    session,
                    task.assignee_user_id,
                    "task_assigned",
                    req,
                    f"{actor.name} answered your question on {_describe(req, names)}. "
                    "It is back in your inbox.",
                    task,
                )
        audit_state(
            session,
            req,
            actor.user_id,
            S.IN_APPROVAL,
            f"{actor.name} sent the request back for approval",
        )
        return
    audit_state(session, req, actor.user_id, S.SUBMITTED, f"{actor.name} submitted the request")
    route(session, req, actor)
    audit_state(
        session, req, actor.user_id, S.IN_APPROVAL, "Approvals opened in parallel for stage 1"
    )


# ---------------------------------------------------------------- decisions


def check_decision_allowed(
    session: Session,
    req: m.Request,
    task: m.ApprovalTaskRow,
    tasks: list[m.ApprovalTaskRow],
    actor: Actor,
) -> None:
    rules = load_rules()
    if task.status == "waiting":
        raise HTTPException(
            409, "This step is not open yet. It opens when every earlier approval is done."
        )
    if task.status != "pending":
        raise HTTPException(409, f"This approval was already {task.status.replace('_', ' ')}.")
    if task.stage != 1:
        raise HTTPException(
            409, "This last step is completed by publishing the record to SAP, not by approving."
        )
    if actor.user_id not in (task.assignee_user_id, task.escalated_to_user_id):
        names = user_names(session)
        raise HTTPException(
            403,
            f"This approval is assigned to {names.get(task.assignee_user_id)}, "
            f"not to {actor.name}.",
        )
    if rules.requestor_cannot_approve and actor.user_id == req.requestor_user_id:
        raise HTTPException(
            403,
            "You can't decide on your own request. Someone else has to approve it "
            "(the person who asks and the person who approves must be different).",
        )
    stage2 = [t for t in tasks if t.stage == 2]
    if (
        rules.publisher_not_finance_approver
        and task.role == "finance"
        and any(t.assignee_user_id == actor.user_id for t in stage2)
    ):
        raise HTTPException(
            403,
            f"{actor.name} is the person who publishes this record to SAP, so {actor.name} "
            "can't also be the Finance approver (the approver and the publisher must be "
            "different people).",
        )
    if req.state not in (S.IN_APPROVAL, S.INFO_REQUESTED):
        raise HTTPException(409, f"This request is {req.state.value.replace('_', ' ').lower()}.")


def decide(
    session: Session,
    req: m.Request,
    task: m.ApprovalTaskRow,
    actor: Actor,
    action: str,
    comment: str | None,
) -> None:
    tasks = tasks_for(session, req.req_id)
    check_decision_allowed(session, req, task, tasks, actor)
    if action in ("reject", "ask_info") and not (comment or "").strip():
        raise HTTPException(
            422,
            "Please add a short comment so the requestor knows "
            + ("why it was rejected." if action == "reject" else "what is missing."),
        )
    names = user_names(session)
    now = clock.now()
    comment = (comment or "").strip() or None
    task.decided_at, task.decided_by, task.comment = now, actor.user_id, comment
    label = role_label(task)
    if action == "approve":
        task.status = "approved"
        _audit_task(
            session, actor.user_id, req, task, f"{actor.name} approved ({label})",
            action=action, comment=comment,
        )  # fmt: skip
        stage1 = [t for t in tasks if t.stage == 1]
        if all(t.status == "approved" for t in stage1):
            audit_state(
                session, req, actor.user_id, S.APPROVED,
                "Every stage-1 approval is in; the MDM publish step is open",
            )  # fmt: skip
            for t in tasks:
                if t.stage == 2 and t.status == "waiting":
                    _open_task(t)
                    _audit_task(
                        session, actor.user_id, req, t, f"{role_label(t)} step opened",
                        assignee=t.assignee_user_id,
                    )  # fmt: skip
                    notify(
                        session, t.assignee_user_id, "task_assigned", req,
                        f"Ready to publish: {_describe(req, names)} is fully approved.", t,
                    )  # fmt: skip
            notify(
                session, req.requestor_user_id, "approved", req,
                f"Your request '{title_of(req.domain.value, bankfields.unseal(req.payload))}' "
                "is fully approved and waiting to be published to SAP.",
            )  # fmt: skip
    elif action == "reject":
        task.status = "rejected"
        _audit_task(
            session, actor.user_id, req, task, f"{actor.name} rejected ({label}): {comment}",
            action=action, comment=comment,
        )  # fmt: skip
        for t in tasks:
            if t is not task and t.status in ("pending", "waiting", "info_requested"):
                t.status = "cancelled"
        audit_state(session, req, actor.user_id, S.REJECTED, f"{actor.name} rejected the request")
        notify(
            session, req.requestor_user_id, "rejected", req,
            f"{actor.name} rejected your request ({label}): {comment}", task,
        )  # fmt: skip
    else:  # ask_info
        task.status = "info_requested"
        _audit_task(
            session, actor.user_id, req, task,
            f"{actor.name} asked for more information ({label}): {comment}",
            action=action, comment=comment,
        )  # fmt: skip
        if req.state != S.INFO_REQUESTED:
            audit_state(
                session, req, actor.user_id, S.INFO_REQUESTED,
                f"{actor.name} asked the requestor for more information",
            )  # fmt: skip
        notify(
            session, req.requestor_user_id, "info_requested", req,
            f"{actor.name} needs more information ({label}): {comment}", task,
        )  # fmt: skip
    req.updated_at = now


def check_publish_allowed(req: m.Request, tasks: list[m.ApprovalTaskRow], actor: Actor) -> None:
    if not actor.has("mdm_analyst"):
        raise HTTPException(
            403, f"Only an MDM analyst can publish to SAP. {actor.name} is acting as {actor.title}."
        )
    if req.state != S.APPROVED:
        raise HTTPException(
            409,
            "This request can only be published once every approval is in "
            f"(it is {req.state.value.replace('_', ' ').lower()}).",
        )
    if load_rules().publisher_not_finance_approver and actor.user_id in finance_approvers(tasks):
        raise HTTPException(
            403,
            f"{actor.name} gave the Finance approval on this request, so {actor.name} can't "
            "also publish it (the approver and the publisher must be different people).",
        )


# ---------------------------------------------------------------- SLA sweep


def run_sla_sweep(session: Session) -> int:
    """Reminder at 50% of the SLA, escalation to the backup at 100%. Returns how many tasks
    changed. Uses the simulated clock only; call it whenever the clock moves and on reads."""
    rules = load_rules()
    now = clock.now()
    pending = session.scalars(
        select(m.ApprovalTaskRow).where(
            m.ApprovalTaskRow.status == "pending", m.ApprovalTaskRow.assigned_at.is_not(None)
        )
    ).all()
    candidates = []
    for task in pending:
        assert task.assigned_at is not None
        remind_due = task.reminded_at is None and now >= sla.reminder_time(task.assigned_at, rules)
        escalate_due = task.escalated_at is None and now >= sla.due_time(task.assigned_at, rules)
        if remind_due or escalate_due:
            candidates.append((task, remind_due, escalate_due))
    if not candidates:
        return 0
    names = user_names(session)
    dir_ = directory(session)
    changed = 0
    for task, remind_due, escalate_due in candidates:
        req = session.get(m.Request, task.req_id)
        if req is None:
            continue
        what = _describe(req, names)
        if remind_due or (escalate_due and task.reminded_at is None):
            task.reminded_at = now
            notify(
                session, task.assignee_user_id, "reminder", req,
                f"Reminder: {what} is waiting for your approval ({role_label(task)}). "
                f"It is due {task.due_at:%a %d %b %H:%M}.", task,
            )  # fmt: skip
            _audit_task(
                session, "system", req, task,
                f"Reminder sent to {names.get(task.assignee_user_id)}", action="reminder",
            )  # fmt: skip
            changed += 1
        if escalate_due:
            task.escalated_at = now
            backup = dir_.backup_of(task.assignee_user_id)
            if backup is not None:
                task.escalated_to_user_id = backup.user_id
                notify(
                    session, backup.user_id, "escalated", req,
                    f"Escalated to you: {what} passed its 2-business-day limit with "
                    f"{names.get(task.assignee_user_id)} ({role_label(task)}). "
                    "It stays in both inboxes until someone decides.", task,
                )  # fmt: skip
                summary = (
                    f"Overdue: escalated from {names.get(task.assignee_user_id)} to {backup.name}"
                )
            else:
                summary = f"Overdue: {names.get(task.assignee_user_id)} has no backup approver"
            notify(
                session, task.assignee_user_id, "escalated", req,
                f"Overdue: {what} passed its limit"
                + (f" and was escalated to {backup.name}." if backup else "."), task,
            )  # fmt: skip
            _audit_task(
                session, "system", req, task, summary, action="escalation",
                escalated_to=task.escalated_to_user_id,
            )  # fmt: skip
            changed += 1
    return changed


def run_sla_sweep_safely() -> int:
    """The sweep as a side effect of a clock move or a read: its own short transaction, and a
    failure never breaks the request that triggered it."""
    if not default_db_path().exists():
        return 0
    try:
        with session_scope() as session:
            return run_sla_sweep(session)
    except SQLAlchemyError as exc:
        log.warning("SLA sweep skipped: %s", type(exc).__name__)
        return 0
