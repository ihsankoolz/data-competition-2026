"""The SAP read-back view for Priya (M7): what was sent, what SAP returned, field by field.

`rows_from_result` runs when a publish succeeds and the rows are stored already masked
(`sap_publish_results`), so no bank number sits in the table in the clear. `view` turns the
stored record into `SapPublishView`; for a Finance actor the bank values are put back from the
request's own (encrypted) fields wherever sent and read-back matched (domain rule 5).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from services.api import bankfields
from services.api.audit import scrub
from services.api.db import models as m
from services.api.sap_publisher import PublishResult, _same
from services.api.schemas import ReadBackRow, SapPublishView

BANK_PATH = re.compile(r"^BPBankAccounts\[(\d+)\]\.(\w+)$")
BANK_LEAVES = ("AccountNo", "IBAN", "BankCode", "AccountName", "BICSwiftCode")


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    """Leaf values by path, e.g. {'CardName': 'x', 'BPAddresses[0].City': 'y'}."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            out.update(_flatten(v, f"{path}.{k}" if path else str(k)))
        return out
    if isinstance(value, list):
        out = {}
        for i, v in enumerate(value):
            out.update(_flatten(v, f"{path}[{i}]"))
        return out
    return {path: value}


def _text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def rows_from_result(result: PublishResult) -> list[dict[str, Any]]:
    """Every field that was sent, with what SAP returned for it. Bank values are masked."""
    sent = _flatten(result.sent)
    got = _flatten(result.read_back or {})
    rows: list[dict[str, Any]] = []
    for path, value in sent.items():
        leaf = re.sub(r"\[\d+\]", "", path.rsplit(".", 1)[-1])
        received = got.get(path)
        rows.append(
            {
                "field": path,
                "sent": _text(scrub({leaf: value})[leaf]),
                "read_back": _text(scrub({leaf: received})[leaf]),
                "match": _same(value, received),
            }
        )
    return rows


def record_from_result(
    req: m.Request, result: PublishResult, published_by: str, when: Any
) -> m.SapPublishRecord:
    rows = rows_from_result(result)
    return m.SapPublishRecord(
        req_id=req.req_id,
        resource=result.resource,
        sap_code=result.key,
        published_at=when,
        published_by=published_by,
        active=result.final_state == "active",
        all_match=all(r["match"] for r in rows),
        rows=rows,
    )


def view(
    session: Session,
    req: m.Request,
    names: dict[str, str],
    *,
    is_finance: bool,
) -> SapPublishView | None:
    rec = session.get(m.SapPublishRecord, req.req_id)
    if rec is None:
        return None
    bank = bankfields.unseal(req.payload).get(bankfields.BANK_KEY) if is_finance else None
    rows: list[ReadBackRow] = []
    for r in rec.rows:
        sent, got = r["sent"], r["read_back"]
        hit = BANK_PATH.match(r["field"])
        if is_finance and hit and r["match"] and isinstance(bank, list):
            i, leaf = int(hit.group(1)), hit.group(2)
            if leaf in BANK_LEAVES and i < len(bank) and isinstance(bank[i], dict):
                real = _text(bank[i].get(leaf))
                if real is not None:
                    sent = got = real
        rows.append(ReadBackRow(field=r["field"], sent=sent, read_back=got, match=r["match"]))
    return SapPublishView(
        resource=rec.resource,  # type: ignore[arg-type]
        sap_code=rec.sap_code,
        published_at=rec.published_at,
        published_by=names.get(rec.published_by, rec.published_by),
        active=rec.active,
        all_match=rec.all_match,
        rows=rows,
    )
