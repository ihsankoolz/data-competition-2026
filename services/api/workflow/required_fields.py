"""Editable required fields (session 13): Priya switches a form field between required and
optional for one record type x country, without going back to IT.

A toggle is a row in `required_field_overrides`, kept only where the choice differs from the
standard lists in `config/required_fields.yaml`. No rows means nothing changes. The toggles are
applied in deterministic code after the model has read an email: they never touch the interpreter
prompt, its extract keys or the replay cache.

A request stores the toggles it was created with (`Request.required_snapshot`), so a later change
applies to new requests only, and resubmits keep the rules their request started with.

Some fields can never be made optional: SAP needs them, or routing, the duplicate check or
Finance depends on them. They are listed in `LOCKED` with a one-line reason shown in the UI.
"""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ds.forms import country_names, extract_to_form_field, load_form_schema, required_keys
from services.api import clock
from services.api.audit import AuditAction, append_audit
from services.api.db import models as m
from services.api.formfields import RequiredOverride
from services.api.schemas import (
    RequiredFieldChange,
    RequiredFieldRow,
    RequiredFieldsSave,
    RequiredFieldsView,
)
from services.api.views import user_names

COUNTRIES = ("SG", "MY", "ID", "VN", "TH")
RECENT_CHANGES = 20
NOTE = (
    "Applies to new requests only. Requests already made keep the rules they started with, "
    "and so do their resubmits."
)
DOMAIN_WORDS = {
    "customer": "customers",
    "vendor": "vendors",
    "item": "items",
    "cost_center": "cost centers",
}

_NAME = "SAP cannot create the record without a name."
_COUNTRY = "The country decides the tax ID rules and who reviews the request."
_TAX = "The duplicate check matches on the tax ID, and tax rules differ by country."
LOCKED: dict[str, dict[str, str]] = {
    "customer": {"CardName": _NAME, "Country": _COUNTRY, "FederalTaxID": _TAX},
    "vendor": {
        "CardName": _NAME,
        "Country": _COUNTRY,
        "FederalTaxID": _TAX,
        "BPBankAccounts": "Finance must check the bank details before anyone is paid.",
    },
    "item": {
        "ItemName": _NAME,
        "U_IVD": "It decides whether Quality/Regulatory must review the item.",
        "selling_countries": "Quality/Regulatory checks one registration per selling country.",
        "registrations": "Quality/Regulatory checks a registration number for every selling "
        "country of an IVD item.",
    },
    "cost_center": {
        "CenterName": _NAME,
        "EffectiveFrom": "SAP needs the date the cost center starts.",
    },
}


def _fail(message: str) -> HTTPException:
    return HTTPException(status_code=422, detail=message)


def standard_fields(domain: str, country: str) -> set[str]:
    """Form fields the standard rules (YAML) require for a home-country request."""
    to_field = extract_to_form_field(domain)  # type: ignore[arg-type]
    keys = required_keys(domain, country, include_form_only=True)  # type: ignore[arg-type]
    out = {to_field[k] for k in keys if k in to_field}
    if domain == "item":  # required when the item is an IVD; locked either way
        out.add("registrations")
    return out


def apply(base: list[str], override: RequiredOverride, domain: str) -> list[str]:
    """A form's required list with the toggles applied, in form order."""
    if not override:
        return base
    order = load_form_schema(domain)["x-order"]  # type: ignore[arg-type]
    names = (set(base) | override.add) - override.drop
    return sorted(names, key=order.index)


# ---------------------------------------------------------------- what a request keeps


def rows_for(session: Session, domain: str, country: str) -> dict[str, bool]:
    q = select(m.RequiredFieldOverride).where(
        m.RequiredFieldOverride.domain == domain, m.RequiredFieldOverride.country == country
    )
    return {r.field: r.required for r in session.scalars(q)}


def override_now(session: Session, domain: str, country: str | None) -> RequiredOverride:
    """The toggles in force today for a form being opened (none for a country outside the five)."""
    if country not in COUNTRIES:
        return RequiredOverride()
    rows = rows_for(session, domain, country)
    return RequiredOverride(
        add=frozenset(f for f, r in rows.items() if r),
        drop=frozenset(f for f, r in rows.items() if not r),
    )


def snapshot_for(session: Session, domain: str) -> dict[str, dict[str, list[str]]] | None:
    """Every country's toggles for this record type, stored on a new request. None if no toggles
    exist (the demo path), so a request made then is byte-for-byte what it was before."""
    out: dict[str, dict[str, list[str]]] = {}
    q = select(m.RequiredFieldOverride).where(m.RequiredFieldOverride.domain == domain)
    for r in session.scalars(q.order_by(m.RequiredFieldOverride.field)):
        entry = out.setdefault(r.country, {"add": [], "drop": []})
        entry["add" if r.required else "drop"].append(r.field)
    return out or None


# ---------------------------------------------------------------- reading and saving


def _check_scope(domain: str, country: str) -> None:
    if country not in COUNTRIES:
        raise _fail("Choose one of the five countries: SG, MY, ID, VN or TH.")
    if domain not in LOCKED:
        raise _fail(f"There is no form for {domain}.")


def view(session: Session, domain: str, country: str) -> RequiredFieldsView:
    _check_scope(domain, country)
    schema = load_form_schema(domain)  # type: ignore[arg-type]
    standard = standard_fields(domain, country)
    toggles = rows_for(session, domain, country)
    locked = LOCKED[domain]
    rows = []
    for name in schema["x-order"]:
        spec = schema["properties"][name]
        now = toggles.get(name, name in standard)
        rows.append(
            RequiredFieldRow(
                field=name,
                label=str(spec.get("title", name)),
                help=spec.get("description"),
                required=now or name in locked,
                standard=name in standard,
                changed=name in toggles,
                locked=name in locked,
                locked_reason=locked.get(name),
            )
        )
    return RequiredFieldsView(domain=domain, country=country, fields=rows, note=NOTE)  # type: ignore[arg-type]


def save(session: Session, actor_id: str, body: RequiredFieldsSave) -> RequiredFieldsView:
    """Switch fields on or off. All-or-nothing: one locked or unknown field refuses the lot.
    Each real change writes a `config_change` audit row."""
    _check_scope(body.domain, body.country)
    schema = load_form_schema(body.domain)  # type: ignore[arg-type]
    props = schema["properties"]
    locked = LOCKED[body.domain]
    standard = standard_fields(body.domain, body.country)
    toggles = rows_for(session, body.domain, body.country)
    seen: set[str] = set()
    for item in body.fields:
        if item.field in seen:
            label = props.get(item.field, {}).get("title", item.field)
            raise _fail(f"{label} is listed twice. Send each field once.")
        seen.add(item.field)
    for item in body.fields:
        if item.field not in props:
            raise _fail(
                f"'{item.field}' is not a field on the {body.domain.replace('_', ' ')} form."
            )
        if not item.required and item.field in locked:
            label = props[item.field].get("title", item.field)
            raise _fail(f"{label} can't be made optional. {locked[item.field]}")
    names = user_names(session)
    who = names.get(actor_id, actor_id)
    place = f"{country_names().get(body.country, body.country)} {DOMAIN_WORDS[body.domain]}"
    for item in body.fields:
        if item.field in locked:  # (already required; nothing to store)
            continue
        before = toggles.get(item.field, item.field in standard)
        if item.required == before:
            continue
        row = session.get(m.RequiredFieldOverride, (body.domain, body.country, item.field))
        if item.required == (item.field in standard):  # back to the standard rules
            if row is not None:
                session.delete(row)
        elif row is None:
            session.add(
                m.RequiredFieldOverride(
                    domain=body.domain, country=body.country, field=item.field,
                    required=item.required, updated_by=actor_id, updated_at=clock.now(),
                )
            )  # fmt: skip
        else:
            row.required, row.updated_by, row.updated_at = item.required, actor_id, clock.now()
        session.flush()
        label = str(props[item.field].get("title", item.field))
        append_audit(
            session,
            actor=actor_id,
            action=AuditAction.config_change,
            entity_type="required_field",
            entity_id=f"{body.domain}/{body.country}/{item.field}",
            payload={
                "summary": f"{who} made {label} {'required' if item.required else 'optional'} "
                f"for {place}",
                "domain": body.domain,
                "country": body.country,
                "field": item.field,
                "field_label": label,
                "old": before,
                "new": item.required,
            },
        )
    return view(session, body.domain, body.country)


def recent_changes(session: Session, limit: int = RECENT_CHANGES) -> list[RequiredFieldChange]:
    rows = session.scalars(
        select(m.AuditLog)
        .where(
            m.AuditLog.action == AuditAction.config_change.value,
            m.AuditLog.entity_type == "required_field",
        )
        .order_by(m.AuditLog.id.desc())
        .limit(limit)
    ).all()
    names = user_names(session)
    out = []
    for r in rows:
        p = json.loads(r.payload)
        out.append(
            RequiredFieldChange(
                id=r.id,
                at=datetime.fromisoformat(r.ts),
                who=names.get(r.actor, r.actor),
                domain=p["domain"],
                country=p["country"],
                field=p["field"],
                field_label=p["field_label"],
                now_required=p["new"],
                summary=p["summary"],
            )
        )
    return out
