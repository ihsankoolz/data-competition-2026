"""M8 regional view (D-009) and our golden clusters (D-018 #5)."""

from __future__ import annotations

import csv
import shutil
import time
from pathlib import Path

import pandas as pd
import pytest

from ds.analytics import golden as golden_mod
from ds.analytics.golden import CACHE_PATH, compute_clusters, golden_clusters
from ds.analytics.regional import merge_impact, regional_view
from services.api.schemas import MergeImpact, RegionalView

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "data" / "fixtures" / "seasonal_trend"


def _rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


# ------------------------------------------------------------------------- golden clusters
def test_cache_is_committed_and_matches_a_fresh_run_without_ground_truth(tmp_path):
    """The clusters come from the master files only: a folder with no ground_truth/ gives the
    same answer as the committed cache."""
    assert CACHE_PATH.exists()
    for name in ("bp_records.csv", "vendors.csv"):
        shutil.copy(FIX / name, tmp_path / name)
    assert not (tmp_path / "ground_truth").exists()
    fresh = compute_clusters(tmp_path)
    assert fresh == golden_mod._read_cache(CACHE_PATH)


def test_clusters_respect_rules_2_and_3():
    clusters = golden_clusters(FIX)
    recs = {r["CardCode"]: r for r in _rows(FIX / "bp_records.csv")}
    assert set(clusters) == {c for c, r in recs.items() if r["CardType"] == "cCustomer"}
    assert not any(c.startswith("V") for c in clusters)  # vendors never join (rule 2)
    by_cluster: dict[str, set[str]] = {}
    for code, gid in clusters.items():
        by_cluster.setdefault(gid, set()).add(recs[code]["Country"])
    assert all(len(cs) == 1 for cs in by_cluster.values())  # never across countries (rule 3)
    # ids are stable: G-<lowest CardCode in the cluster>
    for gid in by_cluster:
        members = sorted(c for c, g in clusters.items() if g == gid)
        assert gid == f"G-{members[0]}"


def test_cross_country_group_members_stay_separate():
    clusters = golden_clusters(FIX)
    gmap = {r["CardCode"]: r["golden_id"] for r in _rows(FIX / "ground_truth/bp_golden_map.csv")}
    groups = _rows(FIX / "ground_truth/groups.csv")
    for g in groups:
        goldens = set(g["golden_ids"].split())
        ours = {clusters[c] for c, gid in gmap.items() if gid in goldens and c in clusters}
        # one cluster per member (country), never merged across the group
        assert len(ours) >= len(goldens)


def test_cache_is_lf_only():
    assert b"\r\n" not in CACHE_PATH.read_bytes()


# ------------------------------------------------------------------------- regional view
@pytest.mark.parametrize("view", ["before", "after"])
@pytest.mark.parametrize("country", [None, "VN"])
def test_regional_view_validates(view, country):
    out = regional_view(FIX, view, country)
    m = RegionalView.model_validate(out)
    assert m.period == "Oct 2025 - Sep 2026 (last 12 full months)"
    assert 3 <= len(m.actions) <= 5
    assert any("Product B" in a.title and "pipeline" in a.title for a in m.actions)
    assert all(any(ch.isdigit() for ch in a.detail) for a in m.actions)
    for k in ("heatmap", "nrr_pct", "bridge", "cross_sell_pct", "lost_customers", "panels"):
        assert m.captions[k].caption
    if country:
        assert {c.country for c in m.heatmap} == {country}
        assert {lc.country for lc in m.lost_customers} <= {country}


def test_revenue_is_confirmed_pos_only():
    """Rule 9: the heatmap total equals confirmed POs in the period; enquiries are a panel."""
    out = regional_view(FIX, "after")
    o = pd.read_csv(FIX / "orders.csv")
    o = o[(o["doc_date"] >= "2025-10-01") & (o["doc_date"] <= "2026-09-30")]
    total = float((o["qty"] * o["unit_price_usd"]).sum())
    assert sum(c["value_usd"] for c in out["heatmap"]) == pytest.approx(total, abs=1.0)
    panels = {p["kind"]: p for p in out["panels"]}
    assert set(panels) == {"confirmed_po", "enquiry", "purchase_request", "mdm_request"}
    assert panels["confirmed_po"]["value_usd"] == pytest.approx(total, abs=1.0)
    assert panels["mdm_request"]["value_usd"] is None


@pytest.mark.parametrize("view", ["before", "after"])
def test_bridge_adds_up_and_nrr_matches(view):
    out = regional_view(FIX, view)
    b = {s["step"]: s["value_usd"] for s in out["bridge"]}
    assert b["start"] + b["new"] + b["expansion"] + b["contraction"] + b["lost"] == pytest.approx(
        b["end"], abs=0.1
    )
    assert b["contraction"] <= 0 <= b["expansion"] and b["lost"] <= 0 <= b["new"]
    retained_t3 = b["start"] + b["expansion"] + b["contraction"] + b["lost"]
    assert out["nrr_pct"] == pytest.approx(100 * retained_t3 / b["start"], abs=0.1)
    # revenue totals do not depend on the view; only customer-level numbers do
    other = regional_view(FIX, "after" if view == "before" else "before")
    assert sum(c["value_usd"] for c in out["heatmap"]) == pytest.approx(
        sum(c["value_usd"] for c in other["heatmap"]), abs=0.01
    )


def test_merging_shrinks_customers_and_false_lost_alerts():
    before, after = regional_view(FIX, "before"), regional_view(FIX, "after")
    assert after["customer_count"] < before["customer_count"]
    assert len(after["lost_customers"]) < len(before["lost_customers"])
    assert not any(lc["is_duplicate_artefact"] for lc in after["lost_customers"])
    assert any(lc["is_duplicate_artefact"] for lc in before["lost_customers"])
    # before merge each company's record only sees its own product family
    assert after["cross_sell_pct"] > before["cross_sell_pct"]


def test_merge_impact_validates_and_adds_up():
    m = MergeImpact.model_validate(merge_impact(FIX))
    assert m.customers_after < m.customers_before
    assert m.lost_that_were_duplicates <= m.lost_before
    assert sum(c.lost_before for c in m.by_country) == m.lost_before
    assert sum(c.lost_after for c in m.by_country) == m.lost_after
    assert sum(c.lost_that_were_duplicates for c in m.by_country) == m.lost_that_were_duplicates
    assert m.nrr_after_pct > m.nrr_before_pct
    assert {c.country for c in m.by_country} == {"SG", "MY", "ID", "VN", "TH"}


def test_fast_after_first_load():
    regional_view(FIX, "before")
    t = time.perf_counter()
    for view in ("before", "after"):
        regional_view(FIX, view)
        regional_view(FIX, view, "TH")
    merge_impact(FIX)
    assert (time.perf_counter() - t) / 5 < 0.5


def test_returned_dicts_are_independent():
    a = regional_view(FIX, "after")
    a["bridge"][0]["value_usd"] = -1
    assert regional_view(FIX, "after")["bridge"][0]["value_usd"] != -1


def test_rejects_bad_inputs():
    with pytest.raises(ValueError):
        regional_view(FIX, "sideways")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        regional_view(FIX, "after", "XX")
