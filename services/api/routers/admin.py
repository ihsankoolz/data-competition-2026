"""Demo administration (D-016). Owner: backend-engineer."""

from fastapi import APIRouter

from services.api.routers._stub import not_built
from services.api.schemas import ResetResult

router = APIRouter(tags=["admin"])


@router.post("/admin/reset-demo", response_model=ResetResult, operation_id="resetDemo")
def reset_demo() -> ResetResult:
    """Restore the seeded demo state in under 10 s without stopping the API: database,
    simulated clock, audit chain and the SAP mock. `make reset-demo` uses the same code path."""
    raise not_built("in-app demo reset")
