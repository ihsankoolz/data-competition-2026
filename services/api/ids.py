"""Human-readable ids (REQ-0007, TSK-0012, ...) from counters kept in `app_state`."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def next_number(session: Session, name: str) -> int:
    """Next value of counter `name`. The UPSERT takes SQLite's write lock, so two requests
    can never get the same number."""
    key = f"seq:{name}"
    session.execute(
        text(
            "INSERT INTO app_state (key, value) VALUES (:k, '1') "
            "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1"
        ),
        {"k": key},
    )
    row = session.execute(text("SELECT value FROM app_state WHERE key = :k"), {"k": key})
    return int(row.scalar_one())


def next_id(session: Session, name: str, prefix: str, width: int = 4) -> str:
    return f"{prefix}-{next_number(session, name):0{width}d}"
