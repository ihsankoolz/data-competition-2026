"""History check: is the audit log still exactly as it was written? (PRD M6, S3)"""

from fastapi import APIRouter

from services.api.audit import plain_message, verify_chain
from services.api.db.session import session_scope
from services.api.deps import CurrentUser
from services.api.schemas import AuditVerifyResult

router = APIRouter(tags=["audit"])


@router.get("/audit/verify", response_model=AuditVerifyResult, operation_id="verifyAudit")
def verify_audit(actor: CurrentUser) -> AuditVerifyResult:
    """Walks the whole history log from the first entry and checks that every entry still
    matches the one before it. Open to every persona; it changes nothing."""
    with session_scope() as session:
        result = verify_chain(session)
    return AuditVerifyResult(
        ok=result.ok,
        checked=result.checked,
        first_broken_id=result.first_broken_id,
        message=plain_message(result),
        reason=result.reason,
    )
