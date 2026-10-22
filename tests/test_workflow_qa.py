"""QA round on session 3 Track B: concurrency, stale decisions, readable errors, no AI on submit.

Reuses the module-scoped app database and helpers of `test_workflow_api.py` (each module that
imports the `client` fixture gets its own database).
"""

# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from services.api import dedup_service
from services.api.audit import verify_chain
from services.api.db import models as m
from services.api.db.session import session_scope
from services.api.main import app
from services.api.sap_publisher import SapPublisher
from services.sap_mock.main import create_app as create_sap_mock
from tests.test_workflow_api import (  # noqa: F401 - fixtures are used by name
    CUSTOMER,
    CUSTOMER_APPROVERS,
    H,
    _clock,
    approve_stage_one,
    client,
    decide,
    new_request,
    sap_mock,
    submit_customer,
    tasks_by_role,
)

OWNS_APP_DB = True  # see tests/conftest.py


def _in_threads(fns):
    """Run callables at the same moment, each with its own TestClient. Returns their results."""
    barrier = threading.Barrier(len(fns))
    results: list = [None] * len(fns)

    def run(i, fn):
        c = TestClient(app)
        barrier.wait()
        try:
            results[i] = fn(c)
        except Exception as exc:  # noqa: BLE001 - surfaced by the assertions
            results[i] = exc

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_reset_succeeds_while_writes_are_in_flight(client):
    stop = threading.Event()
    statuses: list[int] = []

    def writer():
        c = TestClient(app)
        while not stop.is_set():
            r = c.post(
                "/requests",
                headers=H("amy"),
                json={"domain": "customer", "entity": "SPD", "country": "SG", "fields": {}},
            )
            statuses.append(r.status_code)
            time.sleep(0.05)

    th = threading.Thread(target=writer)
    th.start()
    timings = []
    try:
        time.sleep(0.2)
        for _ in range(6):
            r = client.post("/admin/reset-demo")
            assert r.status_code == 200, r.text
            timings.append(r.json()["duration_ms"])
            time.sleep(0.05)
    finally:
        stop.set()
        th.join()
    print(f"resets with a writer thread: {[round(t) for t in timings]} ms")
    assert max(timings) < 10_000
    # the writer got success or a clean retryable answer, never a server error
    assert statuses and set(statuses) <= {201, 503}, set(statuses)
    with session_scope() as s:
        assert verify_chain(s).ok  # no corrupt state, whoever won each race
        # every request that survived the last reset has a matching audit trail
        reqs = s.scalars(select(m.Request.req_id)).all()
        for rid in reqs:
            assert s.scalar(
                select(func.count()).select_from(m.AuditLog).where(m.AuditLog.request_id == rid)
            )


def test_twelve_simultaneous_submits_all_succeed(client):
    ids = []
    for i in range(12):
        fields = {**CUSTOMER, "CardName": f"Parallel Submit {i} Pte Ltd"}
        fields["FederalTaxID"] = f"2026{9000 + i}Q"
        ids.append(new_request(client, fields=fields)["req_id"])
    fns = [(lambda c, rid=rid: c.post(f"/requests/{rid}/submit", headers=H("amy"))) for rid in ids]
    results = _in_threads(fns)
    assert [getattr(r, "status_code", r) for r in results] == [200] * 12


def test_two_simultaneous_publishes_create_one_record(client, sap_mock):
    d = submit_customer(client, "Double Publish Pte Ltd")
    d = approve_stage_one(client, d, CUSTOMER_APPROVERS)
    rid = d["req_id"]
    results = _in_threads([lambda c: c.post(f"/requests/{rid}/publish", headers=H("priya"))] * 2)
    codes = sorted(getattr(r, "status_code", -1) for r in results)
    assert codes == [200, 409], [getattr(r, "text", r) for r in results]
    assert len(sap_mock.app.state.stores["BusinessPartners"]) == 1
    with session_scope() as s:
        n = s.scalar(
            select(func.count())
            .select_from(m.BusinessPartner)
            .where(m.BusinessPartner.U_MDM_ReqID == rid)
        )
    assert n == 1


def test_a_failed_publish_releases_the_claim_so_it_can_be_tried_again(client, monkeypatch):
    from services.api.workflow import publishing

    d = submit_customer(client, "Retry Publish Pte Ltd")
    d = approve_stage_one(client, d, CUSTOMER_APPROVERS)
    rid = d["req_id"]
    r = client.post(f"/requests/{rid}/publish", headers=H("priya"))  # SAP "down": 502
    assert r.status_code == 502
    mock = TestClient(create_sap_mock())
    monkeypatch.setattr(
        publishing,
        "make_publisher",
        lambda: SapPublisher(client=mock, base_url="http://testserver/b1s/v2"),
    )
    monkeypatch.setattr(SapPublisher, "close", lambda self: None)
    r = client.post(f"/requests/{rid}/publish", headers=H("priya"))
    assert r.status_code == 200 and r.json()["state"] == "ACTIVE"


def test_a_change_after_a_question_reopens_earlier_approvals(client):
    bank = [
        {
            "BankCode": "7171",
            "AccountNo": "1111222233",
            "AccountName": "Switch Vendor Pte Ltd",
            "Country": "SG",
        }
    ]
    fields = {**CUSTOMER, "CardName": "Switch Vendor Pte Ltd", "FederalTaxID": "SW2026-1"}
    req = new_request(client, "amy", "vendor", "SPD", "SG", {**fields, "BPBankAccounts": bank})
    rid = req["req_id"]
    d = client.post(f"/requests/{rid}/submit", headers=H("amy")).json()
    t = tasks_by_role(d)
    assert decide(client, t[("finance", None)]["task_id"], "weijie").status_code == 200
    r = decide(client, t[("bu_head", None)]["task_id"], "daniel", "ask_info", "Is the bank right?")
    assert r.json()["state"] == "INFO_REQUESTED"
    bank2 = [{**bank[0], "AccountNo": "9999888877"}]
    client.patch(f"/requests/{rid}", headers=H("amy"), json={"fields": {"BPBankAccounts": bank2}})
    d = client.post(f"/requests/{rid}/submit", headers=H("amy")).json()
    t = tasks_by_role(d)
    # Finance approved the OLD account number: Wei Jie has to look again
    assert t[("finance", None)]["status"] == "pending"
    assert t[("finance", None)]["decided_by"] is None
    assert t[("bu_head", None)]["status"] == "pending"
    assert d["state"] == "IN_APPROVAL" and d["stages"][1]["status"] == "waiting"
    audit = [e["summary"] for e in client.get(f"/requests/{rid}/audit", headers=H("amy")).json()]
    assert any("reopened because the request changed" in s for s in audit)

    # without any change, a plain answer keeps the approvals that exist
    d2 = submit_customer(client, "Plain Answer Pte Ltd")
    t2 = tasks_by_role(d2)
    decide(client, t2[("finance", None)]["task_id"], "weijie")
    decide(client, t2[("bu_head", None)]["task_id"], "daniel", "ask_info", "Just checking")
    d2 = client.post(f"/requests/{d2['req_id']}/submit", headers=H("amy")).json()
    assert tasks_by_role(d2)[("finance", None)]["status"] == "approved"


def test_a_stale_not_a_duplicate_decision_cannot_let_a_real_duplicate_through(client):
    start = {
        "CardName": "Totally Different Trading Co",
        "Country": "VN",
        "City": "Hanoi",
        "FederalTaxID": "0999999999",
        "Street": "1 Street",
        "EmailAddress": "a@b.example",
    }
    rid = new_request(client, "marcus", "customer", "QTG", "VN", start)["req_id"]
    r = client.post(
        f"/requests/{rid}/dedup-decision",
        headers=H("marcus"),
        json={"action": "not_duplicate", "reason": "A different company altogether"},
    )
    assert r.status_code == 200 and r.json()["dedup_decision"] is not None
    # now the draft is changed into an existing hospital...
    r = client.patch(
        f"/requests/{rid}",
        headers=H("marcus"),
        json={
            "fields": {
                "CardName": "Benh vien Cho Ray",
                "FederalTaxID": "0301234567",
                "City": "HCMC",
            }
        },
    )
    assert r.json()["dedup_decision"] is None  # the old decision was cleared
    sub = client.post(f"/requests/{rid}/submit", headers=H("marcus"))
    assert sub.status_code == 409 and "duplicate" in sub.json()["detail"]
    lines = [e["summary"] for e in client.get(f"/requests/{rid}/audit", headers=H("marcus")).json()]
    assert any("decision was cleared" in s for s in lines)


def test_a_decision_made_about_the_real_candidate_still_lets_submit_through(client):
    fields = {
        "CardName": "Benh vien Cho Ray",
        "Country": "VN",
        "City": "HCMC",
        "FederalTaxID": "0301234567",
        "Street": "1 Street",
        "EmailAddress": "a@b.example",
    }
    rid = new_request(client, "marcus", "customer", "QTG", "VN", fields)["req_id"]
    assert client.post(f"/requests/{rid}/submit", headers=H("marcus")).status_code == 409
    client.post(
        f"/requests/{rid}/dedup-decision",
        headers=H("marcus"),
        json={"action": "not_duplicate", "reason": "Different branch, confirmed by phone"},
    )
    assert client.post(f"/requests/{rid}/submit", headers=H("marcus")).status_code == 200


def test_validation_errors_are_one_readable_sentence(client):
    r = client.post(
        "/requests",
        headers=H("amy"),
        json={"domain": "customer", "entity": "SPD", "country": "SG", "fields": "1234567890"},
    )
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    assert "'fields'" in r.json()["detail"] and "1234567890" not in r.text
    r = client.post("/requests", headers=H("amy"), json={"domain": "nonsense"})
    assert isinstance(r.json()["detail"], str) and "nonsense" not in r.text
    # the 10-character rule is the router's, with a plain message
    req = new_request(client, "marcus", "customer", "QTG", "VN", {"CardName": "Short Reason Co"})
    r = client.post(
        f"/requests/{req['req_id']}/dedup-decision",
        headers=H("marcus"),
        json={"action": "not_duplicate", "reason": "short"},
    )
    assert r.status_code == 422 and "at least 10 characters" in r.json()["detail"]


def test_database_busy_is_a_503_not_a_500(client, monkeypatch):
    from sqlalchemy.exc import OperationalError

    from services.api import reset as reset_mod

    def boom():
        raise OperationalError("stmt", {}, Exception("database is locked"))

    monkeypatch.setattr(reset_mod, "reset_demo", boom)
    r = client.post("/admin/reset-demo")
    assert r.status_code == 503
    assert r.json()["detail"] == "The demo database is busy; try again in a moment."


def test_no_ai_judge_on_the_submit_and_decision_path(client, monkeypatch):
    calls: list[bool] = []
    real = dedup_service.check

    def spy(query, master, *args, use_judge=True, **kw):
        calls.append(use_judge)
        return real(query, master, *args, use_judge=use_judge, **kw)

    monkeypatch.setattr(dedup_service, "check", spy)
    monkeypatch.setenv("LLM_MODE", "replay")
    fields = {**CUSTOMER, "CardName": "Judge Free Pte Ltd", "FederalTaxID": "JF-1"}
    rid = new_request(client, fields=fields)["req_id"]
    client.post(
        f"/requests/{rid}/dedup-decision",
        headers=H("amy"),
        json={"action": "not_duplicate", "reason": "Brand new company, checked"},
    )
    client.post(f"/requests/{rid}/submit", headers=H("amy"))
    assert calls and not any(calls)
    calls.clear()
    body = {"domain": "customer", "entity": "SPD", "fields": fields}
    client.post("/dedup/check", headers=H("amy"), json=body)
    assert calls == [True]  # the second opinion lives only on /dedup/check


def test_make_reset_demo_never_overlaps_a_slow_api_reset(monkeypatch):
    import httpx

    from services.api.db import seed

    def slow(*a, **k):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(httpx, "post", slow)
    with pytest.raises(seed.SeedError, match="may still be running"):
        seed._reset_via_running_api()


def test_audit_copy_reads_correctly():
    from services.api import audit_view

    failed = audit_view._sap_summary(
        {"method": "POST", "path": "/BusinessPartners", "status": 400, "b1_error_message": "x"}
    )
    assert failed == "SAP: tried to create the record in SAP, but it failed (x)"
