# %% [markdown]
# # Modelled cycle time, old vs new process (PRD M10, D-018 item 4)
#
# Run: `uv run python notebooks/eval_ops.py` (offline; `make eval`).
# Writes only between `<!-- ops:start -->` and `<!-- ops:end -->` in docs/results.md.
# The model is `ds/analytics/cycle_time.py`; every assumption is listed with its source.

# %%
from __future__ import annotations

import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ds.analytics.cycle_time import WAIT_CAP_BD, ops_details, ops_impact  # noqa: E402

FIX = ROOT / "data" / "fixtures" / "seasonal_trend"
RESULTS = ROOT / "docs" / "results.md"
START, END = "<!-- ops:start -->", "<!-- ops:end -->"
SOURCE = {
    "brief": "the case brief",
    "generated_history": "our synthetic history",
    "our_design": "our design",
    "assumption": "assumption",
}
DOMAIN = {"customer": "Customer", "vendor": "Vendor", "item": "Item", "cost_center": "Cost center"}


# %%
def section() -> str:
    o = ops_impact(FIX)
    d = ops_details(FIX)
    old, new = o["cycle_time"]
    L: list[str] = []
    a = L.append
    a("## Request cycle time, today vs new process (PRD M10)")
    a("")
    cap = o["caption"].removeprefix("Modelled, not measured: ")
    a("> **Modelled, not measured.** " + cap[:1].upper() + cap[1:])
    a("")
    a(
        f"**What was modelled.** All {d['n']} past master-data requests in "
        f"`mdm_requests_history.csv` ({d['months'][0]} to {d['months'][1]}, scenario "
        "`seasonal_trend`, seed 42) are taken as recorded (old) and then replayed through the "
        "new rules (new): checks at entry stop the missing fields the form knows about, all "
        "approvers of a request work in parallel, a reminder goes out after 1 business day and "
        "the backup approver takes over after 2, and MDM publishes from a queue instead of "
        "re-typing. Cycle time runs from submit to live in SAP, in business days."
    )
    a("")
    a(
        "| Measure | Today (one approver after another, by email) "
        "| New (parallel, checked at entry) |"
    )
    a("|---|---|---|")
    a(f"| Median cycle time (business days) | {old['median_bd']:.1f} | {new['median_bd']:.1f} |")
    a(f"| 90th percentile (business days) | {old['p90_bd']:.1f} | {new['p90_bd']:.1f} |")
    a(
        f"| First time right (not sent back for missing fields) | "
        f"{o['first_time_right_before_pct']:.1f}% | {o['first_time_right_after_pct']:.1f}% |"
    )
    a(f"| Amy's IVD item (the brief's example) | {o['amy_before_bd']:.0f} days | "
      f"about {o['amy_after_bd']:.1f} business days |")  # fmt: skip
    a("")
    a(
        "*Median* = half of the requests are faster than this. *90th percentile* = 9 in 10 "
        "requests are faster than this, so it shows the slow tail."
    )
    a("")
    a("| Request type | Requests | Median today | Median new |")
    a("|---|---|---|---|")
    for k, (n, m_old, m_new) in d["by_domain"].items():
        a(f"| {DOMAIN[k]} | {n} | {m_old:.1f} | {m_new:.1f} |")
    a("")
    a(
        "**Read this honestly.** The new median is mostly set by our own service levels, not "
        f"by data: the recorded approver waits (median about 3 business days) are longer "
        f"than the escalation point, so most approval stages end at the {WAIT_CAP_BD:.1f}-day "
        "cap, and the publish step at its 1-day cap. That is why every request type lands on "
        "the same median. Without the escalation cap, parallel approval alone (recorded "
        "waits including bounce loops, recorded keying, no checks at entry) gives a median of "
        f"about {d['parallel_only_median']:.1f} business days (with a 4-day cap on each "
        f"approver: {d['parallel_cap4_median']:.1f}). "
        f"{d['still_bounce']} requests ({100 * d['still_bounce'] / d['n']:.0f}%) "
        "still bounce in the model, because their missing field (credit or payment terms, "
        "risk class, supplier, sales unit, cost-center dimension or owner) is not one the form "
        "checks today; they make up the slow tail. "
        f"{d['slower']} of {d['n']} requests comes out slower in the model than recorded "
        "(it still bounces in the model, and its recorded fix was quicker than the typical "
        "one we assume)."
    )
    a("")
    a(f"**Amy's case.** {o['amy_explanation']}")
    a("")
    a("**Assumptions, each with its source.**")
    a("")
    a("| Assumption | Value | Source |")
    a("|---|---|---|")
    for x in o["assumptions"]:
        a(f"| {x['name']} | {x['value']} | {SOURCE[x['source']]} |")
    a("")
    a(
        f"> **For judges:** in our model a typical request goes from {old['median_bd']:.1f} "
        f"business days to {new['median_bd']:.1f}, and Amy's 18-day item to about "
        f"{o['amy_after_bd']:.0f}, because approvers work at the same time, a backup steps in "
        "after 2 days, and incomplete requests are stopped before anyone approves them. This "
        "is a model of the new rules on past requests, not a measured pilot."
    )
    a("")
    a("_Generated by `uv run python notebooks/eval_ops.py` from `ds/analytics/cycle_time.py`. "
      "Synthetic history._")  # fmt: skip
    return "\n".join(L)


def write_results(text: str) -> None:
    cur = RESULTS.read_text(encoding="utf-8")
    if START not in cur or END not in cur:
        raise SystemExit(f"markers {START} / {END} missing in {RESULTS}")
    pre, rest = cur.split(START, 1)
    post = rest.split(END, 1)[1]
    RESULTS.write_text(pre + f"{START}\n{text}\n{END}" + post, encoding="utf-8", newline="\n")


# %%
if __name__ == "__main__":
    text = section()
    o = ops_impact(FIX)
    print(o["cycle_time"], o["amy_after_bd"], o["first_time_right_before_pct"],
          o["first_time_right_after_pct"])  # fmt: skip
    write_results(text)
    print(f"wrote {RESULTS.relative_to(ROOT)}")
