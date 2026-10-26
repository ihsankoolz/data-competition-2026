"""Lives MDM API (port 8000): workflow, dedup, interpreter, analytics."""

import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from services.api import clock
from services.api.clock import router as clock_router
from services.api.personas import PERSONAS
from services.api.routers import (
    admin,
    analytics,
    approvals,
    cleanup,
    dedup,
    emails,
    forms,
    requests,
)
from services.api.schemas import Health, Persona
from services.api.validation import ValidationFailed

DB_BUSY_MESSAGE = "The demo database is busy; try again in a moment."


def validation_sentence(exc: RequestValidationError) -> str:
    """One plain-English sentence naming the field. Input values are never echoed."""
    errors = exc.errors()
    if not errors:
        return "Please check what you entered and try again."
    first = errors[0]
    parts = [str(p) for p in first.get("loc", ()) if p not in ("body", "query", "path", "header")]
    field = " > ".join(parts) or "request"
    kind = str(first.get("type", ""))
    if kind == "missing":
        problem = "is required"
    elif kind.startswith("literal_error") or kind.startswith("enum"):
        problem = "is not one of the allowed choices"
    elif "type" in kind or "parsing" in kind:
        problem = "is not in the expected format"
    elif "too_short" in kind or "string_too_short" in kind:
        problem = "is too short"
    elif "too_long" in kind:
        problem = "is too long"
    else:
        problem = "is not valid"
    more = f" (and {len(errors) - 1} more to check)" if len(errors) > 1 else ""
    return f"Please check the '{field}' field: it {problem}{more}."


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    clock.restore()  # the simulated time survives a restart
    threading.Thread(target=analytics.warm, name="analytics-warm", daemon=True).start()
    yield


app = FastAPI(title="Lives MDM API", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's default 422 echoes the submitted values (`input`). A form can carry bank
    details (domain rule 5), so only where and why is returned."""
    return JSONResponse(status_code=422, content={"detail": validation_sentence(exc)})


@app.exception_handler(ValidationFailed)
async def _blocked(_: Request, exc: ValidationFailed) -> JSONResponse:
    """422 {"detail": "<one sentence>", "issues": [...]}: messages never echo field values."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "issues": [i.model_dump() for i in exc.issues]},
    )


@app.exception_handler(OperationalError)
async def _database_busy(_: Request, exc: OperationalError) -> JSONResponse:
    """A write that could not get the database in time: tell the client to retry, never a 500
    (and never the SQL, which could carry values)."""
    return JSONResponse(status_code=503, content={"detail": DB_BUSY_MESSAGE})


app.include_router(clock_router)
for _module in (forms, emails, dedup, requests, approvals, admin, analytics, cleanup):
    app.include_router(_module.router)


@app.get("/health", response_model=Health, operation_id="health")
def health() -> Health:
    return Health(status="ok", service="api")


@app.get("/personas", response_model=list[Persona], operation_id="listPersonas")
def list_personas() -> list[Persona]:
    return PERSONAS
