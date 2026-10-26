"""Clean-up queue: the Likely pairs behind the after-merge view, and Priya's review of them."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select

from ds.analytics import cleanup
from ds.analytics.golden import CACHE_PATH as GOLDEN_CACHE
from ds.analytics.golden import _read_cache as read_golden
from ds.analytics.golden import likely_links
from services.api import clock
from services.api.audit import verify_chain
from services.api.db import models as m
from services.api.db.session import dispose_default, session_scope
from services.api.main import app

OWNS_APP_DB = True  # see tests/conftest.py
ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "data" / "fixtures" / "seasonal_trend"


def H(user: str) -> dict[str, str]:
    return {"X-Acting-User": user}


def _master() -> dict[str, dict[str, str]]:
    out = {}
    for name in ("bp_records.csv", "vendors.csv"):
        with open(FIX / name, encoding="utf-8", newline="") as fh:
            out |= {r["CardCode"]: r for r in csv.DictReader(fh)}
    return out


# ------------------------------------------------------------------------- data (ds)


def test_cache_components_equal_the_golden_multi_record_clusters():
    pairs = cleanup.read_cache().pairs
    ours = {c.cluster_id: set(c.codes) for c in cleanup.clusters(pairs)}
    golden: dict[str, set[str]] = {}
    for code, gid in read_golden(GOLDEN_CACHE).items():
        golden.setdefault(gid, set()).add(code)
    multi = {gid: codes for gid, codes in golden.items() if len(codes) > 1}
    assert ours == multi
    assert len(ours) == 168


def test_no_pair_mixes_card_types_or_countries():
    master = _master()
    for p in cleanup.read_cache().pairs:
        a, b = master[p.a], master[p.b]
        assert a["CardType"] == b["CardType"] == "cCustomer"  # rule 2
        assert a["Country"] == b["Country"]  # rule 3
        assert p.a < p.b and p.query in (p.a, p.b)
        assert p.tax_id_match or p.score >= 0.92
        assert p.reasons


def test_recomputing_from_the_master_files_equals_the_cache(tmp_path):
    """No ground truth needed: a folder with only the master files gives the committed cache."""
    for name in ("bp_records.csv", "vendors.csv"):
        shutil.copy(FIX / name, tmp_path / name)
    fresh = cleanup.compute(tmp_path)
    assert fresh == cleanup.read_cache()
    # likely_links (the golden clusters' input) is the same set of pairs by construction
    assert likely_links(tmp_path) == {(p.a, p.b) for p in fresh.pairs}


def test_cache_is_lf_only():
    assert b"\r\n" not in cleanup.CACHE_PATH.read_bytes()


def test_clusters_are_ordered_most_certain_first():
    cl = cleanup.clusters(cleanup.read_cache().pairs)
    keys = [(not c.all_tax_id_match, -c.weakest_score) for c in cl]
    assert keys == sorted(keys)
    assert cl[0].all_tax_id_match


# ------------------------------------------------------------------------- API


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    mp.setenv("APP_DB_PATH", str(tmp_path_factory.mktemp("cleanup") / "app.db"))
    mp.setenv("SAP_BASE_URL", "http://127.0.0.1:9/b1s/v2")
    mp.setenv("LLM_MODE", "replay")
    dispose_default()
    c = TestClient(app)
    assert c.post("/admin/reset-demo").status_code == 200
    clock.reset()
    yield c
    clock.reset()
    dispose_default()
    mp.undo()


@pytest.fixture
def fresh(client):
    assert client.post("/admin/reset-demo").status_code == 200
    clock.reset()
    return client


def _queue(c, user="priya", **params):
    r = c.get("/cleanup/clusters", headers=H(user), params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_queue_lists_every_group_with_records_and_reasons(fresh):
    q = _queue(fresh)
    assert q["total"] == 168 and len(q["clusters"]) == 168
    assert q["reviewed"] == 0 and q["can_decide"] is True and q["note"] is None
    first = q["clusters"][0]
    assert first["all_tax_id_match"] and first["status"] == "not_reviewed"
    assert len(first["records"]) >= 2 and all(r["CardName"] for r in first["records"])
    assert first["links"][0]["reasons"][0]["text"]
    assert first["cluster_id"] == "G-" + min(r["CardCode"] for r in first["records"])
    body = json.dumps(q).lower()
    for bank in ("iban", "accountno", "bankcode", "swift"):
        assert bank not in body


def test_non_analyst_sees_read_only_and_cannot_decide(fresh):
    q = _queue(fresh, "marcus")
    assert q["can_decide"] is False and "Priya" in q["note"]
    cid = q["clusters"][0]["cluster_id"]
    r = fresh.post(
        f"/cleanup/clusters/{cid}/decision", headers=H("marcus"), json={"decision": "confirm"}
    )
    assert r.status_code == 403
    assert _queue(fresh)["reviewed"] == 0


def test_not_same_needs_a_reason(fresh):
    cid = _queue(fresh)["clusters"][1]["cluster_id"]
    url = f"/cleanup/clusters/{cid}/decision"
    for reason in (None, "", "   ", "short"):
        r = fresh.post(url, headers=H("priya"), json={"decision": "not_same", "reason": reason})
        assert r.status_code == 422, reason
    assert _queue(fresh)["reviewed"] == 0


def test_unknown_group_is_404_and_bad_decision_is_422(fresh):
    r = fresh.post(
        "/cleanup/clusters/G-NOPE/decision", headers=H("priya"), json={"decision": "confirm"}
    )
    assert r.status_code == 404
    cid = _queue(fresh)["clusters"][0]["cluster_id"]
    r = fresh.post(f"/cleanup/clusters/{cid}/decision", headers=H("priya"), json={"decision": "x"})
    assert r.status_code == 422


def test_decisions_are_stored_audited_and_counted(fresh):
    clusters = _queue(fresh)["clusters"]
    a, b = clusters[0]["cluster_id"], clusters[1]["cluster_id"]
    clock.advance(hours=3)
    r = fresh.post(
        f"/cleanup/clusters/{a}/decision", headers=H("priya"), json={"decision": "confirm"}
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["reviewed"] == 1 and out["total"] == 168
    assert out["cluster"]["status"] == "confirmed"
    assert out["cluster"]["decision"]["decided_by"] == "Priya"
    assert out["cluster"]["decision"]["decided_at"].startswith(clock.now().isoformat()[:16])

    reason = "Different branches with separate accounts"
    r = fresh.post(
        f"/cleanup/clusters/{b}/decision",
        headers=H("priya"),
        json={"decision": "not_same", "reason": reason},
    )
    assert r.status_code == 200 and r.json()["reviewed"] == 2

    # deciding twice is refused; the first decision stands
    r = fresh.post(
        f"/cleanup/clusters/{a}/decision", headers=H("priya"), json={"decision": "confirm"}
    )
    assert r.status_code == 409

    q = _queue(fresh)
    assert q["reviewed"] == 2
    by_id = {c["cluster_id"]: c for c in q["clusters"]}
    assert by_id[b]["status"] == "not_same" and by_id[b]["decision"]["reason"] == reason
    assert len(_queue(fresh, status="not_reviewed")["clusters"]) == 166
    assert {c["cluster_id"] for c in _queue(fresh, status="reviewed")["clusters"]} == {a, b}

    with session_scope() as s:
        rows = s.scalars(
            select(m.AuditLog)
            .where(m.AuditLog.action == "cleanup_decision")
            .order_by(m.AuditLog.id)
        ).all()
        assert [(r.actor, r.entity_id) for r in rows] == [("priya", a), ("priya", b)]
        assert rows[0].ts == clock.now().isoformat()
        assert json.loads(rows[1].payload)["reason"] == reason
        assert verify_chain(s).ok


def test_status_page_history_still_reads(fresh):
    """The audit view switches on the action: a clean-up row reads as its summary."""
    from services.api import audit_view

    cid = _queue(fresh)["clusters"][0]["cluster_id"]
    fresh.post(
        f"/cleanup/clusters/{cid}/decision", headers=H("priya"), json={"decision": "confirm"}
    )
    with session_scope() as s:
        row = s.scalars(select(m.AuditLog).where(m.AuditLog.action == "cleanup_decision")).one()
        line = audit_view.summarize(row, {"priya": "Priya"}, None)
    assert line.startswith("Priya confirmed that ") and "same customer" in line


def test_decisions_never_change_the_regional_numbers(fresh):
    def bodies():
        return [
            fresh.get("/analytics/regional", params={"view": "after"}).json(),
            fresh.get("/analytics/regional", params={"view": "before"}).json(),
            fresh.get("/analytics/regional", params={"view": "after", "country": "VN"}).json(),
            fresh.get("/analytics/merge-impact").json(),
        ]

    before = bodies()
    clusters = _queue(fresh)["clusters"]
    fresh.post(
        f"/cleanup/clusters/{clusters[0]['cluster_id']}/decision",
        headers=H("priya"),
        json={"decision": "confirm"},
    )
    fresh.post(
        f"/cleanup/clusters/{clusters[5]['cluster_id']}/decision",
        headers=H("priya"),
        json={"decision": "not_same", "reason": "Two different hospitals in one city"},
    )
    assert _queue(fresh)["reviewed"] == 2
    assert bodies() == before


def test_reset_demo_clears_the_decisions(fresh):
    cid = _queue(fresh)["clusters"][0]["cluster_id"]
    r = fresh.post(
        f"/cleanup/clusters/{cid}/decision", headers=H("priya"), json={"decision": "confirm"}
    )
    assert r.status_code == 200
    assert _queue(fresh)["reviewed"] == 1
    assert fresh.post("/admin/reset-demo").status_code == 200
    q = _queue(fresh)
    assert q["reviewed"] == 0 and q["clusters"][0]["status"] == "not_reviewed"
    with session_scope() as s:
        assert s.scalars(select(m.CleanupDecisionRow)).all() == []
