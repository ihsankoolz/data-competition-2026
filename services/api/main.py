"""Lives MDM API (port 8000): workflow, dedup, interpreter, analytics."""

from fastapi import FastAPI

from services.api.schemas import Health

app = FastAPI(title="Lives MDM API", version="0.1.0")


@app.get("/health", response_model=Health, operation_id="health")
def health() -> Health:
    return Health(status="ok", service="api")
