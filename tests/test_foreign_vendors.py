"""D-020 #2: vendors may be anywhere in the world, customers stay within the five countries."""

# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from services.api.db import models as m
from services.api.db.session import session_scope
from tests.test_workflow_api import (  # noqa: F401 - fixtures are used by name
    CUSTOMER_APPROVERS,
    H,
    _clock,
    approve_stage_one,
    client,
    new_request,
    sap_mock,
)

OWNS_APP_DB = True  # see tests/conftest.py

CONFIG = Path(__file__).resolve().parents[1] / "config"
BANK = [
    {
        "BankCode": "DEUTDEFF",
        "AccountNo": "5555666677",
        "AccountName": "Rapid Diagnostik GmbH",
        "Country": "DE",
    }
]
GERMAN_VENDOR = {
    "CardName": "Rapid Diagnostik GmbH",
    "Country": "DE",
    "Street": "Hauptstrasse 1",
    "City": "Berlin",
    "BPBankAccounts": BANK,
}


def _issues(client, req_id, user="amy"):
    return client.post(f"/requests/{req_id}/validate", headers=H(user)).json()


def test_country_list_is_iso_3166_with_english_names_and_matches_the_vendor_form():
    names = json.loads((CONFIG / "countries.json").read_text(encoding="utf-8"))
    assert len(names) == 249 and {"DE", "US", "JP", "SG", "TH"} <= set(names)
    assert all(len(c) == 2 and c.isupper() and n for c, n in names.items())
    vendor = json.loads((CONFIG / "forms" / "vendor.schema.json").read_text(encoding="utf-8"))
    country = vendor["properties"]["Country"]
    assert country["enum"] == sorted(names) and country["x-enum-labels"] == names
    bank = vendor["properties"]["BPBankAccounts"]["items"]["properties"]["Country"]
    assert bank["enum"] == sorted(names)
    customer = json.loads((CONFIG / "forms" / "customer.schema.json").read_text(encoding="utf-8"))
    assert customer["properties"]["Country"]["enum"] == ["SG", "MY", "ID", "VN", "TH"]


def test_vendor_form_served_with_labels_and_a_shorter_required_list_for_a_foreign_country(client):
    home = client.get("/forms/vendor?country=SG").json()
    foreign = client.get("/forms/vendor?country=DE").json()
    assert foreign["json_schema"]["properties"]["Country"]["x-enum-labels"]["DE"] == "Germany"
    assert "FederalTaxID" in home["required"] and "FederalTaxID" not in foreign["required"]
    assert {"CardName", "Country", "Street", "City", "BPBankAccounts"} <= set(foreign["required"])
    assert client.get("/forms/vendor?country=ZZ").status_code == 422
    assert "FederalTaxID" in client.get("/forms/customer?country=SG").json()["required"]


def test_german_vendor_without_a_tax_id_validates(client):
    req = new_request(client, "amy", "vendor", "SPD", "SG", GERMAN_VENDOR)
    assert req["fields"]["Country"] == "DE" and req["country"] == "SG"
    assert req["missing_fields"] == [] and req["issues"] == []
    assert _issues(client, req["req_id"])["ok"] is True


def test_german_vendor_still_needs_name_address_and_city(client):
    bare = {"Country": "DE", "BPBankAccounts": BANK}
    req = new_request(client, "amy", "vendor", "SPD", "SG", bare)
    missing = {i["field"] for i in req["issues"] if i["kind"] == "missing"}
    assert missing == {"CardName", "Street", "City"}
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 422 and {i["field"] for i in r.json()["issues"]} == missing


def test_german_tax_id_is_not_checked_against_the_five_country_formats(client):
    req = new_request(
        client, "amy", "vendor", "SPD", "SG", {**GERMAN_VENDOR, "FederalTaxID": "DE 123 456 789"}
    )
    assert req["issues"] == []


def test_german_customer_is_refused_in_plain_english(client):
    fields = {
        "CardName": "Berliner Klinik GmbH",
        "Country": "DE",
        "FederalTaxID": "123456789",
        "Street": "Hauptstrasse 1",
        "City": "Berlin",
        "EmailAddress": "ap@klinik.example",
    }
    req = new_request(client, "amy", "customer", "SPD", "SG", fields)
    (issue,) = [i for i in req["issues"] if i["field"] == "Country"]
    assert "Customers can only be in" in issue["message"] and "Germany" in issue["message"]
    assert "vendor" in issue["message"]
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 422 and "Customers can only be in" in r.json()["detail"]


def test_singapore_vendor_still_needs_a_valid_uen(client):
    sg = {
        "CardName": "Singapore Supplies Pte Ltd",
        "Country": "SG",
        "Street": "1 Road",
        "City": "Singapore",
        "EmailAddress": "ap@sgsupplies.example",
        "BPBankAccounts": [{**BANK[0], "Country": "SG"}],
    }
    req = new_request(client, "amy", "vendor", "SPD", "SG", sg)
    assert [i["field"] for i in req["issues"]] == ["FederalTaxID"]  # required
    bad = client.patch(
        f"/requests/{req['req_id']}", headers=H("amy"), json={"fields": {"FederalTaxID": "123"}}
    ).json()
    (issue,) = bad["issues"]
    assert issue["field"] == "FederalTaxID" and "UEN" in issue["message"]
    ok = client.patch(
        f"/requests/{req['req_id']}",
        headers=H("amy"),
        json={"fields": {"FederalTaxID": "201912345K"}},
    ).json()
    assert ok["issues"] == []


def test_vendor_country_outside_the_list_is_rejected(client):
    req = new_request(client, "amy", "vendor", "SPD", "SG", {**GERMAN_VENDOR, "Country": "ZZ"})
    (issue,) = [i for i in req["issues"] if i["field"] == "Country"]
    assert "two-letter country code" in issue["message"]


def test_dedup_check_handles_a_foreign_vendor(client):
    r = client.post(
        "/dedup/check",
        headers=H("amy"),
        json={"domain": "vendor", "entity": "SPD", "fields": GERMAN_VENDOR},
    )
    assert r.status_code == 200, r.text
    assert r.json()["block_submit"] is False


def test_german_vendor_is_approved_by_the_normal_route_and_published_to_sap(client, sap_mock):
    req = new_request(client, "amy", "vendor", "SPD", "SG", GERMAN_VENDOR)
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    assert d["state"] == "IN_APPROVAL"
    assert {t["role"] for t in d["stages"][0]["tasks"]} == {
        "bu_head",
        "finance",
        "business_support",
    }
    d = approve_stage_one(client, d, CUSTOMER_APPROVERS)
    r = client.post(f"/requests/{d['req_id']}/publish", headers=H("priya"))
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ACTIVE"
    with session_scope() as s:
        row = s.scalar(
            select(m.BusinessPartner).where(m.BusinessPartner.U_MDM_ReqID == d["req_id"])
        )
    assert row.Country == "DE" and row.CardType == "cSupplier" and row.FederalTaxID is None
    sent = sap_mock.app.state.stores["BusinessPartners"][row.CardCode]
    assert sent["BPAddresses"][0]["Country"] == "DE" and sent["Frozen"] == "tNO"
    assert sent["BPBankAccounts"][0]["Country"] == "DE"
    view = client.get(f"/requests/{d['req_id']}/sap-readback", headers=H("priya"))
    assert view.status_code == 200
    assert view.json()["all_match"] is True and view.json()["active"] is True
