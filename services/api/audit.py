"""Append-only, hash-chained audit log (PRD M6).

One writer function, `append_audit`, adds a row inside the caller's transaction. Rows are chained:

    hash = sha256(prev_hash + canonical_json(row content))

where canonical JSON has sorted keys, no whitespace and ISO timestamps, and the first row's
`prev_hash` is 64 zeros. SQLite triggers (see `db/models.py`) reject UPDATE and DELETE.

How the chain cannot fork: every append first runs a write on the single `audit_head` row,
which takes SQLite's write lock for the rest of the transaction; only then is the newest hash
read. A second writer waits for the first to commit. As a second line of defence `prev_hash`
and `hash` are UNIQUE, so a fork would be rejected by the database.

Timestamps come from the simulated clock. Bank values are masked before a payload is written
(domain rule 5): the audit log never holds an account number or IBAN, and nothing is logged.
"""

from __future__ import annotations

import enum
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from services.api import clock
from services.api.crypto import mask
from services.api.db.models import GENESIS_HASH, AuditHead, AuditLog


class AuditAction(enum.StrEnum):
    state_change = "state_change"
    field_edit = "field_edit"
    dedup_decision = "dedup_decision"
    dedup_check = "dedup_check"
    approval = "approval"
    sap_call = "sap_call"
    seed = "seed"
    cleanup_decision = "cleanup_decision"


class VerifyResult(BaseModel):
    ok: bool
    checked: int
    first_broken_id: int | None = None
    reason: str | None = None


# ------------------------------------------------------------------ canonical JSON + masking


def _jsonable(value: Any) -> Any:
    """Convert to plain JSON types (dates as ISO text) before masking and hashing."""
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(v) for v in value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


# A key is a bank key if its normalised form (lower case, letters and digits only) contains one
# of these. "Account No", account_number, iban_number and BICSwiftCode all match.
_BANK_KEY_PARTS = (
    "iban",
    "accountno",
    "accountnum",
    "acctno",
    "accountname",
    "bankcode",
    "swift",
)
# These show the last four characters when masked; the rest are fully hidden.
_KEEP4_KEY_PARTS = ("iban", "accountno", "accountnum", "acctno")


def _norm(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


def _is_bank_key(key: str) -> bool:
    n = _norm(key)
    return n.startswith("bic") or any(part in n for part in _BANK_KEY_PARTS)


def _keep_for(key: str) -> int:
    n = _norm(key)
    return 4 if any(part in n for part in _KEEP4_KEY_PARTS) else 0


def _last_segment(path: str) -> str:
    """'BPBankAccounts[0].AccountNo' -> 'AccountNo'; 'IBAN[1]' -> 'IBAN'."""
    return re.sub(r"\[\d*\]$", "", path.rsplit(".", 1)[-1])


def _mask_leaves(value: Any, keep: int) -> Any:
    """Mask every scalar under a bank key, whatever the nesting."""
    if isinstance(value, dict):
        return {k: _mask_leaves(v, keep) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_mask_leaves(v, keep) for v in value]
    if value is None:
        return None
    return mask(str(value), keep=keep)


def scrub(value: Any) -> Any:
    """Return a copy with every bank value masked, at any depth.

    Handles bank keys with scalar, list or dict values (`{"IBAN": ["DE89..."]}`), key variants
    (`account_number`, `Account No`, `iban_number`) and field edits, where the `field` path may
    be nested (`{"field": "BPBankAccounts[0].AccountNo", "old": ..., "new": ...}`).
    """
    if isinstance(value, dict):
        field = value.get("field")
        edited_bank_field = isinstance(field, str) and _is_bank_key(_last_segment(field))
        out: dict[str, Any] = {}
        for k, v in value.items():
            if _is_bank_key(str(k)):
                out[k] = _mask_leaves(v, _keep_for(str(k)))
            elif edited_bank_field and k in {"old", "new", "value"}:
                out[k] = _mask_leaves(v, _keep_for(_last_segment(field)))
            else:
                out[k] = scrub(v)
        return out
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    return value


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_hash(prev_hash: str, content: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(content)).encode("utf-8")).hexdigest()


def _content(row: AuditLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "ts": row.ts,
        "actor": row.actor,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "request_id": row.request_id,
        "payload": json.loads(row.payload),
    }


# ------------------------------------------------------------------ the one writer


def append_audit(
    session: Session,
    *,
    actor: str,
    action: AuditAction | str,
    entity_type: str,
    entity_id: str,
    request_id: str | None = None,
    payload: Mapping[str, Any] | BaseModel | None = None,
) -> AuditLog:
    """Add one row to the chain inside the caller's transaction (the caller commits)."""
    action_value = AuditAction(action).value  # unknown actions are a programming error
    payload_obj = scrub(_jsonable(payload)) if payload is not None else {}

    # Take the write lock first (a write on the head row), then read the newest hash.
    session.execute(text("UPDATE audit_head SET last_id = last_id WHERE id = 1"))
    head = session.execute(
        select(AuditHead).where(AuditHead.id == 1).execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if head is None:
        raise RuntimeError("audit_head row is missing: create the schema with create_schema()")

    row = AuditLog(
        id=head.last_id + 1,
        ts=clock.now().isoformat(),
        actor=actor,
        action=action_value,
        entity_type=entity_type,
        entity_id=str(entity_id),
        request_id=request_id,
        payload=canonical_json(payload_obj),
        prev_hash=head.last_hash,
        hash="",
    )
    row.hash = compute_hash(row.prev_hash, _content(row))
    session.add(row)
    head.last_id = row.id
    head.last_hash = row.hash
    session.flush()
    return row


def audit_field_edit(
    session: Session,
    *,
    actor: str,
    entity_type: str,
    entity_id: str,
    field: str,
    old: Any,
    new: Any,
    request_id: str | None = None,
) -> AuditLog:
    """A field edit (old -> new). Bank fields are masked by `scrub`."""
    return append_audit(
        session,
        actor=actor,
        action=AuditAction.field_edit,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=request_id,
        payload={"field": field, "old": old, "new": new},
    )


# ------------------------------------------------------------------ verification


def verify_chain(session: Session) -> VerifyResult:
    """Walk the chain from the genesis row. Returns the first broken row id, or ok."""
    expected_prev = GENESIS_HASH
    checked = 0
    last_id = 0
    rows = session.execute(select(AuditLog).order_by(AuditLog.id)).scalars()
    for row in rows:
        if row.prev_hash != expected_prev:
            return VerifyResult(
                ok=False,
                checked=checked,
                first_broken_id=row.id,
                reason="prev_hash does not match the previous row (row removed or reordered)",
            )
        if compute_hash(row.prev_hash, _content(row)) != row.hash:
            return VerifyResult(
                ok=False,
                checked=checked,
                first_broken_id=row.id,
                reason="hash does not match the row content (row was edited)",
            )
        expected_prev = row.hash
        last_id = row.id
        checked += 1

    head = session.execute(select(AuditHead).where(AuditHead.id == 1)).scalar_one_or_none()
    if head is not None and (head.last_hash != expected_prev or head.last_id != last_id):
        return VerifyResult(
            ok=False,
            checked=checked,
            first_broken_id=last_id + 1,
            reason="newest rows are missing (log was truncated)",
        )
    return VerifyResult(ok=True, checked=checked)


def plain_message(result: VerifyResult) -> str:
    """The user-facing sentence. The technical reason stays in its own field."""
    if result.ok:
        n = result.checked
        return f"All {n} entries intact." if n != 1 else "The 1 entry is intact."
    before = "Everything before it is intact." if result.checked else "Nothing comes before it."
    return f"Entry {result.first_broken_id} was changed or removed. {before}"
