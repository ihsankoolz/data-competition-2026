"""Placeholder for routes whose contract exists but whose behaviour is not built yet."""

from fastapi import HTTPException


def not_built(what: str) -> HTTPException:
    return HTTPException(status_code=501, detail=f"Not built yet: {what}")
