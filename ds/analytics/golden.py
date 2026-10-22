"""Golden IDs for the "after merge" view, from our own duplicate check (D-005), not ground truth.

Records linked at the Likely level (score >= 0.92 or same tax ID, C/V and cross-country rules
respected) are joined into clusters; each cluster gets one golden id. Precomputed once and cached
under data/fixtures/derived/ so the API stays fast and offline.
"""

from __future__ import annotations

from pathlib import Path


def golden_clusters(data_dir: Path) -> dict[str, str]:
    """CardCode -> golden id (our clusters) for every customer record in bp_records.csv."""
    raise NotImplementedError
