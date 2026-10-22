"""Lives MDM API (port 8000): workflow, dedup, interpreter, analytics."""

from fastapi import FastAPI

from services.api.clock import router as clock_router
from services.api.personas import PERSONAS
from services.api.routers import admin, approvals, dedup, emails, forms, requests
from services.api.schemas import Health, Persona

app = FastAPI(title="Lives MDM API", version="0.1.0")
app.include_router(clock_router)
for _module in (forms, emails, dedup, requests, approvals, admin):
    app.include_router(_module.router)


@app.get("/health", response_model=Health, operation_id="health")
def health() -> Health:
    return Health(status="ok", service="api")


@app.get("/personas", response_model=list[Persona], operation_id="listPersonas")
def list_personas() -> list[Persona]:
    return PERSONAS
