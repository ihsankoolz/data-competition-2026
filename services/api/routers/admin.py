"""Demo administration (D-016). Owner: backend-engineer."""

from fastapi import APIRouter, HTTPException

from services.api import reset
from services.api.crypto import EncryptionKeyError
from services.api.schemas import ResetResult

router = APIRouter(tags=["admin"])


@router.post("/admin/reset-demo", response_model=ResetResult, operation_id="resetDemo")
def reset_demo() -> ResetResult:
    """Restore the seeded demo state in under 10 s without stopping the API: database,
    simulated clock, audit chain and the SAP mock. `make reset-demo` uses the same code path."""
    try:
        return reset.reset_demo()
    except (reset.SeedError, EncryptionKeyError) as exc:
        raise HTTPException(status_code=500, detail=f"The demo reset did not run: {exc}") from None
