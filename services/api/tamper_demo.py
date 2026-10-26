"""`make tamper-demo`: show that the history log notices an edit, on a throwaway copy.

1. Copy `data/app.db` to a temporary file (or, if it does not exist, seed a temporary database
   from the demo fixtures and add a few sample entries).
2. Check the chain on the copy: it is intact.
3. On the COPY only, switch off the "no updates" rule and change one field of one entry.
4. Check again: the check now fails at that entry.
5. Delete the copy. The real database is opened read-only and is never written.

Exit code 0 means the demo behaved as expected; non-zero means the check failed to notice.
This is a command-line demo only. There is deliberately no way to do this from the app.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from cryptography.fernet import Fernet

from services.api.audit import AuditAction, append_audit, plain_message, verify_chain
from services.api.crypto import KEY_ENV
from services.api.db.seed import seed_database
from services.api.db.session import (
    REPO_ROOT,
    make_engine,
    make_session_factory,
)

DEFAULT_SOURCE = REPO_ROOT / "data" / "app.db"
DEFAULT_FIXTURES = REPO_ROOT / "data" / "fixtures" / "seasonal_trend"
NO_UPDATE_TRIGGER = "audit_log_no_update"


def _verify(db_path: Path):
    engine = make_engine(db_path)
    try:
        with make_session_factory(engine)() as session:
            return verify_chain(session)
    finally:
        engine.dispose()


def _copy_database(source: Path, target: Path) -> None:
    """Copy through SQLite's backup API, so the newest committed rows (which may still sit in
    the write-ahead file) are included. The source is opened read-only."""
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


@contextmanager
def _key_for_seeding() -> Iterator[None]:
    """Seeding encrypts bank details and needs a key. A throwaway database can use a throwaway
    key, so the demo runs even where .env is not loaded."""
    had_key = bool(os.environ.get(KEY_ENV, "").strip())
    if not had_key:
        os.environ[KEY_ENV] = Fernet.generate_key().decode()
    try:
        yield
    finally:
        if not had_key:
            os.environ.pop(KEY_ENV, None)


def _seed_sample_copy(target: Path, fixtures: Path) -> None:
    """A fresh seed holds one entry, which makes a poor demo: add a small sample history."""
    with _key_for_seeding():
        seed_database(fixtures, target)
    engine = make_engine(target)
    try:
        with make_session_factory(engine).begin() as session:
            story = [
                ("amy", AuditAction.state_change, "request", {"summary": "Submitted for approval"}),
                ("weijie", AuditAction.approval, "approval_task", {"summary": "Finance approved"}),
                ("huimin", AuditAction.approval, "approval_task", {"summary": "Approved"}),
                ("priya", AuditAction.state_change, "request", {"summary": "Published to SAP"}),
            ]
            for actor, action, entity_type, payload in story:
                append_audit(
                    session,
                    actor=actor,
                    action=action,
                    entity_type=entity_type,
                    entity_id="REQ-DEMO-1",
                    request_id="REQ-DEMO-1",
                    payload=payload,
                )
    finally:
        engine.dispose()


def _pick_entry(conn: sqlite3.Connection) -> sqlite3.Row:
    """A recognisable entry: an approval from the middle of the log, else any non-first row."""
    for action in (AuditAction.approval.value, AuditAction.state_change.value):
        rows = conn.execute(
            "SELECT id, actor, action, request_id FROM audit_log WHERE action = ? ORDER BY id",
            (action,),
        ).fetchall()
        if rows:
            return rows[len(rows) // 2]
    return conn.execute(
        "SELECT id, actor, action, request_id FROM audit_log ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _name_of(conn: sqlite3.Connection, user_id: str) -> str:
    try:
        row = conn.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
    except sqlite3.Error:
        row = None
    return row[0] if row else user_id


def _tamper(copy: Path) -> tuple[int, str]:
    """Change who made one entry, on the copy only. Returns (entry number, plain description).
    Only the actor is touched, so no bank data is ever involved."""
    conn = sqlite3.connect(copy)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    try:
        row = _pick_entry(conn)
        old = row["actor"]
        new = "amy" if old != "amy" else "priya"
        old_name, new_name = _name_of(conn, old), _name_of(conn, new)
        conn.execute(f"DROP TRIGGER IF EXISTS {NO_UPDATE_TRIGGER}")
        conn.execute("UPDATE audit_log SET actor = ? WHERE id = ?", (new, row["id"]))
        kind = {"approval": "an approval", "state_change": "a status change"}.get(
            row["action"], "an entry"
        )
        on = f" on {row['request_id']}" if row["request_id"] else ""
        what = (
            f"Changed entry {row['id']} ({kind} by {old_name}{on}): it now says {new_name} did it."
        )
        return int(row["id"]), what
    finally:
        conn.close()


def run(
    source: Path | None = None,
    fixtures: Path | None = None,
    out: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    source = Path(source) if source is not None else DEFAULT_SOURCE
    fixtures = Path(fixtures) if fixtures is not None else DEFAULT_FIXTURES

    with tempfile.TemporaryDirectory(prefix="tamper-demo-", ignore_cleanup_errors=True) as tmp:
        copy = Path(tmp) / "copy.db"
        if source.exists():
            print(
                f"Working on a throwaway copy of {source.name}. The real file is not touched.",
                file=out,
            )
            _copy_database(source, copy)
        else:
            print(
                f"{source.name} does not exist here, so the demo seeds a throwaway database "
                "from the demo data instead.",
                file=out,
            )
            _seed_sample_copy(copy, fixtures)

        before = _verify(copy)
        if not before.ok:
            print(f"Before: the check already fails. {plain_message(before)}", file=out)
            return 2
        print(f"Before: all {before.checked} entries intact", file=out)

        entry, what = _tamper(copy)
        print(what, file=out)

        after = _verify(copy)
        if after.ok or after.first_broken_id != entry:
            print("After: the check did NOT notice the change. That is a bug.", file=out)
            return 1
        print(f"After: the check fails. {plain_message(after)}", file=out)
        print("This is why the history can be trusted: any edit leaves a visible break.", file=out)
    print("The throwaway copy is deleted.", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Show that the history check notices an edit.")
    parser.add_argument("--source", default=None, help="database to copy (default data/app.db)")
    parser.add_argument("--fixtures", default=None, help="fixtures to seed from if no database")
    args = parser.parse_args(argv)
    return run(args.source, args.fixtures)


if __name__ == "__main__":
    sys.exit(main())
