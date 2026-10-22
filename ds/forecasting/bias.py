"""D-020 item 1: does the Excel 6-month average under-forecast the fast-growing markets?

A new cut of the existing backtest (ds/forecasting/backtest.py), not a new backtest: the
generator, the data, origins, horizon, models and settings are untouched.

`python -m ds.forecasting.bias [--from-frames]` (about 30 seconds):
1. refits the country x product level of the backtest exactly as `run_backtest` does (same
   `_grid`, `_forecasts`, `_with_truth`), checks that every per-series score matches the stored
   run JSON, and writes the raw forecast frame to
   data/fixtures/derived/forecast/<scenario>_<data>_country_cv.csv (`--from-frames` skips the
   refit and reuses the committed frames);
2. adds `bias_by_country` and `bias_note` to each stored run JSON.

Analysis design, written down before any bias number was looked at:
- Growth = confirmed-PO units (orders.csv, never the spreadsheet view), last 12 full months vs
  the 12 before, % change; per country (all products) and per country x product. The same growth
  is used for the clean and the dirty run, because it describes the real market.
- "Fast-growing" = a country whose growth is above the growth of the region as a whole
  (plus a 10% floor, added after the first look: see below).
- Scores are pooled exactly like the headline table: WAPE = sum |forecast - actual| / sum actual,
  bias = sum (forecast - actual) / sum actual, over every origin and month ahead; a country's
  "all products" row pools its 3 product series (so it is dominated by Product A units).
- Relationship = Spearman rank correlation of growth vs bias, across the 15 country x product
  series and across the 5 countries. Reported with its sample size; it rests on synthetic data.

Added after the first look (reported as such in docs/results.md):
- The growth window above is the same 12 months the backtest forecasts, so a series that dips by
  chance in that year makes every forecast look high: part of any negative correlation is
  mechanical. Robustness check: the same correlation with growth measured the year *before* the
  test year (`growth(..., offset=12)`), which a planner would have known at the time.
- Fast-growing also needs growth of at least 10% (MIN_FAST_GROWTH): in the flat scenario
  'faster than a -0.4% region' meant +4%. One definition for the note and every table.
- The frame also keeps the three parts of our combination, to explain its bias (diagnosis only).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd

from ds.forecasting import backtest as bt

METHODS = ["excel_6m", "excel_12m", "combination"]
COMPONENTS = ["ets", "theta", "snaive"]
FRAME_COLS = ["country", "product", "cutoff", "ds", "y", *METHODS, *COMPONENTS]
COUNTRIES = ("SG", "MY", "ID", "VN", "TH")
PRODUCTS = ("A", "B", "C")
MIN_FAST_GROWTH = 10.0  # % growth below which no market "stands out" (note wording only)

Growth = dict[tuple[str | None, str | None], float | None]


# -------------------------------------------------------------------------------- growth
def growth(data_dir: Path, offset: int = 0) -> Growth:
    """Confirmed-PO unit growth (%), 12 full months vs the 12 before, ending `offset` months
    before the last month. offset=0: last 12 vs the 12 before (the headline definition).

    Keys: (country, product); None = all products. (None, None) is the whole region."""
    items = pd.read_csv(data_dir / "items.csv", dtype=str)
    family = dict(zip(items["ItemCode"], items["product_family"], strict=True))
    df = pd.read_csv(data_dir / "orders.csv", dtype={"card_code": str, "item_code": str})
    df["month"] = pd.to_datetime(df["doc_date"]).dt.to_period("M")
    df["product"] = df["item_code"].map(family)
    end = df["month"].max() - offset
    cur = (df["month"] <= end) & (df["month"] > end - 12)
    prev = (df["month"] <= end - 12) & (df["month"] > end - 24)

    def pct(mask: pd.Series) -> float | None:
        before = float(df.loc[mask & prev, "qty"].sum())
        now = float(df.loc[mask & cur, "qty"].sum())
        return round(100.0 * (now / before - 1.0), 1) if before else None

    every = pd.Series(True, index=df.index)
    out: Growth = {(None, None): pct(every)}
    for c in COUNTRIES:
        in_c = df["country"] == c
        out[(c, None)] = pct(in_c)
        for p in PRODUCTS:
            out[(c, p)] = pct(in_c & (df["product"] == p))
    return out


# -------------------------------------------------------------------------------- frames
def frame_path(derived_dir: Path, scenario: str, data: str) -> Path:
    return Path(derived_dir) / "forecast" / f"{scenario}_{data}_country_cv.csv"


def country_cv(data_dir: Path, data: bt.Data) -> pd.DataFrame:
    """Refit the country x product level of `bt.run_backtest` (same code path, same settings)."""
    train_df = bt._demand(data_dir, data)
    truth_df = bt._demand(data_dir, "clean") if data == "dirty" else train_df
    months = pd.date_range(truth_df["month"].min(), truth_df["month"].max(), freq="MS")
    tr = bt._grid(train_df, ["country", "family"], months)
    tt = bt._grid(truth_df, ["country", "family"], months)
    cv = bt._with_truth(bt._forecasts(tr, with_tsb=False, components=True), tt)
    parts = cv["unique_id"].str.split("|", expand=True)
    cv["country"], cv["product"] = parts[0], parts[1]
    return cv[FRAME_COLS].sort_values(["country", "product", "cutoff", "ds"], ignore_index=True)


def write_frame(cv: pd.DataFrame, path: Path) -> None:
    out = cv.copy()
    for col in ("cutoff", "ds"):
        out[col] = pd.to_datetime(out[col]).dt.strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    # full precision, read back with round_trip: the frame scores to exactly the stored numbers
    # (a 6-decimal frame flips scores that sit on a .x5 rounding tie)
    out.to_csv(path, index=False, lineterminator="\n")


def read_frame(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"country": str, "product": str}, float_precision="round_trip")


def check_against_run(cv: pd.DataFrame, run: dict[str, Any]) -> None:
    """The refitted frame must reproduce every stored country x product score exactly (as
    rounded in the JSON), otherwise it is not the same backtest."""
    stored = {
        (s["country"], s["product"]): s["scores"]
        for s in run["series"]
        if s["level"] == "country_product"
    }
    for (c, p), g in cv.groupby(["country", "product"], sort=True):
        if bt.score(g, METHODS) != stored[(c, p)]:
            raise AssertionError(f"{run['scenario']}/{run['data']} {c}|{p}: scores differ")


# -------------------------------------------------------------------------------- analysis
def bias_rows(cv: pd.DataFrame, gr: Growth) -> list[dict[str, Any]]:
    """-> list[CountryBias]: per country (all products pooled), then per country x product."""
    rows: list[dict[str, Any]] = []
    for c in COUNTRIES:
        gc = cv[cv["country"] == c]
        rows.append({"country": c, "product": None, "growth_pct": gr[(c, None)],
                     "scores": bt.score(gc, METHODS)})  # fmt: skip
        for p in PRODUCTS:
            rows.append({"country": c, "product": p, "growth_pct": gr[(c, p)],
                         "scores": bt.score(gc[gc["product"] == p], METHODS)})  # fmt: skip
    return rows


def bias_of(row: dict[str, Any], method: str) -> float:
    return next(s["bias_pct"] for s in row["scores"] if s["method"] == method)


def spearman(points: list[tuple[float | None, float]]) -> tuple[float | None, int]:
    """Rank correlation over the (growth, bias) points that have a growth figure."""
    pts = [(g, b) for g, b in points if g is not None]
    if len(pts) < 3:
        return None, len(pts)
    df = pd.DataFrame(pts, columns=["g", "b"])
    rho = df["g"].corr(df["b"], method="spearman")
    return (None if pd.isna(rho) else round(float(rho), 2)), len(pts)


def correlations(
    rows: list[dict[str, Any]], gr_other: Growth | None = None
) -> dict[str, dict[str, tuple[float | None, int]]]:
    """{method: {"series": (rho, n), "countries": (rho, n)}} for growth vs bias. With
    `gr_other`, growth is taken from it instead (the robustness check)."""

    def g(r: dict[str, Any]) -> float | None:
        return r["growth_pct"] if gr_other is None else gr_other[(r["country"], r["product"])]

    out = {}
    for m in METHODS:
        out[m] = {
            "series": spearman([(g(r), bias_of(r, m)) for r in rows if r["product"] is not None]),
            "countries": spearman([(g(r), bias_of(r, m)) for r in rows if r["product"] is None]),
        }
    return out


def fast_growing(gr: Growth) -> list[str]:
    """Countries growing faster than the region AND by at least MIN_FAST_GROWTH %. The one
    definition used by the payload note and every table in docs/results.md."""
    region = gr[(None, None)] or 0.0
    return [
        c
        for c in COUNTRIES
        if gr[(c, None)] is not None and gr[(c, None)] > region and gr[(c, None)] >= MIN_FAST_GROWTH
    ]


def plan_words(b: float) -> str:
    """'9% too low' / '4% too high' / 'about right' (within 1%)."""
    if abs(b) < 1.0:
        return "about right"
    return f"{abs(b):.0f}% too {'low' if b < 0 else 'high'}"


def _range_words(values: list[float]) -> str:
    """'2% too low to 6% too high', or '5% to 16% too high' when both point the same way."""
    lo, hi = min(values), max(values)
    wl, wh = plan_words(lo), plan_words(hi)
    if wl == wh:
        return wl
    if lo <= -1.0 and hi <= -1.0:
        return f"{abs(hi):.0f}% to {abs(lo):.0f}% too low"
    if lo >= 1.0 and hi >= 1.0:
        return f"{lo:.0f}% to {hi:.0f}% too high"
    return f"{wl} to {wh}"


def _list_words(values: list[float]) -> str:
    """'16% and 11% too low' when they point the same way, else each in full."""
    words = [plan_words(v) for v in values]
    if len(values) > 1 and all(w.endswith("too low") for w in words):
        return " and ".join(f"{abs(v):.0f}%" for v in values) + " too low"
    if len(values) > 1 and all(w.endswith("too high") for w in words):
        return " and ".join(f"{abs(v):.0f}%" for v in values) + " too high"
    return " and ".join(words)


def component_bias(cv: pd.DataFrame, country: str) -> dict[str, float]:
    """Bias (%) of each part of our combination in one country, all products pooled
    (diagnosis for docs/results.md only)."""
    g = cv[cv["country"] == country]
    total = float(g["y"].sum())
    return {m: 100.0 * float((g[m] - g["y"]).sum()) / total for m in COMPONENTS}


CAVEAT = "synthetic data, a pattern not proof"
LEAK = " (leaked enquiries counted as orders push all of these up)"


def bias_note(rows: list[dict[str, Any]], gr: Growth, data: str = "clean") -> str:
    """Short plain-English note; the first sentence carries the finding on its own."""
    by_c = {r["country"]: r for r in rows if r["product"] is None}
    names = bt.COUNTRY_NAMES
    fast = fast_growing(gr)
    others = [c for c in COUNTRIES if c not in fast]
    ex = {c: bias_of(by_c[c], "excel_6m") for c in COUNTRIES}
    ours = {c: bias_of(by_c[c], "combination") for c in COUNTRIES}
    leak = LEAK if data == "dirty" else ""
    if not fast:
        grs = [gr[(c, None)] or 0.0 for c in COUNTRIES]
        return (
            f"No market's orders grew {MIN_FAST_GROWTH:.0f}% or more last year "
            f"({min(grs):+.0f}% to {max(grs):+.0f}%), so this market cannot show whether the "
            f"Excel average lags growth. Its country plans ran {_range_words(list(ex.values()))}"
            f"{leak}; ours {_range_words(list(ours.values()))}."
        )
    who = " and ".join(names[c] for c in fast)
    grew = " and ".join(f"{gr[(c, None)]:.0f}%" for c in fast)
    # a growing market that is not "fast" (below the region) is named, never hidden in a range
    growing = [c for c in others if (gr[(c, None)] or 0.0) >= MIN_FAST_GROWTH]
    named = "".join(
        f", {names[c]} (orders {gr[(c, None)]:+.0f}%) {plan_words(ex[c])}" for c in growing
    )
    rest = [c for c in others if c not in growing]
    elsewhere = f"; elsewhere {_range_words([ex[c] for c in rest])}" if rest else ""
    s1 = (
        f"In {who}, whose orders grew {grew} last year, the Excel 6-month average planned "
        f"{_list_words([ex[c] for c in fast])}{named}{elsewhere}{leak}."
    )
    worse = [c for c in fast if ours[c] < ex[c] - 1.0]
    better = [c for c in fast if ours[c] > ex[c] + 1.0]
    ours_txt = _list_words([ours[c] for c in fast])
    if worse and not better:
        s2 = f"Ours planned even lower ({ours_txt})"
    elif better and not worse:
        s2 = f"Ours lagged less ({ours_txt})"
    else:
        s2 = f"Ours planned {ours_txt}"
    return f"{s1} {s2}; {CAVEAT}."


# -------------------------------------------------------------------------------- run
def update_run(derived_dir: Path, scenario: str, data: str, refit: bool) -> dict[str, Any]:
    run = bt.load_backtest(derived_dir, scenario, data)  # type: ignore[arg-type]
    data_dir = bt.scenario_dir(scenario)
    fpath = frame_path(derived_dir, scenario, data)
    if refit:
        write_frame(country_cv(data_dir, data), fpath)  # type: ignore[arg-type]
    cv = read_frame(fpath)  # always score the committed frame, so tests can recompute it
    check_against_run(cv, run)
    gr = growth(data_dir)
    rows = bias_rows(cv, gr)
    run["bias_by_country"] = rows
    run["bias_note"] = bias_note(rows, gr, data)
    bt.write_backtest(run, derived_dir)
    return run


def main(refit: bool = True, derived_dir: Path = bt.DERIVED) -> None:
    os.environ.setdefault("NIXTLA_ID_AS_COL", "1")
    for s in bt.SCENARIOS:
        bt.ensure_scenario(s)
        for d in bt.DATAS:
            run = update_run(derived_dir, s, d, refit)
            print(f"{s}/{d}: {run['bias_note']}")


if __name__ == "__main__":
    main(refit="--from-frames" not in sys.argv[1:])
