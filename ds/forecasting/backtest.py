"""Forecast backtest (PRD M9, D-008). Run offline, results precomputed to JSON; the API only reads.

`python -m ds.forecasting.backtest` regenerates
data/fixtures/derived/forecast/<scenario>_<data>.json for all 3 scenarios x clean/dirty.
Origins, horizon, metrics and baseline are fixed (D-008).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

Data = Literal["clean", "dirty"]


def load_backtest(derived_dir: Path, scenario: str, data: Data = "clean") -> dict[str, Any]:
    """-> ForecastBacktest, read from the precomputed JSON."""
    raise NotImplementedError


def forecast_summary(derived_dir: Path) -> dict[str, Any]:
    """-> ForecastSummary (every scenario x clean/dirty run, plus captions)."""
    raise NotImplementedError
