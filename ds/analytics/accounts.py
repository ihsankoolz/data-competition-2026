"""Account lists for the regional view after merge (PRD S1): drop-off risk and cross-sell
whitespace, one row per real customer (our golden cluster). Pure functions over the confirmed-PO
frame that `ds.analytics.regional` already builds (rule 9: confirmed POs only).

Before merge these lists are not produced: a customer split across several SAP records looks like
it stopped buying (one record went quiet) or never bought a product line (another record buys it),
so neither list would describe a real account.

Definitions (stated period = the last 12 full months; T3 = its last 3 months, P3 = the 3 before):

Drop-off risk
- Measured on repeat purchases only: Product A (test kits) and Product C (services). Product B
  equipment is a one-off purchase, so a quiet quarter after buying a machine is normal.
- A customer is at risk when all of these hold:
  * it is a regular buyer: repeat orders in at least DROP_MIN_MONTHS of the 9 months before T3;
  * its repeat spend in P3 was at least DROP_MIN_P3_USD;
  * its repeat spend in T3 fell by at least DROP_MIN_FALL (or to zero) against P3;
  * it is NOT already on the lost-customer list (those have gone quiet, these are fading).
- value at risk = P3 repeat spend - T3 repeat spend (the quarterly spend that has gone missing).

Cross-sell whitespace
- The missing line X is a repeat family (A test kits or C services). Product B equipment is never
  the suggested gap: it is a one-off capital purchase, so "what similar customers spend a year
  on it" would put a machine's price on every services customer (we tried: it dominated the
  list at ~US$150k a row and summed to an implausible US$11.5M).
- For a customer buying some of A/B/C in the period but not repeat family X: the estimate is the
  median
  12-month spend on X of comparable customers = same country, already buying X and at least one of
  the families this customer buys. Needs at least WS_MIN_PEERS such customers, else no estimate.
- One row per customer: the missing family with the highest estimate.
- Customers on the lost or drop-off lists are left out (win them back first).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

REPEAT_FAMILIES = ("A", "C")
DROP_MIN_FALL = 0.5  # T3 repeat spend at most half of P3
DROP_MIN_P3_USD = 5_000.0
DROP_MIN_MONTHS = 3  # of the 9 months before T3
WS_MIN_PEERS = 3
WS_TARGETS = REPEAT_FAMILIES  # equipment (B) is a one-off capital buy, not a yearly spend
FAMILY_WORDS = {"A": "test kits", "B": "equipment", "C": "services"}


def _usd(x: float) -> str:
    if abs(x) >= 1e6:
        return f"US${x / 1e6:.1f}M"
    if abs(x) >= 1e3:
        return f"US${x / 1e3:.0f}k"
    return f"US${x:.0f}"


def drop_off_risk(
    orders12: pd.DataFrame,
    key: str,
    months: list[pd.Timestamp],
    lost_keys: Iterable[str],
) -> pd.DataFrame:
    """-> one row per at-risk customer: key, country, last_order, p3, t3, value_at_risk,
    change_pct; sorted by value_at_risk desc, then key. `orders12` = confirmed-PO lines of the
    12-month period (already country-filtered), `months` = those 12 months in order."""
    cols = ["key", "country", "last_order", "p3", "t3", "value_at_risk", "change_pct"]
    t3, p3, pre = months[-3:], months[-6:-3], months[:9]
    rep = orders12[orders12["family"].isin(REPEAT_FAMILIES)]
    if rep.empty:
        return pd.DataFrame(columns=cols)
    by = rep.groupby([key, "month"])["value"].sum().unstack(fill_value=0.0)
    w = pd.DataFrame(index=by.index)
    w["t3"] = by[[m for m in t3 if m in by.columns]].sum(axis=1)
    w["p3"] = by[[m for m in p3 if m in by.columns]].sum(axis=1)
    w["regular"] = (by[[m for m in pre if m in by.columns]] > 0).sum(axis=1)
    lost = set(lost_keys)
    risk = w[
        (w["regular"] >= DROP_MIN_MONTHS)
        & (w["p3"] >= DROP_MIN_P3_USD)
        & (w["t3"] <= (1.0 - DROP_MIN_FALL) * w["p3"])
        & ~w.index.isin(lost)
    ]
    rows = []
    for k, r in risk.iterrows():
        g = orders12[orders12[key] == k]
        rows.append(
            {
                "key": k,
                "country": g.sort_values("doc_date")["country"].iloc[-1],
                "last_order": g["doc_date"].max(),
                "p3": float(r["p3"]),
                "t3": float(r["t3"]),
                "value_at_risk": round(float(r["p3"] - r["t3"]), 2),
                "change_pct": round(100.0 * (r["t3"] - r["p3"]) / r["p3"], 1),
            }
        )
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(["value_at_risk", "key"], ascending=[False, True]).reset_index(drop=True)


def drop_off_reason(r: Any) -> str:
    if r.t3 <= 0:
        return (
            f"A regular buyer of test kits or services whose repeat orders stopped in the last "
            f"3 months, after {_usd(r.p3)} in the 3 months before."
        )
    return (
        f"A regular buyer whose test-kit and service orders fell from {_usd(r.p3)} to "
        f"{_usd(r.t3)} in the last 3 months ({r.change_pct:+.0f}%)."
    )


def whitespace(
    orders12: pd.DataFrame, key: str, exclude: Iterable[str], families: Iterable[str]
) -> pd.DataFrame:
    """-> one row per customer with a cross-sell gap: key, country, buys (sorted list),
    missing, est_value, peers, own_12m; sorted by est_value desc, own_12m desc, key."""
    cols = ["key", "country", "buys", "missing", "est_value", "peers", "own_12m"]
    fams = sorted(families)
    targets = [p for p in fams if p in WS_TARGETS]
    if orders12.empty:
        return pd.DataFrame(columns=cols)
    spend = orders12.groupby([key, "family"])["value"].sum().unstack(fill_value=0.0)
    for p in fams:
        if p not in spend.columns:
            spend[p] = 0.0
    country = orders12.sort_values("doc_date").groupby(key)["country"].last()
    skip = set(exclude)
    rows = []
    for k in spend.index:
        if k in skip:
            continue
        buys = [p for p in fams if spend.at[k, p] > 0]
        gaps = [p for p in targets if p not in buys]
        if not buys or not gaps:
            continue
        same = spend[(country == country[k]).reindex(spend.index, fill_value=False)]
        best = None
        for x in gaps:
            peers = same[(same[x] > 0) & (same[buys] > 0).any(axis=1)]
            if len(peers) < WS_MIN_PEERS:
                continue
            est = round(float(peers[x].median()), 2)
            if best is None or est > best[1]:
                best = (x, est, len(peers))
        if best is None:
            continue
        rows.append(
            {
                "key": k,
                "country": country[k],
                "buys": buys,
                "missing": best[0],
                "est_value": best[1],
                "peers": best[2],
                "own_12m": round(float(spend.loc[k, fams].sum()), 2),
            }
        )
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(
        ["est_value", "own_12m", "key"], ascending=[False, False, True]
    ).reset_index(drop=True)


def whitespace_reason(r: Any, country_name: str) -> str:
    bought = " and ".join(f"Product {p}" for p in r.buys)
    return (
        f"Buys {bought} but no Product {r.missing} ({FAMILY_WORDS[r.missing]}); "
        f"{r.peers} similar customers in {country_name} spend a median {_usd(r.est_value)} a "
        f"year on it."
    )
