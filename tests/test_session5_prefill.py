"""Session 5 (c): deterministic suggestions for product family and item group (offline)."""

# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
from __future__ import annotations

from services.api.item_suggestions import suggest_item_fields
from tests.test_workflow_api import (  # noqa: F401 - fixtures are used by name
    H,
    _clock,
    client,
    new_request,
    sap_mock,
)

OWNS_APP_DB = True  # see tests/conftest.py


def test_demo_02_email_gets_suggested_family_and_group_with_reasons(client):
    r = client.post("/requests/from-email/DEMO-02", headers=H("amy"))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["domain"] == "item" and d["entity"] == "SPD"
    assert d["fields"]["ItemsGroupCode"] == 101 and d["fields"]["product_family"] == "A"
    why = d["prefill_suggested"]
    assert set(why) == {"ItemsGroupCode", "product_family"}
    assert "test kit" in why["ItemsGroupCode"] and "Reagents and test kits" in why["ItemsGroupCode"]
    assert "SPD" in why["product_family"]
    # suggested, not quoted: the quotes only cover what the email said
    assert "ItemsGroupCode" not in d["prefill_quotes"]
    assert "product_family" not in d["prefill_quotes"]
    assert d["fields"]["U_IVD"] == "tYES"  # the email's own values are untouched
    # the requestor overrides one; its reason goes away, the other stays
    r = client.patch(
        f"/requests/{d['req_id']}", headers=H("amy"), json={"fields": {"ItemsGroupCode": 102}}
    )
    assert r.json()["fields"]["ItemsGroupCode"] == 102
    assert set(r.json()["prefill_suggested"]) == {"product_family"}


def test_suggestions_follow_the_entity_and_never_overwrite_stated_values():
    s = suggest_item_fields("5-part Haematology Analyser", "QTS", {})
    assert s["ItemsGroupCode"][0] == 102 and s["product_family"][0] == "B"
    s = suggest_item_fields("Annual Analyser Service Contract", "QTG", {})
    assert s["ItemsGroupCode"][0] == 103 and s["product_family"][0] == "C"
    stated = {"ItemsGroupCode": 102, "product_family": "C"}
    assert suggest_item_fields("Malaria Rapid Test Kit", "SPD", stated) == {}
    # no keyword: fall back to the closest existing item, otherwise say nothing about the group
    near = suggest_item_fields(
        "Dengue Combo Panel", "SPD", {}, [("Dengue IgG/IgM Combo Panel", 101), ("Other", 102)]
    )
    assert near["ItemsGroupCode"][0] == 101 and "Dengue IgG/IgM" in near["ItemsGroupCode"][1]
    assert "ItemsGroupCode" not in suggest_item_fields("Widget", "SPD", {})
    assert "product_family" not in suggest_item_fields("Widget", "Group", {})


def test_manual_items_have_no_suggestions(client):
    manual = new_request(client, "amy", "item", "SPD", "SG", {"ItemName": "Malaria Rapid Test Kit"})
    assert manual["prefill_suggested"] == {} and "ItemsGroupCode" not in manual["fields"]
