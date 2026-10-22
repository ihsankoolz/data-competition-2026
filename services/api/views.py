"""Database rows -> API models (RequestSummary / RequestDetail / ApprovalTask / Stage).

Everything the acting user sees is computed here: `pending_with`, `sla_state`, `allowed_actions`,
and the bank masking (domain rule 5).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api import bankfields, clock, item_suggestions, sap_readback
from services.api.db import models as m
from services.api.deps import Actor
from services.api.formfields import missing_form_fields, title_of
from services.api.schemas import (
    ApprovalTask,
    DedupDecisionOut,
    FieldIssue,
    InfoRequestView,
    RequestDetail,
    RequestSummary,
    Stage,
)
from services.api.validation import validate_fields

ROLE_LABEL = {
    "bu_head": "BU Head",
    "finance": "Finance",
    "business_support": "Business Support",
    "quality_regulatory": "Quality / Regulatory",
    "mdm_analyst": "MDM publish",
}
OPEN_STATES = (m.RequestState.IN_APPROVAL, m.RequestState.INFO_REQUESTED)


def role_label(task: m.ApprovalTaskRow) -> str:
    base = ROLE_LABEL.get(task.role, task.role)
    return f"{base} ({task.country})" if task.country else base


def user_names(session: Session) -> dict[str, str]:
    return dict(session.execute(select(m.User.user_id, m.User.name)).all())


def tasks_for(session: Session, req_id: str) -> list[m.ApprovalTaskRow]:
    return list(
        session.scalars(
            select(m.ApprovalTaskRow)
            .where(m.ApprovalTaskRow.req_id == req_id)
            .order_by(m.ApprovalTaskRow.stage, m.ApprovalTaskRow.task_id)
        )
    )


def sla_state(task: m.ApprovalTaskRow) -> str:
    if task.status in ("approved", "rejected", "cancelled"):
        return "done"
    if task.escalated_at is not None:
        return "overdue"
    if task.reminded_at is not None:
        return "reminded"
    return "on_track"


def task_model(task: m.ApprovalTaskRow, names: dict[str, str]) -> ApprovalTask:
    return ApprovalTask(
        task_id=task.task_id,
        req_id=task.req_id,
        stage=task.stage,
        role=task.role,  # type: ignore[arg-type]
        country=task.country,  # type: ignore[arg-type]
        assignee_user_id=task.assignee_user_id,
        assignee_name=names.get(task.assignee_user_id, task.assignee_user_id),
        status=task.status,  # type: ignore[arg-type]
        assigned_at=task.assigned_at,
        due_at=task.due_at,
        reminded_at=task.reminded_at,
        escalated_at=task.escalated_at,
        escalated_to_user_id=task.escalated_to_user_id,
        decided_at=task.decided_at,
        decided_by=task.decided_by,
        comment=task.comment,
        sla_state=sla_state(task),  # type: ignore[arg-type]
    )


def pending_with(
    req: m.Request, tasks: list[m.ApprovalTaskRow], names: dict[str, str]
) -> list[str]:
    if req.state == m.RequestState.INFO_REQUESTED:
        out = [names.get(req.requestor_user_id, req.requestor_user_id)]
    else:
        out = []
    if req.state in OPEN_STATES or req.state == m.RequestState.APPROVED:
        for t in tasks:
            if t.status != "pending":
                continue
            for uid in (t.assignee_user_id, t.escalated_to_user_id):
                if uid and names.get(uid, uid) not in out:
                    out.append(names.get(uid, uid))
    return out


def summary_model(
    req: m.Request, tasks: list[m.ApprovalTaskRow], names: dict[str, str]
) -> RequestSummary:
    return RequestSummary(
        req_id=req.req_id,
        domain=req.domain.value,  # type: ignore[arg-type]
        state=req.state.value,  # type: ignore[arg-type]
        title=title_of(req.domain.value, bankfields.unseal(req.payload)),
        entity=req.entity,  # type: ignore[arg-type]
        country=req.country,  # type: ignore[arg-type]
        requestor_user_id=req.requestor_user_id,
        requestor_name=names.get(req.requestor_user_id, req.requestor_user_id),
        created_at=req.created_at,
        updated_at=req.updated_at,
        pending_with=pending_with(req, tasks, names),
    )


def finance_approvers(tasks: list[m.ApprovalTaskRow]) -> set[str]:
    """People who gave (or are giving) the Finance approval on this request."""
    return {t.decided_by for t in tasks if t.role == "finance" and t.decided_by}


def my_open_tasks(actor: Actor, tasks: list[m.ApprovalTaskRow]) -> list[m.ApprovalTaskRow]:
    return [
        t
        for t in tasks
        if t.status == "pending"
        and t.stage == 1
        and actor.user_id in (t.assignee_user_id, t.escalated_to_user_id)
    ]


def allowed_actions(
    actor: Actor, req: m.Request, tasks: list[m.ApprovalTaskRow], has_decision: bool
) -> list[str]:
    out: list[str] = []
    owner = actor.user_id == req.requestor_user_id and actor.has("requestor")
    if owner and req.state in (m.RequestState.DRAFT, m.RequestState.INFO_REQUESTED):
        out += ["edit", "submit"]
        if req.domain.value in ("customer", "vendor"):
            out.append("decide_duplicate")
    if req.state in OPEN_STATES and actor.user_id != req.requestor_user_id:
        stage2 = [t for t in tasks if t.stage == 2]
        is_publisher = any(t.assignee_user_id == actor.user_id for t in stage2)
        for t in my_open_tasks(actor, tasks):
            if t.role == "finance" and is_publisher:
                continue
            out += ["approve", "reject", "ask_info"]
            break
    if req.state == m.RequestState.APPROVED and actor.has("mdm_analyst"):
        if actor.user_id not in finance_approvers(tasks):
            out.append("publish")
    return out


def decision_model(
    row: m.DedupDecisionRow | None, names: dict[str, str]
) -> DedupDecisionOut | None:
    if row is None:
        return None
    return DedupDecisionOut(
        action=row.action,  # type: ignore[arg-type]
        card_code=row.card_code,
        reason=row.reason,
        decided_by=names.get(row.decided_by, row.decided_by),
        decided_at=row.decided_at,
        verdict_at_decision=row.verdict_at_decision,  # type: ignore[arg-type]
    )


def latest_decision(session: Session, req_id: str) -> m.DedupDecisionRow | None:
    return session.scalars(
        select(m.DedupDecisionRow)
        .where(m.DedupDecisionRow.req_id == req_id)
        .order_by(m.DedupDecisionRow.id.desc())
        .limit(1)
    ).first()


def stage_models(tasks: list[m.ApprovalTaskRow], names: dict[str, str]) -> list[Stage]:
    stages: dict[int, list[m.ApprovalTaskRow]] = {}
    for t in tasks:
        stages.setdefault(t.stage, []).append(t)
    out: list[Stage] = []
    for number in sorted(stages):
        group = stages[number]
        statuses = {t.status for t in group}
        if "rejected" in statuses:
            status = "rejected"
        elif statuses <= {"approved"}:
            status = "done"
        elif statuses <= {"waiting", "cancelled"}:
            status = "waiting"
        else:
            status = "open"
        out.append(
            Stage(
                number=number,
                name=group[0].stage_name,
                status=status,  # type: ignore[arg-type]
                tasks=[task_model(t, names) for t in group],
            )
        )
    return out


def current_issues(req: m.Request, plain: dict[str, Any]) -> list[FieldIssue]:
    """Validation problems shown while the requestor can still edit (empty afterwards)."""
    if req.state not in (m.RequestState.DRAFT, m.RequestState.INFO_REQUESTED):
        return []
    return validate_fields(req.domain.value, req.country, plain, clock.now().date())


def info_request_view(
    req: m.Request, tasks: list[m.ApprovalTaskRow], names: dict[str, str]
) -> InfoRequestView | None:
    """While INFO_REQUESTED: the most recent question and who asked it."""
    if req.state != m.RequestState.INFO_REQUESTED:
        return None
    asked = [t for t in tasks if t.status == "info_requested" and t.decided_at is not None]
    if not asked:
        return None
    task = max(asked, key=lambda t: (t.decided_at, t.task_id))
    who = task.decided_by or task.assignee_user_id
    return InfoRequestView(
        task_id=task.task_id,
        asked_by_user_id=who,
        asked_by_name=names.get(who, who),
        role=task.role,  # type: ignore[arg-type]
        question=task.comment or "",
        asked_at=task.decided_at,  # type: ignore[arg-type]
    )


def linked_card_name(session: Session, req: m.Request) -> str | None:
    if not req.linked_card_code:
        return None
    return session.scalar(
        select(m.BusinessPartner.CardName).where(m.BusinessPartner.CardCode == req.linked_card_code)
    )


def detail_model(session: Session, req: m.Request, actor: Actor) -> RequestDetail:
    clock.now()  # (SLA states are stored; the sweep keeps them current)
    names = user_names(session)
    tasks = tasks_for(session, req.req_id)
    plain: dict[str, Any] = bankfields.unseal(req.payload)
    decision = latest_decision(session, req.req_id)
    base = summary_model(req, tasks, names)
    return RequestDetail(
        **base.model_dump(),
        fields=bankfields.view(plain, is_finance=actor.is_finance),
        missing_fields=missing_form_fields(req.domain.value, req.country, plain),
        source_email_id=req.source_email_id,
        prefill_quotes={k: str(v) for k, v in (req.prefill_quotes or {}).items()},
        prefill_suggested=item_suggestions.shown_reasons(session, req, plain),
        dedup_decision=decision_model(decision, names),
        linked_card_code=req.linked_card_code,
        linked_card_name=linked_card_name(session, req),
        info_request=info_request_view(req, tasks, names),
        stages=stage_models(tasks, names),
        allowed_actions=allowed_actions(actor, req, tasks, decision is not None),  # type: ignore[arg-type]
        issues=current_issues(req, plain),
        sap_publish=sap_readback.view(session, req, names, is_finance=actor.is_finance),
    )
