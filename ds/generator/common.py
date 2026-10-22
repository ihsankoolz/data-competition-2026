"""Shared helpers: seeded RNG streams, month arithmetic, deterministic CSV writing."""

from __future__ import annotations

import csv
import zlib
from datetime import date, timedelta
from pathlib import Path

import numpy as np

WINDOW_START = date(2023, 10, 1)
WINDOW_END = date(2026, 9, 30)


def stream(seed: int, name: str) -> np.random.Generator:
    """Independent RNG per named stream, so adding a new stream never shifts existing output."""
    return np.random.default_rng([seed, zlib.crc32(name.encode("utf-8"))])


def month_date(idx: int, start: date = WINDOW_START) -> date:
    """Month index -> first day of month (index 0 = Oct 2023; negative = before the window)."""
    m = start.year * 12 + (start.month - 1) + idx
    return date(m // 12, m % 12 + 1, 1)


def month_str(idx: int | None) -> str:
    return "" if idx is None else month_date(idx).isoformat()


def add_days(d: date, n: int) -> date:
    return d + timedelta(days=int(n))


def pick(rng: np.random.Generator, items: list):
    return items[int(rng.integers(len(items)))]


def wpick(rng: np.random.Generator, weights: dict[str, float]) -> str:
    keys = list(weights)
    w = np.array([weights[k] for k in keys], dtype=float)
    return keys[int(rng.choice(len(keys), p=w / w.sum()))]


def fmt_money(x: float) -> str:
    return f"{x:.2f}"


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    """UTF-8 (no BOM), '\\n' line endings, fixed column order, minimal quoting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        for r in rows:
            w.writerow(["" if v is None else _cell(v) for v in r])


def _cell(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)
