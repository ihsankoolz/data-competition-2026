"""Session 5, backend track: linked_card_name, ask-for-info -> edit -> resubmit (D-020 #3),
item prefill from email, foreign vendors (D-020 #2).

Reuses the module database and helpers of `test_workflow_api.py` (offline, replay mode).
"""

# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
from __future__ import annotations

from services.api import clock
from tests.test_workflow_api import (  # noqa: F401 - fixtures are used by name
    H,
    _clock,
    client,
    decide,
    new_request,
    sap_mock,
    tasks_by_role,
)

OWNS_APP_DB = True  # see tests/conftest.py


# ---------------------------------------------------------------- (a) linked_card_name


def test_linked_card_name_is_filled_when_linked(client):
    fields = {
        "CardName": "Benh vien Cho Ray",
        "Country": "VN",
        "City": "HCMC",
        "FederalTaxID": "0301234567",
        "Street": "201B Nguyen Chi Thanh",
        "EmailAddress": "mua@choray.example",
    }
    req = new_request(client, "marcus", "customer", "QTG", "VN", fields)
    assert req["linked_card_code"] is None and req["linked_card_name"] is None
    chk = client.post(
        "/dedup/check",
        headers=H("marcus"),
        json={"domain": "customer", "entity": "QTG", "fields": fields},
    ).json()
    existing = chk["candidates"][0]
    r = client.post(
        f"/requests/{req['req_id']}/dedup-decision",
        headers=H("marcus"),
        json={"action": "link_to_existing", "card_code": existing["CardCode"]},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["linked_card_code"] == existing["CardCode"]
    assert d["linked_card_name"] == existing["CardName"]
    again = client.get(f"/requests/{req['req_id']}", headers=H("marcus")).json()
    assert again["linked_card_name"] == existing["CardName"]


# ---------------------------------------------------------------- (b) ask for info -> resubmit

IVD_ITEM = {
    "ItemName": "Resubmit Rapid Test",
    "U_IVD": "tYES",
    "selling_countries": ["SG"],
    "registrations": [{"country": "SG", "reg_no": "S-1", "expiry_date": "2030-12-31"}],
}
SG_REG = {"country": "SG", "reg_no": "S-1", "expiry_date": "2030-12-31"}
VN_REG = {"country": "VN", "reg_no": "V-1", "expiry_date": "2030-12-31"}


def _submit_item(client, name):
    req = new_request(client, "amy", "item", "SPD", "SG", {**IVD_ITEM, "ItemName": name})
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 200, r.text
    return r.json()


def test_info_request_is_described_for_the_requestor(client):
    d = _submit_item(client, "Info View Rapid Test")
    assert d["info_request"] is None
    qr = tasks_by_role(d)[("quality_regulatory", "SG")]
    clock.reset()
    client.post("/clock/advance", json={"hours": 3})
    r = decide(client, qr["task_id"], "joanne", "ask_info", "Which risk class is this?")
    assert r.status_code == 200
    info = r.json()["info_request"]
    assert info["task_id"] == qr["task_id"]
    assert info["asked_by_user_id"] == "joanne" and info["asked_by_name"] == "Joanne Yeo"
    assert info["role"] == "quality_regulatory"
    assert info["question"] == "Which risk class is this?"
    assert info["asked_at"].startswith("2026-10-05T12:00")
    mine = client.get(f"/requests/{d['req_id']}", headers=H("amy")).json()
    assert mine["state"] == "INFO_REQUESTED" and mine["info_request"] == info


def test_resubmit_keeps_given_approvals_and_reopens_only_the_asker(client):
    d = _submit_item(client, "Keep Approvals Rapid Test")
    rid, t = d["req_id"], tasks_by_role(d)
    assert decide(client, t[("bu_head", None)]["task_id"], "daniel").status_code == 200
    assert decide(client, t[("business_support", None)]["task_id"], "meiling").status_code == 200
    sg = t[("quality_regulatory", "SG")]
    old_due = sg["due_at"]
    assert decide(client, sg["task_id"], "joanne", "ask_info", "Risk class?").status_code == 200

    client.post("/clock/advance", json={"days": 1})
    r = client.patch(
        f"/requests/{rid}",
        headers=H("amy"),
        json={"fields": {"registrations": [{**SG_REG, "risk_class": "B"}]}},
    )
    assert r.status_code == 200 and r.json()["info_request"] is not None
    r = client.post(f"/requests/{rid}/submit", headers=H("amy"))
    assert r.status_code == 200, r.text
    d = r.json()
    t = tasks_by_role(d)
    assert d["state"] == "IN_APPROVAL" and d["info_request"] is None
    # approvals already given stay given; same task rows, nobody re-routed
    assert t[("bu_head", None)]["status"] == "approved"
    assert t[("business_support", None)]["status"] == "approved"
    assert t[("bu_head", None)]["decided_by"] == "daniel"
    # only the asker reopens, with a fresh SLA from the simulated clock
    assert t[("quality_regulatory", "SG")]["task_id"] == sg["task_id"]
    assert t[("quality_regulatory", "SG")]["status"] == "pending"
    assert t[("quality_regulatory", "SG")]["due_at"] > old_due
    assert len([x for st in d["stages"] for x in st["tasks"]]) == 4  # no second routing
    inbox = client.get("/approvals/inbox", headers=H("joanne")).json()
    assert any(i["request"]["req_id"] == rid for i in inbox)
    note = client.get("/notifications", headers=H("joanne")).json()[0]
    assert note["kind"] == "task_assigned" and "answered your question" in note["message"]
    audit = client.get(f"/requests/{rid}/audit", headers=H("amy")).json()
    summaries = [e["summary"] for e in audit]
    assert any("changed: registrations; back with Quality / Regulatory (SG)" in s
               for s in summaries)  # fmt: skip
    # the edit itself was audited field by field
    assert any(e["action"] == "field_edit" for e in audit)

    # and it can finish: the last approval completes stage 1
    r = decide(client, sg["task_id"], "joanne")
    assert r.json()["state"] == "APPROVED"


def test_resubmit_adds_a_task_when_the_edit_changes_routing(client):
    d = _submit_item(client, "Routing Change Rapid Test")
    rid, t = d["req_id"], tasks_by_role(d)
    decide(client, t[("bu_head", None)]["task_id"], "daniel")
    sg = t[("quality_regulatory", "SG")]
    decide(client, sg["task_id"], "joanne", "ask_info", "Are you selling this anywhere else?")
    r = client.patch(
        f"/requests/{rid}",
        headers=H("amy"),
        json={"fields": {"selling_countries": ["SG", "VN"], "registrations": [SG_REG, VN_REG]}},
    )
    assert r.status_code == 200, r.text
    d = client.post(f"/requests/{rid}/submit", headers=H("amy")).json()
    t = tasks_by_role(d)
    assert d["state"] == "IN_APPROVAL"
    assert t[("bu_head", None)]["status"] == "approved"  # kept
    assert t[("quality_regulatory", "SG")]["status"] == "pending"  # reopened
    vn = t[("quality_regulatory", "VN")]  # new
    assert vn["status"] == "pending" and vn["assignee_user_id"] == "lan"
    assert "task_assigned" in [
        n["kind"] for n in client.get("/notifications", headers=H("lan")).json()
    ]
    assert len(t) == 5  # 4 original + the new Vietnam reviewer


def test_resubmit_is_revalidated_and_blocked_while_invalid(client):
    d = _submit_item(client, "Revalidate Rapid Test")
    qr = tasks_by_role(d)[("quality_regulatory", "SG")]
    decide(client, qr["task_id"], "joanne", "ask_info", "Registration expiry?")
    client.patch(
        f"/requests/{d['req_id']}",
        headers=H("amy"),
        json={"fields": {"registrations": [{**SG_REG, "expiry_date": "2020-01-01"}]}},
    )
    r = client.post(f"/requests/{d['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 422 and r.json()["issues"]
    assert client.get(f"/requests/{d['req_id']}", headers=H("amy")).json()["state"] == (
        "INFO_REQUESTED"
    )


def test_only_the_requestor_can_resubmit(client):
    d = _submit_item(client, "Only Requestor Rapid Test")
    qr = tasks_by_role(d)[("quality_regulatory", "SG")]
    decide(client, qr["task_id"], "joanne", "ask_info", "Anything to add?")
    rid = d["req_id"]
    for who in ("joanne", "daniel", "weijie", "priya", "marcus"):
        r = client.post(f"/requests/{rid}/submit", headers=H(who))
        assert r.status_code == 403, (who, r.text)
        r = client.patch(f"/requests/{rid}", headers=H(who), json={"fields": {"purpose": "x"}})
        assert r.status_code == 403, who
    assert client.get(f"/requests/{rid}", headers=H("amy")).json()["state"] == "INFO_REQUESTED"
    assert client.post(f"/requests/{rid}/submit", headers=H("amy")).status_code == 200


def test_resubmit_after_bank_change_still_reopens_finance(client):
    """The safety exception: what Finance signed off on changed, so Finance looks again."""
    bank = [{"BankCode": "7171", "AccountNo": "1111222233", "AccountName": "V", "Country": "SG"}]
    fields = {
        "CardName": "Safety Exception Vendor Pte Ltd",
        "Country": "SG",
        "FederalTaxID": "202600002S",
        "Street": "1 Road",
        "City": "Singapore",
        "EmailAddress": "a@b.example",
        "BPBankAccounts": bank,
    }
    d = client.post(
        f"/requests/{new_request(client, 'amy', 'vendor', 'SPD', 'SG', fields)['req_id']}/submit",
        headers=H("amy"),
    ).json()
    t = tasks_by_role(d)
    decide(client, t[("finance", None)]["task_id"], "weijie")
    decide(client, t[("business_support", None)]["task_id"], "meiling")
    decide(client, t[("bu_head", None)]["task_id"], "daniel", "ask_info", "Which bank?")
    client.patch(
        f"/requests/{d['req_id']}",
        headers=H("amy"),
        json={"fields": {"BPBankAccounts": [{**bank[0], "AccountNo": "9999888877"}]}},
    )
    t = tasks_by_role(client.post(f"/requests/{d['req_id']}/submit", headers=H("amy")).json())
    assert t[("finance", None)]["status"] == "pending"
    assert t[("business_support", None)]["status"] == "approved"  # untouched by the change


# ---------------------------------------------------------------- resubmit governance (D-020 #3)


def _approved_item_with_question(client, name):
    """BU head and Business Support approved; Q/R (SG) asked a question."""
    d = _submit_item(client, name)
    t = tasks_by_role(d)
    decide(client, t[("bu_head", None)]["task_id"], "daniel")
    decide(client, t[("business_support", None)]["task_id"], "meiling")
    qr = t[("quality_regulatory", "SG")]
    assert (
        decide(client, qr["task_id"], "joanne", "ask_info", "Is the name right?").status_code == 200
    )
    return d["req_id"]


def _audit_summaries(client, rid):
    return [e["summary"] for e in client.get(f"/requests/{rid}/audit", headers=H("amy")).json()]


def test_an_identity_edit_reopens_every_earlier_approval(client):
    rid = _approved_item_with_question(client, "Identity Edit Rapid Test")
    client.patch(
        f"/requests/{rid}", headers=H("amy"), json={"fields": {"ItemName": "Identity Edit Test v2"}}
    )
    d = client.post(f"/requests/{rid}/submit", headers=H("amy")).json()
    t = tasks_by_role(d)
    assert d["state"] == "IN_APPROVAL"
    assert {t[k]["status"] for k in t if k[0] != "mdm_analyst"} == {"pending"}
    assert any("changed: ItemName; back with" in s for s in _audit_summaries(client, rid))


def test_a_non_identity_edit_keeps_the_other_approvals(client):
    rid = _approved_item_with_question(client, "Plain Edit Rapid Test")
    client.patch(f"/requests/{rid}", headers=H("amy"), json={"fields": {"purpose": "Tender 7"}})
    t = tasks_by_role(client.post(f"/requests/{rid}/submit", headers=H("amy")).json())
    assert t[("bu_head", None)]["status"] == "approved"
    assert t[("business_support", None)]["status"] == "approved"
    assert t[("quality_regulatory", "SG")]["status"] == "pending"


def test_dropping_the_asking_task_reopens_the_others_and_never_jumps_to_approved(client):
    rid = _approved_item_with_question(client, "Dropped Asker Rapid Test")
    r = client.patch(
        f"/requests/{rid}",
        headers=H("amy"),
        json={"fields": {"U_IVD": "tNO", "registrations": []}},
    )
    assert r.status_code == 200, r.text
    d = client.post(f"/requests/{rid}/submit", headers=H("amy")).json()
    t = tasks_by_role(d)
    assert d["state"] == "IN_APPROVAL"  # not APPROVED
    assert t[("quality_regulatory", "SG")]["status"] == "cancelled"
    assert t[("bu_head", None)]["status"] == "pending"
    assert t[("business_support", None)]["status"] == "pending"


def test_the_resubmit_summary_names_changed_fields_but_never_bank_values(client):
    bank = [{"BankCode": "7171", "AccountNo": "4444555566", "AccountName": "N", "Country": "SG"}]
    fields = {
        "CardName": "Audit Names Vendor Pte Ltd",
        "Country": "SG",
        "FederalTaxID": "202600003S",
        "Street": "1 Road",
        "City": "Singapore",
        "EmailAddress": "a@b.example",
        "BPBankAccounts": bank,
    }
    req = new_request(client, "amy", "vendor", "SPD", "SG", fields)
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    decide(client, tasks_by_role(d)[("bu_head", None)]["task_id"], "daniel", "ask_info", "Bank?")
    client.patch(
        f"/requests/{req['req_id']}",
        headers=H("amy"),
        json={"fields": {"BPBankAccounts": [{**bank[0], "AccountNo": "7777888899"}]}},
    )
    client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    text = " ".join(_audit_summaries(client, req["req_id"]))
    assert "changed: BPBankAccounts" in text
    assert "7777888899" not in text and "4444555566" not in text


def test_reset_reports_a_failing_sap_mock_reset_instead_of_swallowing_it(
    client, monkeypatch, caplog
):
    from services.api import reset as reset_mod

    def boom(*_a, **_k):
        raise RuntimeError("mock exploded")

    monkeypatch.setattr(reset_mod, "reset_sap_mock", boom)
    r = client.post("/admin/reset-demo")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["sap_mock_reset"] is False
    assert "SAP mock reset failed" in caplog.text
