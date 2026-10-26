"""History check: GET /audit/verify and `make tamper-demo` (services/api/tamper_demo.py)."""

from __future__ import annotations

import hashlib
import io
import sqlite3
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from services.api import tamper_demo
from services.api.audit import VerifyResult, plain_message
from services.api.db.seed import seed_database
from services.api.db.session import dispose_default
from services.api.main import app

OWNS_APP_DB = True  # see tests/conftest.py
FIXTURES = "data/fixtures/seasonal_trend"
AMY = {"X-Acting-User": "amy"}


@pytest.fixture(scope="module")
def seeded_db(tmp_path_factory) -> Path:
    """One fresh seed, built once. Tests that change it work on their own copy."""
    mp = pytest.MonkeyPatch()
    mp.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    path = tmp_path_factory.mktemp("verify") / "seed.db"
    seed_database(FIXTURES, path)
    yield path
    mp.undo()


@pytest.fixture
def client(seeded_db, tmp_path, monkeypatch):
    """The API on its own copy of the fresh seed."""
    db = tmp_path / "app.db"
    tamper_demo._copy_database(seeded_db, db)
    monkeypatch.setenv("APP_DB_PATH", str(db))
    dispose_default()
    c = TestClient(app)
    c.db_path = db  # type: ignore[attr-defined]
    yield c
    dispose_default()


def _tamper(db: Path, entry: int) -> None:
    dispose_default()  # let go of the file, then edit it behind the API's back
    conn = sqlite3.connect(db)
    conn.execute("DROP TRIGGER audit_log_no_update")
    conn.execute("UPDATE audit_log SET actor = 'mallory' WHERE id = ?", (entry,))
    conn.commit()
    conn.close()


def test_verify_ok_on_a_fresh_seed(client):
    r = client.get("/audit/verify", headers=AMY)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["checked"] >= 1
    assert body["first_broken_id"] is None
    assert body["message"] == f"All {body['checked']} entries intact." or body["checked"] == 1
    assert body["reason"] is None


def test_verify_counts_new_entries_and_is_open_to_every_persona(client):
    before = client.get("/audit/verify", headers=AMY).json()["checked"]
    r = client.post(
        "/requests",
        headers=AMY,
        json={
            "domain": "customer",
            "entity": "SPD",
            "country": "SG",
            "fields": {"CardName": "History Check Pte Ltd", "Country": "SG"},
        },
    )
    assert r.status_code in (200, 201), r.text
    for who in ("amy", "weijie", "priya", "marcus"):
        body = client.get("/audit/verify", headers={"X-Acting-User": who}).json()
        assert body["ok"] is True
        assert body["checked"] > before


def test_verify_needs_to_know_who_is_asking(client):
    assert client.get("/audit/verify").status_code == 400
    assert client.get("/audit/verify", headers={"X-Acting-User": "nobody"}).status_code == 403


def test_verify_reports_the_broken_entry_in_plain_words(client):
    ok = client.get("/audit/verify", headers=AMY).json()
    assert ok["ok"] is True
    # Make the log longer so the broken entry is not the first one.
    client.post(
        "/requests",
        headers=AMY,
        json={
            "domain": "customer",
            "entity": "SPD",
            "country": "SG",
            "fields": {"CardName": "Tamper Test Pte Ltd", "Country": "SG"},
        },
    )
    total = client.get("/audit/verify", headers=AMY).json()["checked"]
    assert total >= 2
    _tamper(client.db_path, total)

    body = client.get("/audit/verify", headers=AMY).json()
    assert body["ok"] is False
    assert body["first_broken_id"] == total
    assert body["checked"] == total - 1
    assert (
        body["message"] == f"Entry {total} was changed or removed. Everything before it is intact."
    )
    # The technical reason is kept apart from the sentence people read.
    assert "hash" in body["reason"]
    assert "hash" not in body["message"]


def test_plain_message_wording():
    assert plain_message(VerifyResult(ok=True, checked=52)) == "All 52 entries intact."
    assert (
        plain_message(VerifyResult(ok=False, checked=9, first_broken_id=10, reason="x"))
        == "Entry 10 was changed or removed. Everything before it is intact."
    )
    assert plain_message(
        VerifyResult(ok=False, checked=0, first_broken_id=1, reason="x")
    ).startswith("Entry 1 was changed or removed.")


# ------------------------------------------------------------------ make tamper-demo


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_tamper_demo_on_a_copy_leaves_the_source_alone(client, seeded_db):
    # Give the source a longer history, close it cleanly, then run the demo against it.
    client.post(
        "/requests",
        headers=AMY,
        json={
            "domain": "customer",
            "entity": "SPD",
            "country": "SG",
            "fields": {"CardName": "Demo Source Pte Ltd", "Country": "SG"},
        },
    )
    dispose_default()
    source = client.db_path
    conn = sqlite3.connect(source)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    before_bytes = _sha(source)

    out = io.StringIO()
    code = tamper_demo.run(source=source, out=out)
    text = out.getvalue()

    assert code == 0, text
    assert "Before: all " in text and " entries intact" in text
    assert "After: the check fails." in text
    assert "Changed entry" in text
    assert text.index("Before:") < text.index("After:")
    assert _sha(source) == before_bytes  # the source file's bytes are unchanged
    assert not list(source.parent.glob("tamper-demo-*"))


def test_tamper_demo_seeds_a_temporary_database_when_there_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    missing = tmp_path / "does-not-exist.db"
    out = io.StringIO()
    code = tamper_demo.run(source=missing, fixtures=Path(FIXTURES), out=out)
    text = out.getvalue()
    assert code == 0, text
    assert "Before: all " in text
    assert "approval" in text
    assert "After: the check fails." in text
    assert not missing.exists()


def test_tamper_demo_main_exit_code(seeded_db, tmp_path, capsys):
    db = tmp_path / "copy.db"
    tamper_demo._copy_database(seeded_db, db)
    assert tamper_demo.main(["--source", str(db)]) == 0
    assert "entries intact" in capsys.readouterr().out
