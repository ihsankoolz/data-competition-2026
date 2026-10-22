from fastapi.testclient import TestClient

from services.api.main import app as api_app
from services.sap_mock.main import app as sap_app


def test_api_health():
    r = TestClient(api_app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "api"}


def test_sap_mock_health():
    r = TestClient(sap_app).get("/b1s/v2/health")
    assert r.status_code == 200
    assert r.json()["service"] == "sap_mock"


def test_ds_package_imports():
    import ds.analytics  # noqa: F401
    import ds.dedup  # noqa: F401
    import ds.forecasting  # noqa: F401
    import ds.generator  # noqa: F401
    import ds.interpreter  # noqa: F401


def test_personas_cover_cast():
    r = TestClient(api_app).get("/personas")
    assert r.status_code == 200
    names = {p["name"] for p in r.json()}
    assert {"Amy", "Marcus", "Wei Jie", "Priya"} <= names
    assert len(names) == 8
