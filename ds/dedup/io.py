"""Load the raw master (bp_records.csv + vendors.csv) into BPRecords. Never reads ground truth."""

from __future__ import annotations

import csv
from pathlib import Path

from .schemas import BPRecord

_FIELDS = set(BPRecord.model_fields)


def _read(path: Path) -> list[BPRecord]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for row in rows:
        # allow-list: bank columns in vendors.csv never enter the duplicate check
        clean = {k: (v if v != "" else None) for k, v in row.items() if k in _FIELDS}
        out.append(BPRecord.model_validate(clean))
    return out


def load_master(folder: Path | str, include_vendors: bool = True) -> list[BPRecord]:
    """Records the app can see: customers (bp_records.csv) and, optionally, vendors."""
    folder = Path(folder)
    recs = _read(folder / "bp_records.csv")
    if include_vendors:
        recs += _read(folder / "vendors.csv")
    return recs
