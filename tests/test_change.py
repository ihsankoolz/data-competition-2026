"""Why a country's 12-month sales changed (`ds.analytics.change`): Singapore, demo scenario."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ds.analytics.change import CUSTOMER_TYPES, country_change_breakdown
from ds.analytics.golden import golden_clusters

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "data" / "fixtures" / "seasonal_trend"


def _windows() -> tuple[pd.DataFrame, pd.DataFrame]:
    o = pd.read_csv(FIX / "orders.csv", dtype={"card_code": str})
    o = o[o["country"] == "SG"].copy()
    o["value"] = o["qty"] * o["unit_price_usd"]
    o["product"] = o["item_code"].str[0]
    now = o[(o["doc_date"] >= "2025-10-01") & (o["doc_date"] <= "2026-09-30")]
    prior = o[(o["doc_date"] >= "2024-10-01") & (o["doc_date"] <= "2025-09-30")]
    return now, prior


@pytest.mark.parametrize("view", ["after", "before"])
def test_singapore_breakdown_sums_to_the_total_and_matches_orders_csv(view):
    """Total computed independently from orders.csv (-16.2%, the country total in
    docs/results.md); both splits add up to it; each part matches an independent recount."""
    now, prior = _windows()
    total = now["value"].sum() - prior["value"].sum()
    out = country_change_breakdown(FIX, "SG", view)

    assert out.change_usd == pytest.approx(total, abs=0.01)
    assert out.growth_pct == pytest.approx(-16.2, abs=0.05)
    assert out.growth_pct == pytest.approx(100 * total / prior["value"].sum(), abs=0.05)
    assert sum(p.change_usd for p in out.by_product) == pytest.approx(total, abs=0.05)
    assert sum(p.change_usd for p in out.by_customer_type) == pytest.approx(total, abs=0.05)
    assert sum(out.type_by_product.values()) == pytest.approx(total, abs=0.05)

    for p in out.by_product:
        expect = (
            now.loc[now["product"] == p.label, "value"].sum()
            - prior.loc[prior["product"] == p.label, "value"].sum()
        )
        assert p.change_usd == pytest.approx(expect, abs=0.01), p

    # customer types, recounted from orders.csv with the same customer key as the view
    gc = golden_clusters(FIX)
    key = (lambda c: gc.get(c, c)) if view == "after" else (lambda c: c)
    n = now.groupby(now["card_code"].map(key))["value"].sum()
    p_ = prior.groupby(prior["card_code"].map(key))["value"].sum()
    df = pd.concat([n.rename("n"), p_.rename("p")], axis=1).fillna(0.0)
    kind = df.apply(
        lambda r: (
            "new"
            if r.p == 0
            else "lost"
            if r.n == 0
            else ("expanding" if r.n > r.p else "shrinking")
        ),
        axis=1,
    )
    got = {p.label: p for p in out.by_customer_type}
    assert list(got) == CUSTOMER_TYPES
    for t in CUSTOMER_TYPES:
        sub = df[kind == t]
        assert got[t].customers == len(sub), t
        assert got[t].change_usd == pytest.approx((sub["n"] - sub["p"]).sum(), abs=0.01), t


def test_singapore_drop_is_mostly_equipment_and_merging_removes_fake_lost_customers():
    """The verdict in docs/results.md: Product B explains more than the whole drop, repeat
    business (A + C) is up; before merge 'lost' records explain far more of the drop."""
    after = country_change_breakdown(FIX, "SG", "after")
    before = country_change_breakdown(FIX, "SG", "before")
    prod = {p.label: p for p in after.by_product}
    assert prod["B"].share_pct > 100
    assert after.repeat_change_usd > 0
    lost_a = next(p for p in after.by_customer_type if p.label == "lost")
    lost_b = next(p for p in before.by_customer_type if p.label == "lost")
    assert lost_b.change_usd < lost_a.change_usd < 0
    assert lost_b.customers > lost_a.customers
    assert len(after.top_repeat_drops) == 5
    assert all(d.change_usd < 0 for d in after.top_repeat_drops)
