# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
"""Field validation (D-018 item 3): the pure checker, the endpoints, the 422 body, the publish-time
expiry re-check and the optional "lapsed licence" demo beat. All offline.

Clock facts used below: the simulated clock starts Mon 5 Oct 2026 09:00 SGT, so "today" is
2026-10-05 unless a test moves it.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from ds.forms import FORM_DOMAINS, load_form_schema
from ds.interpreter.api import interpret_email
from services.api import clock
from services.api.formfields import prefill_from_interpretation
from services.api.validation import TAX_ID_RULES, registration_issues, validate_fields
from tests.test_workflow_api import (  # noqa: F401  (fixtures used by name)
    CUSTOMER,
    CUSTOMER_APPROVERS,
    H,
    _clock,
    approve_stage_one,
    client,
    decide,
    new_request,
    sap_mock,
    tasks_by_role,
)

OWNS_APP_DB = True  # see tests/conftest.py
FIXTURES = Path("data/fixtures/seasonal_trend")
TODAY = date(2026, 10, 5)


def by_field(issues):
    return {i.field: i for i in issues}


# ---------------------------------------------------------------- tax IDs (D-003)


@pytest.mark.parametrize(
    ("country", "good"),
    [
        ("SG", ["201912345K", "53012345A", "T08LL1234A"]),
        ("MY", ["202001012345"]),
        ("ID", ["01.234.567.8-901.000", "012345678901000", "01.234.567.8-901000"]),
        ("VN", ["0301234567", "0301234567-001"]),
        ("TH", ["0105556123456"]),
    ],
)
def test_tax_id_formats_accept_the_documented_shapes(country, good):
    pattern, _ = TAX_ID_RULES[country]
    assert all(pattern.fullmatch(v) for v in good)


@pytest.mark.parametrize(
    ("country", "bad"),
    [
        ("SG", ["2019123K", "201912345k", "2019 12345K", "N/A", "TBC"]),
        ("MY", ["20200101234", "2020010123456", "202001012345-A"]),
        ("ID", ["01.234.567.8-901.00", "0123456789010000", "TBC"]),
        ("VN", ["030123456", "03012345678", "0301234567-1"]),
        ("TH", ["010555612345", "01055561234567", "0105-556-123-456"]),
    ],
)
def test_tax_id_formats_reject_near_misses(country, bad):
    pattern, _ = TAX_ID_RULES[country]
    assert not any(pattern.fullmatch(v) for v in bad)


def test_the_vietnamese_message_is_plain_and_has_an_example():
    issues = validate_fields(
        "customer", "VN", {**CUSTOMER, "Country": "VN", "FederalTaxID": "123"}, TODAY
    )
    tax = by_field(issues)["FederalTaxID"]
    assert tax.kind == "format" and tax.label == "Tax ID (MST)"
    assert tax.message == "A Vietnamese tax ID (MST) has 10 digits, like 0301234567."


def test_every_generated_tax_id_in_the_fixtures_passes():
    """The checker must agree with the generator's synthetic formats (D-003)."""
    rows = []
    with open(FIXTURES / "customers_golden.csv", encoding="utf-8", newline="") as fh:
        rows += [(r["country"], r["tax_id"]) for r in csv.DictReader(fh)]
    with open(FIXTURES / "vendors.csv", encoding="utf-8", newline="") as fh:
        rows += [(r["Country"], r["FederalTaxID"]) for r in csv.DictReader(fh)]
    rows = [(c, t) for c, t in rows if c in TAX_ID_RULES]  # vendors abroad have other formats
    assert len(rows) > 100
    bad = [(c, t) for c, t in rows if not TAX_ID_RULES[c][0].fullmatch(t)]
    assert bad == []


def test_every_demo_email_prefill_passes_validation_of_its_values(monkeypatch):
    """DEMO-01..08 as the form pre-fills them: nothing the email gave us is rejected."""
    monkeypatch.setenv("LLM_MODE", "replay")
    emails = {
        e["email_id"]: e
        for e in map(json.loads, open(FIXTURES / "emails.jsonl", encoding="utf-8"))
        if e["email_id"].startswith("DEMO-")
    }
    assert len(emails) == 8
    seen = []
    for email_id, e in sorted(emails.items()):
        interp = interpret_email(email_id, e["subject"], e["body"], e["from_address"])
        if interp.category != "mdm_request" or interp.domain not in FORM_DOMAINS:
            continue
        if email_id == "DEMO-06":  # the prompt-injection email: a vendor outside our 5 countries
            continue
        fields, _ = prefill_from_interpretation(interp.domain, interp)
        country = str(fields.get("Country") or "SG")
        value_problems = [
            i for i in validate_fields(interp.domain, country, fields, TODAY) if i.kind != "missing"
        ]
        assert value_problems == [], (email_id, value_problems)
        seen.append(email_id)
    # exactly these are master-data requests for a form; the rest are POs, enquiries and so on,
    # and DEMO-06 is the prompt-injection email skipped above
    assert seen == ["DEMO-01", "DEMO-02", "DEMO-07"]
    # DEMO-01's MST in particular
    pattern, _ = TAX_ID_RULES["VN"]
    assert pattern.fullmatch("0301234567")


# ---------------------------------------------------------------- the pure checker


def test_schema_checks_length_choices_types_and_formats():
    fields = {
        "CardName": "x" * 101,
        "Country": "XX",
        "FederalTaxID": "1" * 33,
        "EmailAddress": "not-an-email",
        "PayTermsGrpCode": 7,
        "CreditLimit": "lots",
        "Street": "1 Test Road",
    }
    got = by_field(validate_fields("customer", "SG", fields, TODAY))
    assert got["CardName"].kind == "too_long" and "100" in got["CardName"].message
    assert got["Country"].kind == "not_allowed"
    assert got["FederalTaxID"].kind == "too_long" and "32" in got["FederalTaxID"].message
    assert got["EmailAddress"].kind == "format"
    assert (
        got["PayTermsGrpCode"].kind == "not_allowed" and "30 days" in got["PayTermsGrpCode"].message
    )
    assert got["CreditLimit"].kind == "format"


def test_required_fields_come_back_as_missing_per_domain():
    got = validate_fields("customer", "SG", {"CardName": "Only A Name"}, TODAY)
    assert {i.field for i in got if i.kind == "missing"} == {
        "FederalTaxID",
        "Street",
        "EmailAddress",
    }
    vendor = by_field(validate_fields("vendor", "SG", {"CardName": "V"}, TODAY))
    assert vendor["BPBankAccounts"].kind == "missing"
    item = by_field(validate_fields("item", "SG", {}, TODAY))
    assert {"ItemName", "U_IVD", "selling_countries"} <= set(item)


def test_cost_center_is_checked_too():
    got = by_field(
        validate_fields(
            "cost_center", "SG", {"CenterName": "x" * 31, "EffectiveFrom": "next week"}, TODAY
        )
    )
    assert got["CenterName"].kind == "too_long"
    assert got["EffectiveFrom"].kind == "format"


def test_bank_issues_never_echo_bank_values():
    secret = "9876543210123456"
    fields = {
        **CUSTOMER,
        "BPBankAccounts": [
            {
                "BankCode": "7171",
                "AccountNo": secret * 4,  # too long
                "AccountName": "Vendor Pte Ltd",
                "BICSwiftCode": "TOOLONGSWIFTCODE",
                "Country": "SG",
            },
            {"BankCode": "1", "Country": "SG"},
        ],
    }
    issues = validate_fields("vendor", "SG", fields, TODAY)
    bank = [i for i in issues if i.field.startswith("BPBankAccounts.")]
    kinds = {(i.field, i.kind) for i in bank}
    assert ("BPBankAccounts.0.AccountNo", "too_long") in kinds
    assert ("BPBankAccounts.0.BICSwiftCode", "too_long") in kinds
    assert ("BPBankAccounts.1.AccountNo", "missing") in kinds
    everything = json.dumps([i.model_dump() for i in issues])
    for needle in (secret, "TOOLONGSWIFTCODE", "7171", "Vendor Pte Ltd"):
        assert needle not in everything


def ivd(**regs):
    return {
        "ItemName": "Test Kit",
        "U_IVD": "tYES",
        "selling_countries": list(regs),
        "registrations": [{"country": cc, **row} for cc, row in regs.items()],
    }


def test_an_expired_registration_blocks_that_country_with_a_plain_message():
    fields = ivd(
        SG={"reg_no": "S-1", "expiry_date": "2029-01-01"},
        MY={"reg_no": "M-1", "expiry_date": "2026-08-31"},
    )
    issues = registration_issues(fields, TODAY)
    assert [(i.field, i.kind) for i in issues] == [("registrations.MY.expiry_date", "expired")]
    assert issues[0].message == (
        "The Malaysia registration expired on 31 Aug 2026. "
        "Renew it or remove Malaysia from the selling countries."
    )


def test_expiry_must_be_after_today_not_on_it():
    on_day = registration_issues(ivd(SG={"reg_no": "S", "expiry_date": "2026-10-05"}), TODAY)
    assert [i.kind for i in on_day] == ["expired"] and "expires today" in on_day[0].message
    tomorrow = registration_issues(ivd(SG={"reg_no": "S", "expiry_date": "2026-10-06"}), TODAY)
    assert tomorrow == []


def test_expiry_is_judged_against_the_date_it_is_given_not_the_wall_clock():
    fields = ivd(SG={"reg_no": "S", "expiry_date": "2027-03-01"})
    assert registration_issues(fields, date(2027, 2, 28)) == []
    assert [i.kind for i in registration_issues(fields, date(2027, 3, 2))] == ["expired"]


def test_a_regulated_country_needs_number_and_expiry_and_issue_must_precede_expiry():
    fields = ivd(
        SG={"reg_no": "S"},
        VN={"reg_no": "V", "issue_date": "2028-01-01", "expiry_date": "2027-01-01"},
    )
    got = by_field(validate_fields("item", "SG", fields, TODAY))
    assert got["registrations.SG.expiry_date"].kind == "missing"
    assert got["registrations.VN.issue_date"].kind == "date_order"
    nothing = by_field(validate_fields("item", "SG", ivd(SG={}), TODAY))
    assert nothing["registrations.SG.reg_no"].kind == "missing"
    assert nothing["registrations.SG.expiry_date"].kind == "missing"
    bad_date = registration_issues(ivd(SG={"reg_no": "S", "expiry_date": "31/12/2030"}), TODAY)
    assert [i.kind for i in bad_date] == ["format"]


def test_a_non_ivd_item_needs_no_registration_and_an_old_unlisted_row_is_ignored():
    fields = {
        "ItemName": "Pipette tips",
        "U_IVD": "tNO",
        "selling_countries": ["SG"],
        "registrations": [{"country": "MY", "reg_no": "M", "expiry_date": "2020-01-01"}],
    }
    assert validate_fields("item", "SG", fields, TODAY) == []
    assert "registrations" in load_form_schema("item")["properties"]


# ---------------------------------------------------------------- the API


def test_validate_endpoint_and_issues_on_get_and_patch_while_drafting(client):
    req = new_request(
        client, "amy", "customer", "SPD", "VN", {"CardName": "Half Done Co", "FederalTaxID": "123"}
    )  # noqa: E501
    rid = req["req_id"]
    assert {i["field"] for i in req["issues"]} >= {"FederalTaxID", "Street", "EmailAddress"}
    r = client.post(f"/requests/{rid}/validate", headers=H("amy"))
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    tax = next(i for i in body["issues"] if i["field"] == "FederalTaxID")
    assert tax["kind"] == "format" and "10 digits" in tax["message"]
    # fix it through PATCH: the response carries the fresh issues
    r = client.patch(
        f"/requests/{rid}",
        headers=H("amy"),
        json={
            "fields": {
                "FederalTaxID": "0312345678",
                "Street": "1 Street",
                "EmailAddress": "a@b.example",
                "Country": "VN",
            }
        },
    )
    assert r.json()["issues"] == []
    assert client.get(f"/requests/{rid}", headers=H("amy")).json()["issues"] == []
    ok = client.post(f"/requests/{rid}/validate", headers=H("marcus")).json()
    assert ok == {"ok": True, "issues": []}
    assert client.post("/requests/REQ-9999/validate", headers=H("amy")).status_code == 404


def test_submit_answers_422_with_detail_string_and_issues(client):
    req = new_request(
        client, "amy", "customer", "SPD", "VN", {**CUSTOMER, "Country": "VN", "FederalTaxID": "123"}
    )  # noqa: E501
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 422
    body = r.json()
    assert isinstance(body["detail"], str) and body["detail"].count(". ") == 0
    assert "10 digits, like 0301234567" in body["detail"]
    assert [i["field"] for i in body["issues"]] == ["FederalTaxID"]
    assert set(body["issues"][0]) == {"field", "label", "message", "kind"}
    # nothing happened to the request
    assert client.get(f"/requests/{req['req_id']}", headers=H("amy")).json()["state"] == "DRAFT"


def test_submit_with_only_missing_fields_keeps_the_familiar_sentence(client):
    req = new_request(client, "amy", fields={"CardName": "Quill Two Pte Ltd", "Country": "SG"})
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 422
    assert r.json()["detail"].startswith("Some required details are still missing: Tax ID (UEN)")
    assert all(i["kind"] == "missing" for i in r.json()["issues"])


def test_bank_values_never_appear_in_validation_responses(client):
    secret = "5550001112223334"
    fields = {
        **CUSTOMER,
        "CardName": "Leak Check Vendor Pte Ltd",
        "FederalTaxID": "202600002L",
        "BPBankAccounts": [
            {"BankCode": "7171", "AccountNo": secret, "AccountName": "N" * 300, "Country": "SG"}
        ],
    }
    req = new_request(client, "amy", "vendor", "SPD", "SG", fields)
    texts = [json.dumps(req["issues"])]
    texts.append(client.post(f"/requests/{req['req_id']}/validate", headers=H("amy")).text)
    texts.append(client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).text)
    assert "BPBankAccounts.0.AccountName" in texts[1]
    assert all(secret not in t and "7171" not in t for t in texts)


# ---------------------------------------------------------------- items and the demo paths


def malaria(**over):
    base = {
        "ItemName": "Malaria Pf/Pan Antigen Rapid Test Kit",
        "U_IVD": "tYES",
        "selling_countries": ["SG", "MY", "VN"],
        "registrations": [
            {
                "country": "SG",
                "reg_no": "DIV-001",
                "issue_date": "2025-01-10",
                "expiry_date": "2030-01-10",
            },
            {
                "country": "MY",
                "reg_no": "MDA-002",
                "issue_date": "2025-02-01",
                "expiry_date": "2030-02-01",
            },
            {
                "country": "VN",
                "reg_no": "VN-3",
                "issue_date": "2025-03-01",
                "expiry_date": "2030-03-01",
            },
        ],
        "product_family": "A",
    }
    return {**base, **over}


def test_demo02_malaria_kit_with_valid_registrations_is_not_blocked(client):
    req = new_request(client, "amy", "item", "SPD", "SG", malaria())
    assert req["issues"] == []
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 200 and r.json()["state"] == "IN_APPROVAL"


def test_optional_beat_lapsed_licence_is_stopped_at_submit(client):
    """docs/demo-script.md, "Optional beat: lapsed licence": a different IVD kit (not DEMO-02's
    malaria kit) with the real expired A-CRP-QT Malaysia row from item_registrations.csv."""
    row = next(
        r
        for r in csv.DictReader(open(FIXTURES / "item_registrations.csv", encoding="utf-8"))
        if r["item_code"] == "A-CRP-QT" and r["country"] == "MY"
    )
    assert row["status"] == "expired" and row["expiry_date"] == "2026-08-15"
    fields = {
        "ItemName": "CRP Quantitative Reagent - 200 test pack",
        "U_IVD": "tYES",
        "selling_countries": ["SG", "MY"],
        "registrations": [
            {"country": "SG", "reg_no": "DE2538958", "expiry_date": "2029-11-23"},
            {
                "country": "MY",
                "reg_no": row["reg_no"],
                "issue_date": row["issue_date"],
                "expiry_date": row["expiry_date"],
            },
        ],
        "product_family": "A",
    }
    req = new_request(client, "amy", "item", "SPD", "SG", fields)
    assert [i["kind"] for i in req["issues"]] == ["expired"]
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 422
    body = r.json()
    assert "The Malaysia registration expired on 15 Aug 2026" in body["detail"]
    assert body["issues"][0]["field"] == "registrations.MY.expiry_date"
    # Amy removes Malaysia from the selling countries and the same request goes through
    r = client.patch(
        f"/requests/{req['req_id']}",
        headers=H("amy"),
        json={
            "fields": {"selling_countries": ["SG"], "registrations": fields["registrations"][:1]}
        },
    )
    assert r.json()["issues"] == []
    assert client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).status_code == 200


def test_publish_refuses_an_item_whose_registration_lapsed_after_approval(client, sap_mock):
    fields = malaria(
        selling_countries=["SG"],
        registrations=[{"country": "SG", "reg_no": "DIV-9", "expiry_date": "2026-10-20"}],
    )
    req = new_request(client, "amy", "item", "SPD", "SG", fields)
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    assert d["state"] == "IN_APPROVAL"
    d = approve_stage_one(
        client,
        d,
        {("bu_head", None): "daniel", ("business_support", None): "meiling",
         ("quality_regulatory", "SG"): "joanne"},
    )  # fmt: skip
    assert d["state"] == "APPROVED"
    clock.advance(days=20)  # now 25 Oct: the SG registration ended on 20 Oct
    r = client.post(f"/requests/{d['req_id']}/publish", headers=H("priya"))
    assert r.status_code == 409
    assert "The Singapore registration expired on 20 Oct 2026" in r.json()["detail"]
    assert r.json()["issues"][0]["kind"] == "expired"
    assert sap_mock.app.state.stores["Items"] == {}  # nothing reached SAP
    still = client.get(f"/requests/{d['req_id']}", headers=H("priya")).json()
    assert still["state"] == "APPROVED"
    clock.reset()
    ok = client.post(f"/requests/{d['req_id']}/publish", headers=H("priya"))
    assert ok.status_code == 200 and ok.json()["state"] == "ACTIVE"


# ---------------------------------------------------------------- what gets stored (trim, clean)


@pytest.mark.parametrize(
    ("country", "typed", "stored"),
    [
        ("SG", "  201912345k ", "201912345K"),
        ("MY", " 2020 0101-2345 ", "202001012345"),
        ("TH", "0105-556 123456", "0105556123456"),
        ("ID", " 01.234.567.8-901 .000 ", "01.234.567.8-901.000"),
        ("VN", " 0301234567 ", "0301234567"),
    ],
)
def test_the_tax_id_is_cleaned_before_it_is_stored_and_then_validates(country, typed, stored):
    from services.api.validation import normalise_fields

    cleaned = normalise_fields({"FederalTaxID": typed, "CardName": "  Name  "}, country)
    assert cleaned == {"FederalTaxID": stored, "CardName": "Name"}
    assert TAX_ID_RULES[country][0].fullmatch(stored)


def test_create_and_patch_store_trimmed_text_and_a_cleaned_tax_id(client):
    req = new_request(
        client,
        "amy",
        "customer",
        "SPD",
        "SG",
        {**CUSTOMER, "CardName": "  Tidy Medical Pte Ltd ", "FederalTaxID": " 202600009t "},
    )
    assert req["fields"]["CardName"] == "Tidy Medical Pte Ltd"
    assert req["fields"]["FederalTaxID"] == "202600009T"
    assert req["issues"] == []
    r = client.patch(
        f"/requests/{req['req_id']}",
        headers=H("amy"),
        json={"fields": {"FederalTaxID": " 202600010u", "City": " Jurong  "}},
    )
    assert r.json()["fields"]["FederalTaxID"] == "202600010U"
    assert r.json()["fields"]["City"] == "Jurong"
    assert r.json()["issues"] == []
    # a Thai customer: spaces and dashes are removed
    th = new_request(
        client,
        "amy",
        "customer",
        "SPD",
        "TH",
        {**CUSTOMER, "Country": "TH", "FederalTaxID": "0105-556 123456"},
    )
    assert th["fields"]["FederalTaxID"] == "0105556123456" and th["issues"] == []


def test_yes_no_codes_are_shown_as_plain_words():
    got = by_field(validate_fields("item", "SG", {"ItemName": "X", "U_IVD": "maybe"}, TODAY))
    assert got["U_IVD"].kind == "not_allowed"
    assert got["U_IVD"].message == "In-vitro diagnostic (IVD)? must be one of: Yes, No."
    assert "tYES" not in got["U_IVD"].message and "tNO" not in got["U_IVD"].message
