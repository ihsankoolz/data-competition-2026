"""Regional business view (PRD M8, D-009). Pure functions over the fixture CSVs.

Contract (session 4): each function returns a plain dict shaped exactly like the Pydantic model
named in its docstring (`services/api/schemas.py`); the API validates it. Confirmed POs only feed
revenue (rule 9). "after" = our own dedup clusters (`ds.analytics.golden`), never ground truth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

View = Literal["before", "after"]


def regional_view(data_dir: Path, view: View, country: str | None = None) -> dict[str, Any]:
    """-> RegionalView. `data_dir` = data/fixtures/seasonal_trend."""
    raise NotImplementedError


def merge_impact(data_dir: Path) -> dict[str, Any]:
    """-> MergeImpact (before vs after merge: customer counts, lost alerts, NRR, by country)."""
    raise NotImplementedError
