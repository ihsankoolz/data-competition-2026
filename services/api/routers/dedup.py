"""Live duplicate check (M4, D-005). Owner: backend-engineer."""

from fastapi import APIRouter, HTTPException

from ds.dedup.schemas import DedupResult
from services.api import dedup_service
from services.api.audit import AuditAction, append_audit
from services.api.db import models as m
from services.api.db.session import session_scope
from services.api.deps import CurrentUser
from services.api.schemas import DedupCheckRequest, ItemDedupCheckRequest, ItemDedupResult

router = APIRouter(tags=["dedup"])


@router.post("/dedup/check", response_model=DedupResult, operation_id="checkDuplicates")
def check_duplicates(body: DedupCheckRequest, actor: CurrentUser) -> DedupResult:
    """Called while the requester types (debounced) and again on submit. Read-only, fast."""
    result = dedup_service.run_check(body.domain, body.entity, body.fields, use_judge=True)
    if body.request_id:
        with session_scope(write=True) as session:
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


@router.post(
    "/dedup/check-item", response_model=ItemDedupResult, operation_id="checkItemDuplicates"
)
def check_item_duplicates(body: ItemDedupCheckRequest, actor: CurrentUser) -> ItemDedupResult:
    """Session 13: is this new item already in the catalogue? Rules only (no AI, rule 6):
    normalised name, manufacturer catalogue number (synthetic in the demo) and registration
    number per country. Read-only; logged when `request_id` is set."""
    if not body.request_id:
        return dedup_service.run_item_check(body.fields)
    with session_scope(write=True) as session:
        req = session.get(m.Request, body.request_id)
        if req is None:
            raise HTTPException(404, f"There is no request {body.request_id}.")
        own = [req.published_key] if req.domain == m.RequestDomain.item and req.published_key else []
        result = dedup_service.item_check(session, body.fields, exclude=own)
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
                "top_candidate": top.ItemCode if top else None,
                "top_score": top.score if top else None,
                "summary": f"Item duplicate check run by {actor.name}: {result.message}",
            },
        )
    return result
