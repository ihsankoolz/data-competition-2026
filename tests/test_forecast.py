"""M9 forecast backtest (D-008): fixed design, metric maths, precomputed JSON contract."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ds.forecasting import backtest as bt
from services.api.schemas import ForecastBacktest, ForecastSummary

DERIVED = bt.DERIVED


def test_design_is_fixed():
    assert (bt.H, bt.N_WINDOWS, bt.STEP, bt.SEASON) == (3, 10, 1, 12)
    assert bt.ADI_CUTOFF == 1.32
    assert bt.SCENARIOS == ("seasonal_trend", "flat_noisy", "intermittent")


def test_wape_and_bias_maths():
    cv = pd.DataFrame({"y": [10.0, 10.0, 0.0], "excel_6m": [12.0, 6.0, 2.0]})
    (s,) = bt.score(cv, ["excel_6m"])
    assert s["wape_pct"] == pytest.approx(100 * (2 + 4 + 2) / 20)
    assert s["bias_pct"] == pytest.approx(100 * (2 - 4 + 2) / 20)


def test_adi():
    assert bt.adi(np.array([1, 0, 0, 1, 0, 0])) == 3.0
    assert bt.adi(np.array([1, 1, 1])) == 1.0
    assert bt.adi(np.zeros(4)) == float("inf")


def test_backtest_smoke_on_two_series():
    """Origins and horizon as designed: 10 origins x 3 months per series, all methods present,
    forecasts never negative, origins inside the last 12 months."""
    months = pd.date_range("2023-10-01", periods=36, freq="MS")
    rng = np.random.default_rng(0)
    season = 1 + 0.2 * np.sin(np.arange(36) * 2 * np.pi / 12)
    rows = []
    for uid, level in (("VN|A", 100.0), ("SG|B", 0.4)):
        y = rng.poisson(level * season).astype(float)
        rows += [{"unique_id": uid, "ds": m, "y": v} for m, v in zip(months, y, strict=True)]
    cv = bt._forecasts(pd.DataFrame(rows), with_tsb=True)
    assert len(cv) == 2 * bt.N_WINDOWS * bt.H
    assert set(bt.method_list(True)) <= set(cv.columns)
    assert (cv[bt.method_list(True)] >= 0).all().all()
    assert cv["cutoff"].min() == months[23] and cv["cutoff"].max() == months[32]
    assert cv["ds"].min() == months[24] and cv["ds"].max() == months[35]


def _runs() -> list[Path]:
    return sorted((DERIVED / "forecast").glob("*.json"))


def test_all_six_runs_are_committed():
    names = {p.stem for p in _runs()}
    assert names == {f"{s}_{d}" for s in bt.SCENARIOS for d in bt.DATAS}


@pytest.mark.parametrize("scenario", bt.SCENARIOS)
@pytest.mark.parametrize("data", bt.DATAS)
def test_load_backtest_validates(scenario, data):
    run = ForecastBacktest.model_validate(bt.load_backtest(DERIVED, scenario, data))
    assert run.scenario == scenario and run.data == data
    cp = [s for s in run.series if s.level == "country_product"]
    assert len(cp) == 15
    assert {s.product for s in run.series if s.level == "product"} == {"A", "B", "C"}
    assert {x.method for x in run.overall} == {"excel_6m", "excel_12m", "combination"}
    for s in run.series:
        assert s.winner == min(s.scores, key=lambda x: (x.wape_pct, x.method)).method
        if s.level == "customer_product":
            assert "tsb" in {x.method for x in s.scores}
    assert run.chart_series == "Vietnam, Product A (units)"
    assert len(run.chart) == 36 and sum(p.combination is not None for p in run.chart) == 12
    # D-008: never claim that merging duplicates improves the country forecast
    note = run.honest_note.lower()
    assert "improve" not in note
    if data == "clean":
        assert "does not change this forecast" in note


def test_honest_note_names_the_winner():
    ov = {s["method"]: s for s in bt.load_backtest(DERIVED, "flat_noisy", "clean")["overall"]}
    note = bt.load_backtest(DERIVED, "flat_noisy", "clean")["honest_note"]
    diff = ov["excel_6m"]["wape_pct"] - ov["combination"]["wape_pct"]
    if diff < -1:
        assert "Excel average wins" in note
    elif abs(diff) < 1:
        assert "tied" in note


def test_summary_validates():
    s = ForecastSummary.model_validate(bt.forecast_summary(DERIVED))
    assert len(s.runs) == 6
    assert {"wape_pct", "bias_pct", "excel_6m", "combination"} <= set(s.captions)


def test_load_backtest_rejects_unknown():
    with pytest.raises(ValueError):
        bt.load_backtest(DERIVED, "nope", "clean")
    with pytest.raises(ValueError):
        bt.load_backtest(DERIVED, "flat_noisy", "muddy")  # type: ignore[arg-type]


def test_dedup_does_not_change_country_totals():
    """D-008 nuance in code: country x product units are the same keyed by raw record or by
    our golden clusters; only leakage (dirty) changes them."""
    d = bt.scenario_dir("seasonal_trend")
    clean = bt._demand(d, "clean")
    by_raw = clean.groupby(["country", "family"])["qty"].sum()
    assert clean["customer"].nunique() < clean["card_code"].nunique()  # merging happened
    by_golden = (
        clean.groupby(["country", "family", "customer"])["qty"].sum().groupby(level=[0, 1]).sum()
    )
    pd.testing.assert_series_equal(by_raw, by_golden)
    dirty = bt._demand(d, "dirty").groupby(["country", "family"])["qty"].sum()
    assert (dirty >= by_raw).all() and dirty.sum() > by_raw.sum()
