# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
"""Session 4 track B: analytics endpoints (M8/M9/M10, with the 503 path) and Priya's SAP
read-back view. All offline; the ds functions are replaced by minimal valid dicts."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from services.api.db.session import session_scope
from services.api.routers import analytics as analytics_router
from tests.test_workflow_api import (  # noqa: F401
    CUSTOMER,
    CUSTOMER_APPROVERS,
    H,
    _clock,
    approve_stage_one,
    client,
    new_request,
    sap_mock,
    submit_customer,
)

OWNS_APP_DB = True  # see tests/conftest.py

CAPTIONS = {"nrr": {"title": "Net revenue retention", "caption": "Revenue kept from last year."}}
REGIONAL = {
    "view": "after",
    "period": "Oct 2025 - Sep 2026 (last 12 full months)",
    "country": None,
    "heatmap": [
        {"country": "VN", "product": "A", "value_usd": 10.0, "growth_pct": None, "customers": 3}
    ],
    "nrr_pct": 101.5,
    "bridge": [{"step": "start", "value_usd": 100.0, "customers": 5}],
    "cross_sell_pct": 40.0,
    "customer_count": 5,
    "lost_customers": [],
    "panels": [],
    "actions": [],
    "captions": CAPTIONS,
}
MERGE = {
    "customers_before": 10,
    "customers_after": 8,
    "lost_before": 3,
    "lost_after": 1,
    "lost_that_were_duplicates": 2,
    "by_country": [],
    "nrr_before_pct": 90.0,
    "nrr_after_pct": 99.0,
    "caption": "Before and after merging duplicates.",
}
SCORE = {"method": "tsb", "label": "TSB", "wape_pct": 12.0, "bias_pct": -1.0}
BACKTEST = {
    "scenario": "seasonal_trend",
    "data": "clean",
    "setup": "Rolling origin, 3 months ahead.",
    "overall": [SCORE],
    "series": [],
    "chart": [],
    "chart_series": "Vietnam, Product A (units)",
    "honest_note": "Excel wins in flat_noisy.",
}
OPS = {
    "cycle_time": [
        {"process": "old_email_sequential", "label": "Today", "median_bd": 9.0, "p90_bd": 18.0},
        {"process": "new_parallel", "label": "New", "median_bd": 3.0, "p90_bd": 5.0},
    ],
    "amy_before_bd": 18.0,
    "amy_after_bd": 4.0,
    "amy_explanation": "Parallel approvals.",
    "first_time_right_before_pct": 60.0,
    "first_time_right_after_pct": 95.0,
    "duplicates_prevented": 0,
    "assumptions": [],
    "caption": "Modelled, not measured.",
}


def test_analytics_endpoints_validate_and_serve_what_ds_returns(client, monkeypatch):
    seen = {}

    def regional_view(data_dir, view, country=None):
        seen["regional"] = (data_dir.name, view, country)
        return {**REGIONAL, "view": view, "country": country}

    monkeypatch.setattr(analytics_router.regional, "regional_view", regional_view)
    monkeypatch.setattr(analytics_router.regional, "merge_impact", lambda d: MERGE)
    monkeypatch.setattr(
        analytics_router.backtest,
        "forecast_summary",
        lambda d: {"runs": [BACKTEST], "captions": {}},
    )

    def load_backtest(derived_dir, scenario, data="clean"):
        seen["forecast"] = (derived_dir.parts[-2:], scenario, data)
        return {**BACKTEST, "scenario": scenario, "data": data}

    monkeypatch.setattr(analytics_router.backtest, "load_backtest", load_backtest)

    r = client.get("/analytics/regional?view=before&country=VN", headers=H("amy"))
    assert r.status_code == 200 and r.json()["view"] == "before" and r.json()["country"] == "VN"
    assert seen["regional"] == ("seasonal_trend", "before", "VN")
    assert client.get("/analytics/regional", headers=H("amy")).json()["view"] == "after"
    assert client.get("/analytics/merge-impact").json()["customers_after"] == 8
    assert client.get("/analytics/forecast").json()["runs"][0]["scenario"] == "seasonal_trend"
    r = client.get("/analytics/forecast/flat_noisy?data=dirty")
    assert r.status_code == 200 and r.json()["scenario"] == "flat_noisy"
    assert seen["forecast"] == (("fixtures", "derived"), "flat_noisy", "dirty")
    assert client.get("/analytics/forecast/flat_noisy?data=wrong").status_code == 422


def test_ops_impact_passes_the_number_of_requests_linked_to_an_existing_record(client, monkeypatch):
    captured = []

    def ops_impact(data_dir, duplicates_prevented=0):
        captured.append(duplicates_prevented)
        return {**OPS, "duplicates_prevented": duplicates_prevented}

    monkeypatch.setattr(analytics_router.cycle_time, "ops_impact", ops_impact)
    before = client.get("/analytics/ops-impact").json()["duplicates_prevented"]

    fields = {
        "CardName": "Benh vien Cho Ray",
        "Country": "VN",
        "City": "HCMC",
        "FederalTaxID": "0301234567",
        "Street": "201B Nguyen Chi Thanh",
        "EmailAddress": "mua@choray.example",
    }
    req = new_request(client, "marcus", "customer", "QTG", "VN", fields)
    chk = client.post(
        "/dedup/check",
        headers=H("marcus"),
        json={"domain": "customer", "entity": "QTG", "fields": fields},
    ).json()
    r = client.post(
        f"/requests/{req['req_id']}/dedup-decision",
        headers=H("marcus"),
        json={"action": "link_to_existing", "card_code": chk["candidates"][0]["CardCode"]},
    )
    assert r.json()["state"] == "LINKED_TO_EXISTING"
    after = client.get("/analytics/ops-impact").json()["duplicates_prevented"]
    assert after == before + 1 and captured == [before, after]


@pytest.mark.parametrize(
    "url",
    [
        "/analytics/regional",
        "/analytics/merge-impact",
        "/analytics/forecast",
        "/analytics/forecast/seasonal_trend",
        "/analytics/ops-impact",
    ],
)
def test_results_not_computed_yet_answer_503_with_a_plain_sentence(client, monkeypatch, url):
    def not_written(*args, **kwargs):
        raise NotImplementedError

    for module, names in (
        (analytics_router.regional, ("regional_view", "merge_impact")),
        (analytics_router.backtest, ("load_backtest", "forecast_summary")),
        (analytics_router.cycle_time, ("ops_impact",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, not_written)
    r = client.get(url, headers=H("amy"))
    assert r.status_code == 503
    assert r.json()["detail"] == analytics_router.NOT_READY
    assert "make eval" not in r.text


def test_missing_file_and_unexpected_shape_are_503_never_500(client, monkeypatch):
    def gone(*args, **kwargs):
        raise FileNotFoundError("data/fixtures/derived/forecast/seasonal_trend_clean.json")

    monkeypatch.setattr(analytics_router.backtest, "load_backtest", gone)
    r = client.get("/analytics/forecast/seasonal_trend")
    assert r.status_code == 503
    assert r.json()["detail"] == analytics_router.NOT_READY
    assert "json" not in r.text  # the path is not leaked

    monkeypatch.setattr(analytics_router.regional, "merge_impact", lambda d: {"oops": 1})
    r = client.get("/analytics/merge-impact")
    assert r.status_code == 503 and r.json()["detail"] == analytics_router.UNREADABLE


# ---------------------------------------------------------------- SAP read-back


def test_readback_is_stored_served_and_masks_bank_values_unless_finance(client, sap_mock):
    secret = "7270029477"
    bank = [
        {
            "BankCode": "7171",
            "AccountNo": secret,
            "AccountName": "Readback Vendor Pte Ltd",
            "BICSwiftCode": "DBSSSGSG",
            "Country": "SG",
        }
    ]
    fields = {
        **CUSTOMER,
        "CardName": "Readback Vendor Pte Ltd",
        "FederalTaxID": "202600003R",
        "BPBankAccounts": bank,
    }
    req = new_request(client, "amy", "vendor", "SPD", "SG", fields)
    rid = req["req_id"]
    assert client.get(f"/requests/{rid}/sap-readback", headers=H("priya")).status_code == 404
    assert client.get(f"/requests/{rid}", headers=H("priya")).json()["sap_publish"] is None

    d = client.post(f"/requests/{rid}/submit", headers=H("amy")).json()
    d = approve_stage_one(client, d, CUSTOMER_APPROVERS)
    r = client.post(f"/requests/{rid}/publish", headers=H("priya"))
    assert r.status_code == 200 and r.json()["state"] == "ACTIVE"
    detail = r.json()["sap_publish"]
    assert detail is not None

    view = client.get(f"/requests/{rid}/sap-readback", headers=H("priya")).json()
    assert view == detail
    assert view["resource"] == "BusinessPartners" and view["sap_code"].startswith("V")
    assert view["all_match"] is True and view["active"] is True
    assert view["published_by"] == "Priya" or view["published_by"].startswith("Priya")
    assert view["published_at"].startswith("2026-10-05")  # the simulated clock
    rows = {row["field"]: row for row in view["rows"]}
    assert rows["CardName"] == {
        "field": "CardName",
        "sent": "Readback Vendor Pte Ltd",
        "read_back": "Readback Vendor Pte Ltd",
        "match": True,
    }
    assert rows["CardType"]["sent"] == "cSupplier"
    assert rows["Frozen"]["sent"] == "tYES"  # created inactive, activated after the check
    assert "BPAddresses[0].Country" in rows
    assert rows["BPBankAccounts[0].AccountNo"]["sent"] == "****9477"
    assert secret not in json.dumps(view) and "DBSSSGSG" not in json.dumps(view)
    assert all(row["match"] for row in view["rows"])

    # Finance sees the real values
    fin = client.get(f"/requests/{rid}/sap-readback", headers=H("weijie")).json()
    frows = {row["field"]: row for row in fin["rows"]}
    assert frows["BPBankAccounts[0].AccountNo"]["sent"] == secret
    assert frows["BPBankAccounts[0].AccountNo"]["read_back"] == secret
    assert frows["BPBankAccounts[0].BICSwiftCode"]["sent"] == "DBSSSGSG"
    # and the stored copy never holds the number in the clear
    with session_scope() as s:
        raw = s.execute(
            text("SELECT rows FROM sap_publish_results WHERE req_id = :r"), {"r": rid}
        ).scalar_one()
    assert secret not in raw and "DBSSSGSG" not in raw


def test_readback_for_a_customer_and_an_item_names_the_right_resource(client, sap_mock):
    d = submit_customer(client, "Readback Customer Pte Ltd")
    d = approve_stage_one(client, d, CUSTOMER_APPROVERS)
    r = client.post(f"/requests/{d['req_id']}/publish", headers=H("priya"))
    view = r.json()["sap_publish"]
    assert view["resource"] == "BusinessPartners" and view["sap_code"].startswith("C")
    assert any(row["field"] == "FederalTaxID" and row["match"] for row in view["rows"])


def test_reset_demo_clears_published_read_backs(client, sap_mock):
    d = submit_customer(client, "Reset Readback Pte Ltd")
    d = approve_stage_one(client, d, CUSTOMER_APPROVERS)
    rid = d["req_id"]
    assert client.post(f"/requests/{rid}/publish", headers=H("priya")).status_code == 200
    assert client.get(f"/requests/{rid}/sap-readback", headers=H("priya")).status_code == 200
    with session_scope() as s:
        assert s.execute(text("SELECT COUNT(*) FROM sap_publish_results")).scalar_one() >= 1

    assert client.post("/admin/reset-demo").status_code == 200
    with session_scope() as s:
        assert s.execute(text("SELECT COUNT(*) FROM sap_publish_results")).scalar_one() == 0
    # the request itself is gone with the reset, so the read-back view is gone too
    assert client.get(f"/requests/{rid}/sap-readback", headers=H("priya")).status_code == 404


def test_a_bug_inside_a_ds_function_is_not_reported_as_missing_data(client, monkeypatch):
    def broken(*args, **kwargs):
        raise KeyError("a bug")

    monkeypatch.setattr(analytics_router.regional, "merge_impact", broken)
    with pytest.raises(KeyError):
        client.get("/analytics/merge-impact")
