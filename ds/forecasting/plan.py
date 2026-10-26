"""Forward "Next 3 months plan" (session 13): Oct-Dec 2026, from the last full month (Sep 2026).

Per country x product (15 rows) and per scenario, side by side and never blended:
- Excel 6-month average: the mean of the last 6 months of confirmed-PO units, per month;
- ours: the M9 combination (equal-weight AutoETS(12) + AutoTheta(12) + SeasonalNaive(12),
  each floored at zero; same models and settings as ds/forecasting/backtest.py) fitted on all 36
  months of confirmed POs;
- Product B only: the pipeline plan (ds/forecasting/pipeline.py, both variants), from the
  last origin;
- a separate growth adjustment for the countries that meet the D-020 "fast-growing" definition
  in that scenario (bias.fast_growing): the backtest measured how far the Excel 6-month average
  planned that country too low (all products pooled, clean data, bias_by_country). The
  adjustment is the number of units that closes that measured gap on the Excel plan:
  excel_3m x (-b) / (1 + b), for b < 0. It is its own column; no other column includes it.

Units are rounded to 0.1 so the JSON is byte-stable. Target = confirmed POs only (rule 9).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from ds.forecasting import backtest as bt
from ds.forecasting import bias as fb
from ds.forecasting import pipeline as pl

PLAN_MONTHS = bt.H  # 3


def plan_path(derived_dir: Path, scenario: str) -> Path:
    return Path(derived_dir) / "forecast" / f"{scenario}_clean_plan.json"


def _combination_forward(tr: pd.DataFrame) -> pd.DataFrame:
    """The M9 combination fitted on the whole history, PLAN_MONTHS months ahead."""
    from statsforecast import StatsForecast
    from statsforecast.models import AutoETS, AutoTheta, SeasonalNaive

    sf = StatsForecast(
        models=[
            AutoETS(season_length=bt.SEASON, alias="ets"),
            AutoTheta(season_length=bt.SEASON, alias="theta"),
            SeasonalNaive(season_length=bt.SEASON, alias="snaive"),
        ],
        freq="MS",
        n_jobs=1,
        fallback_model=bt._fallback_model(),
    )
    fc = sf.forecast(df=tr, h=PLAN_MONTHS)
    if "unique_id" not in fc.columns:
        fc = fc.reset_index()
    fc["combination"] = fc[["ets", "theta", "snaive"]].clip(lower=0).mean(axis=1)
    return fc[["unique_id", "ds", "combination"]]


def _r(x: float) -> float:
    return round(float(x) + 0.0, 1)


def build_plan(scenario: str, derived_dir: Path = bt.DERIVED) -> dict[str, Any]:
    data_dir = bt.scenario_dir(scenario)
    dem = bt._demand(data_dir, "clean")
    months = pd.date_range(dem["month"].min(), dem["month"].max(), freq="MS")
    origin = months[-1]
    plan_months = [origin + pd.DateOffset(months=i) for i in range(1, PLAN_MONTHS + 1)]
    tr = bt._grid(dem, ["country", "family"], months)
    combo = _combination_forward(tr)

    # pipeline plan (Product B), from the last full month
    series = pl.load_series(data_dir)
    pipe = {
        c: pl.plan_at_origin(series.orders[c], {k: v[c] for k, v in series.signals.items()}, origin)
        for c in series.orders.columns
    }

    # growth adjustment: D-020 fast-growing countries, measured Excel 6-month bias
    gr = fb.growth(data_dir)
    fast = fb.fast_growing(gr)
    run = bt.load_backtest(derived_dir, scenario, "clean")
    excel_bias = {
        r["country"]: fb.bias_of(r, "excel_6m")
        for r in run["bias_by_country"]
        if r["product"] is None
    }

    rows = []
    for c in bt.COUNTRY_NAMES:
        for p in fb.PRODUCTS:
            uid = f"{c}|{p}"
            hist = tr[tr["unique_id"] == uid].sort_values("ds")["y"]
            excel_m = float(hist.iloc[-6:].mean())
            co = combo[combo["unique_id"] == uid].sort_values("ds")["combination"].tolist()
            row: dict[str, Any] = {
                "country": c,
                "country_name": bt.COUNTRY_NAMES[c],
                "product": p,
                "excel_6m": _r(excel_m * PLAN_MONTHS),
                "excel_6m_monthly": [_r(excel_m)] * PLAN_MONTHS,
                "combination": _r(sum(co)),
                "combination_monthly": [_r(v) for v in co],
                "pipeline_pr": None,
                "pipeline_pr_enq": None,
                "growth_adjustment": None,
                "growth_adjustment_pct": None,
                "growth_adjustment_caption": None,
            }
            if p == pl.PRODUCT:
                row["pipeline_pr"] = _r(sum(pipe[c].plans["pipeline_pr"]))
                row["pipeline_pr_enq"] = _r(sum(pipe[c].plans["pipeline_pr_enq"]))
            b = excel_bias.get(c)
            if c in fast and b is not None and b < 0:
                add = excel_m * PLAN_MONTHS * (-b / 100.0) / (1.0 + b / 100.0)
                row["growth_adjustment"] = _r(add)
                row["growth_adjustment_pct"] = round(-b, 1)
                row["growth_adjustment_caption"] = (
                    f"From the backtest: the Excel average planned {bt.COUNTRY_NAMES[c]} "
                    f"{-b:.0f}% low (orders grew {gr[(c, None)]:.0f}% last year). Add this many "
                    f"units on top of the Excel plan to close that gap."
                )
            rows.append(row)
    return {
        "scenario": scenario,
        "origin": f"{origin:%Y-%m-01}",
        "months": [f"{m:%Y-%m-01}" for m in plan_months],
        "fast_growing": fast,
        "rows": rows,
    }


def main(derived_dir: Path = bt.DERIVED) -> None:
    os.environ.setdefault("NIXTLA_ID_AS_COL", "1")
    for s in bt.SCENARIOS:
        bt.ensure_scenario(s)
        pl.write_json(build_plan(s, derived_dir), plan_path(derived_dir, s))
        print(f"wrote {plan_path(derived_dir, s).relative_to(bt.ROOT)}")


if __name__ == "__main__":
    main()
