"""Regional view (M8), forecast backtest (M9) and ops impact (M10). Read-only; numbers come from
`ds.analytics` / `ds.forecasting` over the frozen fixtures and precomputed results (D-018).

Every result is validated with its Pydantic model. If a number has not been computed yet (the
ds function is not written, or its precomputed file is missing) the answer is 503 with a plain
sentence, never a 500.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select

from ds.analytics import cycle_time, regional
from ds.forecasting import backtest
from services.api.db import models as m
from services.api.db.session import REPO_ROOT, session_scope
from services.api.schemas import (
    CountryCode,
    ForecastBacktest,
    ForecastSummary,
    MergeImpact,
    MergeView,
    OpsImpact,
    RegionalView,
    Scenario,
)

router = APIRouter(tags=["analytics"])

# The one place the analytics inputs are located. Override with env vars if the data moves.
FIXTURE_DIR = REPO_ROOT / "data" / "fixtures" / "seasonal_trend"
FORECAST_DIR = REPO_ROOT / "data" / "fixtures" / "derived" / "forecast"


def data_dir() -> Path:
    """Frozen demo dataset (CSV fixtures) for the regional view and ops impact."""
    return Path(os.environ.get("ANALYTICS_DATA_DIR") or FIXTURE_DIR)


def forecast_dir() -> Path:
    """Precomputed backtest results (written by `make eval`)."""
    return Path(os.environ.get("ANALYTICS_FORECAST_DIR") or FORECAST_DIR)


T = TypeVar("T", bound=BaseModel)

log = logging.getLogger(__name__)
NOT_READY = "These numbers are not ready yet. Ask the team to refresh the results."
UNREADABLE = "These numbers could not be read. Ask the team to refresh the results."


def _serve(area: str, model: type[T], compute: Callable[[], dict[str, Any]]) -> T:
    """Run one ds function and validate its dict. Not computed yet = 503 with a plain sentence.
    Only "not written" and "file missing" count as not ready; any other error is a bug and
    must not look like missing data."""
    try:
        return model.model_validate(compute())
    except (NotImplementedError, FileNotFoundError) as exc:
        log.warning(
            "%s results not ready (%s). Refresh them with: make eval", area, type(exc).__name__
        )
        raise HTTPException(503, NOT_READY) from None
    except ValidationError:
        log.error("%s results do not match the API model. Refresh them with: make eval", area)
        raise HTTPException(503, UNREADABLE) from None


@router.get("/analytics/regional", response_model=RegionalView, operation_id="getRegionalView")
def regional_view(
    view: Annotated[
        MergeView, Query(description="before = raw SAP records, after = golden IDs")
    ] = "after",
    country: CountryCode | None = None,
) -> RegionalView:
    return _serve(
        "regional", RegionalView, lambda: regional.regional_view(data_dir(), view, country)
    )


@router.get("/analytics/merge-impact", response_model=MergeImpact, operation_id="getMergeImpact")
def merge_impact() -> MergeImpact:
    return _serve("regional", MergeImpact, lambda: regional.merge_impact(data_dir()))


@router.get("/analytics/forecast", response_model=ForecastSummary, operation_id="getForecast")
def forecast_summary() -> ForecastSummary:
    return _serve("forecast", ForecastSummary, lambda: backtest.forecast_summary(forecast_dir()))


@router.get(
    "/analytics/forecast/{scenario}",
    response_model=ForecastBacktest,
    operation_id="getForecastRun",
)
def forecast_run(
    scenario: Scenario, data: Annotated[str, Query(pattern="^(clean|dirty)$")] = "clean"
) -> ForecastBacktest:
    return _serve(
        "forecast",
        ForecastBacktest,
        lambda: backtest.load_backtest(forecast_dir(), scenario, data),  # type: ignore[arg-type]
    )


def duplicates_prevented() -> int:
    """Requests a human linked to an existing record instead of creating a duplicate."""
    with session_scope() as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(m.Request)
                .where(m.Request.state == m.RequestState.LINKED_TO_EXISTING)
            )
            or 0
        )


@router.get("/analytics/ops-impact", response_model=OpsImpact, operation_id="getOpsImpact")
def ops_impact() -> OpsImpact:
    prevented = duplicates_prevented()
    return _serve(
        "ops", OpsImpact, lambda: cycle_time.ops_impact(data_dir(), duplicates_prevented=prevented)
    )
