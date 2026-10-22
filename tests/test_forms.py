"""Shared form config (ds/forms.py): required fields agree with the email answer key."""

import json
from pathlib import Path

import pytest

from ds.forms import (
    FORM_DOMAINS,
    extract_to_form_field,
    load_form_schema,
    missing_keys,
    required_keys,
)

LABELS = Path("data/fixtures/seasonal_trend/ground_truth/email_labels.jsonl")
# Hand-written demo emails whose missing list adds a curated question (risk class).
CURATED = {"DEMO-02"}


def _mdm_labels() -> list[dict]:
    rows = [json.loads(line) for line in LABELS.read_text(encoding="utf-8").splitlines() if line]
    return [r for r in rows if r["category"] == "mdm_request"]


def test_missing_keys_match_answer_key():
    rows = [r for r in _mdm_labels() if r["email_id"] not in CURATED]
    assert rows
    for r in rows:
        got = missing_keys(r["domain"], r["expected_fields"])
        assert got == r["missing_fields"], r["email_id"]


def test_ivd_item_needs_registration_per_selling_country():
    keys = required_keys("item", is_ivd=True, selling_countries=["SG", "MY", "VN"])
    assert keys[-3:] == [
        "registration_number_SG",
        "registration_number_MY",
        "registration_number_VN",
    ]
    assert not [k for k in required_keys("item", is_ivd=False) if k.startswith("registration")]


def test_bank_details_are_never_asked_of_the_interpreter():
    assert "bank_account" not in required_keys("vendor")
    assert "bank_account" in required_keys("vendor", include_form_only=True)


@pytest.mark.parametrize("domain", FORM_DOMAINS)
def test_form_schema_is_consistent(domain):
    schema = load_form_schema(domain)
    props = schema["properties"]
    assert set(schema["x-order"]) == set(props)
    mapped = extract_to_form_field(domain)
    for key in required_keys(domain, include_form_only=True):
        assert key in mapped, f"{domain}: required key {key} has no form field"


def test_form_endpoint_lists_required_fields():
    from fastapi.testclient import TestClient

    from services.api.main import app

    client = TestClient(app)
    spec = client.get("/forms/vendor", params={"country": "VN"}).json()
    assert spec["required"][0] == "CardName"
    assert "BPBankAccounts" in spec["required"]
    item = client.get("/forms/item").json()
    assert item["regulated_countries"] == ["SG", "MY", "ID", "VN", "TH"]
    assert client.get("/forms/cost_center").status_code == 404


def test_dedup_query_from_demo_01_form_finds_cho_ray():
    from ds.dedup import MasterIndex, check, load_master
    from ds.forms import dedup_query

    assert dedup_query("customer", "QTG", {"CardName": "x"}) is None
    q = dedup_query(
        "customer",
        "QTG",
        {"CardName": "Benh vien Cho Ray", "Country": "VN", "FederalTaxID": "0301234567"},
    )
    result = check(q, MasterIndex(load_master("data/fixtures/seasonal_trend")), use_judge=False)
    assert result.verdict == "likely" and result.block_submit
    assert result.candidates[0].CardName == "Bệnh viện Chợ Rẫy"
