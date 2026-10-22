"""API contract. Every request and response body is a Pydantic v2 model."""

from pydantic import BaseModel


class Health(BaseModel):
    status: str
    service: str
