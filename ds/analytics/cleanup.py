"""Clean-up queue: the groups behind the "after merge" view, for a person to confirm one by one.

The regional view's "after merge" joins the customer records our duplicate check calls Likely
(`ds.analytics.golden`). This module lists those same links, with the evidence the check gives,
grouped exactly like the golden clusters (same links, same connected components, same
`G-<lowest CardCode>` ids). Nothing here merges anything: Priya confirms each group in the app,
and her decisions never change the regional numbers.

Precomputed once into `data/fixtures/derived/cleanup_pairs.json` (rules only, no LLM, so it is
deterministic and offline), like `golden_clusters.csv`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ds.analytics.golden import ROOT, LikelyPair, PairReason, _customer_codes, likely_pairs

CACHE_PATH = ROOT / "data" / "fixtures" / "derived" / "cleanup_pairs.json"
CACHE_VERSION = 1

_memo: dict[str, QueueData] = {}


@dataclass(frozen=True)
class QueueData:
    """The cached queue: every Likely pair plus the cross-border group of each record in one."""

    customer_codes_sha256: str  # which master the pairs were computed from
    pairs: list[LikelyPair]
    groups: dict[str, str]  # CardCode -> group name (domain rule 3), only for records that have one


@dataclass(frozen=True)
class Cluster:
    """One proposed group of records, ordered most certain first by `clusters()`."""

    cluster_id: str  # G-<lowest CardCode>, the same id as the golden cluster
    codes: list[str]
    pairs: list[LikelyPair]

    @property
    def all_tax_id_match(self) -> bool:
        return all(p.tax_id_match for p in self.pairs)

    @property
    def weakest_score(self) -> float:
        return min(p.score for p in self.pairs)


def _codes_sha(codes: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(codes)).encode("utf-8")).hexdigest()


def compute(data_dir: Path) -> QueueData:
    from ds.dedup import MasterIndex, load_master

    data_dir = Path(data_dir)
    index = MasterIndex(load_master(data_dir))
    pairs = likely_pairs(data_dir, index)
    groups: dict[str, str] = {}
    for code in sorted({c for p in pairs for c in (p.a, p.b)}):
        gid = index.by_code[code].group_id
        if gid:
            groups[code] = index.group_name(gid) or gid
    return QueueData(_codes_sha(_customer_codes(data_dir)), pairs, groups)


def to_json(data: QueueData) -> dict[str, Any]:
    return {
        "version": CACHE_VERSION,
        "customer_codes_sha256": data.customer_codes_sha256,
        "groups": data.groups,
        "pairs": [asdict(p) for p in data.pairs],
    }


def from_json(obj: dict[str, Any]) -> QueueData:
    pairs = [
        LikelyPair(
            a=p["a"],
            b=p["b"],
            query=p["query"],
            score=float(p["score"]),
            tax_id_match=bool(p["tax_id_match"]),
            reasons=tuple(PairReason(r["text"], bool(r["against"])) for r in p["reasons"]),
        )
        for p in obj["pairs"]
    ]
    return QueueData(obj["customer_codes_sha256"], pairs, dict(obj["groups"]))


def write_cache(data: QueueData, path: Path = CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(to_json(data), ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read_cache(path: Path = CACHE_PATH) -> QueueData:
    with open(path, encoding="utf-8") as fh:
        return from_json(json.load(fh))


def queue_data(data_dir: Path, cache_path: Path | None = CACHE_PATH) -> QueueData:
    """The Likely pairs for this folder's customer records, from the cache when it matches.

    The cache matches when it was computed from exactly these customer CardCodes (all three
    scenarios share the same master). Otherwise the pairs are computed (a few seconds); the cache
    is written only when it is missing. Pass `cache_path=None` to always compute.
    """
    data_dir = Path(data_dir)
    key = str(data_dir.resolve())
    if key in _memo:
        return _memo[key]
    data: QueueData | None = None
    if cache_path is not None and cache_path.exists():
        cached = read_cache(cache_path)
        if cached.customer_codes_sha256 == _codes_sha(_customer_codes(data_dir)):
            data = cached
    if data is None:
        data = compute(data_dir)
        if cache_path is not None and not cache_path.exists():
            write_cache(data, cache_path)
    _memo[key] = data
    return data


def clusters(pairs: list[LikelyPair]) -> list[Cluster]:
    """Connected components of the pairs, most certain first.

    A group is as certain as its weakest link: groups where every link has the same tax ID come
    first, then by the weakest link's score (highest first), then by id.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        ra, rb = find(p.a), find(p.b)
        if ra != rb:
            lo, hi = sorted((ra, rb))
            parent[hi] = lo  # root = lowest CardCode, as in golden.compute_clusters
    members: dict[str, list[str]] = {}
    for code in sorted(parent):
        members.setdefault(find(code), []).append(code)
    by_root: dict[str, list[LikelyPair]] = {}
    for p in pairs:
        by_root.setdefault(find(p.a), []).append(p)
    out = [Cluster(f"G-{root}", codes, by_root[root]) for root, codes in members.items()]
    out.sort(key=lambda c: (not c.all_tax_id_match, -c.weakest_score, c.cluster_id))
    return out


if __name__ == "__main__":
    fixtures = ROOT / "data" / "fixtures" / "seasonal_trend"
    q = compute(fixtures)
    write_cache(q)
    print(f"wrote {CACHE_PATH} ({len(q.pairs)} pairs, {len(clusters(q.pairs))} groups)")
