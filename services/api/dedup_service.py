"""The duplicate check as the API uses it (D-005).

The `MasterIndex` is built once, lazily, from the `business_partners` table (customers and
vendors) and rebuilt after a reset and after a publish. `ds.dedup` is only called from here and
from the dedup endpoints, never from the workflow, routing or publishing path.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from sqlalchemy import select

from ds.dedup import BPRecord, DedupResult, MasterIndex, check
from ds.forms import dedup_query
from services.api.db import models as m
from services.api.db.session import session_scope

_lock = threading.Lock()
_index: MasterIndex | None = None


def _records() -> list[BPRecord]:
    cols = (
        m.BusinessPartner.CardCode,
        m.BusinessPartner.CardName,
        m.BusinessPartner.CardForeignName,
        m.BusinessPartner.CardType,
        m.BusinessPartner.FederalTaxID,
        m.BusinessPartner.Country,
        m.BusinessPartner.City,
        m.BusinessPartner.Phone1,
        m.BusinessPartner.EmailAddress,
        m.BusinessPartner.U_Entity,
    )
    with session_scope() as session:
        rows = session.execute(select(*cols)).all()
    return [BPRecord.model_validate(dict(r._mapping)) for r in rows if r.Country]


def get_index() -> MasterIndex:
    global _index
    index = _index
    if index is None:
        with _lock:
            if _index is None:
                _index = MasterIndex(_records())
            index = _index
    return index


def rebuild_index() -> MasterIndex:
    """Build a fresh index and swap it in (after a reset or a publish)."""
    global _index
    fresh = MasterIndex(_records())
    with _lock:
        _index = fresh
    return fresh


def invalidate_index() -> None:
    global _index
    with _lock:
        _index = None


def judge_enabled() -> bool:
    """The AI second opinion is a cache lookup in replay mode; in record/live it would be a
    network call on a keystroke, so only the rules run then."""
    return os.environ.get("LLM_MODE", "replay").strip().lower() == "replay"


def run_check(domain: str, entity: str | None, fields: dict[str, Any]) -> DedupResult:
    query = dedup_query(domain, entity, fields)  # type: ignore[arg-type]
    if query is None:
        return DedupResult(
            verdict="none",
            message="Enter the name and country and we will check for existing records.",
            block_submit=False,
        )
    return check(query, get_index(), use_judge=judge_enabled())
