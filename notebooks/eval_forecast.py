# %% [markdown]
# # Forecast backtest evaluation (PRD M9, D-008, D-017)
#
# Run: `uv run python notebooks/eval_forecast.py` (offline, reads the precomputed backtest in
# data/fixtures/derived/forecast/; regenerate that with `uv run python -m ds.forecasting.backtest`,
# about 10 minutes). Writes only between `<!-- forecast:start -->` and `<!-- forecast:end -->`.
#
# The design (origins, horizon, metrics, baseline, methods) is fixed in ds/forecasting/backtest.py
# and D-008, and was written down before the first run. Nothing was tuned on the test origins.

# %%
from __future__ import annotations

import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from ds.forecasting import backtest as bt  # noqa: E402

RESULTS = ROOT / "docs" / "results.md"
START, END = "<!-- forecast:start -->", "<!-- forecast:end -->"
SC_LABEL = {
    "seasonal_trend": "Seasonal + growth (demo)",
    "flat_noisy": "Flat and noisy",
    "intermittent": "Sparse ordering",
}
SHORT = {
    "excel_6m": "Excel 6-month",
    "excel_12m": "Excel 12-month",
    "combination": "Ours",
    "tsb": "TSB",
}
PRODUCT = {"A": "A (test kits)", "B": "B (equipment)", "C": "C (services)"}


def scores(series: dict) -> dict[str, dict]:
    return {s["method"]: s for s in series["scores"]}


def fmt(s: dict) -> str:
    return f"{s['wape_pct']:.1f}% ({s['bias_pct']:+.1f}%)"


def wins(run: dict, against: str) -> tuple[int, int]:
    cp = [s for s in run["series"] if s["level"] == "country_product"]
    n = sum(1 for s in cp if scores(s)["combination"]["wape_pct"] < scores(s)[against]["wape_pct"])
    return n, len(cp)


def n_customer_series(run: dict) -> int:
    m = re.search(r"the (\d+) intermittent", run["setup"])
    return int(m.group(1)) if m else 0


def leakage(scenario: str) -> dict[str, tuple[float, float]]:
    """Units in the last 12 months: confirmed POs vs the spreadsheet view, per product."""
    d = bt.scenario_dir(scenario)
    out = {}
    clean, dirty = bt._demand(d, "clean"), bt._demand(d, "dirty")
    last = clean["month"].max()
    start = last - pd.DateOffset(months=12)
    clean, dirty = clean[clean["month"] > start], dirty[dirty["month"] > start]
    for p in ("A", "B", "C"):
        out[p] = (
            float(clean.loc[clean["family"] == p, "qty"].sum()),
            float(dirty.loc[dirty["family"] == p, "qty"].sum()),
        )
    return out


# %%
def section() -> str:
    runs = {(s, d): bt.load_backtest(bt.DERIVED, s, d) for s in bt.SCENARIOS for d in bt.DATAS}
    L: list[str] = []
    L.append("## Forecast backtest (PRD M9)")
    L.append("")
    L.append(
        "**What was measured.** Monthly units of confirmed purchase orders for each country x "
        "product (5 x 3 = 15 series, 36 months, Oct 2023 - Sep 2026), in three synthetic "
        "scenarios (seed 42). Rolling origin over the last 12 months: from each of 10 "
        "month-ends, one month apart, every method forecasts the next 3 months using only data "
        "up to that month (`statsforecast` `cross_validation(h=3, n_windows=10, step_size=1)`). "
        "*Excel average* = the mean of the last 6 (or 12) months, today's spreadsheet habit. "
        "*Ours* = the equal-weight average of three standard models (AutoETS, AutoTheta and "
        "seasonal naive, all with a 12-month season; Petropoulos & Svetunkov 2020). For "
        "customers who order only now and then we add TSB (Teunter, Syntetos & Babai 2011)."
    )
    L.append("")
    L.append(
        "**Fixed before the first run, never tuned.** Origins, horizon, metrics, baselines, "
        "model settings (all `Auto*` defaults, TSB smoothing 0.1 / 0.1), the zero floor on "
        "forecasts and the pooled scoring were written into `ds/forecasting/backtest.py` before "
        "any result was seen, and were not changed afterwards. *WAPE* = total absolute error / "
        "total units actually ordered, pooled over every series, origin and month ahead. "
        "*Bias* = total (forecast - actual) / total actual: + means the plan ran high. Each "
        "cell shows WAPE (bias). Lower WAPE is better."
    )
    L.append("")

    # ---------------------------------------------------------------- headline
    L.append("### Headline: 15 country x product series")
    L.append("")
    L.append(
        "| Scenario | Data | Excel average, 6 months | Excel average, 12 months | Ours | "
        "Ours beats Excel 6-month on | Ours beats Excel 12-month on |"
    )
    L.append("|---|---|---|---|---|---|---|")
    for s in bt.SCENARIOS:
        for d in bt.DATAS:
            r = runs[(s, d)]
            ov = {x["method"]: x for x in r["overall"]}
            w6, n = wins(r, "excel_6m")
            w12, _ = wins(r, "excel_12m")
            L.append(
                f"| {SC_LABEL[s]} | {d} | {fmt(ov['excel_6m'])} | {fmt(ov['excel_12m'])} | "
                f"{fmt(ov['combination'])} | {w6} of {n} series | {w12} of {n} series |"
            )
    L.append("")
    L.append(
        "*clean* = confirmed POs only. *dirty* = today's spreadsheet view, where some enquiries, "
        "purchase requests and master-data requests are counted as orders (data-spec 7.1); the "
        "models learn from it but are scored against what customers really ordered. Pooled "
        "units are dominated by Product A (test kits sell in far larger numbers than equipment), "
        "so the products are also shown separately below."
    )
    L.append("")
    st = {x["method"]: x for x in runs[("seasonal_trend", "clean")]["overall"]}
    fn = {x["method"]: x for x in runs[("flat_noisy", "clean")]["overall"]}

    def ov(sc: str) -> dict[str, dict]:
        return {x["method"]: x for x in runs[(sc, "clean")]["overall"]}

    gaps12 = {
        sc: ov(sc)["excel_12m"]["wape_pct"] - ov(sc)["combination"]["wape_pct"]
        for sc in bt.SCENARIOS
    }
    excel_wins = [
        bt.SCENARIO_NAMES[sc]
        for sc in bt.SCENARIOS
        if min(ov(sc)["excel_6m"]["wape_pct"], ov(sc)["excel_12m"]["wape_pct"])
        <= ov(sc)["combination"]["wape_pct"]
    ]
    L.append(
        f"> **For judges:** at country level the honest answer is *no real difference*. On "
        f"clean data our method never beats a 12-month Excel average by more than "
        f"{max(gaps12.values()):.1f} points in any scenario."
        + (
            f" In {' and '.join(excel_wins)}, a plain Excel average does as well as ours or better."
            if excel_wins
            else ""
        )
        + " Demo scenario: "
        f"{st['excel_6m']['wape_pct']:.1f}% error (Excel, 6 months) vs "
        f"{st['combination']['wape_pct']:.1f}% (ours); flat, noisy market: "
        f"{fn['excel_6m']['wape_pct']:.1f}% vs {fn['combination']['wape_pct']:.1f}% (Excel 12 "
        f"months: {fn['excel_12m']['wape_pct']:.1f}%). Ours does better on service contracts "
        f"(Product C) for the region as a whole, because they renew on a yearly cycle that a "
        f"moving average cannot see; country by country that result is mixed (see the detail "
        f"table)."
    )
    L.append("")

    # ---------------------------------------------------------------- product level
    L.append("### Region total by product (D-017: Product B judged at product level)")
    L.append("")
    L.append("| Scenario | Product | Excel 6-month | Excel 12-month | Ours | Best |")
    L.append("|---|---|---|---|---|---|")
    for s in bt.SCENARIOS:
        r = runs[(s, "clean")]
        for ser in (x for x in r["series"] if x["level"] == "product"):
            sc = scores(ser)
            L.append(
                f"| {SC_LABEL[s]} | {PRODUCT[ser['product']]} | {fmt(sc['excel_6m'])} | "
                f"{fmt(sc['excel_12m'])} | {fmt(sc['combination'])} | "
                f"{SHORT[ser['winner']]} |"
            )
    L.append("")
    b = scores(
        next(
            x
            for x in runs[("seasonal_trend", "clean")]["series"]
            if x["level"] == "product" and x["product"] == "B"
        )
    )
    L.append(
        f"> **For judges:** equipment (Product B) orders are rare and lumpy. Even added up over "
        f"the whole region, every method misses by {min(v['wape_pct'] for v in b.values()):.0f}"
        f"-{max(v['wape_pct'] for v in b.values()):.0f}% of volume in the demo scenario, so "
        f"equipment should be planned from the enquiry and purchase-request pipeline, not from "
        f"any average of past orders. That is one of the recommended actions in the regional "
        f"view."
    )
    L.append("")

    # ---------------------------------------------------------------- customer level
    L.append("### Customers who order now and then (customer x product, intermittent only)")
    L.append("")
    L.append(
        "| Scenario | Data | Series | Product | Excel 6-month | Excel 12-month | Ours | TSB | "
        "Best |"
    )
    L.append("|---|---|---|---|---|---|---|---|---|")
    for s in bt.SCENARIOS:
        for d in bt.DATAS:
            r = runs[(s, d)]
            n = n_customer_series(r)
            for ser in (x for x in r["series"] if x["level"] == "customer_product"):
                sc = scores(ser)
                L.append(
                    f"| {SC_LABEL[s]} | {d} | {n} | {PRODUCT[ser['product']]} | "
                    f"{fmt(sc['excel_6m'])} | {fmt(sc['excel_12m'])} | {fmt(sc['combination'])} | "
                    f"{fmt(sc['tsb'])} | {SHORT[ser['winner']]} |"
                )
    L.append("")
    L.append(
        "A customer x product series is *intermittent* when, before the first origin, the "
        "customer ordered that product in fewer than 1 month out of 1.32 on average (ADI > 1.32, "
        "Syntetos & Boylan 2005) and at least twice. Clean = our merged customers; dirty = raw "
        "SAP records, so a customer who moved to a new record keeps being forecast on the old "
        "one. Errors near or above 100% are normal at this level: a single missed order is the "
        "whole month's volume."
    )
    L.append("")
    L.append(
        "> **For judges:** forecasting single customers who order occasionally is hard for "
        "every method; read this table for which method fails least, not for accuracy."
    )
    L.append("")

    # ---------------------------------------------------------------- clean vs dirty
    L.append("### Clean vs dirty: what changes the totals")
    L.append("")
    L.append(
        "| Scenario | Product | Units ordered (confirmed POs, last 12 months) | Units in the "
        "spreadsheet view | Overstated by |"
    )
    L.append("|---|---|---|---|---|")
    a_leaks = []
    for s in bt.SCENARIOS:
        lk = leakage(s)
        a_leaks.append(100 * (lk["A"][1] / lk["A"][0] - 1))
        for p, (c, dd) in lk.items():
            L.append(
                f"| {SC_LABEL[s]} | {PRODUCT[p]} | {c:,.0f} | {dd:,.0f} | "
                f"{100 * (dd / c - 1) if c else 0:+.1f}% |"
            )
    L.append("")
    L.append(
        "Merging duplicate customers leaves every country x product total unchanged: it "
        "regroups the same orders under fewer customers (asserted in "
        "`tests/test_forecast.py`). Leaked enquiries and requests do change the totals, and "
        "almost all of the damage lands on equipment (Product B), where a few leaked enquiries "
        "outnumber the real orders."
    )
    L.append("")
    L.append("Forecast error at region level, clean vs dirty data, WAPE (bias):")
    L.append("")
    L.append(
        "| Scenario | Product | Excel 6-month, clean | Excel 6-month, dirty | Ours, clean | "
        "Ours, dirty |"
    )
    L.append("|---|---|---|---|---|---|")
    prod: dict[tuple[str, str, str], dict] = {}
    for s in bt.SCENARIOS:
        for d in bt.DATAS:
            for ser in runs[(s, d)]["series"]:
                if ser["level"] == "product":
                    prod[(s, d, ser["product"])] = scores(ser)
        for p in ("A", "B", "C"):
            c, dd = prod[(s, "clean", p)], prod[(s, "dirty", p)]
            L.append(
                f"| {SC_LABEL[s]} | {PRODUCT[p]} | {fmt(c['excel_6m'])} | {fmt(dd['excel_6m'])} "
                f"| {fmt(c['combination'])} | {fmt(dd['combination'])} |"
            )
    L.append("")
    L.append(
        "The pooled 15-series error in the headline table barely moves between clean and dirty "
        f"(it is dominated by test-kit units, where leakage is at most {max(a_leaks):.1f}%), so it "
        "is the wrong place to look for the damage."
    )
    L.append("")
    lk_st = leakage("seasonal_trend")
    b_up = 100 * (lk_st["B"][1] / lk_st["B"][0] - 1)
    a_up = 100 * (lk_st["A"][1] / lk_st["A"][0] - 1)
    bst_c, bst_d = prod[("seasonal_trend", "clean", "B")], prod[("seasonal_trend", "dirty", "B")]
    bfn_c, bfn_d = prod[("flat_noisy", "clean", "B")], prod[("flat_noisy", "dirty", "B")]
    L.append(
        f"> **For judges:** cleaning the customer list does not change the country forecast, "
        f"because the totals are the same. Keeping enquiries out of the order numbers matters "
        f"most for equipment: the spreadsheet view counts {b_up:.0f}% more Product B units than "
        f"customers really ordered (test kits {a_up:+.1f}%), and the Excel plan's error on "
        f"regional Product B goes from {bst_c['excel_6m']['wape_pct']:.1f}% on clean data to "
        f"{bst_d['excel_6m']['wape_pct']:.0f}% on the spreadsheet view in the demo scenario "
        f"({bfn_c['excel_6m']['wape_pct']:.0f}% to {bfn_d['excel_6m']['wape_pct']:.0f}% in the "
        f"flat, noisy market)."
    )
    L.append("")

    # ---------------------------------------------------------------- per series detail
    L.append("### Detail: demo scenario, clean data, every country x product")
    L.append("")
    L.append("| Country | Product | Excel 6-month | Excel 12-month | Ours | Best |")
    L.append("|---|---|---|---|---|---|")
    for ser in (
        x for x in runs[("seasonal_trend", "clean")]["series"] if x["level"] == "country_product"
    ):
        sc = scores(ser)
        L.append(
            f"| {bt.COUNTRY_NAMES[ser['country']]} | {PRODUCT[ser['product']]} | "
            f"{fmt(sc['excel_6m'])} | {fmt(sc['excel_12m'])} | {fmt(sc['combination'])} | "
            f"{SHORT[ser['winner']]} |"
        )
    L.append("")
    a_rows = [
        x["wape_pct"]
        for ser in runs[("seasonal_trend", "clean")]["series"]
        if ser["level"] == "country_product" and ser["product"] == "A"
        for x in ser["scores"]
    ]
    c_rows = [
        ser
        for ser in runs[("seasonal_trend", "clean")]["series"]
        if ser["level"] == "country_product" and ser["product"] == "C"
    ]
    c_ours = sum(1 for ser in c_rows if ser["winner"] == "combination")
    c_other = [
        f"{bt.COUNTRY_NAMES[ser['country']]} ({SHORT[ser['winner']]} wins)"
        for ser in c_rows
        if ser["winner"] != "combination"
    ]
    L.append(
        f"> **For judges:** test kits (A) are forecast within {min(a_rows):.0f}-"
        f"{max(a_rows):.0f}% by every method, and equipment (B) per country is too lumpy for any "
        f"method. For service contracts (C) ours is best in {c_ours} of {len(c_rows)} countries"
        + (f"; not in {', '.join(c_other)}." if c_other else ".")
    )
    L.append("")
    L.append("Honest notes generated with each run (shown in the app):")
    L.append("")
    for s in bt.SCENARIOS:
        for d in bt.DATAS:
            L.append(f"- *{SC_LABEL[s]}, {d}:* {runs[(s, d)]['honest_note']}")
    return "\n".join(L)


def write_section(text: str) -> None:
    cur = RESULTS.read_text(encoding="utf-8")
    if START not in cur or END not in cur:
        raise SystemExit(f"{RESULTS} has no {START} / {END} markers")
    pre, rest = cur.split(START, 1)
    post = rest.split(END, 1)[1]
    with open(RESULTS, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(pre + f"{START}\n{text}\n{END}" + post)


if __name__ == "__main__":
    text = section()
    write_section(text)
    print(text)
