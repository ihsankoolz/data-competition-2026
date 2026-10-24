"""Regional business view (PRD M8, D-009). Pure functions over the fixture CSVs.

Contract (session 4): each function returns a plain dict shaped exactly like the Pydantic model
named in its docstring (`services/api/schemas.py`); the API validates it. Confirmed POs only feed
revenue (rule 9). "after" = our own dedup clusters (`ds.analytics.golden`), never ground truth.

Definitions (D-009), with the stated period = the last 12 full months in the data
(Oct 2025 - Sep 2026 for the fixtures):
- revenue = confirmed-PO lines (orders.csv) qty x unit_price_usd. Enquiries, purchase requests
  and MDM requests are counted in separate panels and never added to revenue.
- T3 = the last 3 months of the period (Jul - Sep 2026), P3 = the 3 months before (Apr - Jun).
- heatmap growth (headline, D-022 #3) = the 12-month period vs the 12 months before it.
- NRR = T3 revenue from customers active in P3 / P3 revenue.
- bridge: start (P3) + new + expansion - contraction - lost = end (T3).
- cross-sell penetration = % of customers active in the period buying >= 2 of A/B/C in it.
- lost-customer alert: a customer active in the period whose last PO is more than
  max(90 days, 2 x its median gap between order dates) before the period end.
- "customer" = a raw CardCode before merge, one of our dedup clusters after merge.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import pandas as pd

from ds.analytics.golden import golden_clusters

View = Literal["before", "after"]

COUNTRIES = ["SG", "MY", "ID", "VN", "TH"]
COUNTRY_NAMES = {
    "SG": "Singapore",
    "MY": "Malaysia",
    "ID": "Indonesia",
    "VN": "Vietnam",
    "TH": "Thailand",
}
PRODUCTS = ["A", "B", "C"]
PRODUCT_NAMES = {
    "A": "Product A (test kits)",
    "B": "Product B (equipment)",
    "C": "Product C (services)",
}
LOST_MIN_DAYS = 90


# --------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class _Frames:
    orders: pd.DataFrame  # one row per PO line, with family, month, value, golden
    enquiries: pd.DataFrame
    mdm: pd.DataFrame
    names: dict[str, str]  # CardCode -> CardName
    golden: dict[str, str]  # CardCode -> our cluster id
    golden_names: dict[str, str]  # cluster id -> display name
    months: list[pd.Timestamp]  # the 12 months of the stated period
    period_end: pd.Timestamp  # last day of the period
    key: str  # resolved data_dir, the cache key


def _month(s: pd.Series) -> pd.Series:
    return s.dt.to_period("M").dt.to_timestamp()


@lru_cache(maxsize=8)
def _load(data_dir_key: str) -> _Frames:
    d = Path(data_dir_key)
    items = pd.read_csv(d / "items.csv", dtype=str)
    family = dict(zip(items["ItemCode"], items["product_family"], strict=True))
    bp = pd.read_csv(d / "bp_records.csv", dtype=str, keep_default_na=False)
    names = dict(zip(bp["CardCode"], bp["CardName"], strict=True))
    golden = golden_clusters(d)

    orders = pd.read_csv(
        d / "orders.csv", dtype={"card_code": str, "item_code": str, "doc_num": str}
    )
    orders["doc_date"] = pd.to_datetime(orders["doc_date"])
    orders["month"] = _month(orders["doc_date"])
    orders["family"] = orders["item_code"].map(family)
    orders["value"] = orders["qty"] * orders["unit_price_usd"]
    orders["golden"] = orders["card_code"].map(golden).fillna(orders["card_code"])

    enq = pd.read_csv(d / "enquiries.csv", dtype={"card_code": str, "doc_num": str})
    enq["doc_date"] = pd.to_datetime(enq["doc_date"])
    enq["month"] = _month(enq["doc_date"])
    enq["family"] = enq["item_code"].map(family)
    enq["value"] = enq["qty"] * enq["unit_price_usd"]

    mdm = pd.read_csv(d / "mdm_requests_history.csv", dtype=str)
    mdm["month"] = pd.to_datetime(mdm["submitted_at"].str[:10]).dt.to_period("M").dt.to_timestamp()

    last = orders["month"].max()
    if orders.loc[orders["month"] == last, "doc_date"].max().day < 20:  # partial last month
        last = last - pd.DateOffset(months=1)
    months = [last - pd.DateOffset(months=k) for k in range(11, -1, -1)]
    period_end = last + pd.offsets.MonthEnd(0)

    # cluster display name: the name of its oldest record (lowest CardCode)
    golden_names: dict[str, str] = {}
    for code in sorted(golden):
        golden_names.setdefault(golden[code], names.get(code, code))
    return _Frames(orders, enq, mdm, names, golden, golden_names, months, period_end, data_dir_key)


def _frames(data_dir: Path) -> _Frames:
    return _load(str(Path(data_dir).resolve()))


def period_label(months: list[pd.Timestamp]) -> str:
    return f"{months[0]:%b %Y} - {months[-1]:%b %Y} (last 12 full months)"


# --------------------------------------------------------------------------------------------
def _key(view: View) -> str:
    return "card_code" if view == "before" else "golden"


def _windows(f: _Frames) -> tuple[list[pd.Timestamp], list[pd.Timestamp]]:
    return f.months[-3:], f.months[-6:-3]  # T3, P3


def _pct(num: float, den: float) -> float:
    return round(100.0 * num / den, 1) if den else 0.0


def _growth(t3: float, p3: float) -> float | None:
    return round(100.0 * (t3 - p3) / p3, 1) if p3 > 0 else None


def _lost(f: _Frames, orders: pd.DataFrame, key: str) -> pd.DataFrame:
    """Lost-customer alerts: one row per customer key (key, last_order, country, threshold)."""
    hist = orders[orders["doc_date"] <= f.period_end]
    active = set(hist.loc[hist["month"].isin(f.months), key])
    rows = []
    for k, g in hist[hist[key].isin(active)].groupby(key, sort=True):
        dates = pd.Series(sorted(g["doc_date"].unique()))
        gaps = dates.diff().dt.days.dropna()
        median_gap = float(gaps.median()) if len(gaps) else 0.0
        threshold = max(LOST_MIN_DAYS, 2.0 * median_gap)
        last = dates.iloc[-1]
        days = (f.period_end - last).days
        if days > threshold:
            rows.append(
                {
                    "key": k,
                    "last_order": last,
                    "country": g["country"].iloc[-1],
                    "days_since": days,
                    "threshold": threshold,
                    "value_12m": float(g.loc[g["month"].isin(f.months), "value"].sum()),
                }
            )
    return pd.DataFrame(
        rows, columns=["key", "last_order", "country", "days_since", "threshold", "value_12m"]
    )


def _customer_windows(orders: pd.DataFrame, key: str, t3: list, p3: list) -> pd.DataFrame:
    by = orders.groupby([key, "month"])["value"].sum().unstack(fill_value=0.0)
    out = pd.DataFrame(index=by.index)
    out["t3"] = by[[m for m in t3 if m in by.columns]].sum(axis=1)
    out["p3"] = by[[m for m in p3 if m in by.columns]].sum(axis=1)
    return out


def _bridge(cw: pd.DataFrame) -> tuple[list[dict[str, Any]], float]:
    p3, t3 = cw["p3"], cw["t3"]
    new = cw[(p3 == 0) & (t3 > 0)]
    lost = cw[(p3 > 0) & (t3 == 0)]
    kept = cw[(p3 > 0) & (t3 > 0)]
    up = kept[kept["t3"] > kept["p3"]]
    down = kept[kept["t3"] < kept["p3"]]
    start, end = float(p3.sum()), float(t3.sum())
    steps = [
        ("start", start, int((p3 > 0).sum())),
        ("new", float(new["t3"].sum()), len(new)),
        ("expansion", float((up["t3"] - up["p3"]).sum()), len(up)),
        ("contraction", float((down["t3"] - down["p3"]).sum()), len(down)),
        ("lost", -float(lost["p3"].sum()), len(lost)),
        ("end", end, int((t3 > 0).sum())),
    ]
    nrr = _pct(float(cw.loc[p3 > 0, "t3"].sum()), start)
    return [{"step": s, "value_usd": round(v, 2), "customers": n} for s, v, n in steps], nrr


# --------------------------------------------------------------------------------------------
@dataclass
class _Core:
    """The numbers one view needs (shared by regional_view and merge_impact)."""

    orders12: pd.DataFrame
    customer_count: int
    nrr: float
    bridge: list[dict[str, Any]]
    lost: pd.DataFrame
    cross_sell: float
    families: pd.Series  # customer key -> set of families in the period


_core_memo: dict[tuple[str, str, str | None], _Core] = {}


def _core(f: _Frames, view: View, country: str | None) -> _Core:
    """Memoised per loaded dataset (frames are immutable), so API calls stay fast."""
    memo_key = (f.key, view, country)
    if memo_key not in _core_memo:
        _core_memo[memo_key] = _compute_core(f, view, country)
    return _core_memo[memo_key]


def _compute_core(f: _Frames, view: View, country: str | None) -> _Core:
    key = _key(view)
    orders = f.orders if country is None else f.orders[f.orders["country"] == country]
    orders12 = orders[orders["month"].isin(f.months)]
    t3, p3 = _windows(f)
    bridge, nrr = _bridge(_customer_windows(orders12, key, t3, p3))
    families = orders12.groupby(key)["family"].agg(lambda s: frozenset(s))
    cross = _pct(int((families.map(len) >= 2).sum()), len(families))
    lost = _lost(f, orders, key)
    return _Core(orders12, len(families), nrr, bridge, lost, cross, families)


def _artefacts(f: _Frames, country: str | None) -> set[str]:
    """Raw records flagged lost before merge whose cluster is NOT lost after merge."""
    before = _core(f, "before", country).lost
    after_lost = set(_core(f, "after", country).lost["key"])
    return {k for k in before["key"] if f.golden.get(k, k) not in after_lost}


def _heatmap(f: _Frames, core: _Core, key: str) -> list[dict[str, Any]]:
    t3, p3 = _windows(f)
    o = core.orders12
    prior12 = [m - pd.DateOffset(months=12) for m in f.months]
    po = f.orders[f.orders["month"].isin(prior12)]
    cells = []
    for c in COUNTRIES:
        for p in PRODUCTS:
            g = o[(o["country"] == c) & (o["family"] == p)]
            prior = po.loc[(po["country"] == c) & (po["family"] == p), "value"]
            if g.empty and c not in set(o["country"]):
                continue
            cells.append(
                {
                    "country": c,
                    "product": p,
                    "value_usd": round(float(g["value"].sum()), 2),
                    "growth_pct": _growth(
                        float(g.loc[g["month"].isin(t3), "value"].sum()),
                        float(g.loc[g["month"].isin(p3), "value"].sum()),
                    ),
                    "growth_12m_pct": _growth(float(g["value"].sum()), float(prior.sum())),
                    "customers": int(g[key].nunique()),
                }
            )
    return cells


def _panels(f: _Frames, country: str | None) -> list[dict[str, Any]]:
    def flt(df: pd.DataFrame) -> pd.DataFrame:
        df = df[df["month"].isin(f.months)]
        return df if country is None else df[df["country"] == country]

    o, e, m = flt(f.orders), flt(f.enquiries), flt(f.mdm)
    enq, pr = e[e["kind"] == "enquiry"], e[e["kind"] == "purchase_request"]
    return [
        {
            "kind": "confirmed_po",
            "label": "Confirmed purchase orders",
            "count": int(o["doc_num"].nunique()),
            "value_usd": round(float(o["value"].sum()), 2),
            "caption": "Signed customer POs. The only thing counted as revenue and demand.",
        },
        {
            "kind": "enquiry",
            "label": "Enquiries",
            "count": int(enq["doc_num"].nunique()),
            "value_usd": round(float(enq["value"].sum()), 2),
            "caption": "Customers asking about price or stock. A leading indicator, not demand.",
        },
        {
            "kind": "purchase_request",
            "label": "Purchase requests",
            "count": int(pr["doc_num"].nunique()),
            "value_usd": round(float(pr["value"].sum()), 2),
            "caption": "Customers planning to buy. Some turn into POs later; not counted yet.",
        },
        {
            "kind": "mdm_request",
            "label": "Master data requests",
            "count": int(len(m)),
            "value_usd": None,
            "caption": "Requests to set up customers, items or cost centers. Never demand.",
        },
    ]


def _forecast_b(data_dir: Path) -> dict[str, float] | None:
    """Product B regional WAPE from the precomputed backtest, if it is there."""
    path = Path(data_dir).parent / "derived" / "forecast" / f"{Path(data_dir).name}_clean.json"
    if not path.exists():
        return None
    run = json.loads(path.read_text(encoding="utf-8"))
    for s in run["series"]:
        if s["level"] == "product" and s["product"] == "B":
            return {x["method"]: x["wape_pct"] for x in s["scores"]}
    return None


def _money(x: float) -> str:
    if abs(x) >= 1e6:
        return f"US${x / 1e6:.1f}M"
    if abs(x) >= 1e3:
        return f"US${x / 1e3:.0f}k"
    return f"US${x:.0f}"


def _actions(
    f: _Frames, data_dir: Path, view: View, country: str | None, core: _Core
) -> list[dict[str, str]]:
    t3, _ = _windows(f)
    where = COUNTRY_NAMES[country] if country else "the region"
    out: list[dict[str, str]] = []

    # 1. Product B: plan from the pipeline, not a moving average (D-017). Always present.
    e = f.enquiries if country is None else f.enquiries[f.enquiries["country"] == country]
    eb = e[e["family"] == "B"]
    pipe = eb[eb["month"].isin(t3)]
    hist = eb[eb["month"] < t3[0]]
    pr_hist = hist[hist["kind"] == "purchase_request"]
    conv = _pct(int(pr_hist["converted_doc_num"].notna().sum()), len(pr_hist))
    ob = core.orders12[(core.orders12["family"] == "B") & core.orders12["month"].isin(t3)]
    fb = _forecast_b(data_dir)
    fc = (
        f" In the backtest the 6-month Excel average missed regional Product B by "
        f"{fb['excel_6m']:.0f}% of volume."
        if fb and "excel_6m" in fb
        else ""
    )
    out.append(
        {
            "title": "Plan Product B equipment from the enquiry and purchase-request pipeline",
            "detail": (
                f"Equipment orders are rare and lumpy, so a moving average of past POs is a poor "
                f"guide. In the last 3 months {where} logged {pipe['doc_num'].nunique()} Product B "
                f"enquiries and purchase requests worth {_money(float(pipe['value'].sum()))}, "
                f"against {_money(float(ob['value'].sum()))} of Product B POs; historically "
                f"{conv:.0f}% of purchase requests became orders.{fc}"
            ),
            "evidence": "Enquiries and purchase requests panel; forecast backtest (Product B)",
        }
    )

    # 2. Lost customers to call.
    lost = core.lost
    if len(lost):
        noun = "customer records" if view == "before" else "customers"
        out.append(
            {
                "title": f"Call the {len(lost)} {noun} that have gone quiet",
                "detail": (
                    f"{len(lost)} {noun} in {where} have not ordered for longer than usual "
                    f"(over 90 days, or twice their normal gap). They bought "
                    f"{_money(float(lost['value_12m'].sum()))} in the last 12 months."
                ),
                "evidence": "Lost-customer alerts",
            }
        )

    # 3. Before merge only: most of those alerts are the same customer under another record.
    if view == "before":
        art = _artefacts(f, country)
        after = _core(f, "after", country)
        if art or after.customer_count != core.customer_count:
            out.append(
                {
                    "title": "Merge duplicate customer records before reading this view",
                    "detail": (
                        f"{len(art)} of the {len(lost)} 'lost' alerts are customers still "
                        f"ordering under another record. Before merging, {where} shows "
                        f"{core.customer_count} customers; after merging it is "
                        f"{after.customer_count}."
                    ),
                    "evidence": "Before/after merge toggle; duplicate check clusters",
                }
            )

    # 4. Fastest-growing test-kit market. Product A is the steady consumable, so its growth is
    # the cleanest signal; compared year on year (12 months vs the 12 before) so that holiday
    # dips (Lebaran, Songkran) and lumpy B/C orders cannot fake a trend.
    a = f.orders[f.orders["family"] == "A"]
    prior = [m - pd.DateOffset(months=12) for m in f.months]
    best, best_delta, best_pct = None, 0.0, 0.0
    for c in [country] if country else COUNTRIES:
        g = a[a["country"] == c]
        now = float(g.loc[g["month"].isin(f.months), "value"].sum())
        before = float(g.loc[g["month"].isin(prior), "value"].sum())
        if before > 0 and now - before > best_delta:
            best, best_delta, best_pct = c, now - before, 100.0 * (now - before) / before
    if best is not None:
        out.append(
            {
                "title": f"Secure test-kit stock and sales cover for {COUNTRY_NAMES[best]}",
                "detail": (
                    f"Product A orders in {COUNTRY_NAMES[best]} grew {best_pct:+.0f}% on the "
                    f"previous 12 months ({_money(best_delta)} more)"
                    + (", the largest increase of any country." if not country else ".")
                ),
                "evidence": "Country x product heatmap (Product A, year on year)",
            }
        )

    # 5. Cross-sell: test-kit customers with no service contract (after merge only: before
    # merge each company's record only sees its own product, so the gap is not real).
    if view == "after":
        fam = core.families
        a_not_c = fam[fam.map(lambda s: "A" in s and "C" not in s)]
        if len(a_not_c):
            out.append(
                {
                    "title": "Offer service contracts to test-kit customers",
                    "detail": (
                        f"{len(a_not_c)} of {core.customer_count} active customers in {where} "
                        f"buy Product A test kits but no Product C service. Cross-sell "
                        f"penetration is {core.cross_sell:.0f}%."
                    ),
                    "evidence": "Cross-sell penetration",
                }
            )
    # 6. Filler so there are always at least 3: open purchase requests to chase.
    if len(out) < 3:
        open_pr = e[(e["kind"] == "purchase_request") & e["month"].isin(t3)]
        open_pr = open_pr[open_pr["converted_doc_num"].isna()]
        out.append(
            {
                "title": "Follow up open purchase requests",
                "detail": (
                    f"{open_pr['doc_num'].nunique()} purchase requests from the last 3 months in "
                    f"{where} have not turned into a PO yet (worth "
                    f"{_money(float(open_pr['value'].sum()))})."
                ),
                "evidence": "Purchase requests panel",
            }
        )
    return out[:5]


CAPTIONS: dict[str, dict[str, str]] = {
    "period": {
        "title": "Stated period",
        "caption": "The last 12 full months of confirmed purchase orders.",
    },
    "heatmap": {
        "title": "Sales by country and product",
        "caption": "Value of confirmed POs in the last 12 months, in US dollars.",
    },
    "growth_12m_pct": {
        "title": "Growth (12 months)",
        "caption": (
            "Sales in the last 12 months compared with the 12 months before, as a % change. "
            "This is our main growth measure."
        ),
    },
    "growth_pct": {
        "title": "Short-term change (3 months)",
        "caption": "Last 3 months compared with the 3 months before, as a % change.",
    },
    "product_b_note": {
        "title": "Product B is lumpy",
        "caption": (
            "Equipment sells in a few large orders, so its growth swings from quarter to quarter. "
            "Plan it from the enquiry pipeline, not from past growth."
        ),
    },
    "nrr_pct": {
        "title": "Net revenue retention (NRR)",
        "caption": (
            "What customers who bought 3-6 months ago spent in the last 3 months, as a % of "
            "what they spent then. Over 100% means existing customers are growing."
        ),
    },
    "bridge": {
        "title": "Revenue bridge",
        "caption": (
            "How the prior 3 months' revenue became the last 3 months': plus new customers and "
            "customers who bought more, minus customers who bought less and customers who stopped."
        ),
    },
    "cross_sell_pct": {
        "title": "Cross-sell penetration",
        "caption": "Share of active customers buying at least 2 of Products A, B and C.",
    },
    "customer_count": {
        "title": "Active customers",
        "caption": "Customers with at least one confirmed PO in the last 12 months.",
    },
    "lost_customers": {
        "title": "Lost-customer alerts",
        "caption": (
            "Customers with no PO for more than 90 days, or more than twice their usual gap "
            "between orders, whichever is longer."
        ),
    },
    "panels": {
        "title": "POs, enquiries and requests",
        "caption": (
            "Kept apart on purpose: only confirmed POs are demand. Enquiries and purchase "
            "requests are early signals; master data requests are never demand."
        ),
    },
    "actions": {
        "title": "Recommended actions",
        "caption": "Generated from the numbers on this page by fixed rules, not by AI.",
    },
    "view": {
        "title": "Before / after merge",
        "caption": (
            "Before: every SAP customer record counts as a customer. After: records our "
            "duplicate check links (and a human would confirm) count as one customer."
        ),
    },
}


# --------------------------------------------------------------------------------------------
def regional_view(data_dir: Path, view: View, country: str | None = None) -> dict[str, Any]:
    """-> RegionalView. `data_dir` = data/fixtures/seasonal_trend."""
    if view not in ("before", "after"):
        raise ValueError(f"view must be 'before' or 'after', not {view!r}")
    if country is not None and country not in COUNTRIES:
        raise ValueError(f"unknown country {country!r}")
    f = _frames(data_dir)
    key = _key(view)
    core = _core(f, view, country)
    art = _artefacts(f, country) if view == "before" else set()
    lost_rows = core.lost.sort_values(["value_12m", "key"], ascending=[False, True])
    lost = [
        {
            "card_code": r.key,
            "name": f.names.get(r.key, r.key) if view == "before" else f.golden_names[r.key],
            "country": r.country,
            "last_order": f"{r.last_order:%Y-%m-%d}",
            "is_duplicate_artefact": r.key in art,
        }
        for r in lost_rows.itertuples()
    ]
    heat = _heatmap(f, core, key)
    return {
        "view": view,
        "period": period_label(f.months),
        "country": country,
        "heatmap": heat,
        "nrr_pct": core.nrr,
        "bridge": copy.deepcopy(core.bridge),
        "cross_sell_pct": core.cross_sell,
        "customer_count": core.customer_count,
        "lost_customers": lost,
        "panels": _panels(f, country),
        "actions": _actions(f, Path(data_dir), view, country, core),
        "captions": {k: dict(v) for k, v in CAPTIONS.items()},
    }


def merge_impact(data_dir: Path) -> dict[str, Any]:
    """-> MergeImpact (before vs after merge: customer counts, lost alerts, NRR, by country)."""
    f = _frames(data_dir)
    before, after = _core(f, "before", None), _core(f, "after", None)
    art = _artefacts(f, None)
    by_country = []
    for c in COUNTRIES:
        b = before.lost[before.lost["country"] == c]
        a = after.lost[after.lost["country"] == c]
        by_country.append(
            {
                "country": c,
                "lost_before": len(b),
                "lost_after": len(a),
                "lost_that_were_duplicates": int(b["key"].isin(art).sum()),
            }
        )
    return {
        "customers_before": before.customer_count,
        "customers_after": after.customer_count,
        "lost_before": len(before.lost),
        "lost_after": len(after.lost),
        "lost_that_were_duplicates": len(art),
        "by_country": by_country,
        "nrr_before_pct": before.nrr,
        "nrr_after_pct": after.nrr,
        "caption": (
            f"Counting every SAP record as a customer shows {before.customer_count} customers "
            f"and {len(before.lost)} lost-customer alerts. Once duplicates are linked there are "
            f"{after.customer_count} customers and {len(after.lost)} alerts: {len(art)} of the "
            f"alerts were customers still ordering under another record."
        ),
    }
