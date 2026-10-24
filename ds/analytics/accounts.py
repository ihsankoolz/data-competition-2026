"""Account lists for the regional view after merge (PRD S1): drop-off risk and cross-sell
whitespace, one row per real customer (our golden cluster). Pure functions over the confirmed-PO
frame that `ds.analytics.regional` already builds (rule 9: confirmed POs only).

Before merge these lists are not produced: a customer split across several SAP records looks like
it stopped buying (one record went quiet) or never bought a product line (another record buys it),
so neither list would describe a real account.

Definitions (stated period = the last 12 full months; T3 = its last 3 months; LY3 = the same 3
calendar months one year earlier, D-022 #4):

Drop-off risk (year over year, so seasonal dips such as Lebaran or Songkran cannot fake a fall)
- Measured on repeat purchases only: Product A (test kits) and Product C (services). Product B
  equipment is a one-off purchase, so a quiet quarter after buying a machine is normal.
- A customer is at risk when all of these hold:
  * it is a regular buyer: repeat orders in at least DROP_MIN_MONTHS of the 9 months before T3;
  * its repeat spend in LY3 was at least DROP_MIN_LY3_USD;
  * its repeat spend in T3 fell by at least DROP_MIN_FALL (or to zero) against LY3;
  * it is NOT already on the lost-customer list (those have gone quiet, these are fading).
- value at risk = LY3 repeat spend - T3 repeat spend (what it ordered less than a year earlier).
- A regular buyer with NO repeat orders in LY3 (it started buying later, or skips that season)
  has nothing to compare against, so it is not scored and never listed (`drop_off_unscored`).

Cross-sell whitespace
- The missing line X is a repeat family (A test kits or C services). Product B equipment is never
  the suggested gap: it is a one-off capital purchase, so "what similar customers spend a year
  on it" would put a machine's price on every services customer (we tried: it dominated the
  list at ~US$150k a row and summed to an implausible US$11.5M).
- For a customer buying some of A/B/C in the period but not repeat family X: the estimate is the
  median 12-month spend on X of comparable customers = same country, already buying X and at
  least one of the families this customer buys. Needs at least WS_MIN_PEERS such customers, else
  no estimate.
- Fewer than WS_CONFIDENT_PEERS comparable customers -> `low_confidence`: the row is still listed
  (marked) but left out of the US$ total (D-022 #4). A median of a handful of customers can be
  one big hospital's spend.
- One row per customer: the missing family with the highest estimate, preferring one backed by
  enough comparable customers over a low-confidence one.
- Customers on the lost or drop-off lists are left out (win them back first).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pandas as pd

REPEAT_FAMILIES = ("A", "C")
DROP_MIN_FALL = 0.5  # T3 repeat spend at most half of the same quarter last year
DROP_MIN_LY3_USD = 5_000.0
DROP_MIN_MONTHS = 3  # of the 9 months before T3
WS_MIN_PEERS = 3  # below this there is no estimate at all
WS_CONFIDENT_PEERS = 10  # below this the row is low confidence and left out of the US$ total
WS_TARGETS = REPEAT_FAMILIES  # equipment (B) is a one-off capital buy, not a yearly spend
FAMILY_WORDS = {"A": "test kits", "B": "equipment", "C": "services"}


def _usd(x: float) -> str:
    if abs(x) >= 1e6:
        return f"US${x / 1e6:.1f}M"
    if abs(x) >= 1e3:
        return f"US${x / 1e3:.0f}k"
    return f"US${x:.0f}"


def quarter_label(months: list[pd.Timestamp]) -> str:
    """'Jul-Sep 2026' for three consecutive months (year of the last one)."""
    return f"{months[0]:%b}-{months[-1]:%b %Y}"


def drop_off_windows(
    months: list[pd.Timestamp],
) -> tuple[list[pd.Timestamp], list[pd.Timestamp], list[pd.Timestamp]]:
    """-> (T3, LY3, pre): the latest quarter, the same quarter a year earlier, and the 9 months
    of the period before T3 (used for 'regular buyer')."""
    t3 = months[-3:]
    return t3, [m - pd.DateOffset(months=12) for m in t3], months[:9]


def _drop_frame(
    orders: pd.DataFrame, key: str, months: list[pd.Timestamp], lost_keys: Iterable[str]
) -> pd.DataFrame:
    """Regular, not-lost repeat buyers with their T3 and LY3 repeat spend (index = key)."""
    t3, ly3, pre = drop_off_windows(months)
    rep = orders[orders["family"].isin(REPEAT_FAMILIES)]
    if rep.empty:
        return pd.DataFrame(columns=["t3", "ly3", "regular"])
    by = rep.groupby([key, "month"])["value"].sum().unstack(fill_value=0.0)
    w = pd.DataFrame(index=by.index)
    w["t3"] = by[[m for m in t3 if m in by.columns]].sum(axis=1)
    w["ly3"] = by[[m for m in ly3 if m in by.columns]].sum(axis=1)
    w["regular"] = (by[[m for m in pre if m in by.columns]] > 0).sum(axis=1)
    lost = set(lost_keys)
    return w[(w["regular"] >= DROP_MIN_MONTHS) & ~w.index.isin(lost)]


def drop_off_risk(
    orders: pd.DataFrame,
    key: str,
    months: list[pd.Timestamp],
    lost_keys: Iterable[str],
) -> pd.DataFrame:
    """-> one row per at-risk customer: key, country, last_order, ly3, t3, value_at_risk,
    change_pct; sorted by value_at_risk desc, then key. `orders` = confirmed-PO lines (already
    country-filtered) covering at least the 12-month period and the same quarter a year before
    its last quarter; `months` = the 12 months of the period in order."""
    cols = ["key", "country", "last_order", "ly3", "t3", "value_at_risk", "change_pct"]
    w = _drop_frame(orders, key, months, lost_keys)
    risk = w[(w["ly3"] >= DROP_MIN_LY3_USD) & (w["t3"] <= (1.0 - DROP_MIN_FALL) * w["ly3"])]
    in_period = orders[orders["month"] <= months[-1]]
    rows = []
    for k, r in risk.iterrows():
        g = in_period[in_period[key] == k]
        rows.append(
            {
                "key": k,
                "country": g.sort_values("doc_date")["country"].iloc[-1],
                "last_order": g["doc_date"].max(),
                "ly3": float(r["ly3"]),
                "t3": float(r["t3"]),
                "value_at_risk": round(float(r["ly3"] - r["t3"]), 2),
                "change_pct": round(100.0 * (r["t3"] - r["ly3"]) / r["ly3"], 1),
            }
        )
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(["value_at_risk", "key"], ascending=[False, True]).reset_index(drop=True)


def drop_off_unscored(
    orders: pd.DataFrame, key: str, months: list[pd.Timestamp], lost_keys: Iterable[str]
) -> list[str]:
    """Regular, not-lost repeat buyers with no repeat orders in the same quarter last year: they
    cannot be compared year over year, so the drop-off list never includes them."""
    w = _drop_frame(orders, key, months, lost_keys)
    return sorted(w.index[w["ly3"] <= 0])


def drop_off_reason(r: Any, months: list[pd.Timestamp]) -> str:
    t3, ly3, _ = drop_off_windows(months)
    now, then = quarter_label(t3), quarter_label(ly3)
    if r.t3 <= 0:
        return (
            f"A regular buyer of test kits or services with no repeat orders in {now}, after "
            f"{_usd(r.ly3)} in the same quarter last year ({then})."
        )
    return (
        f"A regular buyer who spent {-r.change_pct:.0f}% less on test kits and services in {now} "
        f"than in the same quarter last year ({_usd(r.t3)}, down from {_usd(r.ly3)} in {then})."
    )


def whitespace(
    orders12: pd.DataFrame, key: str, exclude: Iterable[str], families: Iterable[str]
) -> pd.DataFrame:
    """-> one row per customer with a cross-sell gap: key, country, buys (sorted list),
    missing, est_value, peers, low_confidence, own_12m; sorted by est_value desc, own_12m desc,
    key."""
    cols = ["key", "country", "buys", "missing", "est_value", "peers", "low_confidence", "own_12m"]
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
        best = None  # (confident, estimate, family, peers): confident gaps first, then value
        for x in gaps:
            peers = same[(same[x] > 0) & (same[buys] > 0).any(axis=1)]
            if len(peers) < WS_MIN_PEERS:
                continue
            cand = (len(peers) >= WS_CONFIDENT_PEERS, round(float(peers[x].median()), 2), x)
            if best is None or cand[:2] > best[:2]:
                best = (*cand, len(peers))
        if best is None:
            continue
        rows.append(
            {
                "key": k,
                "country": country[k],
                "buys": buys,
                "missing": best[2],
                "est_value": best[1],
                "peers": best[3],
                "low_confidence": not best[0],
                "own_12m": round(float(spend.loc[k, fams].sum()), 2),
            }
        )
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(
        ["est_value", "own_12m", "key"], ascending=[False, False, True]
    ).reset_index(drop=True)


def whitespace_total(ws: pd.DataFrame) -> float:
    """US$ total of the whitespace list: confident rows only (low-confidence rows are left out)."""
    if ws.empty:
        return 0.0
    return round(float(ws.loc[~ws["low_confidence"].astype(bool), "est_value"].sum()), 2)


def whitespace_reason(r: Any, country_name: str) -> str:
    bought = " and ".join(f"Product {p}" for p in r.buys)
    return (
        f"Buys {bought} but no Product {r.missing} ({FAMILY_WORDS[r.missing]}); "
        f"{r.peers} similar customers in {country_name} spend a median {_usd(r.est_value)} a "
        f"year on it."
    )
