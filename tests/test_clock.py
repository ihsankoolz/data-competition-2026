from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from services.api import clock
from services.api.main import app

SGT = timezone(timedelta(hours=8))
START = datetime(2026, 10, 5, 9, 0, tzinfo=SGT)


@pytest.fixture
def client():
    clock.reset()
    yield TestClient(app)
    clock.reset()


def test_initial_state(client):
    body = client.get("/clock").json()
    assert datetime.fromisoformat(body["now"]) == START
    assert datetime.fromisoformat(body["started_at"]) == START
    assert body["elapsed_hours"] == 0
    assert body["now"].endswith("+08:00")


def test_now_is_timezone_aware(client):
    assert clock.now() == START
    assert clock.now().utcoffset() == timedelta(hours=8)


def test_advance_hours_and_days(client):
    r = client.post("/clock/advance", json={"hours": 5})
    assert r.status_code == 200
    assert datetime.fromisoformat(r.json()["now"]) == START + timedelta(hours=5)
    r = client.post("/clock/advance", json={"days": 2})
    assert datetime.fromisoformat(r.json()["now"]) == START + timedelta(days=2, hours=5)
    assert r.json()["elapsed_hours"] == 53
    assert clock.now() == START + timedelta(days=2, hours=5)


def test_advance_hours_and_days_together(client):
    r = client.post("/clock/advance", json={"hours": 1.5, "days": 1})
    assert r.json()["elapsed_hours"] == 25.5


def test_reset(client):
    client.post("/clock/advance", json={"days": 3})
    r = client.post("/clock/reset")
    assert r.status_code == 200
    assert datetime.fromisoformat(r.json()["now"]) == START
    assert r.json()["elapsed_hours"] == 0


@pytest.mark.parametrize("body", [{"hours": -1}, {"days": -0.5}])
def test_negative_advance_rejected(client, body):
    assert client.post("/clock/advance", json=body).status_code == 422
    assert clock.now() == START
