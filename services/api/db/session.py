"""Engine and session factory for the app database (SQLite, `data/app.db`).

The path is configurable so tests can use temporary files: pass `db_path` to `make_engine`, or
set `APP_DB_PATH`. Everything else asks `get_engine()` / `get_session_factory()` for the default.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "app.db"
DB_PATH_ENV = "APP_DB_PATH"


def default_db_path() -> Path:
    env = os.environ.get(DB_PATH_ENV)
    return Path(env) if env else DEFAULT_DB_PATH


def make_engine(db_path: str | Path | None = None) -> Engine:
    """Create an engine for a SQLite file (parent folder is created if needed)."""
    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        # Error messages must never carry bound values: they can be bank numbers (domain rule 5).
        hide_parameters=True,
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection: sqlite3.Connection, _record: Any) -> None:
        # Take over transaction control from pysqlite so BEGIN is emitted when SQLAlchemy
        # says so (SQLAlchemy docs, "Serializable isolation / Savepoints / Transactional DDL").
        dbapi_connection.isolation_level = None
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        # Belt and braces for the audit log: REPLACE conflicts also fire DELETE triggers.
        cur.execute("PRAGMA recursive_triggers=ON")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Any) -> None:
        conn.exec_driver_sql("BEGIN")

    return engine


_default_engine: Engine | None = None
_default_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _default_engine
    if _default_engine is None:
        _default_engine = make_engine()
    return _default_engine


def get_session_factory() -> sessionmaker[Session]:
    global _default_factory
    if _default_factory is None:
        _default_factory = make_session_factory(get_engine())
    return _default_factory


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def dispose_default() -> None:
    """Forget the default engine (tests, and `reset-demo` when the path changes)."""
    global _default_engine, _default_factory
    if _default_engine is not None:
        _default_engine.dispose()
    _default_engine = None
    _default_factory = None


@contextmanager
def session_scope(factory: sessionmaker[Session] | None = None) -> Iterator[Session]:
    """One transaction: commit on success, roll back on error."""
    with (factory or get_session_factory()).begin() as session:
        yield session


def create_schema(engine: Engine) -> None:
    """Create all tables, the audit triggers and the audit head row."""
    from services.api.db.models import Base

    Base.metadata.create_all(engine)


def reset_schema(engine: Engine) -> None:
    """Drop every table in the database file (even ones this code no longer knows), recreate."""
    from sqlalchemy import MetaData

    existing = MetaData()
    existing.reflect(bind=engine)
    existing.drop_all(bind=engine)
    create_schema(engine)
