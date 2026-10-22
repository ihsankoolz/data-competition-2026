"""Live duplicate check (M4, D-005). Owner: backend-engineer."""

from fastapi import APIRouter, HTTPException

from ds.dedup.schemas import DedupResult
from services.api import dedup_service
from services.api.audit import AuditAction, append_audit
from services.api.db import models as m
from services.api.db.session import session_scope
from services.api.deps import CurrentUser
from services.api.schemas import DedupCheckRequest

router = APIRouter(tags=["dedup"])


@router.post("/dedup/check", response_model=DedupResult, operation_id="checkDuplicates")
def check_duplicates(body: DedupCheckRequest, actor: CurrentUser) -> DedupResult:
    """Called while the requester types (debounced) and again on submit. Read-only, fast."""
    result = dedup_service.run_check(body.domain, body.entity, body.fields)
    if body.request_id:
        with session_scope() as session:
            if session.get(m.Request, body.request_id) is None:
                raise HTTPException(404, f"There is no request {body.request_id}.")
            top = result.candidates[0] if result.candidates else None
            append_audit(
                session,
                actor=actor.user_id,
                action=AuditAction.dedup_check,
                entity_type="request",
                entity_id=body.request_id,
                request_id=body.request_id,
                payload={
                    "verdict": result.verdict,
                    "top_candidate": top.CardCode if top else None,
                    "top_score": top.score if top else None,
                    "summary": f"Duplicate check run by {actor.name}: {result.message}",
                },
            )
    return result
