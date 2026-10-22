"""Seed loader: `make reset-demo` runs this.

    uv run python -m services.api.db.seed --fixtures data/fixtures/seasonal_trend [--db data/app.db]

Reloads the database in place (one transaction, through a normal engine): drops and recreates
every table (with the audit-log triggers), loads the fixture files and writes the first audit
row. Running it twice gives the same database. Missing files, missing columns, unreadable
values and a missing encryption key are all caught before anything is dropped. The running API
uses `reload_in_place` too (`POST /admin/reset-demo`, D-016).

Fixture layout is the contract in D-015 (it mirrors data-spec §10). Only the files listed in
`FILES` are read. `customers_golden.csv` and everything under `ground_truth/` are ground truth
for evaluation and are never opened here.

HOW TO CHANGE A COLUMN MAPPING: every file's columns are declared once, in the `FILES` table
below (`file column -> model attribute, converter`). If a real fixture file uses a different
header or format, fix the one line for that column.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, get_args

from sqlalchemy import Engine, MetaData, func, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.api import clock
from services.api.audit import AuditAction, append_audit
from services.api.crypto import EncryptionKeyError, require_key
from services.api.db import models as m
from services.api.db.session import IMMEDIATE_OPTION, default_db_path, make_engine
from services.api.schemas import Role


class SeedError(Exception):
    """Fixture problem. The message says which file, row and column."""


# ---------------------------------------------------------------- converters


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


def to_str(v: Any) -> str | None:
    return None if _blank(v) else str(v).strip()


def to_int(v: Any) -> int | None:
    return None if _blank(v) else int(float(str(v).strip()))


def to_float(v: Any) -> float | None:
    return None if _blank(v) else float(str(v).strip())


def to_bool(v: Any) -> bool | None:
    if _blank(v):
        return None
    t = str(v).strip().lower()
    if t in {"true", "1", "yes", "y"}:
        return True
    if t in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"not a boolean: {v!r}")


def to_date(v: Any) -> date | None:
    return None if _blank(v) else date.fromisoformat(str(v).strip()[:10])


def to_datetime(v: Any) -> datetime | None:
    if _blank(v):
        return None
    t = str(v).strip().replace("Z", "+00:00")
    return datetime.fromisoformat(t)


def to_pipe_list(v: Any) -> list[str]:
    return [] if _blank(v) else [p.strip() for p in str(v).split("|") if p.strip()]


def to_list(v: Any) -> list[str]:
    """JSON arrays, or pipe/semicolon separated text, to a list of strings."""
    if _blank(v):
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    t = str(v).strip()
    if t.startswith("["):
        return [str(x) for x in json.loads(t)]
    return [p.strip() for p in t.replace(";", "|").split("|") if p.strip()]


def to_address_list(v: Any) -> str | None:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return to_str(v)


# ---------------------------------------------------------------- file specs


@dataclass(frozen=True)
class Col:
    src: str  # header / key in the file
    dest: str  # model attribute
    conv: Callable[[Any], Any] = to_str
    required: bool = True  # the column must exist in the file (values may still be blank)


def _c(
    name: str, conv: Callable[[Any], Any] = to_str, *, req: bool = True, dest: str | None = None
):
    return Col(name, dest or name, conv, req)


@dataclass(frozen=True)
class FileSpec:
    filename: str
    table: str
    model: type[m.Base]
    cols: tuple[Col, ...]
    kind: str = "csv"  # csv | jsonl
    extra_to: str | None = None  # unmapped columns are stored as JSON in this attribute


BP_COLS = (
    _c("CardCode"),
    _c("CardName"),
    _c("CardForeignName", req=False),
    _c("CardType"),
    _c("GroupCode", to_int, req=False),
    _c("FederalTaxID", req=False),
    _c("Currency", req=False),
    _c("PayTermsGrpCode", to_int, req=False),
    _c("CreditLimit", to_float, req=False),
    _c("EmailAddress", req=False),
    _c("Phone1", req=False),
    _c("City", req=False),
    _c("Country", req=False),
    _c("U_Entity", req=False),
    _c("CreateDate", to_date, req=False),
    _c("CreatedBy", req=False),
)

BANK_COLS = (
    _c("BankCode", dest="BankCode"),
    _c("AccountNo"),
    _c("AccountName"),
    _c("BICSwiftCode"),
    _c("IBAN"),
    _c("BankCountry"),
)

_TXN_COLS = (
    _c("doc_num"),
    _c("card_code"),
    _c("entity"),
    _c("country"),
    _c("item_code"),
    _c("qty", to_float),
    _c("unit_price_usd", to_float, req=False),
    _c("doc_date", to_date),
    _c("po_ref", req=False),
    _c("source_email_id", req=False),
)

FILES: dict[str, FileSpec] = {
    "users": FileSpec(
        "users.csv",
        "users",
        m.User,
        (
            _c("user_id"),
            _c("name"),
            _c("title"),
            _c("roles", to_pipe_list),
            _c("entity"),
            _c("country"),
            _c("backup_for", req=False),
        ),
    ),
    "bp_records": FileSpec("bp_records.csv", "business_partners", m.BusinessPartner, BP_COLS),
    "vendors": FileSpec(
        "vendors.csv", "business_partners", m.BusinessPartner, BP_COLS + BANK_COLS
    ),  # bank columns are split off into bank_accounts
    "items": FileSpec(
        "items.csv",
        "items",
        m.Item,
        (
            _c("ItemCode"),
            _c("ItemName"),
            _c("ItemType", req=False),
            _c("ItemsGroupCode", to_int, req=False),
            _c("PurchaseItem", req=False),
            _c("SalesItem", req=False),
            _c("InventoryItem", req=False),
            _c("U_IVD", req=False),
            _c("product_family", req=False),
            _c("entity", req=False),
            _c("sales_unit", req=False),
            _c("unit_price_usd", to_float, req=False),
        ),
    ),
    "item_registrations": FileSpec(
        "item_registrations.csv",
        "item_registrations",
        m.ItemRegistration,
        (
            _c("item_code"),
            _c("country"),
            _c("is_ivd", to_bool),
            _c("risk_class", req=False),
            _c("reg_no", req=False),
            _c("assumed_format", to_bool, req=False),
            _c("reg_holder_entity", req=False),
            _c("issue_date", to_date, req=False),
            _c("expiry_date", to_date, req=False),
            _c("status"),
        ),
    ),
    "orders": FileSpec("orders.csv", "orders", m.Order, _TXN_COLS),
    "enquiries": FileSpec(
        "enquiries.csv",
        "enquiries",
        m.Enquiry,
        _TXN_COLS + (_c("kind"), _c("converted_doc_num", req=False)),
    ),
    "dirty_demand": FileSpec(
        "dirty_demand.csv",
        "dirty_demand",
        m.DirtyDemand,
        (
            _c("doc_num", req=False),
            _c("card_code"),
            _c("entity", req=False),
            _c("country", req=False),
            _c("item_code", req=False),
            _c("qty", to_float),
            _c("unit_price_usd", to_float, req=False),
            _c("doc_date", to_date),
            _c("po_ref", req=False),
            _c("source_email_id", req=False),
            _c("leak_source"),
        ),
    ),
    "mdm_history": FileSpec(
        "mdm_requests_history.csv",
        "mdm_history",
        m.MdmHistory,
        (
            _c("req_id"),
            _c("domain"),
            _c("entity"),
            _c("country"),
            _c("requestor"),
            _c("submitted_at", to_datetime),
            _c("keyed_at", to_datetime),
            _c("bounced_for_missing_fields", to_bool),
            _c("bounce_count", to_int),
        ),
        extra_to="extra",
    ),
    "emails": FileSpec(
        "emails.jsonl",
        "emails",
        m.Email,
        (
            _c("email_id"),
            _c("received_at", to_datetime),
            _c("from_name", req=False),
            _c("from_address"),
            _c("to", to_address_list, req=False, dest="to_address"),
            _c("subject"),
            _c("body"),
            _c("attachments", to_list, req=False),
            _c("thread_id", req=False),
        ),
        kind="jsonl",
    ),
}

CARD_TYPES = {"cCustomer", "cSupplier", "cLid"}
ROLES = set(get_args(Role))
SKIPPED_GROUND_TRUTH = ("customers_golden.csv", "ground_truth/")  # documented, never opened


# ---------------------------------------------------------------- reading


def _read_rows(path: Path, kind: str) -> tuple[list[str], list[dict[str, Any]]]:
    if kind == "jsonl":
        rows = []
        keys: dict[str, None] = {}
        with path.open(encoding="utf-8") as fh:
            for n, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except ValueError as exc:
                    raise SeedError(f"{path.name} line {n}: not valid JSON ({exc})") from None
                if not isinstance(obj, dict):
                    raise SeedError(f"{path.name} line {n}: expected a JSON object")
                keys.update(dict.fromkeys(obj))
                rows.append(obj)
        return list(keys), rows
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def load_file(fixtures: Path, spec: FileSpec) -> list[dict[str, Any]]:
    """Read one fixture file into rows keyed by model attribute."""
    path = fixtures / spec.filename
    header, raw_rows = _read_rows(path, spec.kind)
    missing = [c.src for c in spec.cols if c.required and c.src not in header]
    if missing:
        raise SeedError(
            f"{spec.filename}: missing column(s) {', '.join(missing)}. "
            f"Columns found: {', '.join(header) or '(none)'}. "
            "Fix the mapping in services/api/db/seed.py (FILES) or the fixture."
        )
    known = {c.src for c in spec.cols}
    out: list[dict[str, Any]] = []
    for n, raw in enumerate(raw_rows, start=2 if spec.kind == "csv" else 1):
        row: dict[str, Any] = {}
        for col in spec.cols:
            try:
                row[col.dest] = col.conv(raw.get(col.src))
            except (ValueError, TypeError) as exc:
                raise SeedError(
                    f"{spec.filename} row {n}, column {col.src}: cannot read "
                    f"{raw.get(col.src)!r} ({exc})"
                ) from None
        if spec.extra_to:
            row[spec.extra_to] = {k: raw[k] for k in raw if k not in known and raw[k] != ""}
        out.append(row)
    return out


def check_files_exist(fixtures: Path) -> None:
    if not fixtures.is_dir():
        raise SeedError(f"Fixtures folder not found: {fixtures}")
    missing = [s.filename for s in FILES.values() if not (fixtures / s.filename).is_file()]
    if missing:
        raise SeedError(
            f"Missing fixture file(s) in {fixtures}: {', '.join(missing)}. "
            "Seeding stopped; the database was not changed."
        )


# ---------------------------------------------------------------- seeding


@dataclass
class Loaded:
    tables: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    bank_rows: list[dict[str, Any]] = field(default_factory=list)


def _validate(data: Loaded) -> None:
    for row in data.tables["business_partners"]:
        if row["CardType"] not in CARD_TYPES:
            raise SeedError(
                f"business partner {row['CardCode']}: CardType {row['CardType']!r} is not one of "
                f"{sorted(CARD_TYPES)}"
            )
    for row in data.tables["users"]:
        bad = [r for r in row["roles"] if r not in ROLES]
        if bad:
            raise SeedError(f"user {row['user_id']}: unknown role(s) {bad}; known: {sorted(ROLES)}")
    ids = {r["user_id"] for r in data.tables["users"]}
    for row in data.tables["users"]:
        if row["backup_for"] and row["backup_for"] not in ids:
            raise SeedError(
                f"user {row['user_id']}: backup_for {row['backup_for']!r} is not a user"
            )


def read_fixtures(fixtures: Path) -> Loaded:
    data = Loaded()
    bps: list[dict[str, Any]] = []
    for key, spec in FILES.items():
        rows = load_file(fixtures, spec)
        if key == "vendors":
            bank_dests = {c.dest for c in BANK_COLS}
            for r in rows:
                bank = {k: r.pop(k) for k in bank_dests}
                if any(
                    bank[k]
                    for k in ("BankCode", "AccountNo", "AccountName", "BICSwiftCode", "IBAN")
                ):
                    data.bank_rows.append({"CardCode": r["CardCode"], **bank})
            bps.extend(rows)
        elif key == "bp_records":
            bps.extend(rows)
        else:
            data.tables[spec.table] = rows
    data.tables["business_partners"] = bps
    _validate(data)
    return data


def _users_in_dependency_order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    done: set[str] = set()
    ordered: list[dict[str, Any]] = []
    pending = list(rows)
    while pending:
        ready = [r for r in pending if not r["backup_for"] or r["backup_for"] in done]
        if not ready:
            raise SeedError("users.csv: backup_for forms a cycle")
        ordered.extend(ready)
        done.update(r["user_id"] for r in ready)
        pending = [r for r in pending if r not in ready]
    return ordered


def reload_in_place(engine: Engine, data: Loaded, fixtures_dir: Path) -> dict[str, int]:
    """Replace the whole database content with the fixtures, through a live engine.

    One transaction: every table (including the append-only audit tables, whose triggers go
    with them) is dropped and recreated, the fixtures are bulk-inserted and the first audit row
    is written. Other connections keep reading the old, complete database until the commit and
    see the new, complete one afterwards: nobody can see a half-loaded database. No file is
    replaced, so an open session or connection held by the running API does not get in the way
    (the old temp-file-and-`os.replace` approach fails on Windows).
    """
    # BEGIN IMMEDIATE: take the write lock first and wait for it (busy_timeout). A deferred
    # transaction would read (reflect) and then fail at DROP TABLE with "database is locked"
    # whenever a write was in flight.
    with engine.execution_options(**{IMMEDIATE_OPTION: True}).begin() as conn:
        existing = MetaData()
        existing.reflect(bind=conn)
        existing.drop_all(bind=conn)  # a table this code no longer knows is dropped too
        m.Base.metadata.create_all(conn)  # audit triggers and the audit_head row come with it
        with Session(bind=conn) as session:
            try:
                # Core inserts on the connection: one executemany per table. The ORM bulk path
                # splits rows by which values are None and issues thousands of statements.
                bulk = session.connection()
                bulk.execute(
                    insert(m.User.__table__), _users_in_dependency_order(data.tables["users"])
                )
                for table, model in (
                    ("business_partners", m.BusinessPartner),
                    ("items", m.Item),
                    ("item_registrations", m.ItemRegistration),
                    ("orders", m.Order),
                    ("enquiries", m.Enquiry),
                    ("dirty_demand", m.DirtyDemand),
                    ("mdm_history", m.MdmHistory),
                    ("emails", m.Email),
                ):
                    if data.tables[table]:
                        bulk.execute(insert(model.__table__), data.tables[table])
                if data.bank_rows:
                    bulk.execute(insert(m.BankAccount.__table__), data.bank_rows)
            except IntegrityError as exc:
                raise SeedError(f"Fixture data breaks a database rule: {exc.orig}") from None

            counts = {
                name: session.scalar(select(func.count()).select_from(model)) or 0
                for name, model in _COUNT_TABLES.items()
            }
            clock.persist(session, clock.CLOCK_START)
            append_audit(
                session,
                actor="system",
                action=AuditAction.seed,
                entity_type="database",
                entity_id="app.db",
                payload={"fixtures": fixtures_dir.name, "rows": counts},
            )
            session.flush()
    counts["audit_log"] = 1
    for name in ("requests", "approval_tasks", "notifications", "dedup_decisions"):
        counts[name] = 0
    return counts


def seed_database(fixtures: str | Path, db_path: str | Path | None = None) -> dict[str, int]:
    """Rebuild the database from fixtures. Returns row counts per table.

    Everything that can fail on the way in (missing files, bad columns, no encryption key) is
    checked before the database is touched. The reload itself is one transaction, so a failure
    leaves the existing content as it was.
    """
    fixtures_dir = Path(fixtures)
    check_files_exist(fixtures_dir)
    require_key()  # bank accounts are encrypted: fail before touching the database
    data = read_fixtures(fixtures_dir)

    target = Path(db_path) if db_path is not None else default_db_path()
    engine = make_engine(target)
    try:
        counts = reload_in_place(engine, data, fixtures_dir)
    finally:
        engine.dispose()
    clock.reset()  # the in-memory clock follows the database
    return counts


_COUNT_TABLES: dict[str, type[m.Base]] = {
    "users": m.User,
    "business_partners": m.BusinessPartner,
    "bank_accounts": m.BankAccount,
    "items": m.Item,
    "item_registrations": m.ItemRegistration,
    "orders": m.Order,
    "enquiries": m.Enquiry,
    "dirty_demand": m.DirtyDemand,
    "mdm_history": m.MdmHistory,
    "emails": m.Email,
}


def _reset_via_running_api() -> dict[str, int] | None:
    """If the API is running, ask it to reset (it also resets its clock, duplicate index and the
    SAP mock). None if it is not reachable."""
    import httpx

    url = os.environ.get("API_URL", "http://localhost:8000").rstrip("/") + "/admin/reset-demo"
    try:
        resp = httpx.post(url, timeout=60)
    except (httpx.ConnectError, httpx.ConnectTimeout):
        return None  # nothing is listening: safe to reload the file directly
    except httpx.HTTPError as exc:
        # The API is there but did not answer in time. A reset may still be running in it, and
        # a second one from here would overlap it, so stop instead of falling back.
        raise SeedError(
            f"The running API did not answer ({type(exc).__name__}); its reset may still be "
            "running. Wait a moment, then run `make reset-demo` again."
        ) from None
    if resp.status_code != 200:
        raise SeedError(f"The running API could not reset the demo: {resp.text[:300]}")
    body = resp.json()
    print(
        f"reset by the running API in {body['duration_ms']:.0f} ms; "
        f"SAP mock reset: {body['sap_mock_reset']}"
    )
    return body["counts"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reset the app database from fixture files.")
    parser.add_argument("--fixtures", required=True, help="e.g. data/fixtures/seasonal_trend")
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite file. Given: reload that file directly. Not given (what `make reset-demo` "
        "does): ask the running API (same code path as the Reset demo button), and if it is "
        "not running reload data/app.db directly.",
    )
    args = parser.parse_args(argv)
    try:
        counts = _reset_via_running_api() if args.db is None else None
        if counts is None:
            counts = seed_database(args.fixtures, args.db)
            if args.db is None:
                from services.api.reset import reset_sap_mock

                reset_sap_mock(timeout=1.0)  # best effort: the mock may not be running
    except (SeedError, EncryptionKeyError) as exc:
        print(f"seed failed: {exc}", file=sys.stderr)
        return 1
    width = max(len(k) for k in counts)
    for name, n in counts.items():
        print(f"{name:<{width}}  {n:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
