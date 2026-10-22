"""Freeze the demo dataset: `python -m ds.generator.fixtures` (D-015 fixtures contract).

Generates `seasonal_trend` with seed 42 into a temporary folder and copies it to
`data/fixtures/seasonal_trend/`, mirroring the data-spec §10 layout exactly. The target folder
is cleared first (only that folder). `data/fixtures/llm_cache/` is created with a `.gitkeep`
and its recorded cache files are never touched. Deterministic and idempotent.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from .core import generate

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "data" / "fixtures"


def freeze(out: Path | str = DEFAULT_OUT, scenario: str = "seasonal_trend", seed: int = 42) -> Path:
    out = Path(out)
    target = out / scenario
    with tempfile.TemporaryDirectory() as tmp:
        src = generate(scenario, seed, tmp)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(src, target)
    cache = out / "llm_cache"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / ".gitkeep").touch()
    return target


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ds.generator.fixtures", description=__doc__)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args(argv)
    target = freeze(a.out)
    size = sum(p.stat().st_size for p in target.rglob("*") if p.is_file())
    print(f"ds.generator.fixtures: wrote {target} ({size / 1e6:.1f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
