"""Messy inbox (M2). Owner: backend-engineer (wiring); ds.interpreter does the reading."""

from fastapi import APIRouter

from ds.interpreter.schemas import Interpretation
from services.api.routers._stub import not_built
from services.api.schemas import EmailDetail, EmailSummary

router = APIRouter(tags=["emails"])


@router.get("/emails", response_model=list[EmailSummary], operation_id="listEmails")
def list_emails() -> list[EmailSummary]:
    raise not_built("email list")


@router.get("/emails/{email_id}", response_model=EmailDetail, operation_id="getEmail")
def get_email(email_id: str) -> EmailDetail:
    raise not_built("email detail")


@router.post(
    "/emails/{email_id}/interpret", response_model=Interpretation, operation_id="interpretEmail"
)
def interpret(email_id: str) -> Interpretation:
    """Classify and extract (ds.interpreter.api.interpret_email). Works offline in replay mode."""
    raise not_built("email interpreter")
