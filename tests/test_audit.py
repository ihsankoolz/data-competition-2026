import json
import sqlite3
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from services.api import clock
from services.api.audit import (
    AuditAction,
    append_audit,
    audit_field_edit,
    canonical_json,
    compute_hash,
    scrub,
    verify_chain,
)
from services.api.crypto import mask
from services.api.db import models as m
from services.api.db.models import GENESIS_HASH
from services.api.db.session import create_schema, make_engine, make_session_factory
from tests.db_helpers import sim_clock  # noqa: F401

pytestmark = pytest.mark.usefixtures("sim_clock")


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "audit.db")
    create_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine):
    return make_session_factory(engine)


def _add(factory, n=3, **kw):
    with factory.begin() as s:
        for i in range(n):
            append_audit(
                s,
                actor=kw.get("actor", "priya"),
                action=AuditAction.state_change,
                entity_type="request",
                entity_id="REQ-1",
                request_id="REQ-1",
                payload={"from": "DRAFT", "to": f"S{i}"},
            )


def test_chain_verifies_and_links(factory):
    _add(factory, 4)
    with factory() as s:
        rows = s.scalars(select(m.AuditLog).order_by(m.AuditLog.id)).all()
        assert [r.id for r in rows] == [1, 2, 3, 4]
        assert rows[0].prev_hash == GENESIS_HASH == "0" * 64
        for prev, row in zip(rows, rows[1:], strict=False):
            assert row.prev_hash == prev.hash
        res = verify_chain(s)
    assert res.ok and res.checked == 4 and res.first_broken_id is None


def test_empty_chain_is_ok(factory):
    with factory() as s:
        assert verify_chain(s).ok


def test_hash_is_sha256_of_prev_hash_plus_canonical_json(factory):
    import hashlib
    import json

    _add(factory, 1)
    with factory() as s:
        row = s.scalars(select(m.AuditLog)).one()
    content = {
        "id": row.id,
        "ts": row.ts,
        "actor": row.actor,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "request_id": row.request_id,
        "payload": json.loads(row.payload),
    }
    canon = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert row.hash == hashlib.sha256((GENESIS_HASH + canon).encode()).hexdigest()
    assert canon == canonical_json(content)
    assert row.hash == compute_hash(GENESIS_HASH, content)


def test_canonical_json_is_order_independent():
    assert canonical_json({"b": 1, "a": [2, {"d": 1, "c": 2}]}) == '{"a":[2,{"c":2,"d":1}],"b":1}'


def test_update_is_rejected_by_trigger(factory):
    _add(factory, 2)
    with factory.begin() as s, pytest.raises(DatabaseError, match="append-only"):
        s.execute(text("UPDATE audit_log SET actor = 'mallory' WHERE id = 1"))
    with factory() as s:
        assert verify_chain(s).ok


def test_delete_is_rejected_by_trigger(factory):
    _add(factory, 2)
    with factory.begin() as s, pytest.raises(DatabaseError, match="append-only"):
        s.execute(text("DELETE FROM audit_log WHERE id = 2"))
    with factory.begin() as s, pytest.raises(DatabaseError, match="append-only"):
        s.execute(text("DELETE FROM audit_log"))
    with factory() as s:
        assert len(s.scalars(select(m.AuditLog)).all()) == 2


def test_no_update_or_delete_in_application_code():
    import pathlib
    import re

    code = (pathlib.Path(m.__file__).parents[1] / "audit.py").read_text(encoding="utf-8").lower()
    assert not re.search(r"delete\s+from|\.delete\(|session\.delete", code)
    # the only UPDATE statement is the write lock on audit_head
    assert re.findall(r"update\s+(\w+)\s+set", code) == ["audit_head"]


def _drop_triggers(db_file):
    con = sqlite3.connect(db_file)
    con.execute("DROP TRIGGER audit_log_no_update")
    con.execute("DROP TRIGGER audit_log_no_delete")
    con.commit()
    return con


def test_tampering_with_content_is_detected(factory, engine):
    _add(factory, 5)
    con = _drop_triggers(engine.url.database)
    con.execute("UPDATE audit_log SET actor = 'mallory' WHERE id = 3")
    con.commit()
    con.close()
    with factory() as s:
        res = verify_chain(s)
    assert not res.ok and res.first_broken_id == 3
    assert "edited" in res.reason


def test_removed_middle_row_is_detected(factory, engine):
    _add(factory, 5)
    con = _drop_triggers(engine.url.database)
    con.execute("DELETE FROM audit_log WHERE id = 2")
    con.commit()
    con.close()
    with factory() as s:
        res = verify_chain(s)
    assert not res.ok and res.first_broken_id == 3


def test_truncated_tail_is_detected(factory, engine):
    _add(factory, 4)
    con = _drop_triggers(engine.url.database)
    con.execute("DELETE FROM audit_log WHERE id = 4")
    con.commit()
    con.close()
    with factory() as s:
        res = verify_chain(s)
    assert not res.ok and res.first_broken_id == 4 and "truncated" in res.reason


def test_recomputed_hash_after_edit_still_breaks_the_next_link(factory, engine):
    _add(factory, 3)
    con = _drop_triggers(engine.url.database)
    with factory() as s:
        row = s.get(m.AuditLog, 2)
        content = {
            "id": 2, "ts": row.ts, "actor": "mallory", "action": row.action,
            "entity_type": row.entity_type, "entity_id": row.entity_id,
            "request_id": row.request_id, "payload": {"from": "DRAFT", "to": "S1"},
        }  # fmt: skip
        new_hash = compute_hash(row.prev_hash, content)
    con.execute("UPDATE audit_log SET actor='mallory', hash=? WHERE id=2", (new_hash,))
    con.commit()
    con.close()
    with factory() as s:
        res = verify_chain(s)
    assert not res.ok and res.first_broken_id == 3


def test_timestamps_follow_the_simulated_clock(factory):
    _add(factory, 1)
    clock.advance(days=2, hours=3)
    _add(factory, 1)
    with factory() as s:
        r1, r2 = s.scalars(select(m.AuditLog).order_by(m.AuditLog.id)).all()
    assert r1.ts == clock.CLOCK_START.isoformat()
    assert r2.ts == (clock.CLOCK_START + timedelta(days=2, hours=3)).isoformat()
    assert r1.ts.endswith("+08:00")


def test_bank_values_are_masked_in_payloads(factory):
    with factory.begin() as s:
        append_audit(
            s,
            actor="priya",
            action=AuditAction.sap_call,
            entity_type="BusinessPartners",
            entity_id="V99999",
            payload={
                "body": {
                    "CardCode": "V99999",
                    "BPBankAccounts": [
                        {
                            "BankCode": "7171",
                            "AccountNo": "1234567890123",
                            "AccountName": "Secret Supplies Pte Ltd",
                            "BICSwiftCode": "DBSSSGSG",
                            "IBAN": "DE89370400440532013000",
                            "Country": "SG",
                        }
                    ],
                }
            },
        )
        audit_field_edit(
            s,
            actor="weijie",
            entity_type="bank_account",
            entity_id="V99999",
            field="AccountNo",
            old="1111222233334444",
            new="5555666677778888",
        )
    with factory() as s:
        rows = s.scalars(select(m.AuditLog)).all()
        text_dump = " ".join(r.payload for r in rows)
        assert verify_chain(s).ok
    for secret in ("1234567890123", "DE89370400440532013000", "Secret Supplies", "DBSSSGSG",
                   "1111222233334444", "5555666677778888", "7171"):  # fmt: skip
        assert secret not in text_dump
    assert "****0123" in text_dump  # last four digits survive for AccountNo
    assert "****8888" in text_dump
    assert '"Country":"SG"' in text_dump  # non-bank fields are untouched


def test_scrub_leaves_other_values_alone():
    assert scrub({"CardName": "Acme", "n": [1, {"IBAN": "DE89"}]}) == {
        "CardName": "Acme",
        "n": [1, {"IBAN": "****"}],
    }
    assert mask("1234567890") == "****7890" and mask("123") == "****" and mask(None) is None


def test_field_edit_records_old_and_new(factory):
    with factory.begin() as s:
        audit_field_edit(
            s,
            actor="amy",
            entity_type="request",
            entity_id="REQ-7",
            field="CreditLimit",
            old=1000,
            new=5000,
            request_id="REQ-7",
        )
    with factory() as s:
        row = s.scalars(select(m.AuditLog)).one()
    assert row.action == "field_edit" and row.request_id == "REQ-7"
    assert row.payload == '{"field":"CreditLimit","new":5000,"old":1000}'


def test_unknown_action_is_rejected(factory):
    with factory.begin() as s, pytest.raises(ValueError):
        append_audit(s, actor="x", action="made_up", entity_type="t", entity_id="1")


def test_rollback_leaves_no_row_and_no_gap(factory):
    _add(factory, 1)
    with pytest.raises(RuntimeError), factory.begin() as s:
        append_audit(s, actor="a", action="seed", entity_type="t", entity_id="1")
        raise RuntimeError("caller failed after auditing")
    _add(factory, 1)
    with factory() as s:
        assert [r.id for r in s.scalars(select(m.AuditLog).order_by(m.AuditLog.id))] == [1, 2]
        assert verify_chain(s).ok


def test_second_writer_waits_chain_cannot_fork(factory, engine):
    """Two sessions append at once: the second blocks on the head row, then continues the chain."""
    import threading

    _add(factory, 1)
    started = threading.Event()
    done = threading.Event()

    def writer_two():
        started.set()
        with factory.begin() as s2:
            append_audit(s2, actor="b", action="seed", entity_type="t", entity_id="2")
        done.set()

    with factory.begin() as s1:
        append_audit(s1, actor="a", action="seed", entity_type="t", entity_id="1")
        t = threading.Thread(target=writer_two)
        t.start()
        started.wait(2)
        assert not done.wait(0.5)  # blocked while writer one holds the write lock
    t.join(5)
    assert done.is_set()
    with factory() as s:
        ids = [(r.id, r.actor) for r in s.scalars(select(m.AuditLog).order_by(m.AuditLog.id))]
        assert [i for i, _ in ids] == [1, 2, 3]
        assert [a for _, a in ids][1:] == ["a", "b"]
        assert verify_chain(s).ok


def test_unique_prev_hash_blocks_a_fork(factory, engine):
    _add(factory, 2)
    con = sqlite3.connect(engine.url.database)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(
            "INSERT INTO audit_log (id, ts, actor, action, entity_type, entity_id, payload, "
            "prev_hash, hash) SELECT 99, ts, actor, action, entity_type, entity_id, payload, "
            "prev_hash, 'x' FROM audit_log WHERE id = 2"
        )
    con.close()


def test_insert_or_replace_cannot_overwrite_a_row(factory, engine):
    _add(factory, 3)
    con = sqlite3.connect(engine.url.database)  # a plain connection: recursive_triggers is OFF
    stmt = (
        "INSERT OR REPLACE INTO audit_log (id, ts, actor, action, entity_type, entity_id, "
        "payload, prev_hash, hash) VALUES (?, 't', 'mallory', 'seed', 'x', '1', '{}', ?, ?)"
    )
    for row_id in (1, 2, 3, None):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            con.execute(stmt, (row_id, "p" * 64, "h" * 64))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        con.execute(stmt.replace("INSERT OR REPLACE", "INSERT OR IGNORE"), (2, "p" * 64, "h" * 64))
    con.close()
    with factory() as s:
        assert [r.actor for r in s.scalars(select(m.AuditLog))] == ["priya"] * 3
        assert verify_chain(s).ok


def test_replace_is_also_blocked_through_the_engine(factory):
    _add(factory, 2)
    with pytest.raises(DatabaseError, match="append-only"), factory.begin() as s:
        s.execute(
            text(
                "INSERT OR REPLACE INTO audit_log (id, ts, actor, action, entity_type, "
                "entity_id, payload, prev_hash, hash) VALUES (1, 't', 'm', 'seed', 'x', '1', "
                "'{}', 'p', 'h')"
            )
        )


def test_scrub_masks_every_leaf_under_a_bank_key():
    out = scrub(
        {
            "IBAN": ["DE89370400440532013000", {"alt": "DE00111122223333"}],
            "AccountNo": {"value": "1234567890", "history": ["1111222233"]},
            "BankCode": 7171,
        }
    )
    text_out = json.dumps(out)
    for secret in (
        "DE89370400440532013000",
        "DE00111122223333",
        "1234567890",
        "1111222233",
        "7171",
    ):
        assert secret not in text_out
    assert out["IBAN"][0] == "****3000" and out["BankCode"] == "****"


@pytest.mark.parametrize(
    "path", ["AccountNo", "BPBankAccounts[0].AccountNo", "BPBankAccounts[1].IBAN", "IBAN[0]"]
)
def test_scrub_field_edit_paths_use_the_last_segment(path):
    out = scrub({"field": path, "old": "1111222233334444", "new": ["5555666677778888"]})
    assert out["field"] == path
    assert "1111222233334444" not in json.dumps(out) and "5555666677778888" not in json.dumps(out)
    assert out["old"] == "****4444"


@pytest.mark.parametrize(
    "key",
    ["account_number", "Account No", "iban_number", "AccountNumber", "acct_no", "BIC", "swift_code",
     "bank_code", "BICSwiftCode"],
)  # fmt: skip
def test_scrub_masks_key_variants(key):
    out = scrub({key: "9876543210123"})
    assert "9876543210123" not in json.dumps(out)


def test_scrub_does_not_mask_unrelated_keys():
    data = {"CardName": "Acme", "BankCountry": "SG", "Country": "SG", "BPBankAccounts": []}
    assert scrub(data) == data
