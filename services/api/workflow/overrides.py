"""Editable approval rules (session 12): admin overrides of stage 1 ("Business review").

An override is keyed by record type x entity x country and holds the full ordered list of
approver steps, each `{role, user_id}`. No row means the YAML rule table applies, exactly as it
always did. Routing stays deterministic and LLM-free: `plan_tasks` + `assign` are the only code
that turns a rule into tasks, and the preview here calls them too.

A request stores the override it was routed with (`Request.routing_override`), so saving a rule
later changes new requests only.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api import clock
from services.api.audit import AuditAction, append_audit
from services.api.db import models as m
from services.api.schemas import (
    ConfigChange,
    RoutingRule,
    RoutingRules,
    RoutingRuleSave,
    RuleKey,
    RulePreview,
    RulePreviewRequest,
    RulePreviewTask,
    RuleRole,
    RuleStep,
    RuleStepIn,
)
from services.api.views import ROLE_LABEL, user_names
from services.api.workflow.rules import assign, directory, plan_tasks

ALL_COUNTRIES = "*"
COUNTRIES = ("SG", "MY", "ID", "VN", "TH")
DOMAINS = ("customer", "vendor", "item", "cost_center")
ENTITIES = ("SPD", "QTS", "QTG")
COUNTRY_DOMAINS = ("customer", "vendor")  # records that carry a country of their own
STEP_ROLES = ("bu_head", "finance", "business_support", "quality_regulatory")
MAX_STEPS = 8
REQUESTOR_ROLE = "requestor"
RECENT_CHANGES = 20

DOMAIN_WORDS = {
    "customer": "customers",
    "vendor": "vendors",
    "item": "items",
    "cost_center": "cost centers",
}


def rule_country(domain: str, record_country: str | None) -> str:
    """The country part of a rule key: the record's own country for customers and vendors, and
    "all countries" for items and cost centers, which have no country of their own."""
    if domain in COUNTRY_DOMAINS:
        return (record_country or "").upper()
    return ALL_COUNTRIES


def record_country(req: m.Request, plain_fields: dict[str, Any]) -> str:
    """The country a request's rule is looked up by: the form's Country, else the request's."""
    return rule_country(req.domain.value, str(plain_fields.get("Country") or req.country))


def resolve(
    session: Session, domain: str, entity: str, country: str
) -> list[dict[str, str]] | None:
    """The saved override for this key as `[{role, user_id}]`, or None (the YAML applies)."""
    row = session.get(m.RoutingOverride, (domain, entity, country))
    return [dict(s) for s in row.steps] if row else None


# ---------------------------------------------------------------- reading rules


def _step(role: str, user_id: str, names: dict[str, str]) -> RuleStep:
    return RuleStep(
        role=role,  # type: ignore[arg-type]
        role_label=ROLE_LABEL.get(role, role),
        user_id=user_id,
        name=names.get(user_id, user_id),
    )


def default_steps(session: Session, domain: str, entity: str) -> list[dict[str, str]]:
    """Who the YAML rule table assigns to stage 1 for this record type and entity."""
    dir_ = directory(session)
    taken: set[tuple[int, str, str]] = set()
    out: list[dict[str, str]] = []
    for plan in plan_tasks(domain, {}):
        if plan.stage == 1:
            out.append({"role": plan.role, "user_id": assign(plan, entity, dir_, taken).user_id})
    return out


def all_keys() -> list[tuple[str, str, str]]:
    keys: list[tuple[str, str, str]] = []
    for domain in DOMAINS:
        for entity in ENTITIES:
            for country in COUNTRIES if domain in COUNTRY_DOMAINS else (ALL_COUNTRIES,):
                keys.append((domain, entity, country))
    return keys


def _rule(
    key: tuple[str, str, str],
    row: m.RoutingOverride | None,
    defaults: list[dict[str, str]],
    names: dict[str, str],
) -> RoutingRule:
    domain, entity, country = key
    steps = row.steps if row else defaults
    return RoutingRule(
        domain=domain,  # type: ignore[arg-type]
        entity=entity,  # type: ignore[arg-type]
        country=country,  # type: ignore[arg-type]
        steps=[_step(s["role"], s["user_id"], names) for s in steps],
        is_override=row is not None,
        changed_by=names.get(row.updated_by, row.updated_by) if row else None,
        changed_at=row.updated_at if row else None,
    )


def list_rules(session: Session) -> RoutingRules:
    names = user_names(session)
    rows = {(r.domain, r.entity, r.country): r for r in session.scalars(select(m.RoutingOverride))}
    defaults: dict[tuple[str, str], list[dict[str, str]]] = {}
    rules = []
    for key in all_keys():
        if key[:2] not in defaults:
            defaults[key[:2]] = default_steps(session, key[0], key[1])
        rules.append(_rule(key, rows.get(key), defaults[key[:2]], names))
    users = list(directory(session).users)
    roles = [
        RuleRole(
            role=role,  # type: ignore[arg-type]
            label=ROLE_LABEL[role],
            people=[
                {  # type: ignore[misc]
                    "user_id": u.user_id,
                    "name": u.name,
                    "title": u.title,
                    "roles": list(u.roles),
                    "entity": u.entity,
                    "country": u.country,
                }
                for u in users
                if role in u.roles
            ],
        )
        for role in STEP_ROLES
    ]
    return RoutingRules(
        rules=rules,
        roles=roles,
        publish_note="After these steps, Priya (MDM) publishes the record. That stage is fixed.",
    )


# ---------------------------------------------------------------- validating and saving


def _fail(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def check_key(key: RuleKey) -> None:
    if key.domain in COUNTRY_DOMAINS and key.country == ALL_COUNTRIES:
        raise _fail(f"Choose a country: rules for {DOMAIN_WORDS[key.domain]} are set per country.")
    if key.domain not in COUNTRY_DOMAINS and key.country != ALL_COUNTRIES:
        raise _fail(f"Rules for {DOMAIN_WORDS[key.domain]} apply to all countries.")


def check_steps(session: Session, steps: list[RuleStepIn]) -> list[dict[str, str]]:
    """Plain 422s: no approvers, an unknown person, a person without the step's role, or a
    person who (or whose backup) also raises requests."""
    if not steps:
        raise _fail(
            "Add at least one approver. A request needs someone to review it before MDM publishes."
        )
    if len(steps) > MAX_STEPS:
        raise _fail(f"Use at most {MAX_STEPS} approver steps.")
    dir_ = directory(session)
    users = {u.user_id: u for u in dir_.users}
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, str]] = []
    for step in steps:
        user = users.get(step.user_id)
        label = ROLE_LABEL.get(step.role, step.role)
        if user is None:
            raise _fail(f"'{step.user_id}' is not a known person, so they cannot approve a step.")
        if step.role not in user.roles:
            raise _fail(f"{user.name} does not hold the {label} role, so cannot take that step.")
        # Session 13 (D-026 #3 gap): someone who can raise requests, or whose escalation backup
        # can, could end up approving a request they raised. Maker-checker still blocks that at
        # decision time; refusing it here stops a rule that would leave a task stuck.
        if REQUESTOR_ROLE in user.roles:
            raise _fail(
                f"{user.name} also raises requests, so they could be the person who raised the "
                "request. They cannot be an approver here. Choose someone else."
            )
        backup = dir_.backup_of(user.user_id)
        if backup is not None and REQUESTOR_ROLE in backup.roles:
            raise _fail(
                f"{user.name}'s backup ({backup.name}) could be the person who raised the "
                f"request, so {user.name} cannot be an approver here. Choose someone else."
            )
        if (step.role, step.user_id) in seen:
            raise _fail(f"{user.name} is listed twice as {label}. Remove the repeat.")
        seen.add((step.role, step.user_id))
        out.append({"role": step.role, "user_id": step.user_id})
    return out


def _words(steps: list[dict[str, str]], names: dict[str, str]) -> list[str]:
    return [
        f"{ROLE_LABEL.get(s['role'], s['role'])}: {names.get(s['user_id'], s['user_id'])}"
        for s in steps
    ]


def _where(key: tuple[str, str, str]) -> str:
    domain, entity, country = key
    place = "all countries" if country == ALL_COUNTRIES else country
    return f"{entity} {DOMAIN_WORDS[domain]} ({place})"


def _audit_change(
    session: Session,
    actor_id: str,
    key: tuple[str, str, str],
    old: list[dict[str, str]],
    new: list[dict[str, str]],
    *,
    old_is_default: bool,
    reset: bool,
) -> None:
    names = user_names(session)
    who = names.get(actor_id, actor_id)
    where = _where(key)
    summary = (
        f"{who} put the approvers for {where} back to the standard route"
        if reset
        else f"{who} changed the approvers for {where}"
    )
    append_audit(
        session,
        actor=actor_id,
        action=AuditAction.config_change,
        entity_type="routing_rule",
        entity_id="/".join(key),
        payload={
            "summary": summary,
            "domain": key[0],
            "entity": key[1],
            "country": key[2],
            "old": old,
            "new": new,
            "old_was_standard": old_is_default,
            "old_text": _words(old, names),
            "new_text": _words(new, names),
        },
    )


def save_rule(session: Session, actor_id: str, body: RoutingRuleSave) -> RoutingRule:
    check_key(body)
    steps = check_steps(session, body.steps)
    key = (body.domain, body.entity, body.country)
    row = session.get(m.RoutingOverride, key)
    defaults = default_steps(session, body.domain, body.entity)
    old = [dict(s) for s in row.steps] if row else defaults
    had_override = row is not None
    if row is None:
        row = m.RoutingOverride(
            domain=key[0], entity=key[1], country=key[2], steps=steps,
            updated_by=actor_id, updated_at=clock.now(),
        )  # fmt: skip
        session.add(row)
    else:
        row.steps, row.updated_by, row.updated_at = steps, actor_id, clock.now()
    session.flush()
    _audit_change(session, actor_id, key, old, steps, old_is_default=not had_override, reset=False)
    return _rule(key, row, defaults, user_names(session))


def reset_rule(session: Session, actor_id: str, key_in: RuleKey) -> RoutingRule:
    """Back to the standard route (the YAML). Does nothing if no override was saved."""
    check_key(key_in)
    key = (key_in.domain, key_in.entity, key_in.country)
    row = session.get(m.RoutingOverride, key)
    defaults = default_steps(session, key_in.domain, key_in.entity)
    if row is not None:
        old = [dict(s) for s in row.steps]
        session.delete(row)
        session.flush()
        _audit_change(session, actor_id, key, old, defaults, old_is_default=False, reset=True)
    return _rule(key, None, defaults, user_names(session))


def recent_changes(session: Session, limit: int = RECENT_CHANGES) -> list[ConfigChange]:
    rows = session.scalars(
        select(m.AuditLog)
        .where(
            m.AuditLog.action == AuditAction.config_change.value,
            m.AuditLog.entity_type == "routing_rule",
        )
        .order_by(m.AuditLog.id.desc())
        .limit(limit)
    ).all()
    names = user_names(session)
    out = []
    for r in rows:
        p = json.loads(r.payload)
        out.append(
            ConfigChange(
                id=r.id,
                at=datetime.fromisoformat(r.ts),
                who=names.get(r.actor, r.actor),
                domain=p["domain"],
                entity=p["entity"],
                country=p["country"],
                summary=p["summary"],
                before=list(p.get("old_text", [])),
                after=list(p.get("new_text", [])),
            )
        )
    return out


# ---------------------------------------------------------------- preview


def preview(session: Session, body: RulePreviewRequest) -> RulePreview:
    """Who would approve a sample request, from the same `plan_tasks` + `assign` that submit
    uses. A draft is checked like a save; nothing is stored."""
    check_key(body)
    if body.steps is not None:
        override: list[dict[str, str]] | None = check_steps(session, body.steps)
        source = "draft"
    else:
        override = resolve(session, body.domain, body.entity, body.country)
        source = "saved" if override else "standard"
    dir_ = directory(session)
    taken: set[tuple[int, str, str]] = set()
    tasks = []
    for plan in plan_tasks(body.domain, {}, override):
        person = assign(plan, body.entity, dir_, taken)
        label = ROLE_LABEL.get(plan.role, plan.role)
        tasks.append(
            RulePreviewTask(
                stage=plan.stage,
                stage_name=plan.stage_name,
                role=plan.role,
                role_label=f"{label} ({plan.country})" if plan.country else label,
                user_id=person.user_id,
                name=person.name,
            )
        )
    return RulePreview(tasks=tasks, source=source)  # type: ignore[arg-type]
