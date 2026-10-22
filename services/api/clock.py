"""Simulated clock. All SLA and timestamp logic imports `now()` from here, never `datetime.now()`.

State is in-memory for now; it moves into the database together with the workflow so that
`make reset-demo` and a server restart restore the same simulated time.
"""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter

from services.api.schemas import ClockAdvance, ClockState

SGT = timezone(timedelta(hours=8))
CLOCK_START = datetime(2026, 10, 5, 9, 0, tzinfo=SGT)

_state = {"now": CLOCK_START}

router = APIRouter()


def now() -> datetime:
    """Current simulated time (timezone-aware, SGT)."""
    return _state["now"]


def advance(hours: float = 0, days: float = 0) -> datetime:
    _state["now"] = _state["now"] + timedelta(hours=hours, days=days)
    return _state["now"]


def reset() -> datetime:
    _state["now"] = CLOCK_START
    return _state["now"]


def state() -> ClockState:
    current = now()
    return ClockState(
        now=current,
        started_at=CLOCK_START,
        elapsed_hours=(current - CLOCK_START).total_seconds() / 3600,
    )


@router.get("/clock", response_model=ClockState, operation_id="getClock")
def get_clock() -> ClockState:
    return state()


@router.post("/clock/advance", response_model=ClockState, operation_id="advanceClock")
def advance_clock(body: ClockAdvance) -> ClockState:
    advance(hours=body.hours, days=body.days)
    return state()


@router.post("/clock/reset", response_model=ClockState, operation_id="resetClock")
def reset_clock() -> ClockState:
    reset()
    return state()
