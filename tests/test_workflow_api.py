"""Session 3, Track B: requests, duplicate check, approvals, SLA, publish, reset (all offline).

One app database is built once for the module, through the same code path as the in-app reset
(`POST /admin/reset-demo`) from the real fixtures. Tests create their own requests.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ds.interpreter.schemas import Interpretation, QuotedValue
from services.api import clock, dedup_service
from services.api.audit import verify_chain
from services.api.db import models as m
from services.api.db.session import dispose_default, get_engine, session_scope
from services.api.main import app
from services.api.sap_publisher import SapPublisher
from services.sap_mock.main import create_app as create_sap_mock
from tests.db_helpers import count_lines

OWNS_APP_DB = True  # see tests/conftest.py
SGT = timezone(timedelta(hours=8))
FIXTURES = "data/fixtures/seasonal_trend"


def H(user: str) -> dict[str, str]:
    return {"X-Acting-User": user}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    mp.setenv("APP_DB_PATH", str(tmp_path_factory.mktemp("api") / "app.db"))
    mp.setenv("SAP_BASE_URL", "http://127.0.0.1:9/b1s/v2")  # nothing listens: mock is "down"
    mp.setenv("LLM_MODE", "replay")
    dispose_default()
    c = TestClient(app)
    r = c.post("/admin/reset-demo")
    assert r.status_code == 200, r.text
    yield c
    dispose_default()
    mp.undo()


@pytest.fixture(autouse=True)
def _clock(client):
    clock.reset()
    yield
    clock.reset()


CUSTOMER = {
    "CardName": "Zeta Nova Medical Pte Ltd",
    "Country": "SG",
    "FederalTaxID": "202612345Z",
    "Street": "1 Test Road",
    "City": "Singapore",
    "EmailAddress": "ap@zetanova.example",
}


def new_request(client, user="amy", domain="customer", entity="SPD", country="SG", fields=None):
    r = client.post(
        "/requests",
        headers=H(user),
        json={"domain": domain, "entity": entity, "country": country, "fields": fields or {}},
    )
    assert r.status_code == 201, r.text
    return r.json()


_tax = iter(range(1, 10_000))


def submit_customer(client, name, user="amy"):
    tax = f"2026{next(_tax):05d}Z"  # unique: earlier tests' customers never look like duplicates
    req = new_request(client, user, fields={**CUSTOMER, "CardName": name, "FederalTaxID": tax})
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()


def tasks_by_role(detail):
    return {(t["role"], t["country"]): t for st in detail["stages"] for t in st["tasks"]}


def decide(client, task_id, user, action="approve", comment=None):
    return client.post(
        f"/approvals/{task_id}/decision",
        headers=H(user),
        json={"action": action, "comment": comment},
    )


def approve_stage_one(client, detail, who):
    for (role, country), user in who.items():
        t = tasks_by_role(detail)[(role, country)]
        r = decide(client, t["task_id"], user)
        assert r.status_code == 200, r.text
        detail = r.json()
    return detail


CUSTOMER_APPROVERS = {
    ("bu_head", None): "daniel",
    ("finance", None): "weijie",
    ("business_support", None): "meiling",
}


# ---------------------------------------------------------------- basics


def test_501_stubs_are_gone(client):
    calls = [
        client.get("/emails", headers=H("amy")),
        client.get("/emails/DEMO-01", headers=H("amy")),
        client.get("/requests", headers=H("amy")),
        client.get("/approvals/inbox", headers=H("daniel")),
        client.get("/notifications", headers=H("daniel")),
        client.post(
            "/dedup/check",
            headers=H("amy"),
            json={"domain": "customer", "entity": "SPD", "fields": {}},
        ),
    ]
    assert [c.status_code for c in calls] == [200] * 6


def test_acting_user_header_is_validated(client):
    assert client.get("/requests").status_code == 400
    assert "acting as" in client.get("/requests").json()["detail"]
    r = client.get("/requests", headers=H("nobody"))
    assert r.status_code == 403
    assert "not a known user" in r.json()["detail"]
    # role rules are enforced server-side
    r = client.post(
        "/requests",
        headers=H("weijie"),
        json={"domain": "customer", "entity": "SPD", "country": "SG", "fields": {}},
    )
    assert r.status_code == 403
    assert "requestor" in r.json()["detail"]


def test_validation_errors_do_not_echo_values(client):
    r = client.post(
        "/requests",
        headers=H("amy"),
        json={"domain": "customer", "entity": "SPD", "country": "SG", "fields": "1234567890"},
    )
    assert r.status_code == 422
    assert "1234567890" not in r.text


# ---------------------------------------------------------------- DEMO-01 duplicate flow


def test_demo01_marcus_likely_duplicate_then_link_has_no_tasks(client):
    fields = {
        "CardName": "Benh vien Cho Ray",
        "Country": "VN",
        "City": "HCMC",
        "FederalTaxID": "0301234567",
        "Street": "201B Nguyen Chi Thanh",
        "EmailAddress": "mua@choray.example",
    }
    chk = client.post(
        "/dedup/check",
        headers=H("marcus"),
        json={"domain": "customer", "entity": "QTG", "fields": fields},
    )
    assert chk.status_code == 200
    body = chk.json()
    assert body["verdict"] == "likely" and body["block_submit"] is True
    existing = body["candidates"][0]["CardCode"]
    assert body["elapsed_ms"] < 100

    req = new_request(client, "marcus", "customer", "QTG", "VN", fields)
    # the check is audited when it belongs to a draft
    client.post(
        "/dedup/check",
        headers=H("marcus"),
        json={"domain": "customer", "entity": "QTG", "fields": fields, "request_id": req["req_id"]},
    )
    # submit is refused until a human decides
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("marcus"))
    assert r.status_code == 409
    assert "duplicate" in r.json()["detail"] and existing in r.json()["detail"]

    # link_to_existing needs a card code that exists, of the right type
    bad = client.post(
        f"/requests/{req['req_id']}/dedup-decision",
        headers=H("marcus"),
        json={"action": "link_to_existing", "card_code": "C99999"},
    )
    assert bad.status_code == 422
    r = client.post(
        f"/requests/{req['req_id']}/dedup-decision",
        headers=H("marcus"),
        json={"action": "link_to_existing", "card_code": existing},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["state"] == "LINKED_TO_EXISTING" and d["linked_card_code"] == existing
    assert d["stages"] == [] and d["dedup_decision"]["verdict_at_decision"] == "likely"
    assert d["allowed_actions"] == []
    inbox = client.get("/approvals/inbox", headers=H("tuan")).json()
    assert all(i["request"]["req_id"] != req["req_id"] for i in inbox)

    lines = [
        e["summary"]
        for e in client.get(f"/requests/{req['req_id']}/audit", headers=H("amy")).json()
    ]
    assert any("Duplicate check run" in s for s in lines)
    assert any(f"linked the request to existing record {existing}" in s for s in lines)
    assert any("no new record and no approvals" in s for s in lines)


def test_not_duplicate_needs_a_reason_and_then_submit_goes_through(client):
    fields = {
        "CardName": "Benh vien Cho Ray",
        "Country": "VN",
        "City": "HCMC",
        "FederalTaxID": "0301234567",
        "Street": "1 Some Street",
        "EmailAddress": "x@y.example",
    }
    req = new_request(client, "marcus", "customer", "QTG", "VN", fields)
    url = f"/requests/{req['req_id']}/dedup-decision"
    assert (
        client.post(url, headers=H("marcus"), json={"action": "not_duplicate"}).status_code == 422
    )
    # only the requestor decides (the AI never does, rule 6)
    r = client.post(
        url,
        headers=H("weijie"),
        json={"action": "not_duplicate", "reason": "Different hospital, different tax ID"},
    )
    assert r.status_code == 403
    r = client.post(
        url,
        headers=H("marcus"),
        json={"action": "not_duplicate", "reason": "Different hospital, different tax ID"},
    )
    assert r.status_code == 200
    assert r.json()["dedup_decision"]["reason"].startswith("Different hospital")
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("marcus"))
    assert r.status_code == 200 and r.json()["state"] == "IN_APPROVAL"
    # QTG request: the BU head is the QTG head (Tuan), found from the request's entity
    assert tasks_by_role(r.json())[("bu_head", None)]["assignee_user_id"] == "tuan"


# ---------------------------------------------------------------- requests, fields, bank masking


def test_submit_lists_missing_fields_and_edits_are_audited(client):
    req = new_request(client, fields={"CardName": "Quill Medical Pte Ltd", "Country": "SG"})
    assert req["missing_fields"] == ["FederalTaxID", "Street", "EmailAddress"]
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 422
    assert "Tax ID (FederalTaxID)" in r.json()["detail"]
    r = client.patch(
        f"/requests/{req['req_id']}", headers=H("amy"), json={"fields": {"City": "Singapore"}}
    )
    assert r.status_code == 200
    r = client.patch(
        f"/requests/{req['req_id']}", headers=H("amy"), json={"fields": {"City": "Jurong"}}
    )
    assert r.json()["fields"]["City"] == "Jurong"
    # somebody else cannot edit
    assert (
        client.patch(
            f"/requests/{req['req_id']}", headers=H("marcus"), json={"fields": {}}
        ).status_code
        == 403
    )
    unknown = client.patch(
        f"/requests/{req['req_id']}", headers=H("amy"), json={"fields": {"Nonsense": 1}}
    )
    assert unknown.status_code == 422
    audit = client.get(f"/requests/{req['req_id']}/audit", headers=H("amy")).json()
    edits = [e["summary"] for e in audit if e["action"] == "field_edit"]
    assert edits == [
        "Amy changed City: (empty) -> Singapore",
        "Amy changed City: Singapore -> Jurong",
    ]


def test_bank_details_are_encrypted_masked_by_role_and_never_audited(client):
    bank = [
        {
            "BankCode": "7171",
            "AccountNo": "1234567890",
            "AccountName": "Acme Supplies Pte Ltd",
            "BICSwiftCode": "DBSSSGSG",
            "Country": "SG",
        }
    ]
    req = new_request(
        client, "amy", "vendor", "SPD", "SG",
        {"CardName": "Acme Supplies Pte Ltd", "Country": "SG", "BPBankAccounts": bank},
    )  # fmt: skip
    rid = req["req_id"]
    as_amy = client.get(f"/requests/{rid}", headers=H("amy")).json()
    row = as_amy["fields"]["BPBankAccounts"][0]
    assert row["AccountNo"] == "****7890" and row["BankCode"] == "****"
    assert "1234567890" not in client.get(f"/requests/{rid}", headers=H("daniel")).text
    as_finance = client.get(f"/requests/{rid}", headers=H("weijie")).json()
    assert as_finance["fields"]["BPBankAccounts"][0]["AccountNo"] == "1234567890"

    # sending the masked value back (as a UI would) keeps the stored one
    masked_back = {"BPBankAccounts": [{**row, "AccountName": "Acme Supplies (S) Pte Ltd"}]}
    r = client.patch(f"/requests/{rid}", headers=H("amy"), json={"fields": masked_back})
    assert r.status_code == 200
    stored = client.get(f"/requests/{rid}", headers=H("weijie")).json()
    assert stored["fields"]["BPBankAccounts"][0]["AccountNo"] == "1234567890"
    assert stored["fields"]["BPBankAccounts"][0]["AccountName"] == "Acme Supplies (S) Pte Ltd"

    # at rest: ciphertext in the file, and no plain number anywhere in the audit log
    with session_scope() as s:
        raw = s.execute(
            text("SELECT payload FROM requests WHERE req_id = :r"), {"r": rid}
        ).scalar_one()
        audit_text = " ".join(
            s.scalars(select(m.AuditLog.payload).where(m.AuditLog.request_id == rid))
        )
    assert "1234567890" not in raw and "7171" not in audit_text.replace("****", "")
    assert "1234567890" not in audit_text
    assert '"new":"****"' in audit_text  # edits are logged masked (old -> new)
    assert "Acme Supplies (S)" not in audit_text
    summaries = " ".join(
        e["summary"] for e in client.get(f"/requests/{rid}/audit", headers=H("amy")).json()
    )
    assert "1234567890" not in summaries


def test_email_bodies_are_masked_unless_finance(client):
    with session_scope() as s:
        from ds.interpreter.bank import strip_bank_details

        ids = [e.email_id for e in s.scalars(select(m.Email)) if strip_bank_details(e.body)[1]]
    assert ids, "the fixtures should contain an email with bank details"
    eid = ids[0]
    plain = client.get(f"/emails/{eid}", headers=H("weijie")).json()["body"]
    masked = client.get(f"/emails/{eid}", headers=H("amy")).json()["body"]
    assert "[bank details removed]" in masked and "[bank details removed]" not in plain
    listed = [e for e in client.get("/emails", headers=H("amy")).json() if e["email_id"] == eid]
    assert "[bank details removed]" in listed[0]["snippet"] or len(listed[0]["snippet"]) <= 160


def test_create_from_email_prefills_but_never_bank_or_terms(client, monkeypatch):
    from services.api.routers import requests as req_router

    def fake(email_id, subject, body, from_address, **_):
        return Interpretation(
            email_id=email_id,
            category="mdm_request",
            confidence=0.9,
            domain="vendor",
            fields=[
                QuotedValue(
                    key="name", value="Precision Reagents Pte Ltd", source_quote="Precision"
                ),
                QuotedValue(key="tax_id", value="201234567A", source_quote="UEN 201234567A"),
                QuotedValue(key="bank_account", value="123-456-789", source_quote="acct"),
                QuotedValue(key="credit_limit", value=999999.0, source_quote="limit"),
            ],
            method="llm",
            ai_status="ok",
        )

    monkeypatch.setattr(req_router, "interpret_email", fake)
    r = client.post("/requests/from-email/DEMO-01", headers=H("marcus"))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["domain"] == "vendor" and d["entity"] == "QTG" and d["source_email_id"] == "DEMO-01"
    assert d["fields"]["CardName"] == "Precision Reagents Pte Ltd"
    assert d["prefill_quotes"]["FederalTaxID"] == "UEN 201234567A"
    assert "BPBankAccounts" not in d["fields"] and "CreditLimit" not in d["fields"]
    assert "BPBankAccounts" in d["missing_fields"]
    # only a requestor can do it; an unknown email is a 404
    assert client.post("/requests/from-email/DEMO-01", headers=H("weijie")).status_code == 403
    assert client.post("/requests/from-email/NOPE", headers=H("marcus")).status_code == 404


def test_interpret_endpoint_calls_the_interpreter(client, monkeypatch):
    from services.api.routers import emails as email_router

    monkeypatch.setattr(
        email_router,
        "interpret_email",
        lambda email_id, subject, body, from_address, **_: Interpretation(
            email_id=email_id, category="enquiry", confidence=0.8, method="llm", ai_status="ok"
        ),
    )
    r = client.post("/emails/DEMO-03/interpret", headers=H("amy"))
    assert r.status_code == 200 and r.json()["category"] == "enquiry"
    assert client.post("/emails/NOPE/interpret", headers=H("amy")).status_code == 404


# ---------------------------------------------------------------- parallel stages


def test_customer_runs_three_parallel_tasks_and_stage_two_waits(client):
    d = submit_customer(client, "Orion Health Supplies Pte Ltd")
    assert d["state"] == "IN_APPROVAL"
    stage1, stage2 = d["stages"]
    assert stage1["status"] == "open" and stage2["status"] == "waiting"
    assert {(t["role"], t["assignee_user_id"], t["status"]) for t in stage1["tasks"]} == {
        ("bu_head", "daniel", "pending"),
        ("finance", "weijie", "pending"),
        ("business_support", "meiling", "pending"),
    }
    assert [t["status"] for t in stage2["tasks"]] == ["waiting"]
    assert sorted(d["pending_with"]) == ["Daniel", "Mei Ling", "Wei Jie"]

    # stage 1 tasks are in the approvers' inboxes (parallel), stage 2 is not
    for user in ("daniel", "weijie", "meiling"):
        inbox = client.get("/approvals/inbox", headers=H(user)).json()
        assert any(i["request"]["req_id"] == d["req_id"] for i in inbox)
    priya_inbox = client.get("/approvals/inbox", headers=H("priya")).json()
    assert all(i["request"]["req_id"] != d["req_id"] for i in priya_inbox)

    t = tasks_by_role(d)
    # the stage-2 task cannot be decided early
    stage2_task = tasks_by_role(d)[("mdm_analyst", None)]
    early = decide(client, stage2_task["task_id"], "priya")
    assert early.status_code == 409
    d = decide(client, t[("bu_head", None)]["task_id"], "daniel").json()
    d = decide(client, t[("finance", None)]["task_id"], "weijie").json()
    assert d["state"] == "IN_APPROVAL" and d["stages"][1]["status"] == "waiting"
    d = decide(client, t[("business_support", None)]["task_id"], "meiling").json()
    assert d["state"] == "APPROVED"
    assert d["stages"][0]["status"] == "done" and d["stages"][1]["status"] == "open"
    assert d["pending_with"] == ["Priya"]
    priya_inbox = client.get("/approvals/inbox", headers=H("priya")).json()
    assert any(i["request"]["req_id"] == d["req_id"] for i in priya_inbox)
    kinds = [n["kind"] for n in client.get("/notifications", headers=H("amy")).json()]
    assert "approved" in kinds
    # someone else's task cannot be decided
    assert decide(client, t[("finance", None)]["task_id"], "huimin").status_code == 409


def test_wrong_person_cannot_decide(client):
    d = submit_customer(client, "Lyra Diagnostics Pte Ltd")
    t = tasks_by_role(d)[("finance", None)]
    r = decide(client, t["task_id"], "huimin")  # also Finance, but not the assignee
    assert r.status_code == 403 and "assigned to Wei Jie" in r.json()["detail"]
    assert decide(client, t["task_id"], "amy").status_code == 403


def test_ivd_item_gets_one_quality_task_per_selling_country(client):
    fields = {
        "ItemName": "Malaria Pf/Pan Antigen Rapid Test Kit",
        "U_IVD": "tYES",
        "selling_countries": ["SG", "MY", "VN"],
        "registrations": [
            {"country": "SG", "reg_no": "DIV-001"},
            {"country": "MY", "reg_no": "MDA-002"},
        ],
    }
    req = new_request(client, "amy", "item", "SPD", "SG", fields)
    assert req["missing_fields"] == ["registrations[VN]"]
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 422 and "Registration number for VN" in r.json()["detail"]
    client.patch(
        f"/requests/{req['req_id']}",
        headers=H("amy"),
        json={
            "fields": {
                "registrations": [*fields["registrations"], {"country": "VN", "reg_no": "VN-3"}]
            }
        },
    )
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    assert d["state"] == "IN_APPROVAL"
    stage1 = d["stages"][0]["tasks"]
    qr = {t["country"]: t["assignee_name"] for t in stage1 if t["role"] == "quality_regulatory"}
    assert qr == {"SG": "Joanne Yeo", "MY": "Nurul", "VN": "Nguyễn Thị Lan"}
    assert {t["role"] for t in stage1} == {"bu_head", "business_support", "quality_regulatory"}
    assert len(stage1) == 5


def test_resubmit_after_a_question_re_applies_the_routing_rules(client):
    fields = {
        "ItemName": "Resync Rapid Test",
        "U_IVD": "tYES",
        "selling_countries": ["SG", "MY"],
        "registrations": [
            {"country": "SG", "reg_no": "S-1"},
            {"country": "MY", "reg_no": "M-1"},
        ],
    }
    req = new_request(client, "amy", "item", "SPD", "SG", fields)
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    my = tasks_by_role(d)[("quality_regulatory", "MY")]
    r = decide(
        client, my["task_id"], "nurul", "ask_info", "We do not sell this in Malaysia, do we?"
    )
    assert r.json()["state"] == "INFO_REQUESTED"
    r = client.patch(
        f"/requests/{req['req_id']}",
        headers=H("amy"),
        json={
            "fields": {
                "selling_countries": ["SG", "VN"],
                "registrations": [
                    {"country": "SG", "reg_no": "S-1"},
                    {"country": "VN", "reg_no": "V-1"},
                ],
            }
        },
    )
    assert r.status_code == 200
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    assert d["state"] == "IN_APPROVAL"
    qr = {
        t["country"]: t["status"]
        for t in d["stages"][0]["tasks"]
        if t["role"] == "quality_regulatory"
    }
    assert qr == {"SG": "pending", "MY": "cancelled", "VN": "pending"}
    lan = tasks_by_role(d)[("quality_regulatory", "VN")]
    assert lan["assignee_user_id"] == "lan"


def test_non_ivd_item_has_no_quality_task(client):
    req = new_request(
        client, "amy", "item", "SPD", "SG",
        {"ItemName": "Pipette tips", "U_IVD": "tNO", "selling_countries": ["SG"]},
    )  # fmt: skip
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    assert {t["role"] for t in d["stages"][0]["tasks"]} == {"bu_head", "business_support"}


# ---------------------------------------------------------------- decisions


def test_reject_and_ask_info_need_comments_and_resubmit_reopens_the_task(client):
    d = submit_customer(client, "Vega Clinic Pte Ltd")
    t = tasks_by_role(d)
    fin = t[("finance", None)]["task_id"]
    assert decide(client, fin, "weijie", "ask_info").status_code == 422
    assert decide(client, fin, "weijie", "reject", "  ").status_code == 422
    r = decide(client, fin, "weijie", "ask_info", "Which credit terms do you want?")
    assert r.status_code == 200 and r.json()["state"] == "INFO_REQUESTED"
    assert "Amy" in r.json()["pending_with"]
    note = client.get("/notifications", headers=H("amy")).json()[0]
    assert note["kind"] == "info_requested" and "credit terms" in note["message"]
    # the requestor answers: edit, then submit again
    assert (
        client.patch(
            f"/requests/{d['req_id']}", headers=H("amy"), json={"fields": {"PayTermsGrpCode": 1}}
        ).status_code
        == 200
    )
    r = client.post(f"/requests/{d['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 200 and r.json()["state"] == "IN_APPROVAL"
    again = tasks_by_role(r.json())[("finance", None)]
    assert again["status"] == "pending" and again["task_id"] == fin

    r = decide(
        client,
        tasks_by_role(r.json())[("bu_head", None)]["task_id"],
        "daniel",
        "reject",
        "Not needed",
    )
    assert r.json()["state"] == "REJECTED"
    assert {tk["status"] for st in r.json()["stages"] for tk in st["tasks"]} == {
        "rejected",
        "cancelled",
    }


# ---------------------------------------------------------------- maker-checker


def _set_roles(user_id, roles):
    with session_scope() as s:
        s.get(m.User, user_id).roles = roles


def test_requestor_cannot_approve_own_request(client):
    _set_roles("daniel", ["bu_head", "requestor"])
    try:
        d = submit_customer(client, "Daniel Own Customer Pte Ltd", user="daniel")
        mine = tasks_by_role(d)[("bu_head", None)]
        assert mine["assignee_user_id"] == "daniel"
        r = decide(client, mine["task_id"], "daniel")
        assert r.status_code == 403 and "your own request" in r.json()["detail"]
        assert (
            "approve"
            not in client.get(f"/requests/{d['req_id']}", headers=H("daniel")).json()[
                "allowed_actions"
            ]
        )
    finally:
        _set_roles("daniel", ["bu_head"])


def test_publisher_cannot_be_the_finance_approver(client, monkeypatch):
    d = submit_customer(client, "Maker Checker Pte Ltd")
    d = approve_stage_one(client, d, CUSTOMER_APPROVERS)
    assert d["state"] == "APPROVED"
    _set_roles(
        "weijie", ["finance", "mdm_analyst"]
    )  # Wei Jie approved Finance, now tries to publish
    try:
        r = client.post(f"/requests/{d['req_id']}/publish", headers=H("weijie"))
        assert r.status_code == 403 and "gave the Finance approval" in r.json()["detail"]
        assert (
            "publish"
            not in client.get(f"/requests/{d['req_id']}", headers=H("weijie")).json()[
                "allowed_actions"
            ]
        )
    finally:
        _set_roles("weijie", ["finance"])
    # and only an MDM analyst can publish at all
    assert client.post(f"/requests/{d['req_id']}/publish", headers=H("amy")).status_code == 403


# ---------------------------------------------------------------- SLA on the simulated clock


def test_reminder_at_one_business_day_and_escalation_at_two_across_a_weekend(client):
    client.post("/clock/advance", json={"days": 3})  # Thu 8 Oct 09:00
    assert clock.now() == datetime(2026, 10, 8, 9, 0, tzinfo=SGT)
    d = submit_customer(client, "Weekend Test Pte Ltd")
    rid = d["req_id"]
    t0 = tasks_by_role(d)[("bu_head", None)]
    assert datetime.fromisoformat(t0["due_at"]) == datetime(2026, 10, 12, 9, 0, tzinfo=SGT)  # Mon

    client.post("/clock/advance", json={"hours": 23})  # Fri 08:00: not yet
    d = client.get(f"/requests/{rid}", headers=H("amy")).json()
    assert tasks_by_role(d)[("bu_head", None)]["sla_state"] == "on_track"

    client.post("/clock/advance", json={"hours": 1})  # Fri 09:00 = 1 business day = 50%
    d = client.get(f"/requests/{rid}", headers=H("amy")).json()
    assert {t["sla_state"] for st in d["stages"][:1] for t in st["tasks"]} == {"reminded"}
    reminder = [
        n for n in client.get("/notifications", headers=H("daniel")).json() if n["req_id"] == rid
    ]
    assert [n["kind"] for n in reminder] == ["reminder", "task_assigned"]
    assert (
        reminder[0]["message"].startswith("Reminder:") and "Weekend Test" in reminder[0]["message"]
    )

    client.post("/clock/advance", json={"hours": 48})  # Sun: weekend does not count
    d = client.get(f"/requests/{rid}", headers=H("amy")).json()
    assert tasks_by_role(d)[("bu_head", None)]["escalated_at"] is None

    client.post("/clock/advance", json={"hours": 24})  # Mon 09:00 = 2 business days
    d = client.get(f"/requests/{rid}", headers=H("amy")).json()
    t = tasks_by_role(d)
    assert t[("bu_head", None)]["escalated_to_user_id"] == "kelvin"
    assert t[("finance", None)]["escalated_to_user_id"] == "siti"
    assert t[("business_support", None)]["escalated_to_user_id"] == "farah"
    assert t[("bu_head", None)]["sla_state"] == "overdue"
    assert sorted(d["pending_with"]) == [
        "Daniel",
        "Farah Hassan",
        "Kelvin Ong",
        "Mei Ling",
        "Siti Aminah",
        "Wei Jie",
    ]

    # the task is in BOTH inboxes until someone decides; the backup may decide
    for user in ("daniel", "kelvin"):
        inbox = client.get("/approvals/inbox", headers=H(user)).json()
        assert any(i["task"]["task_id"] == t[("bu_head", None)]["task_id"] for i in inbox)
    assert any(
        n["kind"] == "escalated" and n["req_id"] == rid
        for n in client.get("/notifications", headers=H("kelvin")).json()
    )
    r = decide(client, t[("bu_head", None)]["task_id"], "kelvin")
    assert (
        r.status_code == 200
        and tasks_by_role(r.json())[("bu_head", None)]["decided_by"] == "kelvin"
    )

    # the simulated time survives a restart
    saved = clock.now()
    clock.reset()
    assert clock.restore() is True and clock.now() == saved


def test_business_day_arithmetic_skips_weekends():
    from services.api.workflow.sla import add_business_time

    fri = datetime(2026, 10, 9, 9, 0, tzinfo=SGT)
    assert add_business_time(fri, timedelta(days=1)) == datetime(2026, 10, 12, 9, 0, tzinfo=SGT)
    assert add_business_time(fri, timedelta(days=2)) == datetime(2026, 10, 13, 9, 0, tzinfo=SGT)
    sat = datetime(2026, 10, 10, 15, 0, tzinfo=SGT)
    assert add_business_time(sat, timedelta(hours=1)) == datetime(2026, 10, 12, 1, 0, tzinfo=SGT)


# ---------------------------------------------------------------- publish, audit, dedup index


@pytest.fixture
def sap_mock(monkeypatch):
    from services.api.workflow import publishing

    mock = TestClient(create_sap_mock())

    def make():
        return SapPublisher(client=mock, base_url="http://testserver/b1s/v2")

    monkeypatch.setattr(publishing, "make_publisher", make)
    monkeypatch.setattr(SapPublisher, "close", lambda self: None)
    return mock


def test_publish_ends_active_and_the_new_customer_is_found_by_the_next_check(client, sap_mock):
    d = submit_customer(client, "Publish Flow Medical Pte Ltd")
    d = approve_stage_one(client, d, CUSTOMER_APPROVERS)
    assert d["allowed_actions"] == [] or "publish" not in d["allowed_actions"]
    rid = d["req_id"]
    assert "publish" in client.get(f"/requests/{rid}", headers=H("priya")).json()["allowed_actions"]
    r = client.post(f"/requests/{rid}/publish", headers=H("priya"))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["state"] == "ACTIVE" and d["stages"][1]["status"] == "done"
    assert d["stages"][1]["tasks"][0]["decided_by"] == "priya"

    with session_scope() as s:
        row = s.scalar(select(m.BusinessPartner).where(m.BusinessPartner.U_MDM_ReqID == rid))
        code, tax = row.CardCode, row.FederalTaxID
        assert row.Frozen == "tNO" and row.CardType == "cCustomer"
    sap_row = sap_mock.get(f"/b1s/v2/BusinessPartners('{code}')", cookies=None)
    assert sap_row.status_code == 401  # a fresh call without a session is refused...
    assert code in str(sap_mock.app.state.stores["BusinessPartners"])  # ...but the record is there
    assert sap_mock.app.state.stores["BusinessPartners"][code]["Frozen"] == "tNO"

    kinds = [
        n["kind"]
        for n in client.get("/notifications", headers=H("amy")).json()
        if n["req_id"] == rid
    ]
    assert "published" in kinds
    audit = [e["summary"] for e in client.get(f"/requests/{rid}/audit", headers=H("amy")).json()]
    assert "Wei Jie approved (Finance)" in audit
    assert any("SAP: created the record in SAP" in s for s in audit)
    assert any("is now active" in s for s in audit)
    with session_scope() as s:
        assert verify_chain(s).ok

    # the index was rebuilt: the same customer is now a likely duplicate
    chk = client.post(
        "/dedup/check",
        headers=H("amy"),
        json={
            "domain": "customer",
            "entity": "SPD",
            "fields": {**CUSTOMER, "CardName": "Publish Flow Medical Pte Ltd", "FederalTaxID": tax},
        },
    )
    assert chk.json()["verdict"] == "likely" and chk.json()["candidates"][0]["CardCode"] == code
    # a vendor with the same name is NOT a duplicate (domain rule 2)
    chk = client.post(
        "/dedup/check",
        headers=H("amy"),
        json={
            "domain": "vendor",
            "entity": "SPD",
            "fields": {**CUSTOMER, "CardName": "Publish Flow Medical Pte Ltd", "FederalTaxID": tax},
        },
    )
    assert chk.json()["verdict"] == "none"
    # publishing twice is refused
    assert client.post(f"/requests/{rid}/publish", headers=H("priya")).status_code == 409


def test_vendor_with_bank_details_and_ivd_item_publish_to_the_mock(client, sap_mock):
    bank = [
        {
            "BankCode": "7171",
            "AccountNo": "9876543210",
            "AccountName": "Bank Vendor Pte Ltd",
            "BICSwiftCode": "DBSSSGSG",
            "Country": "SG",
        }
    ]
    vendor = {**CUSTOMER, "CardName": "Bank Vendor Pte Ltd", "FederalTaxID": "V2026-77"}
    req = new_request(client, "amy", "vendor", "SPD", "SG", {**vendor, "BPBankAccounts": bank})
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    assert d["state"] == "IN_APPROVAL"
    d = approve_stage_one(client, d, CUSTOMER_APPROVERS)
    assert (
        client.post(f"/requests/{d['req_id']}/publish", headers=H("priya")).json()["state"]
        == "ACTIVE"
    )
    with session_scope() as s:
        row = s.scalar(
            select(m.BusinessPartner).where(m.BusinessPartner.U_MDM_ReqID == d["req_id"])
        )
        assert row.CardCode.startswith("V") and row.CardType == "cSupplier"
        acct = s.scalar(select(m.BankAccount).where(m.BankAccount.CardCode == row.CardCode))
        assert acct.AccountNo == "9876543210"
        raw = s.execute(
            text("SELECT AccountNo FROM bank_accounts WHERE CardCode = :c"), {"c": row.CardCode}
        ).scalar_one()
        assert raw != "9876543210"
        audit_text = " ".join(
            s.scalars(select(m.AuditLog.payload).where(m.AuditLog.request_id == d["req_id"]))
        )
    sent = sap_mock.app.state.stores["BusinessPartners"][row.CardCode]
    assert sent["BPBankAccounts"][0]["AccountNo"] == "9876543210" and sent["Frozen"] == "tNO"
    assert "9876543210" not in audit_text  # not even in the SAP call rows

    fields = {
        "ItemName": "Malaria Pf/Pan Antigen Rapid Test Kit",
        "U_IVD": "tYES",
        "selling_countries": ["SG", "MY"],
        "registrations": [
            {"country": "SG", "reg_no": "DIV-001"},
            {"country": "MY", "reg_no": "MDA-002"},
        ],
        "product_family": "A",
    }
    req = new_request(client, "amy", "item", "SPD", "SG", fields)
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    who = {
        ("bu_head", None): "daniel",
        ("business_support", None): "meiling",
        ("quality_regulatory", "SG"): "joanne",
        ("quality_regulatory", "MY"): "nurul",
    }
    d = approve_stage_one(client, d, who)
    assert d["state"] == "APPROVED"
    d = client.post(f"/requests/{d['req_id']}/publish", headers=H("priya")).json()
    assert d["state"] == "ACTIVE"
    with session_scope() as s:
        item = s.scalar(select(m.Item).where(m.Item.U_MDM_ReqID == d["req_id"]))
        regs = s.scalars(
            select(m.ItemRegistration).where(m.ItemRegistration.item_code == item.ItemCode)
        ).all()
    assert item.ItemCode.startswith("A-MAL-") and item.U_IVD == "tYES" and len(regs) == 2
    assert (
        sap_mock.app.state.stores["Items"][item.ItemCode]["U_RegSummary"]
        == "SG: DIV-001; MY: MDA-002"
    )


def test_publish_reports_a_plain_message_when_sap_is_down(client):
    d = submit_customer(client, "Unreachable Pte Ltd")
    d = approve_stage_one(client, d, CUSTOMER_APPROVERS)
    r = client.post(f"/requests/{d['req_id']}/publish", headers=H("priya"))
    assert r.status_code == 502 and "still approved" in r.json()["detail"]
    assert client.get(f"/requests/{d['req_id']}", headers=H("priya")).json()["state"] == "APPROVED"


# ---------------------------------------------------------------- in-app reset (D-016)


def test_make_reset_demo_falls_back_to_the_database_when_the_api_is_not_running(monkeypatch):
    from services.api.db import seed

    monkeypatch.setenv("API_URL", "http://127.0.0.1:9")  # nothing listens here
    assert seed._reset_via_running_api() is None


def test_sap_mock_reset_endpoint_clears_records_and_sessions():
    mock = TestClient(create_sap_mock())
    login = {"CompanyDB": "LIVES_DEMO", "UserName": "mdm_integration", "Password": "demo"}
    assert mock.post("/b1s/v2/Login", json=login).status_code == 200
    r = mock.post(
        "/b1s/v2/BusinessPartners",
        json={"CardCode": "C1", "CardName": "x", "CardType": "cCustomer"},
    )
    assert r.status_code == 201
    out = mock.post("/_mock/reset")
    assert out.status_code == 200 and out.json()["cleared"]["BusinessPartners"] == 1
    assert mock.app.state.stores["BusinessPartners"] == {}
    assert mock.get("/b1s/v2/BusinessPartners").status_code == 401  # sessions are gone too


def test_reset_restores_everything_with_a_connection_held_open(client, monkeypatch):
    from services.api import reset as reset_mod

    # state to throw away: requests, tasks, notifications, audit rows, a moved clock
    d = submit_customer(client, "Reset Me Pte Ltd")
    client.post("/clock/advance", json={"days": 2})
    assert client.get("/requests", params={"scope": "all"}, headers=H("amy")).json()

    # the running app holds an open session with a read in progress and an idle connection
    held = Session(get_engine())
    held.execute(select(m.User)).all()
    idle = get_engine().connect()
    idle.execute(text("SELECT 1"))

    # a SAP mock that IS reachable: the reset must clear it
    mock = TestClient(create_sap_mock())
    login = {"CompanyDB": "LIVES_DEMO", "UserName": "mdm_integration", "Password": "demo"}
    mock.post("/b1s/v2/Login", json=login)
    mock.post(
        "/b1s/v2/BusinessPartners",
        json={"CardCode": "C1", "CardName": "x", "CardType": "cCustomer"},
    )
    monkeypatch.setattr(
        reset_mod.httpx, "post", lambda url, timeout=None: mock.post("/_mock/reset")
    )

    # readers keep working while the reset runs and never see a half-loaded database
    seen: list[int] = []
    errors: list[str] = []
    stop = threading.Event()

    def poll():
        c = TestClient(app)
        while not stop.is_set():
            r = c.get("/emails", headers=H("amy"))
            if r.status_code != 200:
                errors.append(f"{r.status_code} {r.text[:200]}")
            else:
                seen.append(len(r.json()))

    th = threading.Thread(target=poll)
    th.start()
    time.sleep(0.2)
    t0 = time.perf_counter()
    r = client.post("/admin/reset-demo")
    elapsed = time.perf_counter() - t0
    time.sleep(0.2)
    stop.set()
    th.join()
    held.close()
    idle.close()

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and elapsed < 10 and body["duration_ms"] < 10_000
    print(f"reset took {body['duration_ms']:.0f} ms")
    assert body["sap_mock_reset"] is True and mock.app.state.stores["BusinessPartners"] == {}
    assert not errors, errors
    expected_emails = count_lines_jsonl(f"{FIXTURES}/emails.jsonl")
    assert seen and set(seen) == {expected_emails}  # always the complete database

    counts = body["counts"]
    assert counts["users"] == count_lines(_p("users.csv"))
    assert counts["items"] == count_lines(_p("items.csv"))
    assert counts["business_partners"] == count_lines(_p("bp_records.csv")) + count_lines(
        _p("vendors.csv")
    )
    assert counts["orders"] == count_lines(_p("orders.csv"))
    assert counts["requests"] == counts["approval_tasks"] == counts["notifications"] == 0
    assert counts["audit_log"] == 1
    assert datetime.fromisoformat(body["clock"]["now"]) == datetime(2026, 10, 5, 9, 0, tzinfo=SGT)
    with session_scope() as s:
        v = verify_chain(s)
        assert v.ok and v.checked == 1
    assert client.get(f"/requests/{d['req_id']}", headers=H("amy")).status_code == 404
    # the API keeps working: ids start again, the dedup index is fresh
    assert new_request(client)["req_id"] == "REQ-0001"
    assert dedup_service.get_index() is not None
    # a second reset in a row works too (idempotent)
    assert client.post("/admin/reset-demo").json()["counts"] == counts | {"requests": 0}


def test_reset_with_a_broken_fixture_folder_leaves_the_database_alone(client, tmp_path):
    from services.api import reset as reset_mod

    before = reset_mod.table_counts()
    with pytest.raises(reset_mod.SeedError):
        reset_mod.reset_demo(tmp_path)  # no fixture files here
    assert reset_mod.table_counts() == before


def _p(name):
    from pathlib import Path

    return Path(FIXTURES) / name


def count_lines_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())
