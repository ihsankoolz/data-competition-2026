"""Shared FastAPI dependencies: the acting user (X-Acting-User) and role checks.

There is no login in this prototype (CLAUDE.md): the header switcher in the web app names a user
and the backend checks it against the `users` table and enforces roles on every action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select

from services.api.db import models as m
from services.api.db.session import session_scope


@dataclass(frozen=True)
class Actor:
    user_id: str
    name: str
    title: str
    roles: tuple[str, ...]
    entity: str
    country: str
    backup_for: str | None

    def has(self, role: str) -> bool:
        return role in self.roles

    @property
    def is_finance(self) -> bool:
        return "finance" in self.roles


def acting_user(
    x_acting_user: Annotated[
        str | None, Header(description="user_id of the persona chosen in the header switcher")
    ] = None,
) -> Actor:
    if not x_acting_user or not x_acting_user.strip():
        raise HTTPException(
            status_code=400,
            detail="Choose who you are acting as first (the X-Acting-User header is missing).",
        )
    with session_scope() as session:
        user = session.scalar(select(m.User).where(m.User.user_id == x_acting_user.strip()))
    if user is None:
        raise HTTPException(
            status_code=403,
            detail=f"'{x_acting_user}' is not a known user, so no action is allowed.",
        )
    return Actor(
        user_id=user.user_id,
        name=user.name,
        title=user.title,
        roles=tuple(user.roles),
        entity=user.entity,
        country=user.country,
        backup_for=user.backup_for,
    )


CurrentUser = Annotated[Actor, Depends(acting_user)]

ROLE_LABELS = {
    "requestor": "a requestor",
    "bu_head": "a BU head",
    "finance": "in Finance",
    "quality_regulatory": "in Quality / Regulatory",
    "business_support": "in Business Support",
    "mdm_analyst": "an MDM analyst",
}


def require_role(actor: Actor, role: str, action: str) -> None:
    if not actor.has(role):
        raise HTTPException(
            status_code=403,
            detail=f"Only someone who is {ROLE_LABELS.get(role, role)} can {action}. "
            f"{actor.name} is acting as {actor.title}.",
        )
