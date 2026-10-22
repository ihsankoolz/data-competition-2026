"""Sanity checks for the synthetic data generator (docs/data-spec.md §11, items for §1-5)."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from anyascii import anyascii

from ds.generator.core import generate, load_params

SCENARIO, SEED = "seasonal_trend", 42
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def runs(tmp_path_factory) -> tuple[Path, Path]:
    """Run A in-process; run B through the CLI in a fresh process with another hash seed."""
    a = generate(SCENARIO, SEED, tmp_path_factory.mktemp("gen_a"))
    out_b = tmp_path_factory.mktemp("gen_b")
    env = {**os.environ, "PYTHONHASHSEED": "12345"}
    subprocess.run(
        [
            sys.executable,
            "-m",
            "ds.generator",
            "--scenario",
            SCENARIO,
            "--seed",
            str(SEED),
            "--out",
            str(out_b),
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
    )
    return a, out_b / SCENARIO


@pytest.fixture(scope="module")
def out(runs) -> Path:
    return runs[0]


def _csv(out: Path, name: str) -> pd.DataFrame:
    return pd.read_csv(out / name, dtype=str, keep_default_na=False)


@pytest.fixture(scope="module")
def bp(out) -> pd.DataFrame:
    return _csv(out, "bp_records.csv")


@pytest.fixture(scope="module")
def gmap(out) -> dict[str, str]:
    m = _csv(out, "ground_truth/bp_golden_map.csv")
    return dict(zip(m.CardCode, m.golden_id, strict=True))


def test_deterministic_byte_identical(runs):
    a, b = runs
    files_a = sorted(p.relative_to(a).as_posix() for p in a.rglob("*") if p.is_file())
    files_b = sorted(p.relative_to(b).as_posix() for p in b.rglob("*") if p.is_file())
    assert files_a == files_b
    for f in files_a:
        raw = (a / f).read_bytes()
        assert raw == (b / f).read_bytes(), f"{f} differs between runs"
        assert not raw.startswith(b"\xef\xbb\xbf") and b"\r\n" not in raw, f


def test_expected_files(out):
    for f in [
        "params.yaml",
        "customers_golden.csv",
        "bp_records.csv",
        "vendors.csv",
        "items.csv",
        "item_registrations.csv",
        "ground_truth/dup_pairs.csv",
        "ground_truth/hard_negatives.csv",
        "ground_truth/migrations.csv",
        "ground_truth/churn.csv",
        "ground_truth/bp_golden_map.csv",
        # v2 (data-spec §6-9)
        "users.csv",
        "orders.csv",
        "enquiries.csv",
        "dirty_demand.csv",
        "mdm_requests_history.csv",
        "emails.jsonl",
        "ground_truth/email_labels.jsonl",
    ]:
        assert (out / f).is_file(), f


# sha256 of the v1 (§1-5) master for seed 42 / seasonal_trend. The duplicate-check evaluation
# depends on these files: v2 tables must use new RNG streams and never shift them.
PINNED_SHA256 = {
    "bp_records.csv": "1965c844745d959d942e05990e93d1d51a1fb04f059d023241ca544635268b59",
    "ground_truth/bp_golden_map.csv": (
        "c1a98f4decbea576693f8123b539f7f73fbbc353c7dfbf882d70f2310cb50918"
    ),
}


def test_master_hashes_pinned(out):
    for f, digest in PINNED_SHA256.items():
        assert hashlib.sha256((out / f).read_bytes()).hexdigest() == digest, f


def within(x: float, target: float, tol: float = 0.10) -> bool:
    return abs(x - target) <= tol * target


def test_row_counts(out, bp):
    g = _csv(out, "customers_golden.csv")
    params = load_params(SCENARIO)
    for c, spec in params["countries"].items():
        assert within((g.country == c).sum(), spec["n_golden"]), c
    assert within(len(g), 350)
    assert within(len(bp), 560)
    assert within(len(_csv(out, "vendors.csv")), 60)
    assert len(_csv(out, "items.csv")) == 15
    assert within((g.start_month >= "2024-10-01").sum(), 0.12 * 350)
    assert within((g.churn_month != "").sum(), 0.10 * 350)
    assert within(len(_csv(out, "ground_truth/migrations.csv")), 0.06 * 350)
    d = _csv(out, "ground_truth/dup_pairs.csv")
    assert within(d.golden_id.nunique(), 0.20 * 350)


def test_dup_type_shares(out):
    d = _csv(out, "ground_truth/dup_pairs.csv")
    shares = load_params(SCENARIO)["duplicates"]["type_shares"]
    actual = d.dup_type.value_counts(normalize=True)
    assert set(actual.index) == set(shares)
    for t, s in shares.items():
        assert abs(actual.get(t, 0.0) - s) <= 0.05, (t, actual.get(t, 0.0), s)


def test_dup_pairs_are_same_customer(out, gmap):
    d = _csv(out, "ground_truth/dup_pairs.csv")
    for a, b, gid in zip(d.card_code_a, d.card_code_b, d.golden_id, strict=True):
        assert gmap[a] == gmap[b] == gid


def test_hard_negatives(out, gmap):
    h = _csv(out, "ground_truth/hard_negatives.csv")
    d = _csv(out, "ground_truth/dup_pairs.csv")
    pairs = {r: set() for r in h.not_dup_reason.unique()}
    for r, ga, gb in zip(h.not_dup_reason, h.golden_id_a, h.golden_id_b, strict=True):
        pairs[r].add(frozenset((ga, gb)))
    assert 9 <= len(pairs["customer_vendor_pair"]) <= 11
    assert 13 <= len(pairs["similar_name_different_site"]) <= 17
    assert len(pairs["same_group_other_country"]) >= 6
    # domain rules 2 and 3: never labelled as duplicates
    dup_set = {frozenset(p) for p in zip(d.card_code_a, d.card_code_b, strict=True)}
    neg_set = {frozenset(p) for p in zip(h.card_code_a, h.card_code_b, strict=True)}
    assert not dup_set & neg_set
    # group / site negatives are different customers; C/V pairs are customer vs supplier
    for a, b, r in zip(h.card_code_a, h.card_code_b, h.not_dup_reason, strict=True):
        if r == "customer_vendor_pair":
            assert a.startswith("C") and b.startswith("V")
        else:
            assert gmap[a] != gmap[b]


def test_no_exact_name_clash_across_customers(bp, gmap):
    owner: dict[str, str] = {}
    for code, name in zip(bp.CardCode, bp.CardName, strict=True):
        key = name.lower()
        assert owner.setdefault(key, gmap[code]) == gmap[code], name


def test_cho_ray_anchor(out, bp):
    rows = bp[bp.FederalTaxID == "0301234567"]
    assert len(rows) == 1
    r = rows.iloc[0]
    assert r.CardName == "Bệnh viện Chợ Rẫy"
    assert r.City == "Ho Chi Minh City" and r.U_Entity == "SPD" and r.Country == "VN"
    # DEMO-01: no QTG (or any other) record for Cho Ray, by name or MST
    names = bp.CardName.map(lambda s: anyascii(s).lower())
    assert (names.str.contains("cho ray")).sum() == 1
    vendors = _csv(out, "vendors.csv")
    assert "0301234567" not in set(vendors.FederalTaxID)
    assert not any("0301234567" in t for t in bp.FederalTaxID if t != "0301234567")


def _golden_of(bp, gmap, name) -> set[str]:
    codes = bp.loc[bp.CardName == name, "CardCode"]
    assert len(codes) >= 1, f"missing anchor record {name!r}"
    return {gmap[c] for c in codes}


def test_demo_anchors(out, bp, gmap):
    nuh = _golden_of(bp, gmap, "National University Hospital (S) Pte Ltd")
    assert _golden_of(bp, gmap, "NUH") == nuh
    rscm = _golden_of(bp, gmap, "RS Cipto Mangunkusumo")
    assert _golden_of(bp, gmap, "Rumah Sakit Cipto Mangunkusumo") == rscm
    assert _golden_of(bp, gmap, "RSCM") == rscm
    assert _golden_of(bp, gmap, "โรงพยาบาลศิริราช") == _golden_of(bp, gmap, "Siriraj Hospital")
    _golden_of(bp, gmap, "Hospital Kuala Lumpur")
    # BioMed: customer + supplier twin, same tax ID, labelled as a hard negative
    cust = bp[bp.CardName == "BioMed Lab Supplies Pte Ltd"]
    vend = _csv(out, "vendors.csv")
    vend = vend[vend.CardName == "BioMed Lab Supplies Pte Ltd"]
    assert len(cust) == 1 and len(vend) == 1
    assert cust.FederalTaxID.iloc[0] == vend.FederalTaxID.iloc[0]
    h = _csv(out, "ground_truth/hard_negatives.csv")
    hit = h[(h.card_code_a == cust.CardCode.iloc[0]) & (h.card_code_b == vend.CardCode.iloc[0])]
    assert list(hit.not_dup_reason) == ["customer_vendor_pair"]
    # Sentosa Healthcare Group: SG / MY / ID, separate legal entities
    groups = _csv(out, "ground_truth/groups.csv").set_index("group_name")
    assert groups.loc["Sentosa Healthcare Group", "countries"] == "SG MY ID"
    g = _csv(out, "customers_golden.csv")
    sentosa = g[g.group_id == groups.loc["Sentosa Healthcare Group", "group_id"]]
    assert sentosa.tax_id.nunique() == 3


def test_vietnam_product_a_migrations(out):
    m = _csv(out, "ground_truth/migrations.csv")
    assert ((m.country == "VN") & (m.product_family == "A")).sum() >= 3
    d = _csv(out, "ground_truth/dup_pairs.csv")
    mig_pairs = set(
        zip(
            d.card_code_a[d.is_migration == "true"],
            d.card_code_b[d.is_migration == "true"],
            strict=True,
        )
    )
    assert set(zip(m.old_card_code, m.new_card_code, strict=True)) == mig_pairs


def test_registrations_and_items(out):
    r = _csv(out, "item_registrations.csv")
    assert (r.status == "expired").sum() == 1
    items = _csv(out, "items.csv")
    assert {"A-DEN-NS1", "B-HEM-5P", "C-SVC-ANN"} <= set(items.ItemCode)
    assert items.groupby("product_family").size().to_dict() == {"A": 5, "B": 5, "C": 5}
    assert set(items.U_IVD) <= {"tYES", "tNO"}


def test_sap_columns(bp):
    assert not any("golden" in c.lower() for c in bp.columns)
    for c in ["CardCode", "CardName", "CardType", "FederalTaxID", "U_Entity"]:
        assert c in bp.columns
    assert bp.CardCode.str.fullmatch(r"C\d{5}").all() and bp.CardCode.is_unique
    assert (bp.CardType == "cCustomer").all()
    assert bp.CardName.str.len().max() <= 100
