"""In-app demo reset (D-016): restore the seeded state in seconds, without stopping the API.

What is reset, in this order:

1. the database, reloaded **in place** through the live engine in one transaction
   (`services.api.db.seed.reload_in_place`): other requests see the old complete database until
   the commit and the new complete one after it, never a half-loaded one. This includes the
   append-only audit log, which goes back to its seeded rows (its tables and triggers are
   recreated inside the same transaction; no application code can delete or update audit rows);
2. the simulated clock (back to Mon 5 Oct 2026 09:00 SGT, also saved in the database);
3. the duplicate-check index (rebuilt from the reloaded master data);
4. the SAP mock (`POST /_mock/reset`, outside `/b1s/v2`), after 1-3 succeeded. If the mock is
   down or fails the reset still succeeds and reports `sap_mock_reset=false`.

`make reset-demo` goes through the same function (see `services.api.db.seed.main`).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import httpx
from sqlalchemy import func, select

from services.api import clock, dedup_service
from services.api.crypto import require_key
from services.api.db import models as m
from services.api.db.seed import (
    SeedError,
    check_files_exist,
    read_fixtures,
    reload_in_place,
)
from services.api.db.session import REPO_ROOT, get_engine, session_scope
from services.api.schemas import ResetResult

log = logging.getLogger(__name__)
DEFAULT_FIXTURES = REPO_ROOT / "data" / "fixtures" / "seasonal_trend"
SAP_BASE_PATH = "/b1s/v2"
_lock = threading.Lock()  # one reset at a time


def sap_mock_root() -> str:
    base = os.environ.get("SAP_BASE_URL", f"http://localhost:8001{SAP_BASE_PATH}").rstrip("/")
    return base.removesuffix(SAP_BASE_PATH)


def reset_sap_mock(timeout: float = 1.0) -> bool:
    """Clear the SAP mock's records and sessions. False if it can't be reached."""
    url = f"{sap_mock_root()}/_mock/reset"
    try:
        # A short connect timeout: a mock that is not running refuses slowly on Windows (about a
        # second), and the reset must not wait for it. No TLS context for a plain http URL
        # (building one costs 0.2-0.5 s per call).
        resp = httpx.post(
            url,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 0.3)),
            verify=not url.startswith("http://"),
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        return False


def table_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    with session_scope() as session:
        for table in m.Base.metadata.sorted_tables:
            counts[table.name] = session.scalar(select(func.count()).select_from(table)) or 0
    return counts


def reset_demo(fixtures: Path | str | None = None) -> ResetResult:
    t0 = time.perf_counter()
    fixtures_dir = Path(fixtures) if fixtures else DEFAULT_FIXTURES
    # Everything that can fail on bad input happens before the database is touched.
    check_files_exist(fixtures_dir)
    require_key()
    data = read_fixtures(fixtures_dir)
    with _lock:
        reload_in_place(get_engine(), data, fixtures_dir)
        clock.reset()
        dedup_service.rebuild_index()
    # Only after the database reload succeeded (a failed reload must leave the mock alone).
    try:
        sap_ok = reset_sap_mock()
    except Exception:  # noqa: BLE001 - the demo reset must still report; the cause is logged
        log.exception("SAP mock reset failed")
        sap_ok = False
    return ResetResult(
        ok=True,
        duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        counts=table_counts(),
        clock=clock.state(),
        sap_mock_reset=sap_ok,
    )


__all__ = ["SeedError", "reset_demo", "reset_sap_mock"]
