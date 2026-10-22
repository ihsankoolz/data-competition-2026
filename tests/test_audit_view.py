"""Status-page history lines are plain English: no Python reprs for lists or dicts."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from services.api import audit_view, clock
from services.api.db.session import dispose_default
from services.api.main import app

OWNS_APP_DB = True  # see tests/conftest.py


def H(user: str) -> dict[str, str]:
    return {"X-Acting-User": user}


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("FIELD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    mp.setenv("APP_DB_PATH", str(tmp_path_factory.mktemp("audit_view") / "app.db"))
    mp.setenv("SAP_BASE_URL", "http://127.0.0.1:9/b1s/v2")
    mp.setenv("LLM_MODE", "replay")
    dispose_default()
    c = TestClient(app)
    assert c.post("/admin/reset-demo").status_code == 200
    clock.reset()
    yield c
    clock.reset()
    dispose_default()
    mp.undo()


def _row(field: str, old, new):
    payload = json.dumps({"field": field, "old": old, "new": new})
    return SimpleNamespace(action="field_edit", payload=payload, actor="amy")


def _line(field, old, new, domain="item"):
    return audit_view.summarize(_row(field, old, new), {"amy": "Amy"}, domain)


SG = {"country": "SG", "reg_no": "DE2538958", "expiry_date": "2026-08-15"}
MY = {"country": "MY", "reg_no": "MDA-2", "expiry_date": "2027-06-30"}
VN = {"country": "VN", "reg_no": "VN-3", "expiry_date": "2028-01-01"}


def test_registration_added_changed_removed_sentences():
    assert (
        _line("registrations", [], [SG])
        == "Amy set the Singapore registration (DE2538958, expires 15 Aug 2026)"
    )
    assert (
        _line("registrations", [SG, MY], [SG, {**MY, "expiry_date": "2027-12-31"}])
        == "Amy changed the Malaysia registration expiry to 31 Dec 2027"
    )
    assert _line("registrations", [SG, VN], [SG]) == "Amy removed the Vietnam registration"
    several = _line("registrations", [MY, VN], [SG, {**MY, "reg_no": "MDA-9"}])
    assert several == (
        "Amy set the Singapore registration (DE2538958, expires 15 Aug 2026); "
        "changed the Malaysia registration number to MDA-9; "
        "removed the Vietnam registration"
    )


def test_other_lists_and_dicts_read_naturally():
    assert (
        _line("selling_countries", [], ["SG", "MY", "VN"])
        == "Amy changed Selling countries: (empty) -> Singapore, Malaysia, Vietnam"
    )
    assert "{'" not in _line("Weird", {"a": 1}, {"a": 2, "b": {"c": 3}})
    assert "[{" not in _line("Other", [{"x": 1}], [{"x": 2}, {"x": 3}])
    assert _line("Other", [{"x": 1}], [{"x": 2}, {"x": 3}]).endswith("1 entries -> 2 entries")
    long = _line("Notes", None, ["word"] * 200)
    assert len(long) <= 240 and long.endswith("…")


def test_bank_edits_stay_value_free():
    line = _line("BPBankAccounts[0].IBAN", "SG123", "SG456", domain="customer")
    assert line == "Amy changed the bank details" and "SG" not in line


def test_item_request_history_has_no_python_structures(client):
    r = client.post(
        "/requests",
        headers=H("amy"),
        json={
            "domain": "item",
            "entity": "SPD",
            "country": "SG",
            "fields": {
                "ItemName": "Audit View Rapid Test",
                "U_IVD": "tYES",
                "selling_countries": ["SG", "MY"],
                "registrations": [
                    {"country": "SG", "reg_no": "DE2538958", "expiry_date": "2030-08-15"},
                    {"country": "MY", "reg_no": "MDA-2", "expiry_date": "2030-06-30"},
                ],
            },
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["req_id"]
    r = client.patch(
        f"/requests/{rid}",
        headers=H("amy"),
        json={
            "fields": {
                "selling_countries": ["SG", "MY", "VN"],
                "registrations": [
                    {"country": "SG", "reg_no": "DE2538958", "expiry_date": "2031-12-31"},
                    {"country": "VN", "reg_no": "VN-3", "expiry_date": "2030-12-31"},
                    {"country": "MY", "reg_no": "MDA-2", "expiry_date": "2030-06-30"},
                ],
            }
        },
    )
    assert r.status_code == 200, r.text
    r = client.post(f"/requests/{rid}/submit", headers=H("amy"))
    assert r.status_code == 200, r.text
    lines = [e["summary"] for e in client.get(f"/requests/{rid}/audit", headers=H("amy")).json()]
    assert lines
    for s in lines:
        assert "{'" not in s and "[{" not in s and "['" not in s, s
    reg = next(x for x in lines if "registration" in x and x.startswith("Amy"))
    assert "set the Vietnam registration (VN-3, expires 31 Dec 2030)" in reg
    assert "changed the Singapore registration expiry to 31 Dec 2031" in reg
    assert any("Singapore, Malaysia, Vietnam" in x for x in lines)
