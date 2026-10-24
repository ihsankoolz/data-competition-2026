"""PRD S1: drop-off risk and cross-sell whitespace lists, after merge only (ds.analytics.accounts
via the regional view), plus the actions that point at them and the D-021 #3 growth action."""

# ruff: noqa: F811  (the `client` fixture from test_workflow_api is used by name)
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ds.analytics import accounts
from ds.analytics.regional import _core, _frames, regional_view
from services.api.schemas import RegionalView
from tests.test_workflow_api import client  # noqa: F401  (seeded API on a temp database)

OWNS_APP_DB = True
ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "data" / "fixtures" / "seasonal_trend"


def _view(view: str, country: str | None = None) -> RegionalView:
    return RegionalView.model_validate(regional_view(FIX, view, country))  # type: ignore[arg-type]


@pytest.mark.parametrize("country", [None, "VN"])
def test_lists_are_empty_before_merge(country):
    m = _view("before", country)
    assert m.drop_off_risk == [] and m.cross_sell_whitespace == []
    assert not any("fading" in a.title or "missing product" in a.title for a in m.actions)


@pytest.mark.parametrize("country", [None, "VN", "SG"])
def test_lists_after_merge_are_sorted_non_negative_and_capped(country):
    m = _view("after", country)
    assert 0 < len(m.drop_off_risk) <= 10 and 0 < len(m.cross_sell_whitespace) <= 10
    risk = [r.value_at_risk_usd for r in m.drop_off_risk]
    est = [r.est_value_usd for r in m.cross_sell_whitespace]
    assert risk == sorted(risk, reverse=True) and est == sorted(est, reverse=True)
    assert all(v > 0 for v in risk + est)
    assert all(r.change_pct is not None and r.change_pct <= -50.0 for r in m.drop_off_risk)
    assert all(r.card_code.startswith("G-") for r in m.drop_off_risk + m.cross_sell_whitespace)
    for w in m.cross_sell_whitespace:
        assert w.missing in ("A", "C") and w.missing not in w.buys and w.buys
    if country:
        assert {r.country for r in m.drop_off_risk + m.cross_sell_whitespace} == {country}


def test_no_customer_is_both_lost_and_dropping_off_or_whitespace():
    core = _core(_frames(FIX), "after", None)
    lost = set(core.lost["key"])
    drop = set(core.drop_off["key"])
    assert drop and not (drop & lost)
    assert not (set(core.whitespace["key"]) & (lost | drop))


# 24 months: the 12-month period is the last 12; months[-15:-12] is the same quarter last year.
ALL_MONTHS = list(pd.date_range("2024-10-01", periods=24, freq="MS"))
PERIOD = ALL_MONTHS[12:]


def _rows(key: str, per_month: dict[int, float], family: str = "A", country: str = "VN"):
    """Order lines for one customer; keys of `per_month` index ALL_MONTHS (12 = period start)."""
    return [
        {
            "k": key,
            "month": ALL_MONTHS[i],
            "doc_date": ALL_MONTHS[i],
            "value": v,
            "family": family,
            "country": country,
        }
        for i, v in per_month.items()
    ]


def test_drop_off_is_year_over_year_on_a_tiny_frame():
    regular = {i: 10_000.0 for i in range(12, 21)}  # the 9 period months before the last quarter
    last_year_q = {i: 10_000.0 for i in (9, 10, 11)}  # the same quarter one year earlier
    df = pd.DataFrame(
        # same quarter last year 30k -> last quarter 1k: at risk
        _rows("fading", {**last_year_q, **regular, 21: 1_000.0})
        + _rows("steady", {**last_year_q, **regular, 21: 10_000.0, 22: 10_000.0, 23: 10_000.0})
        # seasonal: the last quarter is low, but it was just as low a year ago -> not at risk,
        # although it halved against the 3 months before (the old, quarter-on-quarter rule)
        + _rows("seasonal", {9: 3_000.0, 10: 3_000.0, **regular, 21: 4_000.0})
        # regular and fading, but no orders in that quarter last year: cannot be compared
        + _rows("no_last_year", {**regular, 21: 500.0})
        + _rows("lost", {**last_year_q, **regular})  # stopped, but already on the lost list
        + _rows("one_off", {19: 20_000.0, 9: 20_000.0})  # not a regular buyer
        + _rows("machine", {**last_year_q, **regular}, family="B")  # equipment only
    )
    out = accounts.drop_off_risk(df, "k", PERIOD, lost_keys=["lost"])
    assert list(out["key"]) == ["fading"]
    assert out["value_at_risk"].iloc[0] == 29_000.0 and out["change_pct"].iloc[0] == -96.7
    assert accounts.drop_off_unscored(df, "k", PERIOD, lost_keys=["lost"]) == ["no_last_year"]
    reason = accounts.drop_off_reason(out.iloc[0], PERIOD)
    assert "97% less" in reason and "same quarter last year" in reason
    assert "Jul-Sep 2026" in reason and "Jul-Sep 2025" in reason


def test_drop_off_caption_says_unscored_customers_are_left_out():
    m = _view("after")
    assert "same 3 months last year" in m.captions["drop_off_risk"].caption
    assert "no orders in that quarter last year" in m.captions["drop_off_risk"].caption
    assert m.drop_off_total is not None
    core = _core(_frames(FIX), "after", None)
    assert m.drop_off_total.customers == len(core.drop_off)
    assert m.drop_off_total.total_usd == pytest.approx(core.drop_off["value_at_risk"].sum())
    if core.drop_unscored:
        assert f"{core.drop_unscored} regular customer" in m.drop_off_total.caption
    for r in m.drop_off_risk:
        assert "same quarter last year" in r.reason


def _peer_frame(n_a_peers: int, n_c_peers: int) -> pd.DataFrame:
    """One B-only customer 'target'; n_a_peers buy B+A, n_c_peers buy B+C (all in VN)."""
    rows = _rows("target", {12: 50_000.0}, family="B")
    for i in range(n_a_peers):
        rows += _rows(f"pa{i:02d}", {12: 1_000.0}, family="B") + _rows(
            f"pa{i:02d}", {13: 30_000.0}, family="A"
        )
    for i in range(n_c_peers):
        rows += _rows(f"pc{i:02d}", {12: 1_000.0}, family="B") + _rows(
            f"pc{i:02d}", {13: 20_000.0}, family="C"
        )
    return pd.DataFrame(rows)


@pytest.mark.parametrize(
    ("n_a", "n_c", "missing", "low"),
    [
        (9, 0, "A", True),  # 9 comparable customers: listed but low confidence
        (10, 0, "A", False),  # 10 is enough
        (4, 12, "C", False),  # a confident gap beats a higher low-confidence estimate
        (12, 12, "A", False),  # both confident: the higher estimate wins
        (2, 0, None, None),  # under 3 comparable customers: no estimate, no row
    ],
)
def test_whitespace_low_confidence_under_10_comparable_customers(n_a, n_c, missing, low):
    ws = accounts.whitespace(_peer_frame(n_a, n_c), "k", [], ["A", "B", "C"])
    row = ws[ws["key"] == "target"]
    if missing is None:
        assert row.empty
        return
    assert row["missing"].iloc[0] == missing
    assert bool(row["low_confidence"].iloc[0]) is low


def test_whitespace_total_excludes_low_confidence_rows():
    ws = pd.DataFrame(
        {"est_value": [70_000.0, 40_000.0, 5_000.0], "low_confidence": [True, False, False]}
    )
    assert accounts.whitespace_total(ws) == 45_000.0
    assert accounts.whitespace_total(ws.iloc[:0]) == 0.0


@pytest.mark.parametrize("country", [None, "VN"])
def test_whitespace_view_total_and_marks(country):
    m = _view("after", country)
    core = _core(_frames(FIX), "after", country)
    ws = core.whitespace
    t = m.whitespace_total
    assert t is not None and t.customers == len(ws)
    low = ws[ws["low_confidence"].astype(bool)]
    assert len(low) > 0  # the demo data has some, so the UI mark is exercised
    assert t.low_confidence == len(low)
    assert t.total_usd == pytest.approx(ws.loc[~ws["low_confidence"], "est_value"].sum())
    assert t.total_usd < ws["est_value"].sum()
    assert f"Total excludes {len(low)} low-confidence" in t.caption
    for r in m.cross_sell_whitespace:
        assert r.low_confidence is (r.comparable_customers < 10)
        assert r.comparable_customers >= 3
    act = next(a for a in m.actions if "missing product" in a.title)
    assert accounts._usd(t.total_usd).replace("US$", "") in act.detail
    assert "fewer than 10 similar customers" in act.detail


def test_totals_are_none_before_merge():
    m = _view("before")
    assert m.drop_off_total is None and m.whitespace_total is None


def test_growth_action_reads_vietnam_bias_from_the_backtest():
    run = json.loads(
        (ROOT / "data/fixtures/derived/forecast/seasonal_trend_clean.json").read_text("utf-8")
    )
    vn = next(r for r in run["bias_by_country"] if r["country"] == "VN" and r["product"] is None)
    ex = next(s["bias_pct"] for s in vn["scores"] if s["method"] == "excel_6m")
    for view in ("before", "after"):
        m = _view(view)
        act = [a for a in m.actions if a.title.startswith("Add an explicit growth adjustment")]
        assert len(act) == 1
        assert f"planned Vietnam {abs(ex):.0f}% too low" in act[0].detail
        assert "does not fix this" in act[0].detail  # never claims our model fixes it
        assert 3 <= len(m.actions) <= 5


def test_after_merge_actions_point_at_both_lists():
    m = _view("after")
    titles = [a.title for a in m.actions]
    assert any("fading" in t for t in titles) and any("missing product" in t for t in titles)
    assert len(m.actions) <= 5


def test_api_after_merge_returns_both_lists(client):
    r = client.get("/analytics/regional?view=after", headers={"X-Acting-User": "priya"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["drop_off_risk"] and body["cross_sell_whitespace"]
    assert set(body["drop_off_risk"][0]) == {
        "card_code",
        "name",
        "country",
        "last_order",
        "value_at_risk_usd",
        "change_pct",
        "reason",
    }
    assert set(body["cross_sell_whitespace"][0]) == {
        "card_code",
        "name",
        "country",
        "buys",
        "missing",
        "est_value_usd",
        "comparable_customers",
        "low_confidence",
        "reason",
    }
    assert body["whitespace_total"]["total_usd"] > 0 and body["drop_off_total"]["customers"] > 0
    before = client.get("/analytics/regional?view=before", headers={"X-Acting-User": "priya"})
    assert before.json()["drop_off_risk"] == [] and before.json()["cross_sell_whitespace"] == []
    assert before.json()["whitespace_total"] is None
