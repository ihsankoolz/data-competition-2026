"""Regional view (M8), forecast backtest (M9) and ops impact (M10). Read-only; numbers come from
`ds.analytics` / `ds.forecasting` over the frozen fixtures and precomputed results (D-018)."""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

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

NOT_YET = "This view is being built."


@router.get("/analytics/regional", response_model=RegionalView, operation_id="getRegionalView")
def regional_view(
    view: Annotated[
        MergeView, Query(description="before = raw SAP records, after = golden IDs")
    ] = "after",
    country: CountryCode | None = None,
) -> RegionalView:
    raise HTTPException(501, NOT_YET)


@router.get("/analytics/merge-impact", response_model=MergeImpact, operation_id="getMergeImpact")
def merge_impact() -> MergeImpact:
    raise HTTPException(501, NOT_YET)


@router.get("/analytics/forecast", response_model=ForecastSummary, operation_id="getForecast")
def forecast_summary() -> ForecastSummary:
    raise HTTPException(501, NOT_YET)


@router.get(
    "/analytics/forecast/{scenario}",
    response_model=ForecastBacktest,
    operation_id="getForecastRun",
)
def forecast_run(
    scenario: Scenario, data: Annotated[str, Query(pattern="^(clean|dirty)$")] = "clean"
) -> ForecastBacktest:
    raise HTTPException(501, NOT_YET)


@router.get("/analytics/ops-impact", response_model=OpsImpact, operation_id="getOpsImpact")
def ops_impact() -> OpsImpact:
    raise HTTPException(501, NOT_YET)
