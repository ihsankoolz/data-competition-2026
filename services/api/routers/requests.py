"""MDM requests (M3, M5). Owner: backend-engineer."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ds.forms import FORM_DOMAINS, load_form_schema
from ds.interpreter.api import interpret_email
from services.api import audit_view, bankfields, clock, dedup_service
from services.api.audit import AuditAction, append_audit, audit_field_edit
from services.api.db import models as m
from services.api.db.session import session_scope
from services.api.deps import CurrentUser
from services.api.formfields import (
    form_properties,
    missing_form_fields,
    prefill_from_interpretation,
)
from services.api.ids import next_id
from services.api.schemas import (
    AuditEntry,
    DedupDecisionIn,
    RequestCreate,
    RequestDetail,
    RequestStateName,
    RequestSummary,
    RequestUpdate,
)
from services.api.views import (
    detail_model,
    summary_model,
    tasks_for,
    user_names,
)
from services.api.workflow import engine, publishing

router = APIRouter(tags=["requests"])
EDITABLE = (m.RequestState.DRAFT, m.RequestState.INFO_REQUESTED)
MIN_REASON_CHARS = 10
# Changing any of these makes an earlier "not a duplicate" decision meaningless.
IDENTITY_FIELDS = ("CardName", "CardForeignName", "FederalTaxID", "Country")


# ---------------------------------------------------------------- helpers


def _get(session: Session, req_id: str) -> m.Request:
    req = session.get(m.Request, req_id)
    if req is None:
        raise HTTPException(404, f"There is no request {req_id}.")
    return req


def _require_owner(req: m.Request, actor) -> None:
    if not actor.has("requestor"):
        raise HTTPException(
            403, f"Only a requestor can do this. {actor.name} is acting as {actor.title}."
        )
    if actor.user_id != req.requestor_user_id:
        raise HTTPException(403, "Only the person who made this request can change or submit it.")


def _check_keys(domain: str, fields: dict[str, Any]) -> None:
    allowed = form_properties(domain)
    unknown = sorted(k for k in fields if k not in allowed)
    if unknown:
        raise HTTPException(
            422,
            f"These are not fields on the {domain.replace('_', ' ')} form: {', '.join(unknown)}.",
        )


def _field_label(domain: str, name: str) -> str:
    if name.startswith("registrations["):
        return f"Registration number for {name[len('registrations[') : -1]}"
    if name == bankfields.BANK_KEY:
        return "Bank account"
    if domain in FORM_DOMAINS:
        title = load_form_schema(domain)["properties"].get(name, {}).get("title")  # type: ignore[arg-type]
        if title:
            return f"{title} ({name})"
    return name


def _diffs(key: str, old: Any, new: Any):
    if key == bankfields.BANK_KEY and isinstance(new, list):
        old_rows = old if isinstance(old, list) else []
        for i in range(max(len(old_rows), len(new))):
            o = old_rows[i] if i < len(old_rows) and isinstance(old_rows[i], dict) else {}
            n = new[i] if i < len(new) and isinstance(new[i], dict) else {}
            for leaf in sorted(set(o) | set(n)):
                if o.get(leaf) != n.get(leaf):
                    yield f"{key}[{i}].{leaf}", o.get(leaf), n.get(leaf)
    elif old != new:
        yield key, old, new


def _sweep() -> None:
    engine.run_sla_sweep_safely()


def _detail(session: Session, req_id: str, actor) -> RequestDetail:
    return detail_model(session, _get(session, req_id), actor)


# ---------------------------------------------------------------- list / create / read / update


@router.get("/requests", response_model=list[RequestSummary], operation_id="listRequests")
def list_requests(
    actor: CurrentUser,
    scope: Literal["mine", "all"] = "mine",
    state: RequestStateName | None = None,
) -> list[RequestSummary]:
    """`mine` = requests I made plus requests with a task for me. `all` = everything."""
    _sweep()
    with session_scope() as session:
        q = select(m.Request).order_by(m.Request.updated_at.desc(), m.Request.req_id.desc())
        if state:
            q = q.where(m.Request.state == m.RequestState(state))
        if scope == "mine":
            mine = select(m.ApprovalTaskRow.req_id).where(
                or_(
                    m.ApprovalTaskRow.assignee_user_id == actor.user_id,
                    m.ApprovalTaskRow.escalated_to_user_id == actor.user_id,
                )
            )
            q = q.where(
                or_(m.Request.requestor_user_id == actor.user_id, m.Request.req_id.in_(mine))
            )
        reqs = list(session.scalars(q))
        names = user_names(session)
        by_req: dict[str, list[m.ApprovalTaskRow]] = {}
        if reqs:
            for t in session.scalars(
                select(m.ApprovalTaskRow).where(
                    m.ApprovalTaskRow.req_id.in_([r.req_id for r in reqs])
                )
            ):
                by_req.setdefault(t.req_id, []).append(t)
        return [summary_model(r, by_req.get(r.req_id, []), names) for r in reqs]


def _new_request(
    session: Session,
    actor,
    domain: str,
    entity: str,
    country: str,
    fields: dict[str, Any],
    source_email_id: str | None = None,
    quotes: dict[str, str] | None = None,
) -> m.Request:
    if not actor.has("requestor"):
        raise HTTPException(
            403, f"Only a requestor can start a request. {actor.name} is acting as {actor.title}."
        )
    _check_keys(domain, fields)
    fields = dict(fields)
    if domain in ("customer", "vendor"):
        fields.setdefault("Country", country)
    now = clock.now()
    req = m.Request(
        req_id=next_id(session, "request", "REQ", 4),
        domain=m.RequestDomain(domain),
        state=m.RequestState.DRAFT,
        requestor_user_id=actor.user_id,
        entity=entity,
        country=country,
        payload=bankfields.seal(fields),
        created_at=now,
        updated_at=now,
        source_email_id=source_email_id,
        prefill_quotes=quotes or {},
    )
    session.add(req)
    session.flush()
    append_audit(
        session,
        actor=actor.user_id,
        action=AuditAction.state_change,
        entity_type="request",
        entity_id=req.req_id,
        request_id=req.req_id,
        payload={
            "from": None,
            "to": "DRAFT",
            "summary": f"{actor.name} started "
            f"{'an' if domain == 'item' else 'a'} {domain.replace('_', ' ')} request"
            + (f" from email {source_email_id}" if source_email_id else ""),
            "fields": sorted(fields),
        },
    )
    return req


@router.post(
    "/requests", response_model=RequestDetail, status_code=201, operation_id="createRequest"
)
def create_request(body: RequestCreate, actor: CurrentUser) -> RequestDetail:
    """Creates a DRAFT for the acting user."""
    with session_scope(write=True) as session:
        req = _new_request(
            session, actor, body.domain, body.entity, body.country, body.fields,
            body.source_email_id,
        )  # fmt: skip
        return detail_model(session, req, actor)


@router.post(
    "/requests/from-email/{email_id}",
    response_model=RequestDetail,
    status_code=201,
    operation_id="createRequestFromEmail",
)
def create_request_from_email(email_id: str, actor: CurrentUser) -> RequestDetail:
    """Interprets the email and creates a pre-filled DRAFT with a source quote per field.
    Email text never sets approvers, bank details or credit terms (rule 7)."""
    if not actor.has("requestor"):
        raise HTTPException(
            403, f"Only a requestor can start a request. {actor.name} is acting as {actor.title}."
        )
    with session_scope() as session:
        email = session.get(m.Email, email_id)
        if email is None:
            raise HTTPException(404, f"There is no email {email_id}.")
        subject, body, sender = email.subject, email.body, email.from_address
    interp = interpret_email(email_id, subject, body, sender)
    if interp.category != "mdm_request" or interp.domain is None:
        raise HTTPException(
            422,
            "This email is not a request for a new customer, vendor, item or cost center, "
            "so there is nothing to pre-fill.",
        )
    fields, quotes = prefill_from_interpretation(interp.domain, interp)
    country = str(fields.get("Country") or "")
    if country not in ("SG", "MY", "ID", "VN", "TH"):
        country = actor.country if actor.country in ("SG", "MY", "ID", "VN", "TH") else "SG"
    entity = actor.entity if actor.entity in ("SPD", "QTS", "QTG") else "SPD"
    with session_scope(write=True) as session:
        req = _new_request(
            session, actor, interp.domain, entity, country, fields, email_id, quotes
        )  # fmt: skip
        return detail_model(session, req, actor)


@router.get("/requests/{req_id}", response_model=RequestDetail, operation_id="getRequest")
def get_request(req_id: str, actor: CurrentUser) -> RequestDetail:
    _sweep()
    with session_scope() as session:
        return _detail(session, req_id, actor)


@router.patch("/requests/{req_id}", response_model=RequestDetail, operation_id="updateRequest")
def update_request(req_id: str, body: RequestUpdate, actor: CurrentUser) -> RequestDetail:
    with session_scope(write=True) as session:
        req = _get(session, req_id)
        _require_owner(req, actor)
        if req.state not in EDITABLE:
            raise HTTPException(
                409,
                "This request can't be edited any more "
                f"(it is {req.state.value.replace('_', ' ').lower()}).",
            )
        domain = req.domain.value
        _check_keys(domain, body.fields)
        old = bankfields.unseal(req.payload)
        incoming = bankfields.merge_masked(old, body.fields)
        new = dict(old)
        for key, value in incoming.items():
            if value is None:
                new.pop(key, None)
            else:
                new[key] = value
        for key in incoming:
            for path, o, n in _diffs(key, old.get(key), new.get(key)):
                audit_field_edit(
                    session, actor=actor.user_id, entity_type="request", entity_id=req_id,
                    field=path, old=o, new=n, request_id=req_id,
                )  # fmt: skip
        country_changed = bool(body.country and body.country != req.country)
        if body.country and country_changed:
            audit_field_edit(
                session, actor=actor.user_id, entity_type="request", entity_id=req_id,
                field="country", old=req.country, new=body.country, request_id=req_id,
            )  # fmt: skip
            req.country = body.country
        changed_identity = country_changed or any(old.get(k) != new.get(k) for k in IDENTITY_FIELDS)
        if changed_identity:
            stale = session.scalars(
                select(m.DedupDecisionRow).where(m.DedupDecisionRow.req_id == req_id)
            ).all()
            if stale:
                for row in stale:
                    session.delete(row)
                append_audit(
                    session, actor=actor.user_id, action=AuditAction.dedup_decision,
                    entity_type="request", entity_id=req_id, request_id=req_id,
                    payload={
                        "action": "cleared",
                        "summary": "The earlier 'not a duplicate' decision was cleared because "
                        "the name, tax ID or country changed; the check must be decided again",
                    },
                )  # fmt: skip
        req.payload = bankfields.seal(new)
        req.updated_at = clock.now()
        session.flush()
        return detail_model(session, req, actor)


# ---------------------------------------------------------------- duplicate decision and submit


@router.post(
    "/requests/{req_id}/dedup-decision",
    response_model=RequestDetail,
    operation_id="decideDuplicate",
)
def decide_duplicate(req_id: str, body: DedupDecisionIn, actor: CurrentUser) -> RequestDetail:
    """Link to the existing record (-> LINKED_TO_EXISTING, no approvals) or confirm it is not
    a duplicate with a reason. Always a human decision; always audited."""
    with session_scope(write=True) as session:
        req = _get(session, req_id)
        _require_owner(req, actor)
        domain = req.domain.value
        if domain not in ("customer", "vendor"):
            raise HTTPException(409, "Duplicate checks only apply to customers and vendors.")
        if req.state != m.RequestState.DRAFT:
            raise HTTPException(
                409, "A duplicate decision can only be made while the request is a draft."
            )
        link: m.BusinessPartner | None = None
        if body.action == "link_to_existing":
            if not body.card_code:
                raise HTTPException(422, "Choose which existing record to link to (card_code).")
            link = session.get(m.BusinessPartner, body.card_code)
            if link is None:
                raise HTTPException(422, f"There is no record {body.card_code} in the master data.")
            wanted = "cCustomer" if domain == "customer" else "cSupplier"
            if link.CardType != wanted:
                raise HTTPException(
                    422,
                    f"{link.CardCode} is a {'vendor' if wanted == 'cCustomer' else 'customer'} "
                    f"record. A {domain} request can only link to a {domain} record "
                    "(a company that is both needs two separate records).",
                )
        elif len((body.reason or "").strip()) < MIN_REASON_CHARS:
            raise HTTPException(
                422,
                "Please say why this is a different company, in at least "
                f"{MIN_REASON_CHARS} characters.",
            )
        plain = bankfields.unseal(req.payload)
        check = dedup_service.run_check(domain, req.entity, plain)  # rules only, no AI
        verdict = check.verdict
        now = clock.now()
        session.add(
            m.DedupDecisionRow(
                req_id=req_id, action=body.action, card_code=body.card_code,
                reason=(body.reason or "").strip() or None, decided_by=actor.user_id,
                decided_at=now, verdict_at_decision=verdict,
                covered_codes=[c.CardCode for c in check.candidates],
            )
        )  # fmt: skip
        if link is not None:
            summary = (
                f"{actor.name} linked the request to existing record "
                f"{link.CardCode} ({link.CardName})"
            )
        else:
            reason = (body.reason or "").strip()
            summary = f"{actor.name} confirmed it is not a duplicate: {reason}"
        append_audit(
            session, actor=actor.user_id, action=AuditAction.dedup_decision,
            entity_type="request", entity_id=req_id, request_id=req_id,
            payload={
                "action": body.action, "card_code": body.card_code, "reason": body.reason,
                "verdict_at_decision": verdict, "summary": summary,
            },
        )  # fmt: skip
        if link is not None:
            req.linked_card_code = link.CardCode
            engine.audit_state(
                session, req, actor.user_id, m.RequestState.LINKED_TO_EXISTING,
                f"Linked to {link.CardCode}; no new record and no approvals needed",
            )  # fmt: skip
        req.updated_at = now
        session.flush()
        return detail_model(session, req, actor)


@router.post(
    "/requests/{req_id}/submit", response_model=RequestDetail, operation_id="submitRequest"
)
def submit_request(req_id: str, actor: CurrentUser) -> RequestDetail:
    """Re-runs the duplicate check. 409 if a Likely duplicate has no human decision; 422 if
    required fields are missing. Otherwise routes approvals (config/routing_rules.yaml)."""
    with session_scope(write=True) as session:
        req = _get(session, req_id)
        _require_owner(req, actor)
        if req.state not in EDITABLE:
            raise HTTPException(
                409,
                "This request was already submitted "
                f"(it is {req.state.value.replace('_', ' ').lower()}).",
            )
        domain = req.domain.value
        plain = bankfields.unseal(req.payload)
        missing = missing_form_fields(domain, req.country, plain)
        if missing:
            raise HTTPException(
                422,
                "Some required details are still missing: "
                + ", ".join(_field_label(domain, f) for f in missing)
                + ". Fill them in and submit again.",
            )
        if domain in ("customer", "vendor"):
            result = dedup_service.run_check(domain, req.entity, plain)
            decision = session.scalars(
                select(m.DedupDecisionRow)
                .where(m.DedupDecisionRow.req_id == req_id)
                .order_by(m.DedupDecisionRow.id.desc())
                .limit(1)
            ).first()
            top = result.candidates[0] if result.candidates else None
            covered = bool(
                decision
                and decision.action == "not_duplicate"
                and top is not None
                and top.CardCode in (decision.covered_codes or [])
            )
            if result.block_submit and not covered:
                what = f"{top.CardCode} {top.CardName}" if top else "an existing record"
                raise HTTPException(
                    409,
                    f"This looks like a duplicate of {what}. Link your request to the existing "
                    "record, or confirm it is a different company and say why, before you submit.",
                )
        engine.submit(session, req, actor)
        session.flush()
        return detail_model(session, req, actor)


@router.post(
    "/requests/{req_id}/publish", response_model=RequestDetail, operation_id="publishRequest"
)
def publish_request(req_id: str, actor: CurrentUser) -> RequestDetail:
    """MDM analyst only, after every approval. Publishes to the SAP B1 mock (D-004)."""
    publishing.publish(req_id, actor)
    with session_scope() as session:
        return _detail(session, req_id, actor)


@router.get(
    "/requests/{req_id}/audit", response_model=list[AuditEntry], operation_id="getRequestAudit"
)
def get_request_audit(req_id: str, actor: CurrentUser) -> list[AuditEntry]:
    with session_scope() as session:
        req = _get(session, req_id)
        names = user_names(session)
        rows = session.scalars(
            select(m.AuditLog).where(m.AuditLog.request_id == req_id).order_by(m.AuditLog.id)
        ).all()
        return [audit_view.entry(r, names, req.domain.value) for r in rows]


__all__ = ["router", "tasks_for"]
