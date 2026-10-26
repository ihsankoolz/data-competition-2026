"""Session 13: required-field toggles (Priya switches a field between required and optional per
record type x country), offline.

Reuses the module database and helpers of `test_workflow_api.py`. Toggles are cleared before
every test; the test that proves Reset demo clears them runs last because it wipes the database.
"""

# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from ds.interpreter.api import interpret_email
from services.api.audit import verify_chain
from services.api.db import models as m
from services.api.db.session import session_scope
from tests.test_workflow_api import (  # noqa: F401 - fixtures are used by name
    CUSTOMER,
    H,
    _clock,
    client,
    new_request,
)

OWNS_APP_DB = True  # see tests/conftest.py

SNAPSHOT = Path(__file__).parent / "fixtures" / "required_fields_main_3438e6d.json"
COUNTRIES = ("SG", "MY", "ID", "VN", "TH")


@pytest.fixture(autouse=True)
def _no_toggles(client):
    def wipe():
        with session_scope(write=True) as s:
            s.execute(text("DELETE FROM required_field_overrides"))

    wipe()
    with session_scope() as s:
        _BASELINE["id"] = s.scalar(select(func.coalesce(func.max(m.AuditLog.id), 0)))
    yield
    wipe()


def put(client, domain, country, changes, user="priya"):
    return client.put(
        "/admin/required-fields",
        headers=H(user),
        json={
            "domain": domain,
            "country": country,
            "fields": [{"field": f, "required": r} for f, r in changes.items()],
        },
    )


def form_required(client, domain, country, **params):
    r = client.get(f"/forms/{domain}", params={"country": country, **params})
    assert r.status_code == 200, r.text
    return r.json()["required"]


_BASELINE = {"id": 0}  # the audit log is append-only, so tests only look at their own rows


def config_changes(client):
    rows = client.get("/admin/required-field-changes", headers=H("amy")).json()
    return [r for r in rows if r["id"] > _BASELINE["id"]]


# ---------------------------------------------------------------- nothing changes without toggles


def test_no_toggle_rows_leave_every_required_list_exactly_as_on_main(client):
    """Customer, vendor and item x 5 countries: the form's required list and the missing-fields
    list of a new empty request equal what main (3438e6d) produced before this feature."""
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert len(expected) == 15
    got_required, got_missing = {}, {}
    for key in expected:
        domain, country = key.split("/")
        got_required[key] = form_required(client, domain, country)
        draft = new_request(client, "amy", domain, "SPD", country, {})
        got_missing[key] = draft["missing_fields"]
        with session_scope() as s:
            assert s.get(m.Request, draft["req_id"]).required_snapshot is None
    assert got_required == {k: v["required"] for k, v in expected.items()}
    assert got_missing == {k: v["missing_when_empty"] for k, v in expected.items()}


def test_an_empty_view_matches_the_standard_rules(client):
    r = client.get("/admin/required-fields", headers=H("amy"), params=cust("SG"))
    assert r.status_code == 200
    body = r.json()
    assert "new requests only" in body["note"].lower()
    rows = {f["field"]: f for f in body["fields"]}
    assert [f for f, row in rows.items() if row["required"]] == form_required(
        client, "customer", "SG"
    )
    assert not any(row["changed"] for row in rows.values())
    assert rows["Street"]["standard"] is True and rows["Street"]["locked"] is False
    assert rows["CardName"]["locked"] is True and rows["CardName"]["locked_reason"]
    assert rows["City"]["required"] is False


def cust(country):
    return {"domain": "customer", "country": country}


# ---------------------------------------------------------------- who may change them


def test_only_the_mdm_analyst_can_change_a_field(client):
    for user in ("amy", "marcus", "weijie", "daniel"):
        r = put(client, "customer", "SG", {"City": True}, user=user)
        assert r.status_code == 403, user
        assert "MDM" in r.json()["detail"] or "mdm" in r.json()["detail"].lower()
    assert form_required(client, "customer", "SG") == form_required(client, "customer", "MY")
    assert put(client, "customer", "SG", {"City": True}).status_code == 200


# ---------------------------------------------------------------- optional / required


def test_make_a_field_optional_for_one_country_only(client):
    r = put(client, "customer", "SG", {"Street": False})
    assert r.status_code == 200, r.text
    row = next(f for f in r.json()["fields"] if f["field"] == "Street")
    assert row["required"] is False and row["standard"] is True and row["changed"] is True
    assert "Street" not in form_required(client, "customer", "SG")
    assert "Street" in form_required(client, "customer", "MY")  # other countries unchanged

    fields = {k: v for k, v in CUSTOMER.items() if k != "Street"}
    fields["FederalTaxID"] = "202699001A"
    draft = new_request(client, "amy", "customer", "SPD", "SG", fields)
    assert "Street" not in draft["missing_fields"]
    assert draft["issues"] == []
    assert client.post(f"/requests/{draft['req_id']}/submit", headers=H("amy")).status_code == 200


def test_make_a_field_required_is_enforced_on_submit_and_listed_as_missing(client):
    assert "City" not in form_required(client, "customer", "SG")
    assert put(client, "customer", "SG", {"City": True}).status_code == 200
    assert form_required(client, "customer", "SG") == [
        "CardName",
        "Country",
        "FederalTaxID",
        "City",
        "Street",
        "EmailAddress",
    ]

    fields = {k: v for k, v in CUSTOMER.items() if k != "City"}
    fields["FederalTaxID"] = "202699002B"
    draft = new_request(client, "amy", "customer", "SPD", "SG", fields)
    assert draft["missing_fields"] == ["City"]
    r = client.post(f"/requests/{draft['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 422
    assert [(i["field"], i["kind"]) for i in r.json()["issues"]] == [("City", "missing")]
    assert "City is required" in r.json()["issues"][0]["message"]

    client.patch(
        f"/requests/{draft['req_id']}", headers=H("amy"), json={"fields": {"City": "Singapore"}}
    )
    assert client.post(f"/requests/{draft['req_id']}/submit", headers=H("amy")).status_code == 200


def test_cost_center_dimension_can_be_made_required(client):
    assert put(client, "cost_center", "SG", {"InWhichDimension": True}).status_code == 200
    assert form_required(client, "cost_center", "SG") == [
        "CenterName",
        "EffectiveFrom",
        "InWhichDimension",
    ]
    draft = new_request(
        client,
        "amy",
        "cost_center",
        "SPD",
        "SG",
        {"CenterName": "SPD SG Ops", "EffectiveFrom": "2026-11-02"},
    )
    assert draft["missing_fields"] == ["InWhichDimension"]
    assert client.post(f"/requests/{draft['req_id']}/submit", headers=H("amy")).status_code == 422


def test_switching_back_to_the_standard_removes_the_toggle(client):
    put(client, "customer", "SG", {"Street": False})
    put(client, "customer", "SG", {"Street": True})
    with session_scope() as s:
        assert s.scalars(select(m.RequiredFieldOverride)).all() == []
    assert form_required(client, "customer", "SG") == form_required(client, "customer", "MY")
    # both switches were audited
    assert [c["now_required"] for c in config_changes(client)] == [True, False]


# ---------------------------------------------------------------- locked fields


LOCKED = [
    ("customer", "CardName"),
    ("customer", "Country"),
    ("customer", "FederalTaxID"),
    ("vendor", "CardName"),
    ("vendor", "Country"),
    ("vendor", "FederalTaxID"),
    ("vendor", "BPBankAccounts"),
    ("item", "ItemName"),
    ("item", "U_IVD"),
    ("item", "selling_countries"),
    ("item", "registrations"),
    ("cost_center", "CenterName"),
    ("cost_center", "EffectiveFrom"),
]


@pytest.mark.parametrize(("domain", "field"), LOCKED)
def test_locked_fields_cannot_be_made_optional(client, domain, field):
    # (a valid change in the same save is refused with it: all or nothing)
    other = {"customer": "City", "vendor": "City", "item": "SalesUnit", "cost_center": "purpose"}
    r = put(client, domain, "SG", {other[domain]: True, field: False})
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "can't be made optional" in detail and len(detail) > 40
    with session_scope() as s:
        assert s.scalars(select(m.RequiredFieldOverride)).all() == []
    assert config_changes(client) == []
    view = client.get(
        "/admin/required-fields", headers=H("amy"), params={"domain": domain, "country": "SG"}
    ).json()
    row = next(f for f in view["fields"] if f["field"] == field)
    assert row["locked"] is True and row["required"] is True and row["locked_reason"]


def test_an_unknown_field_is_refused(client):
    r = put(client, "customer", "SG", {"CreditRating": True})
    assert r.status_code == 422 and "not a field on the customer form" in r.json()["detail"]


def test_asking_a_locked_field_to_stay_required_is_not_an_error(client):
    assert put(client, "customer", "SG", {"CardName": True}).status_code == 200
    assert config_changes(client) == []


# ---------------------------------------------------------------- new requests only


def test_a_request_keeps_the_rules_it_was_created_with(client):
    fields = {k: v for k, v in CUSTOMER.items() if k != "City"}
    fields["FederalTaxID"] = "202699003C"
    early = new_request(client, "amy", "customer", "SPD", "SG", fields)
    assert early["missing_fields"] == []

    put(client, "customer", "SG", {"City": True})
    # the request made before the change still needs nothing more, and can be submitted
    again = client.get(f"/requests/{early['req_id']}", headers=H("amy")).json()
    assert again["missing_fields"] == []
    assert "City" not in form_required(client, "customer", "SG", req_id=early["req_id"])
    assert "City" in form_required(client, "customer", "SG")
    r = client.post(f"/requests/{early['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 200, r.text

    # one made afterwards needs it
    fields["FederalTaxID"] = "202699004D"
    late = new_request(client, "amy", "customer", "SPD", "SG", fields)
    assert late["missing_fields"] == ["City"]
    # ...and keeps needing it after the toggle is switched off again
    put(client, "customer", "SG", {"City": False})
    assert client.get(f"/requests/{late['req_id']}", headers=H("amy")).json()["missing_fields"] == [
        "City"
    ]
    assert "City" in form_required(client, "customer", "SG", req_id=late["req_id"])


# ---------------------------------------------------------------- audit


def test_every_change_is_audited_and_the_chain_stays_intact(client):
    r = put(client, "vendor", "VN", {"City": True, "Street": False})
    assert r.status_code == 200
    changes = config_changes(client)
    assert {c["field"] for c in changes} == {"City", "Street"}
    assert all(c["who"] == "Priya" and c["domain"] == "vendor" for c in changes)
    assert "Priya made City required for Vietnam vendors" in {c["summary"] for c in changes}
    with session_scope() as s:
        rows = s.scalars(
            select(m.AuditLog).where(
                m.AuditLog.action == "config_change",
                m.AuditLog.entity_type == "required_field",
                m.AuditLog.id > _BASELINE["id"],
            )
        ).all()
        assert len(rows) == 2 and all(r.actor == "priya" for r in rows)
        assert all(r.hash and r.prev_hash for r in rows)
        assert verify_chain(s).ok
    # the approval-rules history is unaffected by these rows
    assert client.get("/admin/config-changes", headers=H("amy")).json() == []


# ---------------------------------------------------------------- the AI path is untouched


def test_toggles_do_not_change_what_the_interpreter_reads(client, monkeypatch):
    """Toggles apply after the model's output, in deterministic code. The reading of every demo
    email (and so the replay-cache key it was built from) is identical with and without them."""
    monkeypatch.setenv("LLM_MODE", "replay")
    fixtures = Path("data/fixtures/seasonal_trend/emails.jsonl")
    emails = [
        e
        for e in map(json.loads, fixtures.read_text(encoding="utf-8").splitlines())
        if e["email_id"].startswith("DEMO-")
    ]
    assert len(emails) == 8

    def read_all():
        out = {}
        for e in emails:
            i = interpret_email(e["email_id"], e["subject"], e["body"], e["from_address"])
            assert i.ai_status == "ok", (e["email_id"], i.ai_status)
            out[e["email_id"]] = i.model_dump(mode="json")
        return out

    before = read_all()
    assert put(client, "customer", "SG", {"City": True, "Street": False}).status_code == 200
    assert put(client, "item", "SG", {"SalesUnit": True}).status_code == 200
    assert read_all() == before


# ---------------------------------------------------------------- reset demo (last: wipes the DB)


def test_reset_demo_clears_the_toggles(client):
    assert put(client, "customer", "SG", {"City": True, "Street": False}).status_code == 200
    assert "City" in form_required(client, "customer", "SG")
    r = client.post("/admin/reset-demo")
    assert r.status_code == 200, r.text
    with session_scope() as s:
        assert s.scalars(select(m.RequiredFieldOverride)).all() == []
    assert config_changes(client) == []
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert form_required(client, "customer", "SG") == expected["customer/SG"]["required"]
    view = client.get("/admin/required-fields", headers=H("amy"), params=cust("SG")).json()
    assert not any(f["changed"] for f in view["fields"])
