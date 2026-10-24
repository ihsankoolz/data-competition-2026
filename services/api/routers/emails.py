"""Messy inbox (M2). Owner: backend-engineer (wiring); ds.interpreter does the reading."""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ds.interpreter.api import interpret_email
from ds.interpreter.bank import strip_bank_details
from ds.interpreter.schemas import Interpretation
from services.api.db import models as m
from services.api.db.session import session_scope
from services.api.deps import CurrentUser
from services.api.schemas import EmailDetail, EmailSummary, InterpretStep

router = APIRouter(tags=["emails"])


def _snippet(body: str) -> str:
    safe, _ = strip_bank_details(body)  # a snippet never shows bank details, whoever asks
    flat = " ".join(safe.split())
    return flat if len(flat) <= 160 else flat[:159] + "…"


def _summary(e: m.Email) -> EmailSummary:
    return EmailSummary(
        email_id=e.email_id,
        received_at=e.received_at,
        from_name=e.from_name,
        from_address=e.from_address,
        subject=e.subject,
        snippet=_snippet(e.body),
        has_attachments=bool(e.attachments),
    )


@router.get("/emails", response_model=list[EmailSummary], operation_id="listEmails")
def list_emails(actor: CurrentUser) -> list[EmailSummary]:
    with session_scope() as session:
        rows = session.scalars(
            select(m.Email).order_by(m.Email.received_at.desc(), m.Email.email_id)
        ).all()
        return [_summary(e) for e in rows]


@router.get("/emails/{email_id}", response_model=EmailDetail, operation_id="getEmail")
def get_email(email_id: str, actor: CurrentUser) -> EmailDetail:
    with session_scope() as session:
        e = session.get(m.Email, email_id)
        if e is None:
            raise HTTPException(404, f"There is no email {email_id}.")
        body = e.body if actor.is_finance else strip_bank_details(e.body)[0]
        return EmailDetail(
            **_summary(e).model_dump(),
            to_address=e.to_address,
            body=body,
            attachments=list(e.attachments or []),
            thread_id=e.thread_id,
        )


@router.post(
    "/emails/{email_id}/interpret", response_model=Interpretation, operation_id="interpretEmail"
)
def interpret(email_id: str, actor: CurrentUser) -> Interpretation:
    """Classify and extract (ds.interpreter.api.interpret_email). Works offline in replay mode."""
    with session_scope() as session:
        e = session.get(m.Email, email_id)
        if e is None:
            raise HTTPException(404, f"There is no email {email_id}.")
        subject, body, sender = e.subject, e.body, e.from_address
    return interpret_email(email_id, subject, body, sender)


@router.post(
    "/emails/{email_id}/interpret/stream",
    operation_id="streamInterpretEmail",
    response_class=StreamingResponse,
    # `model` puts the step types into the OpenAPI components, so the web client gets them typed.
    # The body is really text/event-stream: `event: step`, `data:` one InterpretStep as JSON.
    responses={
        200: {
            "model": InterpretStep,
            "description": "Server-sent events, one InterpretStep per `event: step` (D-023). "
            "Replays the same Interpretation POST /emails/{id}/interpret returns.",
        }
    },
)
def interpret_stream(
    email_id: str,
    actor: CurrentUser,
    step_ms: int | None = Query(
        default=None,
        ge=0,
        le=500,
        description="Pause between steps. Default: about 1.5 s for the whole trace. "
        "0 = all at once (reduced motion, tests)",
    ),
):
    """Live AI trace (Stretch S1, D-023). Contract stub: backend-engineer implements."""
    raise HTTPException(501, "The live AI trace is not built yet.")
