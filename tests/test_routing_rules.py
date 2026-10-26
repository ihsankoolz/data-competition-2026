"""Session 12, item B: editable approval rules (stage 1 overrides), offline.

Reuses the module database and helpers of `test_workflow_api.py`. Overrides are cleared before
every test; the test that proves Reset demo clears them runs last because it wipes the database.
"""

# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
from __future__ import annotations

import itertools

import pytest
from sqlalchemy import select, text

from services.api import clock
from services.api.audit import verify_chain
from services.api.db import models as m
from services.api.db.session import session_scope
from tests.test_route_snapshot import tasks as snapshot_tasks
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

_n = itertools.count(1)

VN_CUSTOMER_KEY = {"domain": "customer", "entity": "QTG", "country": "VN"}
LAN_STEPS = [
    {"role": "bu_head", "user_id": "tuan"},
    {"role": "finance", "user_id": "weijie"},
    {"role": "business_support", "user_id": "meiling"},
    {"role": "quality_regulatory", "user_id": "lan"},
]


@pytest.fixture(autouse=True)
def _no_overrides(client):
    def wipe():
        with session_scope(write=True) as s:
            s.execute(text("DELETE FROM routing_overrides"))

    wipe()
    yield
    wipe()


def put(client, user="priya", key=None, steps=None):
    return client.put(
        "/admin/routing-rules",
        headers=H(user),
        json={**(key or VN_CUSTOMER_KEY), "steps": LAN_STEPS if steps is None else steps},
    )


def last_change(client):
    """Id of the newest rule change (0 if none): the audit log is append-only, so tests compare
    this before and after instead of expecting an empty list."""
    rows = client.get("/admin/config-changes", headers=H("amy")).json()
    return rows[0]["id"] if rows else 0


def vn_customer(client):
    """A Vietnam customer for QTG, submitted by Marcus; returns the detail."""
    i = next(_n)
    fields = {
        "CardName": f"Rules Test Medical {i} Co Ltd",
        "Country": "VN",
        "FederalTaxID": f"88{i:08d}",
        "Street": "1 Test Street",
        "City": "Hanoi",
        "EmailAddress": f"ap{i}@rulestest.example",
    }
    req = new_request(client, "marcus", "customer", "QTG", "VN", fields)
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("marcus"))
    assert r.status_code == 200, r.text
    return r.json()


def people(detail):
    return {(r[0], r[2], r[4]) for r in snapshot_tasks(detail)}  # (stage, role, user)


def preview(client, steps=None, key=None):
    body = {**(key or VN_CUSTOMER_KEY)}
    if steps is not None:
        body["steps"] = steps
    r = client.post("/admin/routing-rules/preview", headers=H("amy"), json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- reading


def test_list_shows_every_key_with_the_standard_route_and_who_can_be_chosen(client):
    r = client.get("/admin/routing-rules", headers=H("amy"))
    assert r.status_code == 200, r.text
    body = r.json()
    rules = body["rules"]
    assert len(rules) == 2 * 3 * 5 + 3 + 3  # customer+vendor per country, item+cost center "*"
    assert not any(x["is_override"] for x in rules)
    vn = next(
        x for x in rules if (x["domain"], x["entity"], x["country"]) == ("customer", "QTG", "VN")
    )
    assert [(s["role"], s["user_id"], s["name"]) for s in vn["steps"]] == [
        ("bu_head", "tuan", "Nguyễn Minh Tuấn"),
        ("finance", "weijie", "Wei Jie"),
        ("business_support", "meiling", "Mei Ling"),
    ]
    assert vn["steps"][0]["role_label"] == "BU Head"
    item = next(x for x in rules if (x["domain"], x["entity"]) == ("item", "SPD"))
    assert item["country"] == "*"
    qr = next(x for x in body["roles"] if x["role"] == "quality_regulatory")
    assert "lan" in {p["user_id"] for p in qr["people"]}
    assert "weijie" not in {p["user_id"] for p in qr["people"]}
    assert "Priya" in body["publish_note"]


def test_the_rule_endpoints_need_an_acting_user(client):
    assert client.get("/admin/routing-rules").status_code == 400
    assert client.get("/admin/config-changes").status_code == 400


# ---------------------------------------------------------------- saving


def test_zero_approvers_is_a_plain_422(client):
    r = put(client, steps=[])
    assert r.status_code == 422
    assert "at least one approver" in r.json()["detail"]


def test_unknown_user_is_a_plain_422(client):
    r = put(client, steps=[{"role": "finance", "user_id": "nobody"}])
    assert r.status_code == 422
    assert "not a known person" in r.json()["detail"]


def test_a_user_without_the_steps_role_is_a_plain_422(client):
    r = put(client, steps=[{"role": "finance", "user_id": "daniel"}])
    assert r.status_code == 422
    assert "Daniel does not hold the Finance role" in r.json()["detail"]


def test_a_repeated_person_and_a_wrong_key_are_plain_422s(client):
    before = last_change(client)
    twice = [{"role": "finance", "user_id": "weijie"}] * 2
    assert "listed twice" in put(client, steps=twice).json()["detail"]
    r = put(client, key={**VN_CUSTOMER_KEY, "country": "*"})
    assert r.status_code == 422 and "Choose a country" in r.json()["detail"]
    r = put(client, key={"domain": "item", "entity": "SPD", "country": "SG"})
    assert r.status_code == 422 and "all countries" in r.json()["detail"]
    assert last_change(client) == before  # nothing was saved or audited


@pytest.mark.parametrize("user", ["amy", "marcus", "weijie", "daniel"])
def test_only_the_mdm_team_can_change_rules(client, user):
    r = put(client, user=user)
    assert r.status_code == 403
    assert "change approval rules" in r.json()["detail"]
    d = client.delete("/admin/routing-rules", headers=H(user), params=VN_CUSTOMER_KEY)
    assert d.status_code == 403
    rules = client.get("/admin/routing-rules", headers=H("amy")).json()["rules"]
    assert not any(x["is_override"] for x in rules)


def test_saving_writes_an_audit_row_with_who_when_and_before_after(client):
    clock.reset()
    client.post("/clock/advance", json={"days": 2})
    stamped = clock.now()
    r = put(client)
    assert r.status_code == 200, r.text
    rule = r.json()
    assert rule["is_override"] and rule["changed_by"] == "Priya"
    assert [s["user_id"] for s in rule["steps"]] == [s["user_id"] for s in LAN_STEPS]

    with session_scope() as s:
        row = s.scalars(
            select(m.AuditLog)
            .where(m.AuditLog.action == "config_change")
            .order_by(m.AuditLog.id.desc())
        ).first()
        assert row is not None
        assert row.actor == "priya"
        assert row.ts == stamped.isoformat()  # the simulated clock, not the wall clock
        assert row.entity_id == "customer/QTG/VN"
        assert row.request_id is None
        assert verify_chain(s).ok

    change = client.get("/admin/config-changes", headers=H("amy")).json()[0]
    assert change["who"] == "Priya"
    assert change["at"].startswith(stamped.isoformat()[:16])
    assert change["before"] == [
        "BU Head: Nguyễn Minh Tuấn",
        "Finance: Wei Jie",
        "Business Support: Mei Ling",
    ]
    assert change["after"][-1] == "Quality / Regulatory: Nguyễn Thị Lan"
    assert "QTG customers (VN)" in change["summary"]

    # a second change shows the first as its "before", newest first
    put(client, steps=[{"role": "bu_head", "user_id": "tuan"}])
    first, second = client.get("/admin/config-changes", headers=H("amy")).json()[:2]
    assert first["after"] == ["BU Head: Nguyễn Minh Tuấn"]
    assert first["before"] == second["after"]


def test_the_status_page_audit_of_a_request_is_unchanged_by_rule_rows(client):
    put(client)
    d = vn_customer(client)
    r = client.get(f"/requests/{d['req_id']}/audit", headers=H("marcus"))
    assert r.status_code == 200
    assert all(e["action"] != "config_change" for e in r.json())


def test_reset_puts_a_key_back_to_the_standard_route_and_is_audited(client):
    put(client)
    r = client.delete("/admin/routing-rules", headers=H("priya"), params=VN_CUSTOMER_KEY)
    assert r.status_code == 200 and r.json()["is_override"] is False
    assert len(r.json()["steps"]) == 3
    assert (
        "back to the standard route"
        in client.get("/admin/config-changes", headers=H("amy")).json()[0]["summary"]
    )
    # and nothing happens (no audit row) when there was nothing to reset
    before = last_change(client)
    client.delete("/admin/routing-rules", headers=H("priya"), params=VN_CUSTOMER_KEY)
    assert last_change(client) == before


# ---------------------------------------------------------------- routing


def test_a_new_request_picks_up_the_override_and_other_keys_do_not(client):
    plain = vn_customer(client)
    assert ("quality_regulatory" in {r[2] for r in snapshot_tasks(plain)}) is False

    assert put(client).status_code == 200
    d = vn_customer(client)
    assert people(d) == {
        (1, "bu_head", "tuan"),
        (1, "finance", "weijie"),
        (1, "business_support", "meiling"),
        (1, "quality_regulatory", "lan"),
        (2, "mdm_analyst", "priya"),
    }
    # Lan has the task in her inbox; the MDM publish stage still waits
    inbox = client.get("/approvals/inbox", headers=H("lan")).json()
    assert any(i["request"]["req_id"] == d["req_id"] for i in inbox)
    assert tasks_by_role(d)[("mdm_analyst", None)]["status"] == "waiting"

    # a Thai customer for the same entity is not touched
    fields = {
        "CardName": f"Thai Rules Test {next(_n)} Co Ltd",
        "Country": "TH",
        "FederalTaxID": f"77{next(_n):011d}",
        "Street": "1 Test Road",
        "City": "Bangkok",
        "EmailAddress": "ap@thaitest.example",
    }
    req = new_request(client, "marcus", "customer", "QTG", "TH", fields)
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("marcus"))
    assert r.status_code == 200, r.text
    assert "lan" not in {x[4] for x in snapshot_tasks(r.json())}

    # the whole route can be approved: the override does not break the flow
    t = tasks_by_role(d)
    for (role, country), user in {
        ("bu_head", None): "tuan",
        ("finance", None): "weijie",
        ("business_support", None): "meiling",
        ("quality_regulatory", None): "lan",
    }.items():
        res = decide(client, t[(role, country)]["task_id"], user)
        assert res.status_code == 200, res.text
    assert res.json()["state"] == "APPROVED"


def test_the_bank_rule_and_ivd_add_ons_still_apply_on_top_of_an_override(client):
    item_key = {"domain": "item", "entity": "SPD", "country": "*"}
    steps = [{"role": "bu_head", "user_id": "kelvin"}]
    assert put(client, key=item_key, steps=steps).status_code == 200
    fields = {
        "ItemName": f"Override IVD Kit {next(_n)}",
        "U_IVD": "tYES",
        "selling_countries": ["SG", "VN"],
        "registrations": [
            {"country": c, "reg_no": f"R-{c}", "expiry_date": "2030-12-31"} for c in ("SG", "VN")
        ],
    }
    req = new_request(client, "amy", "item", "SPD", "SG", fields)
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    assert people(d) == {
        (1, "bu_head", "kelvin"),  # the override, not Daniel and not Mei Ling
        (1, "quality_regulatory", "joanne"),  # the IVD add-ons, per selling country
        (1, "quality_regulatory", "lan"),
        (2, "mdm_analyst", "priya"),
    }


def _item_in_flight(client, name):
    fields = {
        "ItemName": name,
        "U_IVD": "tYES",
        "selling_countries": ["SG"],
        "registrations": [{"country": "SG", "reg_no": "S-1", "expiry_date": "2030-12-31"}],
    }
    req = new_request(client, "amy", "item", "SPD", "SG", fields)
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 200, r.text
    return r.json()


def _ask_edit_resubmit(client, d):
    t = tasks_by_role(d)
    sg = t[("quality_regulatory", "SG")]
    assert decide(client, sg["task_id"], "joanne", "ask_info", "Risk class?").status_code == 200
    r = client.patch(
        f"/requests/{d['req_id']}",
        headers=H("amy"),
        json={"fields": {"registrations": [{
            "country": "SG", "reg_no": "S-1", "expiry_date": "2030-12-31", "risk_class": "B"}]}},
    )  # fmt: skip
    assert r.status_code == 200, r.text
    r = client.post(f"/requests/{d['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 200, r.text
    return r.json()


def test_an_in_flight_request_and_its_resubmit_keep_the_old_route(client):
    item_key = {"domain": "item", "entity": "SPD", "country": "*"}
    d = _item_in_flight(client, f"In Flight Kit {next(_n)}")
    old = people(d)
    assert (1, "business_support", "meiling") in old

    # the rule changes while the request is in approval
    steps = [{"role": "bu_head", "user_id": "kelvin"}]
    assert put(client, key=item_key, steps=steps).status_code == 200
    after = _ask_edit_resubmit(client, d)
    assert after["state"] == "IN_APPROVAL"
    assert people(after) == old  # same people; no Kelvin, nobody cancelled
    assert all(r[5] != "cancelled" for r in snapshot_tasks(after))
    assert sum(1 for st in after["stages"] for t in st["tasks"] if t["role"] == "bu_head") == 1

    # a request routed from now on does use the new rule
    fresh = _item_in_flight(client, f"Fresh Kit {next(_n)}")
    assert (1, "bu_head", "kelvin") in people(fresh)
    assert (1, "business_support", "meiling") not in people(fresh)


def test_a_request_keeps_its_override_after_the_rule_is_reset(client):
    item_key = {"domain": "item", "entity": "SPD", "country": "*"}
    steps = [{"role": "bu_head", "user_id": "kelvin"}]
    assert put(client, key=item_key, steps=steps).status_code == 200
    d = _item_in_flight(client, f"Kept Override Kit {next(_n)}")
    assert (1, "bu_head", "kelvin") in people(d)
    r = client.delete("/admin/routing-rules", headers=H("priya"), params=item_key)
    assert r.status_code == 200
    after = _ask_edit_resubmit(client, d)
    assert people(after) == people(d)
    with session_scope() as s:
        row = s.get(m.Request, d["req_id"])
        assert row.routing_override == steps


def test_a_request_routed_by_the_standard_rule_stores_no_override(client):
    d = vn_customer(client)
    with session_scope() as s:
        assert s.get(m.Request, d["req_id"]).routing_override is None
    assert put(client).status_code == 200
    d2 = vn_customer(client)
    with session_scope() as s:
        assert s.get(m.Request, d2["req_id"]).routing_override == LAN_STEPS


# ---------------------------------------------------------------- preview


def test_preview_of_the_standard_and_saved_rule_and_a_draft(client):
    before = last_change(client)
    std = preview(client)
    assert std["source"] == "standard"
    assert [(t["stage"], t["role"], t["name"]) for t in std["tasks"]] == [
        (1, "bu_head", "Nguyễn Minh Tuấn"),
        (1, "finance", "Wei Jie"),
        (1, "business_support", "Mei Ling"),
        (2, "mdm_analyst", "Priya"),
    ]
    assert std["tasks"][3]["role_label"] == "MDM publish"

    draft = preview(client, steps=LAN_STEPS)
    assert draft["source"] == "draft"
    assert draft["tasks"][3]["name"] == "Nguyễn Thị Lan"
    assert draft["tasks"][3]["role_label"] == "Quality / Regulatory"
    # a draft is never stored
    assert last_change(client) == before
    assert preview(client)["source"] == "standard"

    put(client)
    assert preview(client)["source"] == "saved"


def test_preview_checks_a_draft_like_a_save(client):
    r = client.post(
        "/admin/routing-rules/preview",
        headers=H("amy"),
        json={**VN_CUSTOMER_KEY, "steps": []},
    )
    assert r.status_code == 422 and "at least one approver" in r.json()["detail"]


def test_preview_equals_what_submit_then_creates(client):
    draft = preview(client, steps=LAN_STEPS)
    put(client)
    saved = preview(client)
    d = vn_customer(client)
    created = {(t[0], t[2], t[4]) for t in snapshot_tasks(d)}
    for p in (draft, saved):
        assert {(t["stage"], t["role"], t["user_id"]) for t in p["tasks"]} == created
    # and for the standard route, with no rule saved
    client.delete("/admin/routing-rules", headers=H("priya"), params=VN_CUSTOMER_KEY)
    std = preview(client)
    d = vn_customer(client)
    assert {(t["stage"], t["role"], t["user_id"]) for t in std["tasks"]} == {
        (t[0], t[2], t[4]) for t in snapshot_tasks(d)
    }


# ---------------------------------------------------------------- reset demo (last: wipes the DB)


def test_reset_demo_clears_the_overrides(client):
    assert put(client).status_code == 200
    assert any(
        x["is_override"]
        for x in client.get("/admin/routing-rules", headers=H("amy")).json()["rules"]
    )
    r = client.post("/admin/reset-demo")
    assert r.status_code == 200, r.text
    rules = client.get("/admin/routing-rules", headers=H("amy")).json()["rules"]
    assert not any(x["is_override"] for x in rules)
    with session_scope() as s:
        assert s.scalars(select(m.RoutingOverride)).all() == []
    assert client.get("/admin/config-changes", headers=H("amy")).json() == []
    # the standard route is back for new requests
    d = vn_customer(client)
    assert "lan" not in {t[4] for t in snapshot_tasks(d)}
