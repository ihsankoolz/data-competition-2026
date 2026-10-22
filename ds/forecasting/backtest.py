"""Forecast backtest (PRD M9, D-008). Run offline, results precomputed to JSON; the API only reads.

`python -m ds.forecasting.backtest [scenario ...]` regenerates
data/fixtures/derived/forecast/<scenario>_<data>.json for all 3 scenarios x clean/dirty (about
10 minutes). `--notes-only` rewrites just the honest notes from the stored scores.
Origins, horizon, metrics and baseline are fixed (D-008).

Design (fixed before the first run; nothing below was tuned on the test origins):
- Target: monthly units per series, 36 months of history (Oct 2023 - Sep 2026).
- Rolling origin: `cross_validation(h=3, n_windows=10, step_size=1)`. The first origin is the end
  of month 24, the last is month 33, so the forecasts cover the last 12 months.
- Methods: the Excel habit `WindowAverage(6)` and `WindowAverage(12)`; ours = the equal-weight
  mean of `AutoETS(12)`, `AutoTheta(12)` and `SeasonalNaive(12)` (Petropoulos & Svetunkov 2020);
  `TSB(alpha_d=0.1, alpha_p=0.1)` (Teunter, Syntetos & Babai 2011, textbook smoothing values) for
  customer x product series that are intermittent (ADI > 1.32, measured on the first 24 months
  only). Forecasts are clipped at zero (units cannot be negative).
- Levels: country x product (15 series, the headline), product = region total (3 series; D-017:
  Product B is too sparse per country to judge alone), customer x product (intermittent only).
- Metrics, pooled over every (series, origin, horizon) point of a level: WAPE = sum |error| / sum
  actual; bias = sum (forecast - actual) / sum actual. Both in %.
- clean = confirmed POs (orders.csv), customers = our dedup clusters (ds.analytics.golden).
  dirty = the spreadsheet view (dirty_demand.csv: POs + leaked enquiries, purchase requests and
  MDM requests), customers = raw CardCodes. Both are scored against what customers really
  ordered (confirmed POs), because that is what the plan has to meet.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

Data = Literal["clean", "dirty"]

ROOT = Path(__file__).resolve().parents[2]
DERIVED = ROOT / "data" / "fixtures" / "derived"
SCENARIOS = ("seasonal_trend", "flat_noisy", "intermittent")
DATAS: tuple[Data, ...] = ("clean", "dirty")

H, N_WINDOWS, STEP, SEASON = 3, 10, 1, 12
ADI_CUTOFF = 1.32
TSB_ALPHA_D, TSB_ALPHA_P = 0.1, 0.1
CHART_SERIES = ("VN", "A")

LABELS = {
    "excel_6m": "Excel average (last 6 months)",
    "excel_12m": "Excel average (last 12 months)",
    "combination": "Our method (ETS + Theta + seasonal naive, averaged)",
    "tsb": "Intermittent-demand method (TSB)",
}
COUNTRY_NAMES = {
    "SG": "Singapore",
    "MY": "Malaysia",
    "ID": "Indonesia",
    "VN": "Vietnam",
    "TH": "Thailand",
}
SETUP = (
    "Rolling-origin backtest over the last 12 months: from each of 10 month-ends (one month "
    "apart) we forecast the next 3 months using only the data up to that point, then compare "
    "with what customers actually ordered. Units per month. Error = WAPE (absolute error as % "
    "of volume); bias = over (+) or under (-) forecasting as % of volume."
)


def scenario_dir(scenario: str) -> Path:
    """Where each scenario's generated data lives (the demo scenario is the committed fixture)."""
    if scenario == "seasonal_trend":
        return ROOT / "data" / "fixtures" / "seasonal_trend"
    return ROOT / "data" / "generated" / scenario


# -------------------------------------------------------------------------------- data
def _demand(data_dir: Path, data: Data) -> pd.DataFrame:
    """Rows: card_code, country, family, month, qty, plus the customer key used at that level."""
    items = pd.read_csv(data_dir / "items.csv", dtype=str)
    family = dict(zip(items["ItemCode"], items["product_family"], strict=True))
    name = "orders.csv" if data == "clean" else "dirty_demand.csv"
    df = pd.read_csv(data_dir / name, dtype={"card_code": str, "item_code": str})
    df["month"] = pd.to_datetime(df["doc_date"]).dt.to_period("M").dt.to_timestamp()
    df["family"] = df["item_code"].map(family)
    if data == "clean":
        from ds.analytics.golden import golden_clusters

        gold = golden_clusters(data_dir)
        df["customer"] = df["card_code"].map(gold).fillna(df["card_code"])
    else:
        df["customer"] = df["card_code"]
    return df[["card_code", "customer", "country", "family", "month", "qty"]]


def _grid(df: pd.DataFrame, id_cols: list[str], months: pd.DatetimeIndex) -> pd.DataFrame:
    """Long frame unique_id / ds / y with every month present (zeros filled)."""
    g = df.groupby([*id_cols, "month"])["qty"].sum().astype(float)
    wide = g.unstack("month", fill_value=0.0).reindex(columns=months, fill_value=0.0)
    wide.index = ["|".join(map(str, ix if isinstance(ix, tuple) else (ix,))) for ix in wide.index]
    long = wide.stack().rename("y").reset_index()
    long.columns = ["unique_id", "ds", "y"]
    long["y"] = long["y"].astype(float)
    return long.sort_values(["unique_id", "ds"], ignore_index=True)


def adi(y: np.ndarray) -> float:
    """Average demand interval: periods per non-zero period (inf if never ordered)."""
    nz = int((y > 0).sum())
    return float(len(y)) / nz if nz else float("inf")


# -------------------------------------------------------------------------------- models
def _cv(train: pd.DataFrame, models: list) -> pd.DataFrame:
    from statsforecast import StatsForecast
    from statsforecast.models import SeasonalNaive

    sf = StatsForecast(
        models=models, freq="MS", n_jobs=1, fallback_model=SeasonalNaive(season_length=SEASON)
    )
    return sf.cross_validation(df=train, h=H, n_windows=N_WINDOWS, step_size=STEP)


def _forecasts(train: pd.DataFrame, with_tsb: bool, with_combo: bool = True) -> pd.DataFrame:
    """Cross-validated forecasts: unique_id, ds, cutoff, excel_6m, excel_12m, combination[, tsb]."""
    from statsforecast.models import TSB, AutoETS, AutoTheta, SeasonalNaive, WindowAverage

    models: list = [
        WindowAverage(window_size=6, alias="excel_6m"),
        WindowAverage(window_size=12, alias="excel_12m"),
    ]
    if with_combo:
        models += [
            AutoETS(season_length=SEASON, alias="ets"),
            AutoTheta(season_length=SEASON, alias="theta"),
            SeasonalNaive(season_length=SEASON, alias="snaive"),
        ]
    if with_tsb:
        models.append(TSB(alpha_d=TSB_ALPHA_D, alpha_p=TSB_ALPHA_P, alias="tsb"))
    cv = _cv(train, models)
    if "unique_id" not in cv.columns:  # older statsforecast returned it as the index
        cv = cv.reset_index()
    if with_combo:
        cv["combination"] = cv[["ets", "theta", "snaive"]].clip(lower=0).mean(axis=1)
    methods = method_list(with_tsb, with_combo)
    cv[methods] = cv[methods].clip(lower=0)
    return cv[["unique_id", "ds", "cutoff", *methods]]


def method_list(with_tsb: bool, with_combo: bool = True) -> list[str]:
    out = ["excel_6m", "excel_12m"]
    if with_combo:
        out.append("combination")
    if with_tsb:
        out.append("tsb")
    return out


def score(cv: pd.DataFrame, methods: list[str]) -> list[dict[str, Any]]:
    """Pooled WAPE and bias (%) for each method over every row of `cv` (needs column `y`)."""
    total = float(cv["y"].sum())
    out = []
    for m in methods:
        err = cv[m] - cv["y"]
        wape = 100.0 * float(err.abs().sum()) / total if total else 0.0
        bias = 100.0 * float(err.sum()) / total if total else 0.0
        out.append(
            {
                "method": m,
                "label": LABELS[m],
                "wape_pct": round(wape, 1),
                "bias_pct": round(bias, 1),
            }
        )
    return out


def _winner(scores: list[dict[str, Any]]) -> str:
    return min(scores, key=lambda s: (s["wape_pct"], s["method"]))["method"]


def _with_truth(cv: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """Attach the confirmed-PO actual for each forecast row (0 when the series has none)."""
    t = truth[["unique_id", "ds", "y"]]
    out = cv.merge(t, on=["unique_id", "ds"], how="left")
    out["y"] = out["y"].fillna(0.0)
    return out


# -------------------------------------------------------------------------------- run
def run_backtest(data_dir: Path, scenario: str, data: Data) -> dict[str, Any]:
    """-> ForecastBacktest dict for one scenario and one data view (slow: seconds to a minute)."""
    train_df = _demand(data_dir, data)
    truth_df = _demand(data_dir, "clean") if data == "dirty" else train_df
    months = pd.date_range(truth_df["month"].min(), truth_df["month"].max(), freq="MS")
    first_cutoff = months[len(months) - H - (N_WINDOWS - 1) * STEP - 1]

    series: list[dict[str, Any]] = []

    # --- country x product (headline) ---
    tr = _grid(train_df, ["country", "family"], months)
    tt = _grid(truth_df, ["country", "family"], months)
    cv = _with_truth(_forecasts(tr, with_tsb=False), tt)
    methods = method_list(False)
    for uid, g in cv.groupby("unique_id", sort=True):
        c, p = uid.split("|")
        sc = score(g, methods)
        series.append(
            {
                "level": "country_product",
                "country": c,
                "product": p,
                "scores": sc,
                "winner": _winner(sc),
            }
        )
    overall = score(cv, methods)

    # --- product = region total (D-017) ---
    trp = _grid(train_df, ["family"], months)
    ttp = _grid(truth_df, ["family"], months)
    cvp = _with_truth(_forecasts(trp, with_tsb=False), ttp)
    for uid, g in cvp.groupby("unique_id", sort=True):
        sc = score(g, methods)
        series.append(
            {
                "level": "product",
                "country": None,
                "product": uid,
                "scores": sc,
                "winner": _winner(sc),
            }
        )

    # --- customer x product, intermittent series only (ADI on the first training window) ---
    trc = _grid(train_df, ["customer", "family"], months)
    hist = trc[trc["ds"] <= first_cutoff]
    keep = [
        uid
        for uid, g in hist.groupby("unique_id", sort=True)
        if (g["y"].to_numpy() > 0).sum() >= 2 and adi(g["y"].to_numpy()) > ADI_CUTOFF
    ]
    n_cust = len(keep)
    if keep:
        # truth by the same customer key: our clusters (clean) or the raw record (dirty)
        tkey = "customer" if data == "clean" else "card_code"
        ttc = _grid(truth_df.assign(customer=truth_df[tkey]), ["customer", "family"], months)
        cmethods = method_list(True)
        cvc = _with_truth(_forecasts(trc[trc["unique_id"].isin(keep)], with_tsb=True), ttc)
        cvc["product"] = cvc["unique_id"].str.rsplit("|", n=1).str[1]
        for p, g in cvc.groupby("product", sort=True):
            sc = score(g, cmethods)
            series.append(
                {
                    "level": "customer_product",
                    "country": None,
                    "product": p,
                    "scores": sc,
                    "winner": _winner(sc),
                }
            )

    # --- chart: VN x A, the latest-origin (shortest lead) forecast for each test month ---
    cid = "|".join(CHART_SERIES)
    ch = cv[cv["unique_id"] == cid].sort_values(["ds", "cutoff"]).groupby("ds").tail(1)
    fc = {d: r for d, r in zip(ch["ds"], ch.itertuples(), strict=True)}
    actual = tt[tt["unique_id"] == cid].set_index("ds")["y"]
    chart = []
    for m in months:
        r = fc.get(m)
        chart.append(
            {
                "month": f"{m:%Y-%m-01}",
                "actual": round(float(actual.get(m, 0.0)), 2),
                "excel_6m": None if r is None else round(float(r.excel_6m), 2),
                "combination": None if r is None else round(float(r.combination), 2),
            }
        )

    setup = (
        f"{SETUP} Overall = all 15 country x product series pooled. Customer-level rows cover "
        f"the {n_cust} intermittent customer x product series (ordering in fewer than 1 month in "
        f"{ADI_CUTOFF:g} on average before the first origin)."
    )
    if data == "dirty":
        setup += (
            " Dirty: the models learn from the spreadsheet view (POs plus leaked enquiries, "
            "purchase requests and master data requests, raw customer records) but are scored "
            "against the real confirmed POs."
        )
    return {
        "scenario": scenario,
        "data": data,
        "setup": setup,
        "overall": overall,
        "series": series,
        "chart": chart,
        "chart_series": f"{COUNTRY_NAMES[CHART_SERIES[0]]}, Product {CHART_SERIES[1]} (units)",
        "honest_note": _honest_note(scenario, data, overall, series),
    }


def _honest_note(
    scenario: str, data: Data, overall: list[dict[str, Any]], series: list[dict[str, Any]]
) -> str:
    by = {s["method"]: s for s in overall}
    ex, co = by["excel_6m"], by["combination"]
    cp = [s for s in series if s["level"] == "country_product"]
    wins = sum(
        1
        for s in cp
        if {x["method"]: x["wape_pct"] for x in s["scores"]}["combination"]
        < {x["method"]: x["wape_pct"] for x in s["scores"]}["excel_6m"]
    )
    diff = ex["wape_pct"] - co["wape_pct"]
    if abs(diff) < 1.0:
        head = (
            f"In {scenario} the two are effectively tied: our method's error is "
            f"{co['wape_pct']:.1f}% of volume against {ex['wape_pct']:.1f}% for the 6-month "
            f"Excel average."
        )
    elif diff > 0:
        head = (
            f"In {scenario} our method's error is {co['wape_pct']:.1f}% of volume against "
            f"{ex['wape_pct']:.1f}% for the 6-month Excel average."
        )
    else:
        head = (
            f"In {scenario} the 6-month Excel average wins: {ex['wape_pct']:.1f}% error against "
            f"{co['wape_pct']:.1f}% for our method."
        )
    head += f" Ours is better on {wins} of {len(cp)} country x product series."
    e12 = by["excel_12m"]
    d12 = e12["wape_pct"] - co["wape_pct"]
    if abs(d12) < 1.0:
        head += (
            f" A 12-month Excel average ({e12['wape_pct']:.1f}%) does as well as ours, so we do "
            f"not claim a better country-level forecast here."
        )
    elif d12 < 0:
        head += f" A 12-month Excel average does better still ({e12['wape_pct']:.1f}%)."
    if data == "dirty":
        tail = (
            f" Planning from the spreadsheet view biases every method upwards (Excel average "
            f"{ex['bias_pct']:+.1f}%), because leaked enquiries and requests are counted as orders."
        )
    else:
        tail = (
            " Merging duplicate customers does not change these country x product totals, so it "
            "does not change this forecast; it changes customer-level numbers. Removing leaked "
            "enquiries does change the totals (compare the dirty run)."
        )
    return head + tail


# -------------------------------------------------------------------------------- read side
def _path(derived_dir: Path, scenario: str, data: Data) -> Path:
    return Path(derived_dir) / "forecast" / f"{scenario}_{data}.json"


def load_backtest(derived_dir: Path, scenario: str, data: Data = "clean") -> dict[str, Any]:
    """-> ForecastBacktest, read from the precomputed JSON."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    if data not in DATAS:
        raise ValueError(f"data must be 'clean' or 'dirty', not {data!r}")
    path = _path(derived_dir, scenario, data)
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run `uv run python -m ds.forecasting.backtest`")
    return json.loads(path.read_text(encoding="utf-8"))


SUMMARY_CAPTIONS: dict[str, dict[str, str]] = {
    "wape_pct": {
        "title": "Forecast error (WAPE)",
        "caption": "How far off the forecast was, as a % of the units actually ordered. Lower is "
        "better.",
    },
    "bias_pct": {
        "title": "Bias",
        "caption": "Whether the forecast ran high (+) or low (-) overall, as a % of units ordered.",
    },
    "excel_6m": {
        "title": "Excel average",
        "caption": "Today's habit: next month = the average of the last 6 (or 12) months.",
    },
    "combination": {
        "title": "Our method",
        "caption": "The average of three standard statistical forecasts that learn trend and "
        "seasonality from 3 years of SAP history.",
    },
    "tsb": {
        "title": "Intermittent-demand method (TSB)",
        "caption": "For customers who order only now and then: forecasts how often they order "
        "and how much, separately.",
    },
    "clean_dirty": {
        "title": "Clean vs dirty data",
        "caption": "Dirty = today's spreadsheet, where some enquiries and requests are counted as "
        "orders. Clean = confirmed POs only. Both are checked against real orders.",
    },
    "scenarios": {
        "title": "Scenarios",
        "caption": "Three synthetic markets: growing and seasonal (the demo), flat and noisy "
        "(where a plain average should do fine), and sparse ordering.",
    },
}


def forecast_summary(derived_dir: Path) -> dict[str, Any]:
    """-> ForecastSummary (every scenario x clean/dirty run, plus captions)."""
    runs = [
        load_backtest(derived_dir, s, d)
        for s in SCENARIOS
        for d in DATAS
        if _path(derived_dir, s, d).exists()
    ]
    return {"runs": runs, "captions": {k: dict(v) for k, v in SUMMARY_CAPTIONS.items()}}


def write_backtest(result: dict[str, Any], derived_dir: Path = DERIVED) -> Path:
    path = _path(derived_dir, result["scenario"], result["data"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(result, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    return path


def ensure_scenario(scenario: str, seed: int = 42) -> Path:
    """Generate a non-demo scenario into data/generated/ if it is not there yet."""
    d = scenario_dir(scenario)
    if not (d / "orders.csv").exists():
        import subprocess

        subprocess.run(
            [
                sys.executable,
                "-m",
                "ds.generator",
                "--scenario",
                scenario,
                "--seed",
                str(seed),
                "--out",
                str(d.parent),
            ],
            check=True,
            cwd=ROOT,
        )
    return d


def refresh_notes(derived_dir: Path = DERIVED) -> None:
    """Rewrite only the honest_note of each stored run from its stored scores (no refit)."""
    for s in SCENARIOS:
        for d in DATAS:
            if _path(derived_dir, s, d).exists():
                run = load_backtest(derived_dir, s, d)
                run["honest_note"] = _honest_note(s, d, run["overall"], run["series"])
                write_backtest(run, derived_dir)


def main(scenarios: tuple[str, ...] = SCENARIOS) -> None:
    os.environ.setdefault("NIXTLA_ID_AS_COL", "1")
    for s in scenarios:
        d = ensure_scenario(s)
        for data in DATAS:
            path = write_backtest(run_backtest(d, s, data))
            print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    if sys.argv[1:] == ["--notes-only"]:
        refresh_notes()
    else:
        main(tuple(sys.argv[1:]) or SCENARIOS)
