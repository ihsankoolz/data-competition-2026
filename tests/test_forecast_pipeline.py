"""Session 13: Product B planned from the request pipeline (ds/forecasting/pipeline.py) and the
forward "Next 3 months plan" (ds/forecasting/plan.py)."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ds.forecasting import backtest as bt
from ds.forecasting import pipeline as pl
from ds.forecasting import plan as fp
from services.api.schemas import ForecastBacktest, ForecastPlan

DEMO = bt.scenario_dir("seasonal_trend")
DERIVED = bt.DERIVED


def _needs_data(scenario: str) -> None:
    if not (bt.scenario_dir(scenario) / "orders.csv").exists():
        pytest.skip(f"{scenario} not generated (make data SCENARIO={scenario})")


def test_constants_are_the_ones_fixed_before_the_first_run():
    # commit b4b7e1e; changing one means keeping the first version and reporting both
    assert (pl.LMAX, pl.CONVERSION_WINDOW, pl.REQUEST_FILL_MONTHS) == (2, 12, 6)
    assert (pl.FALLBACK_EXCEL_MONTHS, pl.FLOOR, pl.PRODUCT) == (6, 0.0, "B")
    assert (pl.H, pl.N_WINDOWS, pl.STEP) == (bt.H, bt.N_WINDOWS, bt.STEP) == (3, 10, 1)
    assert "converted_doc_num" not in pl.ENQUIRY_COLUMNS


def _copy_inputs(dst, drop_link: bool):
    """Only the three files the method may read; nothing else (no MDM, no dirty view)."""
    dst.mkdir()
    for name in ("items.csv", "orders.csv"):
        shutil.copy(DEMO / name, dst / name)
    enq = pd.read_csv(DEMO / "enquiries.csv", dtype=str)
    if drop_link:
        enq = enq.drop(columns=["converted_doc_num"])
    enq.to_csv(dst / "enquiries.csv", index=False)
    return dst


def test_request_to_order_link_is_never_read(tmp_path):
    """Dropping converted_doc_num (and every file except orders, enquiries and items) gives
    exactly the same backtest: the method uses totals only."""
    full = pl.backtest_frame(pl.load_series(DEMO))
    bare = pl.backtest_frame(pl.load_series(_copy_inputs(tmp_path / "bare", drop_link=True)))
    pd.testing.assert_frame_equal(full, bare)


def test_scrambling_the_link_changes_nothing(tmp_path):
    d = _copy_inputs(tmp_path / "scrambled", drop_link=False)
    enq = pd.read_csv(d / "enquiries.csv", dtype=str)
    enq["converted_doc_num"] = enq["converted_doc_num"].sample(frac=1, random_state=1).values
    enq.to_csv(d / "enquiries.csv", index=False)
    a = pl.load_series(DEMO)
    b = pl.load_series(d)
    pd.testing.assert_frame_equal(a.orders, b.orders)
    for k in pl.SIGNALS:
        pd.testing.assert_frame_equal(a.signals[k], b.signals[k])


def test_only_data_up_to_the_origin_is_used():
    """Leakage test: wiping or inflating everything after the origin leaves the plan unchanged."""
    s = pl.load_series(DEMO)
    origin = pl.origins(s.orders.index)[0]
    c = "VN"
    y, sig = s.orders[c], {k: v[c] for k, v in s.signals.items()}
    base = pl.plan_at_origin(y, sig, origin)
    after = y.index > origin
    y2 = y.where(~after, y * 50 + 7)
    sig2 = {k: v.where(~after, 999.0) for k, v in sig.items()}
    moved = pl.plan_at_origin(y2, sig2, origin)
    assert moved.plans == base.plans and moved.months == base.months


def test_plan_matches_the_written_formula_on_a_toy_series():
    months = pd.date_range("2024-01-01", periods=14, freq="MS")
    y = pd.Series([2.0] * 14, index=months)
    r = pd.Series([1.0] * 12 + [4.0, 4.0], index=months)  # last two known months jump
    e = pd.Series([0.0] * 14, index=months)  # no enquiries at all -> Excel fallback
    origin = months[-1]
    op = pl.plan_at_origin(y, {"purchase_request": r, "enquiry": e}, origin, h=3)
    # window = last 12 months; P(t) = mean of r[t-2..t]
    p_win = [np.mean(r.iloc[i - 2 : i + 1]) for i in range(2, 14)]
    k = 24.0 / sum(p_win)
    fill = r.iloc[-6:].mean()  # (4*1 + 2*4) / 6 = 2
    expect = [k * np.mean([fill, 4.0, 4.0]), k * np.mean([fill, fill, 4.0]), k * fill]
    assert op.plans["pipeline_pr"] == pytest.approx(expect)
    assert op.fallbacks == {"purchase_request": 0, "enquiry": 1}
    # variant 2 averages the requests plan with the enquiry plan (= Excel 6-month = 2.0)
    assert op.plans["pipeline_pr_enq"] == pytest.approx([(v + 2.0) / 2 for v in expect])


def test_region_is_the_sum_of_the_countries():
    cv = pl.backtest_frame(pl.load_series(DEMO))
    reg = cv[cv["country"] == "REGION"].set_index(["cutoff", "ds"])
    summed = cv[cv["country"] != "REGION"].groupby(["cutoff", "ds"])[["y", *pl.VARIANTS]].sum()
    pd.testing.assert_frame_equal(reg[["y", *pl.VARIANTS]].sort_index(), summed.sort_index())
    assert len(reg) == bt.N_WINDOWS * bt.H


@pytest.mark.parametrize("scenario", bt.SCENARIOS)
def test_stored_results_reproduce(scenario):
    """Same origins and actuals as the stored M9 frame (checked inside run_scenario), and the
    committed JSON is exactly what the method gives today."""
    _needs_data(scenario)
    result, _ = pl.run_scenario(scenario)
    result["note"] = pl.pipeline_note(result)
    assert result == pl.load_pipeline(DERIVED, scenario)
    by = {s["method"]: s for s in result["region"]}
    m9 = next(
        s for s in bt.load_backtest(DERIVED, scenario)["series"]
        if s["level"] == "product" and s["product"] == "B"
    )  # fmt: skip
    for s in m9["scores"]:  # M9 numbers are read, never refitted
        assert by[s["method"]]["wape_pct"] == s["wape_pct"]


def test_pooled_score_is_the_m9_arithmetic():
    cv = pd.DataFrame({"y": [1.0, 3.0, 0.0], "excel_6m": [2.0, 2.0, 1.0]})
    assert pl.score(cv, ["excel_6m"])[0] | {"label": ""} == bt.score(cv, ["excel_6m"])[0] | {
        "label": ""
    }


def test_forward_plan_is_reproducible_and_keeps_the_adjustment_separate():
    plan = fp.build_plan("seasonal_trend")
    stored = json.loads(fp.plan_path(DERIVED, "seasonal_trend").read_text("utf-8"))
    assert plan == stored
    assert plan["origin"] == "2026-09-01"
    assert plan["months"] == ["2026-10-01", "2026-11-01", "2026-12-01"]
    rows = plan["rows"]
    assert len(rows) == 15
    assert plan["fast_growing"] == ["VN"]
    for r in rows:
        assert (r["pipeline_pr"] is not None) == (r["product"] == "B")
        assert (r["growth_adjustment"] is not None) == (r["country"] == "VN")
        assert r["excel_6m"] == pytest.approx(sum(r["excel_6m_monthly"]), abs=0.2)
    vn = next(r for r in rows if r["country"] == "VN" and r["product"] == "A")
    assert "Vietnam" in vn["growth_adjustment_caption"]
    assert vn["growth_adjustment"] > 0
    # the adjustment closes the measured Excel gap and is not folded into the Excel column
    b = -vn["growth_adjustment_pct"] / 100
    assert vn["growth_adjustment"] == pytest.approx(vn["excel_6m"] * -b / (1 + b), abs=0.2)


def test_forecast_api_serves_the_pipeline_fields():
    from services.api.main import app

    client = TestClient(app)
    r = client.get("/analytics/forecast/seasonal_trend")
    assert r.status_code == 200
    run = ForecastBacktest.model_validate(r.json())
    assert run.pipeline_note and "pilot must measure the conversion rate" in run.pipeline_note
    assert {s.method for s in run.pipeline_region} == {
        "excel_6m",
        "excel_12m",
        "combination",
        "pipeline_pr",
        "pipeline_pr_enq",
    }
    plan = ForecastPlan.model_validate(run.plan_next_3m.model_dump())
    assert len(plan.rows) == 15
    assert {"excel_6m", "combination", "pipeline_pr", "growth_adjustment"} <= set(plan.captions)
    dirty = client.get("/analytics/forecast/seasonal_trend?data=dirty").json()
    assert dirty["plan_next_3m"] is None and dirty["pipeline_note"] is None
    summary = client.get("/analytics/forecast").json()
    clean = [x for x in summary["runs"] if x["data"] == "clean"]
    assert all(x["plan_next_3m"] for x in clean)
