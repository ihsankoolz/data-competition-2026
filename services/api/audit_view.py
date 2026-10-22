"""Plain-English lines for the status-page timeline, built from `audit_log` rows.

The rows already hold masked bank values (`audit.scrub`); this module never decrypts anything.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from ds.forms import FORM_DOMAINS, load_form_schema
from services.api.db import models as m
from services.api.schemas import AuditEntry

SPECIAL_ACTORS = {"system": "System", "sap_publisher": "SAP publisher"}


def _short(v: Any, n: int = 60) -> str:
    text = "(empty)" if v in (None, "", [], {}) else str(v)
    return text if len(text) <= n else text[: n - 1] + "..."


def _field_label(domain: str | None, path: str) -> str:
    key = path.split("[", 1)[0].split(".", 1)[0]
    if key == "BPBankAccounts":
        return "the bank details"
    if domain in FORM_DOMAINS:
        props = load_form_schema(domain)["properties"]  # type: ignore[arg-type]
        return str(props.get(key, {}).get("title", key))
    return key


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


def summarize(row: m.AuditLog, names: dict[str, str], domain: str | None) -> str:
    p: dict[str, Any] = json.loads(row.payload)
    actor = names.get(row.actor) or SPECIAL_ACTORS.get(row.actor, row.actor)
    if row.action == "field_edit":
        field = str(p.get("field", ""))
        label = _field_label(domain, field)
        if "Bank" in field or "Account" in field or "IBAN" in field:
            return f"{actor} changed {label}"
        return f"{actor} changed {label}: {_short(p.get('old'))} -> {_short(p.get('new'))}"
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
