"""Live duplicate check (M4, D-005). Owner: backend-engineer."""

from fastapi import APIRouter

from ds.dedup.schemas import DedupResult
from services.api.routers._stub import not_built
from services.api.schemas import DedupCheckRequest

router = APIRouter(tags=["dedup"])


@router.post("/dedup/check", response_model=DedupResult, operation_id="checkDuplicates")
def check_duplicates(body: DedupCheckRequest) -> DedupResult:
    """Called while the requester types (debounced) and again on submit. Read-only, fast."""
    raise not_built("duplicate check")
