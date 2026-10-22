"""API contract. Every request and response body is a Pydantic v2 model."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str
    service: str


class ClockState(BaseModel):
    """Simulated clock. All SLA logic uses `now`, never the wall clock."""

    now: datetime = Field(description="Current simulated time (timezone-aware, SGT)")
    started_at: datetime = Field(description="Simulated time after the last reset")
    elapsed_hours: float = Field(description="Simulated hours since the last reset")


class ClockAdvance(BaseModel):
    hours: float = Field(default=0, ge=0)
    days: float = Field(default=0, ge=0)


Role = Literal[
    "requestor", "bu_head", "finance", "quality_regulatory", "business_support", "mdm_analyst"
]


class Persona(BaseModel):
    """A seeded demo user. The web app sends the chosen `user_id` in the X-Acting-User header."""

    user_id: str
    name: str
    title: str
    roles: list[Role]
    entity: str = Field(description="SPD | QTS | QTG | Group")
    country: str = Field(description="ISO-2")
