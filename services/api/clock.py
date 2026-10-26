"""Simulated clock. All SLA and timestamp logic imports `now()` from here, never `datetime.now()`.

The time lives in memory (cheap to read from anywhere) and is saved to the `app_state` table
whenever it moves (`/clock/advance`, reset), so a server restart restores the same simulated
time (`restore()`, called at API start-up). Advancing the clock also runs the SLA sweep
(reminders and escalations, D-007).
"""

import logging
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

import yaml
from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from services.api.db.models import AppState
from services.api.schemas import ClockAdvance, ClockState

log = logging.getLogger(__name__)
CLOCK_KEY = "clock_now"

SGT = timezone(timedelta(hours=8))
CLOCK_START = datetime(2026, 10, 5, 9, 0, tzinfo=SGT)

_state = {"now": CLOCK_START}

router = APIRouter()


def format_sgt(when: datetime) -> str:
    """ "Wed 7 Oct 2026, 9:00 am" in Singapore time: the same words as the web's `formatSgt`."""
    d = when.astimezone(SGT) if when.tzinfo else when
    hour = d.hour % 12 or 12
    return f"{d:%a} {d.day} {d:%b %Y}, {hour}:{d:%M} {'am' if d.hour < 12 else 'pm'}"


# ---------------------------------------------------------------- local time (session 13)
# Display only: due times stay in SGT and every SLA rule runs on SGT. Fixed UTC offsets from
# config/timezones.yaml, NOT zoneinfo/tzdata: Windows has no system time zone database, no new
# dependency is allowed, and none of the five countries uses daylight saving.

TIMEZONES_PATH = Path(__file__).resolve().parents[2] / "config" / "timezones.yaml"


@lru_cache(maxsize=1)
def _timezones() -> dict[str, tuple[timezone, str]]:
    cfg = yaml.safe_load(TIMEZONES_PATH.read_text(encoding="utf-8"))
    return {
        code.upper(): (timezone(timedelta(hours=float(c["utc_offset_hours"]))), str(c["phrase"]))
        for code, c in cfg["countries"].items()
    }


def _clock_words(d: datetime) -> str:
    hour = d.hour % 12 or 12
    return f"{hour}:{d:%M} {'am' if d.hour < 12 else 'pm'}"


def format_local(when: datetime, country: str | None) -> str | None:
    """The local part of a due time, or None when the country keeps Singapore time (SG, MY) or
    is unknown: "8:00 am in Vietnam", "8:00 am Jakarta time", and with the day when it differs
    from the SGT day: "Wed 7 Oct, 11:30 pm in Vietnam"."""
    zone = _timezones().get((country or "").upper())
    if zone is None:
        return None
    tz, phrase = zone
    sgt = when.astimezone(SGT) if when.tzinfo else when.replace(tzinfo=SGT)
    local = sgt.astimezone(tz)
    if local.utcoffset() == sgt.utcoffset():
        return None
    day = "" if local.date() == sgt.date() else f"{local:%a} {local.day} {local:%b}, "
    return f"{day}{_clock_words(local)} {phrase}"


def format_due(when: datetime, country: str | None) -> str:
    """A due time for an approver in `country`: plain SGT words for SG and MY (unchanged), and
    "Wed 7 Oct 2026, 9:00 am SGT, 8:00 am in Vietnam" where the local time differs."""
    local = format_local(when, country)
    return format_sgt(when) if local is None else f"{format_sgt(when)} SGT, {local}"


def now() -> datetime:
    """Current simulated time (timezone-aware, SGT)."""
    return _state["now"]


def advance(hours: float = 0, days: float = 0) -> datetime:
    _state["now"] = _state["now"] + timedelta(hours=hours, days=days)
    return _state["now"]


def reset() -> datetime:
    _state["now"] = CLOCK_START
    return _state["now"]


def persist(session: Session, when: datetime) -> None:
    """Save the simulated time inside the caller's transaction."""
    row = session.get(AppState, CLOCK_KEY)
    if row is None:
        session.add(AppState(key=CLOCK_KEY, value=when.isoformat()))
    else:
        row.value = when.isoformat()


def restore() -> bool:
    """Load the saved time into memory (API start-up). False if there is nothing saved."""
    from services.api.db.session import default_db_path, session_scope

    if not default_db_path().exists():
        return False
    try:
        with session_scope() as session:
            value = session.scalar(select(AppState.value).where(AppState.key == CLOCK_KEY))
    except SQLAlchemyError:
        log.warning("Could not read the saved simulated time; starting at the default.")
        return False
    if not value:
        return False
    _state["now"] = datetime.fromisoformat(value)
    return True


def _save() -> None:
    """Best effort: the clock keeps working even when there is no database yet."""
    from services.api.db.session import default_db_path, session_scope

    if not default_db_path().exists():
        return
    try:
        with session_scope(write=True) as session:
            persist(session, now())
    except SQLAlchemyError:
        log.warning("Could not save the simulated time.")


def _sweep() -> None:
    from services.api.workflow.engine import run_sla_sweep_safely

    run_sla_sweep_safely()


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
    _save()
    _sweep()  # reminders and escalations that fell due while the clock moved
    return state()


@router.post("/clock/reset", response_model=ClockState, operation_id="resetClock")
def reset_clock() -> ClockState:
    reset()
    _save()
    return state()
