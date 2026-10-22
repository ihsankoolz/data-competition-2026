"""Routing rules (D-007) read from `config/routing_rules.yaml`, and how a role becomes a person.

No LLM anywhere in here: an approver is chosen from the request's entity and selling countries
and the `users` table, never from anything an e-mail says (domain rule 7).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import literal_column, select
from sqlalchemy.orm import Session

from services.api.bankfields import has_bank_details
from services.api.db import models as m

CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "routing_rules.yaml"


@dataclass(frozen=True)
class Rules:
    business_days: float
    reminder_at: float
    escalate_at: float
    assignment: dict[str, str]
    domains: dict[str, Any]
    requestor_cannot_approve: bool = True
    publisher_not_finance_approver: bool = True


@lru_cache(maxsize=1)
def load_rules() -> Rules:
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    sla = cfg["sla"]
    mc = cfg.get("maker_checker", {})
    return Rules(
        business_days=float(sla["business_days"]),
        reminder_at=float(sla["reminder_at"]),
        escalate_at=float(sla["escalate_at"]),
        assignment=dict(cfg["assignment"]),
        domains=dict(cfg["domains"]),
        requestor_cannot_approve=bool(mc.get("requestor_cannot_approve", True)),
        publisher_not_finance_approver=bool(mc.get("publisher_not_finance_approver", True)),
    )


@dataclass(frozen=True)
class TaskPlan:
    stage: int
    stage_name: str
    role: str
    country: str | None = None


@dataclass
class _Directory:
    users: list[m.User] = field(default_factory=list)

    def with_role(self, role: str) -> list[m.User]:
        return [u for u in self.users if role in u.roles]

    def primaries(self, role: str) -> list[m.User]:
        return [u for u in self.with_role(role) if not u.backup_for]

    def backup_of(self, user_id: str) -> m.User | None:
        return next((u for u in self.users if u.backup_for == user_id), None)


def directory(session: Session) -> _Directory:
    # rowid = users.csv order, so "the first user with the role" is stable
    rows = session.scalars(select(m.User).order_by(literal_column("rowid"))).all()
    return _Directory(list(rows))


def _truthy_ivd(fields: dict[str, Any]) -> bool:
    return fields.get("U_IVD") == "tYES"


def plan_tasks(domain: str, fields: dict[str, Any]) -> list[TaskPlan]:
    """Stages and tasks for a request, from the rule table. Stage-1 tasks run in parallel."""
    spec = load_rules().domains.get(domain)
    if spec is None:
        raise ValueError(f"No routing rule for domain {domain!r}")
    plans: list[TaskPlan] = []
    for number, stage in enumerate(spec["stages"], start=1):
        roles = list(stage["roles"])
        if number == 1:
            if domain == "item" and _truthy_ivd(fields) and "when_ivd" in stage:
                roles += stage["when_ivd"]["add_roles"]
            bank_rule = stage.get("when_bank_details")
            if bank_rule and bank_rule.get("enabled") and has_bank_details(fields):
                roles += bank_rule["add_roles"]
        for role in roles:
            if role == "quality_regulatory":
                countries = [str(c) for c in fields.get("selling_countries") or []]
                for c in countries or [None]:  # type: ignore[list-item]
                    plans.append(TaskPlan(number, stage["name"], role, c))
            else:
                plans.append(TaskPlan(number, stage["name"], role))
    return plans


def assign(
    plan: TaskPlan, entity: str, dir_: _Directory, taken: set[tuple[int, str, str]]
) -> m.User:
    """The person for one task. `taken` stops two tasks of the same role (for example a second
    Finance approver) from landing on the same person."""
    how = load_rules().assignment.get(plan.role, "primary")
    primaries = dir_.primaries(plan.role)
    if not primaries:
        raise ValueError(f"No user with the role {plan.role!r} to assign the task to")
    candidates = primaries
    if how == "entity":
        candidates = [u for u in primaries if u.entity == entity] or primaries
    elif how == "selling_country" and plan.country:
        candidates = [u for u in primaries if u.country == plan.country] or primaries
    for u in candidates:
        if (plan.stage, plan.role, u.user_id) not in taken:
            taken.add((plan.stage, plan.role, u.user_id))
            return u
    return candidates[0]
