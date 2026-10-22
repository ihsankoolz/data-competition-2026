"""SLA arithmetic on the simulated clock: business days only, Saturday and Sunday do not count.

A task's SLA is `business_days` (config/routing_rules.yaml). The reminder fires at
`reminder_at` x SLA, the escalation at `escalate_at` x SLA. Nothing here reads the wall clock.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from services.api.workflow.rules import Rules

SATURDAY = 5


def _is_weekend(d: datetime) -> bool:
    return d.weekday() >= SATURDAY


def _next_midnight(d: datetime) -> datetime:
    return datetime.combine(d.date() + timedelta(days=1), time(0), tzinfo=d.tzinfo)


def _skip_weekend(d: datetime) -> datetime:
    while _is_weekend(d):
        d = _next_midnight(d)
    return d


def add_business_time(start: datetime, amount: timedelta) -> datetime:
    """`start` + `amount` of working time. Weekend days contribute nothing:
    Fri 09:00 + 1 business day = Mon 09:00."""
    cur = _skip_weekend(start)
    remaining = amount
    while True:
        day_left = _next_midnight(cur) - cur
        if remaining <= day_left:
            return cur + remaining
        remaining -= day_left
        cur = _skip_weekend(_next_midnight(cur))


def reminder_time(assigned_at: datetime, rules: Rules) -> datetime:
    return add_business_time(assigned_at, timedelta(days=rules.business_days * rules.reminder_at))


def due_time(assigned_at: datetime, rules: Rules) -> datetime:
    return add_business_time(assigned_at, timedelta(days=rules.business_days * rules.escalate_at))
