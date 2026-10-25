"""Plain-English lines for the status-page timeline, built from `audit_log` rows.

The rows already hold masked bank values (`audit.scrub`); this module never decrypts anything.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from ds.forms import FORM_DOMAINS, load_form_schema
from services.api.db import models as m
from services.api.schemas import AuditEntry
from services.api.validation import COUNTRY_NAME

SPECIAL_ACTORS = {"system": "System", "sap_publisher": "SAP publisher"}


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _nice_date(v: Any) -> str:
    try:
        d = date.fromisoformat(str(v)[:10])
    except ValueError:
        return str(v)
    return f"{d.day} {d:%b %Y}"


def _country(code: Any) -> str:
    return COUNTRY_NAME.get(str(code), str(code))


def _human(key: str) -> str:
    return key.replace("_", " ")


def _plain(v: Any, key: str = "") -> str:
    """A value as people would say it: never a Python repr."""
    if v in (None, "", [], {}):
        return "(empty)"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        if all(isinstance(x, (str, int, float)) for x in v):
            as_country = key.endswith("countries") or key == "country"
            return ", ".join(_country(x) if as_country else str(x) for x in v)
        return f"{len(v)} entries"
    if isinstance(v, dict):
        return ", ".join(f"{_human(str(k))} {_plain(x, str(k))}" for k, x in v.items() if x)
    if key.endswith("_date"):
        return _nice_date(v)
    return str(v)


def _short(v: Any, n: int = 60, key: str = "") -> str:
    return _clip(_plain(v, key), n)


_REG_LEAF = {"reg_no": "number", "expiry_date": "expiry", "issue_date": "issue date"}


def _reg_rows(v: Any) -> dict[str, dict[str, Any]]:
    rows = v if isinstance(v, list) else []
    return {str(r.get("country")): r for r in rows if isinstance(r, dict) and r.get("country")}


def _reg_clauses(old: Any, new: Any) -> list[str]:
    o, n = _reg_rows(old), _reg_rows(new)
    out: list[str] = []
    for cc, row in n.items():
        name = _country(cc)
        if cc not in o:
            bits = [str(row["reg_no"])] if row.get("reg_no") else []
            if row.get("expiry_date"):
                bits.append(f"expires {_nice_date(row['expiry_date'])}")
            out.append(f"set the {name} registration" + (f" ({', '.join(bits)})" if bits else ""))
            continue
        changes = [
            f"{label} to {_nice_date(row[leaf]) if leaf.endswith('_date') else row[leaf]}"
            for leaf, label in _REG_LEAF.items()
            if row.get(leaf) and row.get(leaf) != o[cc].get(leaf)
        ]
        if changes:
            out.append(f"changed the {name} registration " + " and ".join(changes))
    out += [f"removed the {_country(cc)} registration" for cc in o if cc not in n]
    return out


def _registrations_summary(actor: str, old: Any, new: Any) -> str:
    clauses = _reg_clauses(old, new) or ["updated the registrations"]
    return _clip(f"{actor} " + "; ".join(clauses), 240)


def _field_label(domain: str | None, path: str) -> str:
    key = path.split("[", 1)[0].split(".", 1)[0]
    if key == "BPBankAccounts":
        return "the bank details"
    if domain in FORM_DOMAINS:
        props = load_form_schema(domain)["properties"]  # type: ignore[arg-type]
        return str(props.get(key, {}).get("title", key))
    return key


def _option_label(domain: str | None, key: str, v: Any) -> Any:
    """A coded value as its option label ("30 days", "Vietnam", "yes"); anything else unchanged."""
    if v in (None, "", [], {}) or domain not in FORM_DOMAINS:
        return v
    prop = load_form_schema(domain)["properties"].get(key, {})  # type: ignore[arg-type]
    for option in prop.get("oneOf", []):
        if option.get("const") == v or str(option.get("const")) == str(v):
            return option.get("title", v)
    if prop.get("enum") == ["tYES", "tNO"]:
        return {"tYES": "yes", "tNO": "no"}.get(str(v), v)
    if key == "Country":
        return _country(v)
    return v


# (what happened, what it tried to do when it failed)
_SAP_WORDS = {
    ("POST", "/Login"): ("signed in to SAP", "sign in to SAP"),
    ("POST", "/Logout"): ("signed out of SAP", "sign out of SAP"),
    ("GET", None): (
        "read the record back from SAP to check it",
        "read the record back from SAP to check it",
    ),
}


def _sap_summary(p: dict[str, Any]) -> str:
    method, path, status = p.get("method"), str(p.get("path") or ""), p.get("status")
    if (method, path) in _SAP_WORDS:
        done, attempted = _SAP_WORDS[(method, path)]
    elif method == "POST":
        done = "created the record in SAP (inactive until checked)"
        attempted = "create the record in SAP"
    elif method == "GET":
        done, attempted = _SAP_WORDS[("GET", None)]
    elif method == "PATCH":
        done = "activated the record in SAP"
        attempted = "activate the record in SAP"
    else:
        done = attempted = f"{method} {path}"
    if status is None or status >= 400:
        err = p.get("b1_error_message")
        return f"SAP: tried to {attempted}, but it failed" + (f" ({err})" if err else "")
    return f"SAP: {done}"


def _is_bank_field(field: str) -> bool:
    return "Bank" in field or "Account" in field or "IBAN" in field


def _noise_kind(row: m.AuditLog) -> str | None:
    """Rows that repeat in a burst: one bank edit per sub-field, one duplicate check per pause
    in typing. Each burst reads as one history line."""
    if row.action == "dedup_check":
        return "dedup"
    if row.action == "field_edit" and _is_bank_field(str(json.loads(row.payload).get("field", ""))):
        return "bank"
    return None


def summarize(row: m.AuditLog, names: dict[str, str], domain: str | None) -> str:
    p: dict[str, Any] = json.loads(row.payload)
    actor = names.get(row.actor) or SPECIAL_ACTORS.get(row.actor, row.actor)
    if row.action == "field_edit":
        field = str(p.get("field", ""))
        label = _field_label(domain, field)
        if _is_bank_field(field):
            return f"{actor} changed {label}"
        if field == "registrations":
            return _registrations_summary(actor, p.get("old"), p.get("new"))
        key = field.split("[", 1)[0].split(".", 1)[0]
        old = _short(_option_label(domain, field, p.get("old")), 80, key)
        new = _short(_option_label(domain, field, p.get("new")), 80, key)
        return _clip(f"{actor} changed {label}: {old} -> {new}", 240)
    if row.action == "sap_call":
        return _sap_summary(p)
    if row.action == "seed":
        return "Demo data loaded"
    summary = p.get("summary")
    if isinstance(summary, str) and summary:
        return summary
    return f"{actor}: {row.action.replace('_', ' ')}"


def entry(row: m.AuditLog, names: dict[str, str], domain: str | None) -> AuditEntry:
    return AuditEntry(
        id=row.id,
        ts=datetime.fromisoformat(row.ts),
        actor=names.get(row.actor) or SPECIAL_ACTORS.get(row.actor, row.actor),
        action=row.action,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        summary=summarize(row, names, domain),
    )


def entries(rows: list[m.AuditLog], names: dict[str, str], domain: str | None) -> list[AuditEntry]:
    """The timeline for a request. Back-to-back bank edits by one person show once (the first),
    back-to-back duplicate checks once (the latest result). The audit log itself keeps every row."""
    kept: list[m.AuditLog] = []
    for row in rows:
        kind = _noise_kind(row)
        prev = kept[-1] if kept else None
        if kind and prev is not None and _noise_kind(prev) == kind and prev.actor == row.actor:
            if kind == "dedup":
                kept[-1] = row
            continue
        kept.append(row)
    return [entry(r, names, domain) for r in kept]
