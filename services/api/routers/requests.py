"""MDM requests (M3, M5). Owner: backend-engineer."""

from typing import Literal

from fastapi import APIRouter

from services.api.routers._stub import not_built
from services.api.schemas import (
    AuditEntry,
    DedupDecisionIn,
    RequestCreate,
    RequestDetail,
    RequestStateName,
    RequestSummary,
    RequestUpdate,
)

router = APIRouter(tags=["requests"])


@router.get("/requests", response_model=list[RequestSummary], operation_id="listRequests")
def list_requests(
    scope: Literal["mine", "all"] = "mine", state: RequestStateName | None = None
) -> list[RequestSummary]:
    raise not_built("request list")


@router.post(
    "/requests", response_model=RequestDetail, status_code=201, operation_id="createRequest"
)
def create_request(body: RequestCreate) -> RequestDetail:
    """Creates a DRAFT for the acting user."""
    raise not_built("create request")


@router.post(
    "/requests/from-email/{email_id}",
    response_model=RequestDetail,
    status_code=201,
    operation_id="createRequestFromEmail",
)
def create_request_from_email(email_id: str) -> RequestDetail:
    """Interprets the email and creates a pre-filled DRAFT with a source quote per field.
    Email text never sets approvers, bank details or credit terms (rule 7)."""
    raise not_built("create request from email")


@router.get("/requests/{req_id}", response_model=RequestDetail, operation_id="getRequest")
def get_request(req_id: str) -> RequestDetail:
    raise not_built("request detail")


@router.patch("/requests/{req_id}", response_model=RequestDetail, operation_id="updateRequest")
def update_request(req_id: str, body: RequestUpdate) -> RequestDetail:
    raise not_built("update request")


@router.post(
    "/requests/{req_id}/dedup-decision",
    response_model=RequestDetail,
    operation_id="decideDuplicate",
)
def decide_duplicate(req_id: str, body: DedupDecisionIn) -> RequestDetail:
    """Link to the existing record (-> LINKED_TO_EXISTING, no approvals) or confirm it is not
    a duplicate with a reason. Always a human decision; always audited."""
    raise not_built("duplicate decision")


@router.post(
    "/requests/{req_id}/submit", response_model=RequestDetail, operation_id="submitRequest"
)
def submit_request(req_id: str) -> RequestDetail:
    """Re-runs the duplicate check. 409 if a Likely duplicate has no human decision; 422 if
    required fields are missing. Otherwise routes approvals (config/routing_rules.yaml)."""
    raise not_built("submit request")


@router.post(
    "/requests/{req_id}/publish", response_model=RequestDetail, operation_id="publishRequest"
)
def publish_request(req_id: str) -> RequestDetail:
    """MDM analyst only, after every approval. Publishes to the SAP B1 mock (D-004)."""
    raise not_built("publish request")


@router.get(
    "/requests/{req_id}/audit", response_model=list[AuditEntry], operation_id="getRequestAudit"
)
def get_request_audit(req_id: str) -> list[AuditEntry]:
    raise not_built("request audit trail")
