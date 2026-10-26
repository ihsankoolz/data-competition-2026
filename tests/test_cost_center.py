"""Session 13: Cost Center on "New request" (schema-driven form, same routing/approval/publish).

Reuses the module database and helpers of `test_workflow_api.py`. Offline: the SAP mock is
driven in process.
"""

# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
from __future__ import annotations

import json

from sqlalchemy import select

from services.api.audit import verify_chain
from services.api.db import models as m
from services.api.db.session import session_scope
from tests.test_workflow_api import (  # noqa: F401 - fixtures are used by name
    H,
    _clock,
    approve_stage_one,
    client,
    new_request,
    sap_mock,
    tasks_by_role,
)

OWNS_APP_DB = True  # see tests/conftest.py

COST_CENTER = {
    "CenterName": "SPD SG Tender Desk",
    "EffectiveFrom": "2026-11-02",
    "InWhichDimension": 2,
    "purpose": "Tracks the cost of preparing public tenders.",
}


def published_key(req_id):
    with session_scope() as s:
        return s.get(m.Request, req_id).published_key


def test_form_is_schema_driven_like_the_other_three(client):
    spec = client.get("/forms/cost_center", params={"country": "SG"}).json()
    props = spec["json_schema"]["properties"]
    assert spec["required"] == ["CenterName", "EffectiveFrom"]
    assert props["CenterName"]["maxLength"] == 30
    assert props["EffectiveFrom"]["format"] == "date"
    assert [o["const"] for o in props["InWhichDimension"]["oneOf"]] == [1, 2, 3, 4, 5]
    assert "distribution rule" in spec["sap_note"]


def test_name_longer_than_30_characters_is_refused_in_plain_english(client):
    req = new_request(
        client, fields={"CenterName": "x" * 31, "EffectiveFrom": "2026-11-02"}, domain="cost_center"
    )
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 422
    assert any(i["field"] == "CenterName" and i["kind"] == "too_long" for i in r.json()["issues"])


def test_missing_name_and_date_are_listed(client):
    req = new_request(client, domain="cost_center")
    assert req["missing_fields"] == ["CenterName", "EffectiveFrom"]
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 422
    assert "Cost center name" in r.json()["detail"] and "Effective from" in r.json()["detail"]


def test_unknown_field_is_refused(client):
    r = client.post(
        "/requests",
        headers=H("amy"),
        json={
            "domain": "cost_center",
            "entity": "SPD",
            "country": "SG",
            "fields": {"CenterCode": "PC9999"},
        },
    )
    assert r.status_code == 422 and "CenterCode" in r.json()["detail"]


def test_submit_approve_publish_to_the_mock_and_audit(client, sap_mock):
    req = new_request(client, domain="cost_center", fields=COST_CENTER)
    assert req["missing_fields"] == [] and req["issues"] == []
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    assert d["state"] == "IN_APPROVAL"
    # Finance + BU Head review in stage 1, then MDM publishes (config/routing_rules.yaml).
    assert set(tasks_by_role(d)) == {("finance", None), ("bu_head", None), ("mdm_analyst", None)}
    d = approve_stage_one(client, d, {("finance", None): "weijie", ("bu_head", None): "daniel"})
    assert d["state"] == "APPROVED"
    d = client.post(f"/requests/{d['req_id']}/publish", headers=H("priya")).json()
    assert d["state"] == "ACTIVE"
    rid = d["req_id"]
    code = published_key(rid)
    assert code.startswith("PC") and len(code) <= 8

    record = sap_mock.app.state.stores["ProfitCenters"][code]
    assert record["CenterName"] == "SPD SG Tender Desk"
    assert record["EffectiveFrom"] == "2026-11-02"
    assert record["InWhichDimension"] == 2
    assert record["Active"] == "tYES"  # created tNO, read back, then activated

    with session_scope() as s:
        calls = [
            json.loads(p)
            for p in s.scalars(
                select(m.AuditLog.payload).where(
                    m.AuditLog.request_id == rid, m.AuditLog.action == "sap_call"
                )
            )
        ]
        assert verify_chain(s).ok
    methods = [(c.get("method"), c.get("path", "")) for c in calls]
    post = next(i for i, (mth, p) in enumerate(methods) if mth == "POST" and "ProfitCenters" in p)
    get = next(i for i, (mth, p) in enumerate(methods) if mth == "GET" and "ProfitCenters" in p)
    patch = next(i for i, (mth, p) in enumerate(methods) if mth == "PATCH" and "ProfitCenters" in p)
    assert post < get < patch  # create inactive -> read back -> activate
    assert calls[post]["body"]["Active"] == "tNO"
    assert calls[patch]["body"]["Active"] == "tYES"

    audit = [e["summary"] for e in client.get(f"/requests/{rid}/audit", headers=H("amy")).json()]
    assert "Wei Jie approved (Finance)" in audit
    assert any("is now active" in s for s in audit)


def test_dimension_defaults_to_one_when_not_chosen(client, sap_mock):
    fields = {"CenterName": "QTG VN Service Hanoi", "EffectiveFrom": "2026-11-02"}
    req = new_request(client, "marcus", "cost_center", "QTG", "VN", fields)
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("marcus")).json()
    assert d["state"] == "IN_APPROVAL"
    who = {
        t["role"]: t["assignee_user_id"]
        for st in d["stages"]
        for t in st["tasks"]
        if st["number"] == 1
    }
    d = approve_stage_one(
        client, d, {("finance", None): who["finance"], ("bu_head", None): who["bu_head"]}
    )
    d = client.post(f"/requests/{d['req_id']}/publish", headers=H("priya")).json()
    assert d["state"] == "ACTIVE"
    assert sap_mock.app.state.stores["ProfitCenters"][published_key(d["req_id"])]["InWhichDimension"] == 1
