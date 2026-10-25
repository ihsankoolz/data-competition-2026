"""Why did a country's 12-month sales change? (PRD M8, D-009, D-022 #3.)

Splits one country's headline growth (confirmed-PO value in the stated 12-month period minus the
12 months before it, the same windows as `RegionalView.country_growth`) two ways:

- by product family A / B / C (B = equipment, lumpy one-off purchases);
- by customer type, one row per customer (our golden cluster after merge, a raw CardCode before):
  * new: no orders in the prior 12 months, orders in the last 12;
  * lost: orders in the prior 12 months, none in the last 12;
  * expanding: orders in both, last 12 higher;
  * shrinking: orders in both, last 12 lower or equal (an equal one adds US$0).

Each split's parts sum exactly to the total change. Confirmed POs only (rule 9). Pure function over
the frame `ds.analytics.regional` already builds; "after" uses our dedup clusters, never ground
truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from ds.analytics import regional as rg

CUSTOMER_TYPES = ["new", "expanding", "shrinking", "lost"]
REPEAT_FAMILIES = ["A", "C"]  # test kits and services: repeat purchases (B is one-off equipment)
TOP_REPEAT_DROPS = 5  # accounts named in the follow-up line


@dataclass(frozen=True)
class Part:
    label: str  # product family ("A"/"B"/"C") or customer type
    change_usd: float  # last 12 minus prior 12, US$
    share_pct: float  # % of the total change (opposite sign = offsets the change)
    # customer-type split: customers of that type; product split: buyers in either window
    customers: int
    prior_usd: float  # the part's prior-12-month spend (0 for new customers)


def growth_of(p: Part) -> float | None:
    """The part's own 12-month growth in % (None when it had no prior spend)."""
    return round(100.0 * p.change_usd / p.prior_usd, 1) if p.prior_usd > 0 else None


@dataclass(frozen=True)
class AccountDrop:
    key: str  # golden id (after) or CardCode (before)
    name: str
    change_usd: float  # repeat (A + C) spend, last 12 minus prior 12


@dataclass(frozen=True)
class ChangeBreakdown:
    country: str
    view: str
    period: str  # e.g. "Oct 2025 - Sep 2026"
    prior_period: str
    now_usd: float
    prior_usd: float
    change_usd: float
    growth_pct: float | None
    by_product: list[Part]
    by_customer_type: list[Part]
    type_by_product: dict[tuple[str, str], float]  # (customer type, family) -> change US$
    repeat_change_usd: float  # A + C only
    repeat_prior_usd: float
    top_repeat_drops: list[AccountDrop]  # customers whose A + C spend fell most


def _share(part: float, total: float) -> float:
    return round(100.0 * part / total, 1) if total else 0.0


def customer_type(now: float, prior: float) -> str:
    if prior <= 0:
        return "new"
    if now <= 0:
        return "lost"
    return "expanding" if now > prior else "shrinking"


def country_change_breakdown(
    data_dir: Path, country: str, view: rg.View = "after"
) -> ChangeBreakdown:
    f = rg._frames(data_dir)
    key = rg._key(view)
    prior_months = [m - pd.DateOffset(months=12) for m in f.months]
    o = f.orders[f.orders["country"] == country]
    now = o[o["month"].isin(f.months)]
    prior = o[o["month"].isin(prior_months)]
    now_v, prior_v = float(now["value"].sum()), float(prior["value"].sum())
    total = now_v - prior_v

    # customer x family, both windows
    cell = pd.concat(
        [
            now.groupby([key, "family"])["value"].sum().rename("now"),
            prior.groupby([key, "family"])["value"].sum().rename("prior"),
        ],
        axis=1,
    ).fillna(0.0)
    cell["d"] = cell["now"] - cell["prior"]
    cust = cell.groupby(level=0)[["now", "prior", "d"]].sum()
    cust["type"] = [customer_type(n, p) for n, p in zip(cust["now"], cust["prior"], strict=True)]
    cell = cell.reset_index()
    cell["type"] = cell[key].map(cust["type"])

    by_product = []
    for fam in rg.PRODUCTS:
        g = cell[cell["family"] == fam]
        d = float(g["d"].sum())
        by_product.append(
            Part(
                fam,
                round(d, 2),
                _share(d, total),
                int(g[key].nunique()),
                round(float(g["prior"].sum()), 2),
            )
        )
    by_type = []
    for t in CUSTOMER_TYPES:
        g = cust[cust["type"] == t]
        d = float(g["d"].sum())
        by_type.append(
            Part(t, round(d, 2), _share(d, total), len(g), round(float(g["prior"].sum()), 2))
        )
    type_by_product = {
        (t, fam): round(
            float(cell.loc[(cell["type"] == t) & (cell["family"] == fam), "d"].sum()), 2
        )
        for t in CUSTOMER_TYPES
        for fam in rg.PRODUCTS
    }

    rep = cell[cell["family"].isin(REPEAT_FAMILIES)]
    rep_c = rep.groupby(key)["d"].sum()
    rep_c = rep_c[rep_c < 0].sort_values(kind="mergesort")  # stable: ties keep key order
    names = f.golden_names if view == "after" else f.names
    drops = [
        AccountDrop(k, names.get(k, k), round(float(v), 2))
        for k, v in rep_c.head(TOP_REPEAT_DROPS).items()
    ]
    return ChangeBreakdown(
        country=country,
        view=view,
        period=f"{f.months[0]:%b %Y} - {f.months[-1]:%b %Y}",
        prior_period=f"{prior_months[0]:%b %Y} - {prior_months[-1]:%b %Y}",
        now_usd=round(now_v, 2),
        prior_usd=round(prior_v, 2),
        change_usd=round(total, 2),
        growth_pct=rg._growth(now_v, prior_v),
        by_product=by_product,
        by_customer_type=by_type,
        type_by_product=type_by_product,
        repeat_change_usd=round(float(rep["d"].sum()), 2),
        repeat_prior_usd=round(float(rep["prior"].sum()), 2),
        top_repeat_drops=drops,
    )
