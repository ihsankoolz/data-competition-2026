"""Golden IDs for the "after merge" view, from our own duplicate check (D-005), not ground truth.

Records linked at the Likely level (score >= 0.92 or same tax ID, C/V and cross-country rules
respected) are joined into clusters; each cluster gets one golden id. Precomputed once and cached
under data/fixtures/derived/ so the API stays fast and offline.

How the links are made (D-018 #5):
- every customer record in bp_records.csv is run through `ds.dedup.score_candidates`, which only
  scores records of the same CardType (rule 2: a vendor twin is never a candidate) and the same
  country (rule 3: a group member in another country is never a candidate);
- a pair is linked when the check would say "Likely" (same valid tax ID, or score >= the
  `likely` threshold in ds/dedup/config.yaml);
- clusters are the connected components of those links. The cluster id is `G-<lowest CardCode>`.

No LLM is called (rules only), so the result is deterministic and offline. Ground truth
(`ground_truth/bp_golden_map.csv`) is never read here; the evaluation scores these clusters.
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE_PATH = ROOT / "data" / "fixtures" / "derived" / "golden_clusters.csv"

_memo: dict[str, dict[str, str]] = {}


def _customer_codes(data_dir: Path) -> list[str]:
    with open(data_dir / "bp_records.csv", encoding="utf-8", newline="") as fh:
        return [r["CardCode"] for r in csv.DictReader(fh) if r.get("CardType") == "cCustomer"]


def likely_links(data_dir: Path) -> set[tuple[str, str]]:
    """Every customer record pair our duplicate check calls 'Likely' (sorted code pairs)."""
    from ds.dedup import BPQuery, MasterIndex, load_master, score_candidates

    master = load_master(data_dir)
    index = MasterIndex(master)
    likely = index.config.thresholds.likely
    links: set[tuple[str, str]] = set()
    for r in master:
        if r.CardType != "cCustomer":
            continue
        _, scored = score_candidates(index, BPQuery.model_validate(r.model_dump()))
        for c in scored:
            if c.CardType == "cCustomer" and (c.tax_id_match or c.score >= likely):
                a, b = sorted((r.CardCode, c.CardCode))
                links.add((a, b))
    return links


def compute_clusters(data_dir: Path) -> dict[str, str]:
    """Connected components of the Likely links. Singletons get their own cluster."""
    codes = _customer_codes(data_dir)
    parent = {c: c for c in codes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in sorted(likely_links(data_dir)):
        ra, rb = find(a), find(b)
        if ra != rb:
            lo, hi = sorted((ra, rb))
            parent[hi] = lo  # root = lowest CardCode, so ids are stable
    return {c: f"G-{find(c)}" for c in sorted(codes)}


def _read_cache(path: Path) -> dict[str, str]:
    with open(path, encoding="utf-8", newline="") as fh:
        return {r["CardCode"]: r["golden_id"] for r in csv.DictReader(fh)}


def write_cache(clusters: dict[str, str], path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["CardCode", "golden_id"])
        for code in sorted(clusters):
            w.writerow([code, clusters[code]])


def golden_clusters(data_dir: Path, cache_path: Path | None = CACHE_PATH) -> dict[str, str]:
    """CardCode -> golden id (our clusters) for every customer record in bp_records.csv.

    Read from `cache_path` when it covers exactly this folder's customer records (all three
    scenarios share the same master files); otherwise computed (a few seconds). The cache is
    written only when it is missing. Pass `cache_path=None` to always compute.
    """
    data_dir = Path(data_dir)
    key = str(data_dir.resolve())
    if key in _memo:
        return _memo[key]
    codes = set(_customer_codes(data_dir))
    clusters: dict[str, str] | None = None
    if cache_path is not None and cache_path.exists():
        cached = _read_cache(cache_path)
        if set(cached) == codes:
            clusters = cached
    if clusters is None:
        clusters = compute_clusters(data_dir)
        if cache_path is not None and not cache_path.exists():
            write_cache(clusters, cache_path)
    _memo[key] = clusters
    return clusters


if __name__ == "__main__":
    fixtures = ROOT / "data" / "fixtures" / "seasonal_trend"
    cl = compute_clusters(fixtures)
    write_cache(cl)
    print(f"wrote {CACHE_PATH} ({len(cl)} records, {len(set(cl.values()))} clusters)")
