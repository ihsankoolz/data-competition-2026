"""Entry point: python -m ds.generator --scenario seasonal_trend --seed 42 --out data/generated/"""

from __future__ import annotations

import argparse
import sys
import time

from .core import generate


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ds.generator", description=__doc__)
    ap.add_argument("--scenario", default="seasonal_trend")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/generated/")
    a = ap.parse_args(argv)
    t0 = time.perf_counter()
    root = generate(a.scenario, a.seed, a.out)
    print(f"ds.generator: wrote {root} in {time.perf_counter() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
