"""SAP Business One Service Layer mock (port 8001, base path /b1s/v2). Contract: D-004, D-014."""

from fastapi import APIRouter, FastAPI

app = FastAPI(title="SAP B1 Service Layer mock", version="0.1.0")
router = APIRouter(prefix="/b1s/v2")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "sap_mock"}


app.include_router(router)
