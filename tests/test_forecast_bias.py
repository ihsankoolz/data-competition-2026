"""D-020 item 1: bias by country, a cut of the same backtest forecasts (ds/forecasting/bias.py)."""

from __future__ import annotations

import pandas as pd
import pytest

from ds.forecasting import backtest as bt
from ds.forecasting import bias as fb
from services.api.schemas import ForecastBacktest

DERIVED = bt.DERIVED
RUNS = [(s, d) for s in bt.SCENARIOS for d in bt.DATAS]


def _needs_data(scenario: str) -> None:
    if not (bt.scenario_dir(scenario) / "orders.csv").exists():
        pytest.skip(f"{scenario} not generated (make data SCENARIO={scenario})")


@pytest.mark.parametrize(("scenario", "data"), RUNS)
def test_payload_has_bias_by_country(scenario, data):
    run = ForecastBacktest.model_validate(bt.load_backtest(DERIVED, scenario, data))
    rows = run.bias_by_country
    assert len(rows) == 5 * 4  # per country: all products, then A, B, C
    assert {r.country for r in rows} == set(fb.COUNTRIES)
    assert sum(r.product is None for r in rows) == 5
    for r in rows:
        assert {s.method for s in r.scores} == {"excel_6m", "excel_12m", "combination"}
    assert run.bias_note and scenario not in run.bias_note
    if "whose orders grew" in run.bias_note:  # a finding is claimed: the caveat travels with it
        assert fb.CAVEAT in run.bias_note
    else:
        assert "cannot show" in run.bias_note


@pytest.mark.parametrize(("scenario", "data"), RUNS)
def test_frame_is_the_same_backtest(scenario, data):
    """The committed raw frame reproduces every stored country x product score exactly."""
    run = bt.load_backtest(DERIVED, scenario, data)
    cv = fb.read_frame(fb.frame_path(DERIVED, scenario, data))
    assert len(cv) == 15 * bt.N_WINDOWS * bt.H
    fb.check_against_run(cv, run)


@pytest.mark.parametrize(("scenario", "data"), RUNS)
def test_bias_rows_are_deterministic(scenario, data):
    """Recomputing from the committed frame and the data gives the stored payload exactly."""
    _needs_data(scenario)
    run = bt.load_backtest(DERIVED, scenario, data)
    cv = fb.read_frame(fb.frame_path(DERIVED, scenario, data))
    gr = fb.growth(bt.scenario_dir(scenario))
    rows = fb.bias_rows(cv, gr)
    assert rows == run["bias_by_country"]
    assert fb.bias_note(rows, gr, data) == run["bias_note"]


def test_vietnam_bias_recomputed_by_hand():
    """Vietnam, all products, demo scenario, clean: bias = sum(forecast - actual) / sum(actual)
    over every origin and month ahead, straight from the raw frame."""
    cv = pd.read_csv(fb.frame_path(DERIVED, "seasonal_trend", "clean"))
    vn = cv[cv["country"] == "VN"]
    assert len(vn) == 3 * bt.N_WINDOWS * bt.H
    stored = next(
        r
        for r in bt.load_backtest(DERIVED, "seasonal_trend", "clean")["bias_by_country"]
        if r["country"] == "VN" and r["product"] is None
    )
    for s in stored["scores"]:
        err = vn[s["method"]] - vn["y"]
        assert s["bias_pct"] == pytest.approx(100 * err.sum() / vn["y"].sum(), abs=0.05)
        assert s["wape_pct"] == pytest.approx(100 * err.abs().sum() / vn["y"].sum(), abs=0.05)


def test_vietnam_growth_recomputed_by_hand():
    d = bt.scenario_dir("seasonal_trend")
    o = pd.read_csv(d / "orders.csv", dtype={"card_code": str})
    o = o[o["country"] == "VN"]
    last = o["doc_date"] >= "2025-10-01"
    prev = (o["doc_date"] >= "2024-10-01") & (o["doc_date"] < "2025-10-01")
    by_hand = 100 * (o.loc[last, "qty"].sum() / o.loc[prev, "qty"].sum() - 1)
    assert fb.growth(d)[("VN", None)] == pytest.approx(by_hand, abs=0.05)


def test_growth_uses_confirmed_orders_only():
    """The same growth is shown on the clean and the dirty run (it describes the real market)."""
    clean = bt.load_backtest(DERIVED, "seasonal_trend", "clean")["bias_by_country"]
    dirty = bt.load_backtest(DERIVED, "seasonal_trend", "dirty")["bias_by_country"]
    assert [r["growth_pct"] for r in clean] == [r["growth_pct"] for r in dirty]


def test_plan_words_and_spearman():
    assert fb.plan_words(-9.4) == "9% too low"
    assert fb.plan_words(4.2) == "4% too high"
    assert fb.plan_words(0.6) == "about right"
    assert fb.spearman([(1.0, 3.0), (2.0, 2.0), (3.0, 1.0)]) == (-1.0, 3)
    assert fb.spearman([(None, 1.0), (1.0, 2.0)]) == (None, 1)


def test_fast_growing_is_measured_not_assumed():
    gr = {(None, None): 10.0, **{(c, None): 0.0 for c in fb.COUNTRIES}}
    gr[("SG", None)] = 30.0
    assert fb.fast_growing(gr) == ["SG"]
    # one definition: faster than the region AND at least 10%
    flat = {(None, None): -0.4, **{(c, None): 4.0 for c in fb.COUNTRIES}}
    assert fb.fast_growing(flat) == []


def test_demo_note_is_short_and_leads_with_the_finding():
    note = bt.load_backtest(DERIVED, "seasonal_trend", "clean")["bias_note"]
    assert len(note) <= 230
    first = note.split(". ")[0]
    assert "Vietnam" in first and "Excel 6-month average planned" in first and "too low" in first
    assert "because" not in note  # no causal claim in the app; the diagnosis is in results.md


def test_dirty_notes_flag_leakage():
    for s in bt.SCENARIOS:
        assert "leaked enquiries" in bt.load_backtest(DERIVED, s, "dirty")["bias_note"]


def test_growing_market_is_named_not_hidden():
    """Sparse ordering: Thailand grew 10%+ but slower than the region; the note names it."""
    note = bt.load_backtest(DERIVED, "intermittent", "clean")["bias_note"]
    gr_th = next(
        r["growth_pct"]
        for r in bt.load_backtest(DERIVED, "intermittent", "clean")["bias_by_country"]
        if r["country"] == "TH" and r["product"] is None
    )
    if gr_th >= fb.MIN_FAST_GROWTH:
        assert "Thailand" in note
