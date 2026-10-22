"""Lives MDM API (port 8000): workflow, dedup, interpreter, analytics."""

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI

from services.api.personas import PERSONAS
from services.api.schemas import ClockAdvance, ClockState, Health, Persona

app = FastAPI(title="Lives MDM API", version="0.1.0")


@app.get("/health", response_model=Health, operation_id="health")
def health() -> Health:
    return Health(status="ok", service="api")


# --- Contract stubs (orchestrator). backend-engineer replaces the bodies; shapes are fixed. ---

SGT = timezone(timedelta(hours=8))
_CLOCK_START = datetime(2026, 10, 5, 9, 0, tzinfo=SGT)
_clock = {"now": _CLOCK_START}


def _clock_state() -> ClockState:
    now = _clock["now"]
    return ClockState(
        now=now,
        started_at=_CLOCK_START,
        elapsed_hours=(now - _CLOCK_START).total_seconds() / 3600,
    )


@app.get("/clock", response_model=ClockState, operation_id="getClock")
def get_clock() -> ClockState:
    return _clock_state()


@app.post("/clock/advance", response_model=ClockState, operation_id="advanceClock")
def advance_clock(body: ClockAdvance) -> ClockState:
    _clock["now"] += timedelta(hours=body.hours, days=body.days)
    return _clock_state()


@app.post("/clock/reset", response_model=ClockState, operation_id="resetClock")
def reset_clock() -> ClockState:
    _clock["now"] = _CLOCK_START
    return _clock_state()


@app.get("/personas", response_model=list[Persona], operation_id="listPersonas")
def list_personas() -> list[Persona]:
    return PERSONAS
