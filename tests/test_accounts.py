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


def test_drop_off_rule_on_a_tiny_frame():
    months = list(pd.date_range("2025-10-01", periods=12, freq="MS"))

    def rows(key: str, per_month: dict[int, float], family: str = "A") -> list[dict]:
        return [
            {
                "k": key,
                "month": months[i],
                "doc_date": months[i],
                "value": v,
                "family": family,
                "country": "VN",
            }
            for i, v in per_month.items()
        ]

    regular = {i: 10_000.0 for i in range(9)}
    df = pd.DataFrame(
        rows("fading", {**regular, 9: 1_000.0})  # P3 30k -> T3 1k: at risk
        + rows("steady", {**regular, 9: 10_000.0, 10: 10_000.0, 11: 10_000.0})
        + rows("lost", regular)  # stopped, but already on the lost list
        + rows("one_off", {7: 20_000.0})  # not a regular buyer
        + rows("machine", {**{i: 50_000.0 for i in range(9)}}, family="B")  # equipment only
    )
    out = accounts.drop_off_risk(df, "k", months, lost_keys=["lost"])
    assert list(out["key"]) == ["fading"]
    assert out["value_at_risk"].iloc[0] == 29_000.0 and out["change_pct"].iloc[0] == -96.7


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
        "reason",
    }
    before = client.get("/analytics/regional?view=before", headers={"X-Acting-User": "priya"})
    assert before.json()["drop_off_risk"] == [] and before.json()["cross_sell_whitespace"] == []
