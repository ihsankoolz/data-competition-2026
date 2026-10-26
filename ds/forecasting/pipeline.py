"""Product B (equipment) forecast from the request pipeline (session 13, D-017 insight).

The brief asks how data science could improve on the 6-to-12-month Excel average. For capital
equipment the answer we test here is: plan from what customers are asking for now (purchase
requests, optionally enquiries) times a conversion rate learned from history, instead of from
an average of past orders.

METHOD, FIXED BEFORE THE FIRST RUN (26 Oct 2026, commit "feat: pipeline forecast method, fixed
before first run"). Nothing below is tuned on the test origins. If a constant ever has to
change, the first version is kept and both are reported (docs/results.md and the orchestrator).

Plain English
1. For each country, count the equipment (Product B) units in purchase requests each month. An
   order usually follows its request within 0-2 months (data-spec §7: requests convert "within 2
   months"), so the pipeline for a month = the average of units requested that month and the
   2 months before.
2. Conversion rate = units ordered over the last 12 months / pipeline units over the same 12
   months, from monthly totals only. Plan = conversion rate x pipeline; request months not yet
   seen at the origin are filled with the average of the last 6 months of requests.
3. Region = the sum of the 5 country plans. Variant 2 averages this plan with the same plan
   built from enquiries instead of purchase requests.

Exact rules
- Target (CLAUDE.md rule 9): confirmed customer POs (orders.csv), units per country x month,
  Product B only. Purchase requests and enquiries are predictors only. MDM requests and the
  spreadsheet view (dirty_demand.csv) are never read.
- No request-to-order link (real SAP data does not have one): `converted_doc_num` is never read.
  `enquiries.csv` is loaded with `usecols=ENQUIRY_COLUMNS`, which leaves it out.
- Pipeline index for signal x (requests or enquiries) at month t:
      P_x(t) = mean(x[t - l] for l in 0..LMAX)
  with x[s] for any s after the origin T replaced by the fill value
      fill_x(T) = mean(x[T - REQUEST_FILL_MONTHS + 1 .. T]).
- Conversion rate at origin T, estimated from data up to T only:
      k_x(T) = sum(y[t]) / sum(P_x(t)),  t in T - CONVERSION_WINDOW + 1 .. T
  where every P_x(t) in the window uses only months <= T (so no fill is needed there). A ratio of
  totals, one number per country x signal; the lag shape is not estimated (equal weights over
  0..LMAX), because 12 noisy monthly points cannot pin down per-lag weights without overfitting.
- Orders not explained by the pipeline: not modelled separately. k is "units ordered per unit in
  the pipeline", so orders that arrive with no earlier request are carried in proportion to the
  pipeline. No intercept, no base level.
- Single-signal plan: yhat_x(T + h) = max(FLOOR, k_x(T) * P_x(T + h)), h = 1..H.
  If the window holds no pipeline units (sum P_x = 0, k undefined), that plan falls back to the
  Excel 6-month average of orders at T (what the planner would do today); fallbacks are counted
  and reported.
- Variants (both declared now, both reported):
      pipeline_pr      = yhat_requests                                  (primary)
      pipeline_pr_enq  = (yhat_requests + yhat_enquiries) / 2           (equal weights, like the
                                                                         M9 combination)
- Region = sum of the 5 country plans for each (origin, month); scored against the region's
  confirmed POs (= the sum of the country actuals).
- Backtest: the same rolling origins, horizon and metrics as M9 (ds/forecasting/backtest.py):
  h = 3, n_windows = 10, step 1; WAPE = sum |error| / sum actual, bias = sum error / sum actual,
  pooled over every (series, origin, month ahead), via `backtest.score`. Clean data only, all 3
  scenarios. Excel 6 / Excel 12 / our combination are read from the stored M9 outputs
  (`<scenario>_clean_country_cv.csv` for countries, `<scenario>_clean.json` level "product" for
  the region), never refitted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ds.forecasting import backtest as bt

# ----------------------------------------------------------------------------- fixed constants
PRODUCT = "B"  # equipment (QTS); the only product the pipeline plan is built for
LMAX = 2  # longest request -> order lag in months (lags 0, 1, 2; data-spec §7 "within 2 months")
CONVERSION_WINDOW = 12  # months ending at the origin used to estimate the conversion rate
REQUEST_FILL_MONTHS = 6  # request months after the origin are filled with this trailing mean
FALLBACK_EXCEL_MONTHS = 6  # no pipeline in the window -> Excel average of the last 6 months
FLOOR = 0.0  # units cannot be negative
H, N_WINDOWS, STEP = bt.H, bt.N_WINDOWS, bt.STEP  # same rolling origins as M9

SIGNALS = ("purchase_request", "enquiry")
VARIANTS: dict[str, tuple[str, ...]] = {
    "pipeline_pr": ("purchase_request",),  # primary
    "pipeline_pr_enq": ("purchase_request", "enquiry"),  # declared second variant
}
VARIANT_LABELS = {
    "pipeline_pr": "Pipeline plan (purchase requests x conversion rate)",
    "pipeline_pr_enq": "Pipeline plan (purchase requests and enquiries, averaged)",
}
ORDER_COLUMNS = ["country", "item_code", "qty", "doc_date"]
ENQUIRY_COLUMNS = ["country", "item_code", "qty", "doc_date", "kind"]  # never converted_doc_num


# ----------------------------------------------------------------------------- data
@dataclass(frozen=True)
class MonthlySeries:
    """Monthly Product B units per country (index = month start, columns = countries)."""

    orders: pd.DataFrame
    signals: dict[str, pd.DataFrame]  # kind -> same shape as orders


def _family_map(data_dir: Path) -> dict[str, str]:
    items = pd.read_csv(data_dir / "items.csv", dtype=str)
    return dict(zip(items["ItemCode"], items["product_family"], strict=True))


def _monthly(df: pd.DataFrame, months: pd.DatetimeIndex) -> pd.DataFrame:
    g = df.groupby(["month", "country"])["qty"].sum().astype(float).unstack("country")
    return g.reindex(index=months, columns=list(bt.COUNTRY_NAMES), fill_value=0.0).fillna(0.0)


def load_series(data_dir: Path) -> MonthlySeries:
    """Read confirmed POs and the request / enquiry pipeline for Product B (totals only)."""
    fam = _family_map(data_dir)
    orders = pd.read_csv(data_dir / "orders.csv", usecols=ORDER_COLUMNS, dtype={"item_code": str})
    enq = pd.read_csv(data_dir / "enquiries.csv", usecols=ENQUIRY_COLUMNS, dtype={"item_code": str})
    for df in (orders, enq):
        df["month"] = pd.to_datetime(df["doc_date"]).dt.to_period("M").dt.to_timestamp()
    orders = orders[orders["item_code"].map(fam) == PRODUCT]
    enq = enq[enq["item_code"].map(fam) == PRODUCT]
    all_orders = pd.read_csv(data_dir / "orders.csv", usecols=["doc_date"])
    m = pd.to_datetime(all_orders["doc_date"]).dt.to_period("M").dt.to_timestamp()
    months = pd.date_range(m.min(), m.max(), freq="MS")  # same grid as the M9 backtest
    return MonthlySeries(
        orders=_monthly(orders, months),
        signals={k: _monthly(enq[enq["kind"] == k], months) for k in SIGNALS},
    )


# ----------------------------------------------------------------------------- method
def pipeline_index(x: pd.Series, origin: pd.Timestamp, months: list[pd.Timestamp]) -> list[float]:
    """P_x(t) for each t in `months`, using only x up to `origin` (later months = fill value)."""
    known = x.loc[:origin]
    fill = float(known.iloc[-REQUEST_FILL_MONTHS:].mean())
    out = []
    for t in months:
        vals = []
        for lag in range(LMAX + 1):
            s = t - pd.DateOffset(months=lag)
            vals.append(fill if s > origin else float(known.get(s, 0.0)))
        out.append(float(np.mean(vals)))
    return out


def conversion_rate(y: pd.Series, x: pd.Series, origin: pd.Timestamp) -> float | None:
    """k_x(origin) = sum orders / sum pipeline over the CONVERSION_WINDOW months ending at the
    origin. None when the window holds no pipeline units."""
    yk = y.loc[:origin].iloc[-CONVERSION_WINDOW:]
    p = pipeline_index(x, origin, list(yk.index))
    den = float(np.sum(p))
    return float(yk.sum()) / den if den > 0 else None


@dataclass(frozen=True)
class OriginPlan:
    """One country's plan from one origin."""

    months: list[pd.Timestamp]
    plans: dict[str, list[float]]  # variant -> units per month ahead
    fallbacks: dict[str, int]  # signal -> 1 if that signal fell back to the Excel average


def plan_at_origin(
    y: pd.Series, signals: dict[str, pd.Series], origin: pd.Timestamp, h: int = H
) -> OriginPlan:
    """Pipeline plans for months origin+1 .. origin+h, from data up to the origin only."""
    y = y.loc[:origin]
    signals = {k: v.loc[:origin] for k, v in signals.items()}
    months = [origin + pd.DateOffset(months=i) for i in range(1, h + 1)]
    excel = float(y.iloc[-FALLBACK_EXCEL_MONTHS:].mean())
    single: dict[str, list[float]] = {}
    fallbacks: dict[str, int] = {}
    for kind in SIGNALS:
        k = conversion_rate(y, signals[kind], origin)
        if k is None:
            single[kind] = [max(FLOOR, excel)] * h
            fallbacks[kind] = 1
        else:
            p = pipeline_index(signals[kind], origin, months)
            single[kind] = [max(FLOOR, k * v) for v in p]
            fallbacks[kind] = 0
    plans = {
        v: [max(FLOOR, float(np.mean([single[s][i] for s in sig]))) for i in range(h)]
        for v, sig in VARIANTS.items()
    }
    return OriginPlan(months=months, plans=plans, fallbacks=fallbacks)


def origins(months: pd.DatetimeIndex) -> list[pd.Timestamp]:
    """The M9 cutoffs: first = months[len - H - (N_WINDOWS-1)*STEP - 1], then every STEP."""
    first = len(months) - H - (N_WINDOWS - 1) * STEP - 1
    return [months[first + i * STEP] for i in range(N_WINDOWS)]


def backtest_frame(series: MonthlySeries) -> pd.DataFrame:
    """Rolling-origin pipeline forecasts: country, cutoff, ds, y, <variants>, plus region rows
    (country = None as "REGION") that are the sum of the 5 countries."""
    rows = []
    months = series.orders.index
    for cutoff in origins(months):
        for c in series.orders.columns:
            op = plan_at_origin(
                series.orders[c], {k: v[c] for k, v in series.signals.items()}, cutoff
            )
            for i, ds in enumerate(op.months):
                rows.append(
                    {
                        "country": c,
                        "cutoff": cutoff,
                        "ds": ds,
                        "y": float(series.orders[c].get(ds, 0.0)),
                        **{v: op.plans[v][i] for v in VARIANTS},
                        **{f"fallback_{s}": op.fallbacks[s] for s in SIGNALS},
                    }
                )
    cv = pd.DataFrame(rows)
    region = cv.groupby(["cutoff", "ds"], as_index=False)[["y", *VARIANTS]].sum()
    region["country"] = "REGION"
    return pd.concat([cv, region], ignore_index=True)


# ============================================================================= runner (phase 2)
# Everything below scores, stores and serves the method above. It adds no constant to the
# method and changes none of its rules.
M9_METHODS = ["excel_6m", "excel_12m", "combination"]
ALL_METHODS = [*M9_METHODS, *VARIANTS]
METHOD_LABELS = {**{m: bt.LABELS[m] for m in M9_METHODS}, **VARIANT_LABELS}


def score(cv: pd.DataFrame, methods: list[str]) -> list[dict[str, Any]]:
    """Pooled WAPE and bias (%), the same arithmetic and rounding as `backtest.score`."""
    total = float(cv["y"].sum())
    out = []
    for m in methods:
        err = cv[m] - cv["y"]
        wape = 100.0 * float(err.abs().sum()) / total if total else 0.0
        bias = 100.0 * float(err.sum()) / total if total else 0.0
        out.append(
            {
                "method": m,
                "label": METHOD_LABELS[m],
                "wape_pct": round(wape, 1),
                "bias_pct": round(bias, 1),
            }
        )
    return out


def pipeline_path(derived_dir: Path, scenario: str) -> Path:
    return Path(derived_dir) / "forecast" / f"{scenario}_clean_pipeline.json"


def frame_path(derived_dir: Path, scenario: str) -> Path:
    return Path(derived_dir) / "forecast" / f"{scenario}_clean_pipeline_cv.csv"


def _stored_country_b(derived_dir: Path, scenario: str) -> pd.DataFrame:
    """The stored M9 country x product frame, Product B rows (never refitted)."""
    from ds.forecasting import bias as fb

    cv = fb.read_frame(fb.frame_path(derived_dir, scenario, "clean"))
    cv = cv[cv["product"] == PRODUCT].copy()
    for col in ("cutoff", "ds"):
        cv[col] = pd.to_datetime(cv[col])
    return cv[["country", "cutoff", "ds", "y", *M9_METHODS]]


def run_scenario(scenario: str, derived_dir: Path = bt.DERIVED) -> tuple[dict, pd.DataFrame]:
    """Backtest the pipeline plan for one scenario (clean data) and compare with stored M9."""
    series = load_series(bt.scenario_dir(scenario))
    cv = backtest_frame(series)
    countries = cv[cv["country"] != "REGION"]
    region = cv[cv["country"] == "REGION"]

    stored = _stored_country_b(derived_dir, scenario)
    joined = countries.merge(stored, on=["country", "cutoff", "ds"], suffixes=("", "_m9"))
    if len(joined) != len(countries) or len(joined) != len(stored):
        raise AssertionError(f"{scenario}: origins or months differ from the stored M9 frame")
    if not np.allclose(joined["y"], joined["y_m9"]):
        raise AssertionError(f"{scenario}: confirmed-PO actuals differ from the stored M9 frame")

    run = bt.load_backtest(derived_dir, scenario, "clean")
    m9_region = next(
        s["scores"] for s in run["series"] if s["level"] == "product" and s["product"] == PRODUCT
    )
    per_country = [
        {"country": c, "scores": score(joined[joined["country"] == c], ALL_METHODS)}
        for c in bt.COUNTRY_NAMES
    ]
    n_origin = len(countries) // H
    result = {
        "scenario": scenario,
        "data": "clean",
        "product": PRODUCT,
        "constants": {
            "LMAX": LMAX,
            "CONVERSION_WINDOW": CONVERSION_WINDOW,
            "REQUEST_FILL_MONTHS": REQUEST_FILL_MONTHS,
            "FALLBACK_EXCEL_MONTHS": FALLBACK_EXCEL_MONTHS,
            "FLOOR": FLOOR,
            "H": H,
            "N_WINDOWS": N_WINDOWS,
            "STEP": STEP,
        },
        # region: M9 numbers fitted top-down on the region total (stored JSON), pipeline built
        # bottom-up as the sum of the 5 country plans
        "region": [*m9_region, *score(region, list(VARIANTS))],
        "countries_pooled": score(joined, ALL_METHODS),
        "per_country": per_country,
        "fallbacks": {
            s: {"used": int(countries[f"fallback_{s}"].sum()) // H, "of": n_origin} for s in SIGNALS
        },
    }
    return result, cv


def write_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def write_frame(cv: pd.DataFrame, path: Path) -> None:
    out = cv.copy()
    for col in ("cutoff", "ds"):
        out[col] = pd.to_datetime(out[col]).dt.strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, lineterminator="\n")


def load_pipeline(derived_dir: Path, scenario: str) -> dict[str, Any] | None:
    path = pipeline_path(derived_dir, scenario)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


TIE_POINTS = 1.0  # same wording rule as the M9 honest note: < 1 point apart = a tie
FAVOURS = (
    "The test data creates requests from later orders, so this test favours a pipeline "
    "method; a pilot must measure the conversion rate on real data."
)


def verdict_words(result: dict[str, Any]) -> str:
    """Region, Product B, primary variant vs the best M9 method, in words."""
    by = {s["method"]: s for s in result["region"]}
    pr = by["pipeline_pr"]["wape_pct"]
    others = {m: by[m]["wape_pct"] for m in M9_METHODS}
    best_m = min(others, key=lambda m: (others[m], m))
    short = {
        "excel_6m": "the Excel 6-month average",
        "excel_12m": "the Excel 12-month average",
        "combination": "our statistical method",
    }
    diff = others[best_m] - pr
    if abs(diff) < TIE_POINTS:
        return f"effectively a tie with {short[best_m]}"
    if diff > 0:
        return f"better than every average-based method ({diff:.1f} points below the best)"
    return f"{short[best_m]} still does better"


def pipeline_note(result: dict[str, Any]) -> str:
    """One plain-English line for the app: region, Product B, primary variant vs the rest."""
    by = {s["method"]: s for s in result["region"]}
    pr = by["pipeline_pr"]["wape_pct"]
    others = {m: by[m]["wape_pct"] for m in M9_METHODS}
    verdict = verdict_words(result)
    return (
        f"Equipment (Product B), whole region: planning from purchase requests x a conversion "
        f"rate was off by {pr:.1f}% of units, against {others['excel_6m']:.1f}% for the Excel "
        f"6-month average, {others['excel_12m']:.1f}% for the 12-month average and "
        f"{others['combination']:.1f}% for ours: {verdict}. {FAVOURS}"
    )


def main(derived_dir: Path = bt.DERIVED) -> None:
    for s in bt.SCENARIOS:
        bt.ensure_scenario(s)
        result, cv = run_scenario(s, derived_dir)
        result["note"] = pipeline_note(result)
        write_json(result, pipeline_path(derived_dir, s))
        write_frame(cv, frame_path(derived_dir, s))
        print(f"{s}: {result['note']}")


if __name__ == "__main__":
    main()
