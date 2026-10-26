# %% [markdown]
# # Equipment forecast from the request pipeline (session 13)
#
# Run: `uv run python notebooks/eval_pipeline.py` (offline, about 20 seconds). It regenerates
# data/fixtures/derived/forecast/pipeline/<scenario>_clean_pipeline{.json,_cv.csv} and
# <scenario>_clean_plan.json (deterministic), then writes only between
# `<!-- pipeline:start -->` and `<!-- pipeline:end -->` in docs/results.md (the markers are
# added once, right after the M9 forecast section; nothing else in the file is touched).
#
# The method and its constants were fixed in ds/forecasting/pipeline.py (commit b4b7e1e)
# before the first run. Excel 6 / Excel 12 / ours are read from the stored M9 outputs.

# %%
from __future__ import annotations

import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ds.forecasting import backtest as bt  # noqa: E402
from ds.forecasting import pipeline as pl  # noqa: E402
from ds.forecasting import plan as fp  # noqa: E402

RESULTS = ROOT / "docs" / "results.md"
START, END = "<!-- pipeline:start -->", "<!-- pipeline:end -->"
AFTER = "<!-- forecast:end -->"
SC_LABEL = {
    "seasonal_trend": "Seasonal + growth (demo)",
    "flat_noisy": "Flat and noisy",
    "intermittent": "Sparse ordering",
}
COLS = ["excel_6m", "excel_12m", "combination", "pipeline_pr", "pipeline_pr_enq"]
HEAD = (
    "| Scenario | Excel 6-month | Excel 12-month | Ours | Pipeline (requests) "
    "| Pipeline (requests + enquiries) | Best |"
)
SHORT = {
    "excel_6m": "Excel 6-month",
    "excel_12m": "Excel 12-month",
    "combination": "Ours",
    "pipeline_pr": "Pipeline (requests)",
    "pipeline_pr_enq": "Pipeline (requests + enquiries)",
}


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def fmt(s: dict) -> str:
    return f"{s['wape_pct']:.1f}% ({s['bias_pct']:+.1f}%)"


def by(scores: list[dict]) -> dict[str, dict]:
    return {s["method"]: s for s in scores}


def best(scores: list[dict]) -> str:
    b = min(scores, key=lambda s: (s["wape_pct"], s["method"]))
    return SHORT[b["method"]]


def table(res: dict, level: str) -> list[str]:
    L = [HEAD, "|---|---|---|---|---|---|---|"]
    for s in bt.SCENARIOS:
        sc = res[s][level]
        b = by(sc)
        L.append(f"| {SC_LABEL[s]} | " + " | ".join(fmt(b[m]) for m in COLS) + f" | {best(sc)} |")
    return L


def verdict(res: dict) -> str:
    parts = []
    for s in bt.SCENARIOS:
        b = by(res[s]["region"])
        pr = b["pipeline_pr"]["wape_pct"]
        m9 = {m: b[m]["wape_pct"] for m in pl.M9_METHODS}
        top = min(m9, key=lambda m: (m9[m], m))
        d = m9[top] - pr
        if abs(d) < pl.TIE_POINTS:
            w = f"ties with {SHORT[top]} ({pr:.1f}% vs {m9[top]:.1f}%)"
        elif d > 0:
            w = f"beats the best average-based method, {SHORT[top]} ({pr:.1f}% vs {m9[top]:.1f}%)"
        else:
            w = f"loses to {SHORT[top]} ({pr:.1f}% vs {m9[top]:.1f}%)"
        parts.append(f"{SC_LABEL[s].lower()}: {w}")
    return "; ".join(parts)


def plan_table(plan: dict) -> list[str]:
    L = [
        "| Country | Product | Excel 6-month | Ours | Pipeline (requests) "
        "| Pipeline (requests + enquiries) | Growth adjustment (separate) |",
        "|---|---|---|---|---|---|---|",
    ]

    def u(x: float | None) -> str:
        return "-" if x is None else f"{x:,.1f}"

    for r in plan["rows"]:
        adj = (
            "-"
            if r["growth_adjustment"] is None
            else f"+{r['growth_adjustment']:,.1f} "
            f"(Excel planned {r['growth_adjustment_pct']:.0f}% low)"
        )
        L.append(
            f"| {r['country_name']} | {r['product']} | {u(r['excel_6m'])} | {u(r['combination'])} "
            f"| {u(r['pipeline_pr'])} | {u(r['pipeline_pr_enq'])} | {adj} |"
        )
    return L


def section(res: dict, plans: dict) -> str:
    st = by(res["seasonal_trend"]["region"])
    fb_used = {s: sum(res[x]["fallbacks"][s]["used"] for x in bt.SCENARIOS) for s in pl.SIGNALS}
    fb_of = sum(res[x]["fallbacks"]["purchase_request"]["of"] for x in bt.SCENARIOS)
    reg = {s: by(res[s]["region"]) for s in bt.SCENARIOS}
    enq_better = sum(
        1
        for s in bt.SCENARIOS
        if reg[s]["pipeline_pr_enq"]["wape_pct"] < reg[s]["pipeline_pr"]["wape_pct"]
    )
    pr_wins = sum(
        1
        for s in bt.SCENARIOS
        if min(reg[s][m]["wape_pct"] for m in pl.M9_METHODS) - reg[s]["pipeline_pr"]["wape_pct"]
        >= pl.TIE_POINTS
    )
    L = [
        "## Equipment forecast from the request pipeline (session 13)",
        "",
        "**The question.** The brief asks how data science could improve on the 6-to-12-month "
        "Excel average. For equipment (Product B), which customers order rarely and in lumps, the "
        "idea is to plan from what customers are asking for now, instead of from past orders.",
        "",
        "**The method, fixed before the first run** (`ds/forecasting/pipeline.py`, commit "
        "`b4b7e1e`, not changed afterwards):",
        "",
        "1. For each country, the equipment *pipeline* in a month is the average of Product B "
        "units in purchase requests that month and the 2 months before (a request usually turns "
        f"into an order within 2 months; `LMAX = {pl.LMAX}`).",
        "2. *Conversion rate* = units ordered over the last "
        f"{pl.CONVERSION_WINDOW} months / pipeline units over the same months, from monthly totals "
        "only, using only data up to the forecast date. Plan = conversion rate x pipeline. "
        "Request months not yet seen are filled with the average of the last "
        f"{pl.REQUEST_FILL_MONTHS} months of requests. Plans are floored at zero.",
        "3. Region = the sum of the 5 country plans. Variant 2 (declared in advance) averages "
        "this plan with the same plan built from enquiries.",
        "",
        "- *No request-to-order link is used.* Real SAP data does not link a request to the "
        "order it became, so the `converted_doc_num` column is never read (a test checks this). "
        "Orders that arrive with no earlier request are not modelled separately: the conversion "
        "rate is simply units ordered per unit in the pipeline.",
        "- *What is forecast:* confirmed customer POs only (CLAUDE.md rule 9). Requests and "
        "enquiries are only predictors; master-data requests and the spreadsheet view are never "
        "read.",
        f"- *Fallback:* if a country had no pipeline at all in the {pl.CONVERSION_WINDOW}-month "
        f"window, that plan would fall back to the Excel 6-month average. It was used "
        f"{fb_used['purchase_request']} times for requests and {fb_used['enquiry']} times for "
        f"enquiries, out of {fb_of} country x forecast-date plans (3 scenarios x 5 countries x "
        f"{pl.N_WINDOWS} dates).",
        "- *Same test as M9:* the same 10 forecast dates, 3 months ahead, the same WAPE and bias "
        "pooled over every country, date and month ahead. Clean data, all 3 scenarios, seed 42. "
        "Excel 6-month, Excel 12-month and ours are read from the stored M9 results, not refitted.",
        "",
        "> **Read this first: the test data favours this method.** The generator creates "
        "requests from later orders (data-spec §7 and §12.1, `ds/generator/demand.py` "
        "`build_enquiries`): about 45% of Product B orders have a purchase request 0-2 months "
        "before them, with nearly the same quantity. So this test favours a pipeline method. A "
        "pilot must measure the conversion rate on real data before anyone plans from it.",
        "",
        "### Region total, Product B",
        "",
        "Each cell is WAPE (bias): error as % of the units customers really ordered (lower is "
        "better), and whether the plan ran high (+) or low (-).",
        "",
        *table(res, "region"),
        "",
        "*Excel 6-month, Excel 12-month and Ours* were fitted by M9 on the region total "
        "(top-down). *The pipeline* is built bottom-up as the sum of the 5 country plans. Same "
        "forecast dates, months and actuals.",
        "",
        "### Country level, Product B (5 countries pooled)",
        "",
        *table(res, "countries_pooled"),
        "",
        "Every method is scored on the same 5 country series (from the stored M9 country frame) "
        "and the errors are added up before dividing, so a country's misses do not cancel "
        "another's.",
        "",
        "### Detail: demo scenario, each country, Product B",
        "",
        "| Country | Excel 6-month | Excel 12-month | Ours | Pipeline (requests) "
        "| Pipeline (requests + enquiries) | Best |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in res["seasonal_trend"]["per_country"]:
        b = by(r["scores"])
        L.append(
            f"| {bt.COUNTRY_NAMES[r['country']]} | "
            + " | ".join(fmt(b[m]) for m in COLS)
            + f" | {best(r['scores'])} |"
        )
    L += [
        "",
        "One country's equipment orders are a handful of units a month, so every method misses "
        "by about the whole volume there; judge the method at region level (D-017).",
        "",
        f"**Verdict (honest).** Region, Product B, primary variant (requests): {verdict(res)}. "
        f"Adding enquiries (variant 2) lowers the region error in {enq_better} of "
        f"{len(bt.SCENARIOS)} scenarios. "
        + (
            "Even on test data that builds requests out of later orders, the pipeline plan "
            "never beats the best average-based method by a point or more, so we do not claim "
            "it beats Excel. What it offers is a plan that moves when the pipeline moves, which "
            "a pilot should test on real conversion rates."
            if not pr_wins
            else f"It beats every average-based method in {pr_wins} of {len(bt.SCENARIOS)} "
            "scenarios, on test data that favours it; a pilot must confirm this on real data."
        ),
        "",
        f"> **For judges:** for equipment across the region, planning from purchase requests was "
        f"off by {st['pipeline_pr']['wape_pct']:.1f}% of units in the demo market, against "
        f"{st['excel_6m']['wape_pct']:.1f}% for the 6-month Excel average, "
        f"{st['excel_12m']['wape_pct']:.1f}% for the 12-month one and "
        f"{st['combination']['wape_pct']:.1f}% for ours. "
        + _cap(pl.verdict_words(res["seasonal_trend"]))
        + ", on data that favours it. Worth a pilot, not a claim.",
        "",
        "### Next 3 months plan (Oct - Dec 2026)",
        "",
        "Units for the 3 months together, from the last full month (Sep 2026), per country x "
        "product. *Excel 6-month* = 3 x the average of the last 6 months. *Ours* = the M9 "
        "combination fitted on all 36 months. *Pipeline* = the plan above, equipment only. "
        "*Growth adjustment* = shown only for countries that meet the D-020 fast-growing "
        "definition in that scenario: the units that close the gap the backtest measured, where "
        "the Excel 6-month average planned that country too low (all products pooled). It is a "
        "separate number; no other column includes it.",
        "",
    ]
    for s in bt.SCENARIOS:
        p = plans[s]
        fast = ", ".join(bt.COUNTRY_NAMES[c] for c in p["fast_growing"]) or "none"
        L += [f"**{SC_LABEL[s]}** (fast-growing: {fast})", "", *plan_table(p), ""]
    L.append(
        "_Generated by `uv run python notebooks/eval_pipeline.py`. Synthetic data, seed 42; every "
        "name, ID and amount is invented._"
    )
    return "\n".join(L)


def write_section(text: str) -> None:
    cur = RESULTS.read_text(encoding="utf-8")
    if START not in cur:
        if AFTER not in cur:
            raise SystemExit(f"{RESULTS} has no {AFTER} marker")
        cur = cur.replace(AFTER, f"{AFTER}\n\n{START}\n{END}", 1)
    pre, rest = cur.split(START, 1)
    post = rest.split(END, 1)[1]
    with open(RESULTS, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(pre + f"{START}\n{text}\n{END}" + post)


if __name__ == "__main__":
    pl.main()
    fp.main()
    res = {s: pl.load_pipeline(bt.DERIVED, s) for s in bt.SCENARIOS}
    plans = {s: pl.json.loads(fp.plan_path(bt.DERIVED, s).read_text("utf-8")) for s in bt.SCENARIOS}
    text = section(res, plans)
    write_section(text)
    print(text)
