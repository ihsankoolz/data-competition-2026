"""Messy inbox (M2). Owner: backend-engineer (wiring); ds.interpreter does the reading."""

import asyncio
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from ds.interpreter.api import interpret_email
from ds.interpreter.bank import strip_bank_details
from ds.interpreter.llm import llm_mode
from ds.interpreter.schemas import Interpretation
from services.api.db import models as m
from services.api.db.session import session_scope
from services.api.deps import CurrentUser
from services.api.schemas import (
    EmailDetail,
    EmailSummary,
    InterpretStep,
    TraceBankStripped,
    TraceCategory,
    TraceDone,
    TraceField,
    TraceInjection,
    TraceLine,
    TraceMissing,
    TraceStart,
)

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


def _interpret_email_by_id(email_id: str) -> Interpretation:
    """One code path for POST /interpret and the live trace. 404 if the email is unknown."""
    with session_scope() as session:
        e = session.get(m.Email, email_id)
        if e is None:
            raise HTTPException(404, f"There is no email {email_id}.")
        subject, body, sender = e.subject, e.body, e.from_address
    return interpret_email(email_id, subject, body, sender)


@router.post(
    "/emails/{email_id}/interpret", response_model=Interpretation, operation_id="interpretEmail"
)
def interpret(email_id: str, actor: CurrentUser) -> Interpretation:
    """Classify and extract (ds.interpreter.api.interpret_email). Works offline in replay mode."""
    return _interpret_email_by_id(email_id)


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
async def interpret_stream(
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
    """Live AI trace (Stretch S1, D-023): replays a finished Interpretation step by step.

    The steps come only from the already bank-stripped Interpretation (rule 5). No new LLM call
    is made here beyond what POST /interpret does (rules 7 and 8).
    """
    interp = await run_in_threadpool(_interpret_email_by_id, email_id)  # 404 before the stream
    steps = _trace_steps(interp)
    middle = len(steps) - 1  # steps between start and done (each is preceded by a pause)
    default_ms = max(80, min(350, round(1500 / max(middle, 1))))
    pause_ms = step_ms if step_ms is not None else default_ms
    if interp.method == "keyword_fallback":
        source = "keyword_fallback"
    else:
        source = "replay" if llm_mode() == "replay" else "live"
    start = TraceStart(email_id=email_id, source=source, total_steps=len(steps), step_ms=pause_ms)

    # A client that goes away cancels this generator (Starlette), so no disconnect polling here.
    async def events() -> AsyncIterator[str]:
        yield _sse(start)
        for i, step in enumerate(steps):
            # Pause before each step except `done`, which follows the last one straight away.
            if pause_ms and i < len(steps) - 1:
                await asyncio.sleep(pause_ms / 1000)
            yield _sse(step)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(step) -> str:
    return "event: step\ndata: " + step.model_dump_json() + "\n\n"


def _trace_steps(interp: Interpretation) -> list:
    """The steps after `start`, in contract order, ending with `done`."""
    steps: list = []
    if interp.bank_details_stripped:
        steps.append(TraceBankStripped())
    steps += [TraceField(index=i, field=f) for i, f in enumerate(interp.fields)]
    steps += [TraceLine(index=i, line=ln) for i, ln in enumerate(interp.lines)]
    steps.append(
        TraceCategory(
            category=interp.category,
            confidence=interp.confidence,
            domain=interp.domain,
            needs_review=interp.needs_review,
            method=interp.method,
        )
    )
    if interp.missing_fields or interp.questions_for_requester:
        steps.append(
            TraceMissing(
                missing_fields=interp.missing_fields,
                questions_for_requester=interp.questions_for_requester,
            )
        )
    if interp.injection_suspected:
        steps.append(TraceInjection())
    steps.append(TraceDone(interpretation=interp))
    return steps
