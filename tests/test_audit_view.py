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


def test_coded_fields_show_their_option_label():
    assert (
        _line("PayTermsGrpCode", None, 1, domain="customer")
        == "Amy changed Credit terms: (empty) -> 30 days"
    )
    assert _line("PayTermsGrpCode", 1, -1, domain="customer").endswith(
        "30 days -> Cash on delivery"
    )
    assert _line("PayTermsGrpCode", 2, 3, domain="vendor").endswith(
        "Payment terms: 60 days -> 90 days"
    )
    assert _line("ItemsGroupCode", 101, 102).endswith(
        "Reagents and test kits -> Analysers and equipment"
    )
    assert _line("U_IVD", "tNO", "tYES").endswith(": no -> yes")
    assert _line("Country", "SG", "VN", domain="customer").endswith("Singapore -> Vietnam")


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
                    # (not an existing item's number: that is a Likely duplicate since session 13)
                    {"country": "SG", "reg_no": "DE9000001", "expiry_date": "2030-08-15"},
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
                    {"country": "SG", "reg_no": "DE9000001", "expiry_date": "2031-12-31"},
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


def _raw(i: int, action: str, actor: str = "amy", **payload):
    return SimpleNamespace(
        id=i, ts="2026-10-07T09:00:00+08:00", actor=actor, action=action,
        entity_type="request", entity_id="REQ-1", payload=json.dumps(payload),
    )  # fmt: skip


def test_bursts_of_bank_edits_and_duplicate_checks_read_as_one_line():
    bank = [
        _raw(i, "field_edit", field=f"BPBankAccounts[0].{leaf}", old="x", new="y")
        for i, leaf in enumerate(("AccountNo", "BankCode", "IBAN"), 1)
    ]
    checks = [_raw(i, "dedup_check", summary=f"Duplicate check run by Amy: run {i}") for i in (4, 5, 6)]
    rows = [*bank, *checks, _raw(7, "field_edit", field="City", old="A", new="B"), bank[0]]
    lines = [e.summary for e in audit_view.entries(rows, {"amy": "Amy"}, "customer")]
    assert lines == [
        "Amy changed the bank details",
        "Duplicate check run by Amy: run 6",
        "Amy changed City: A -> B",
        "Amy changed the bank details",
    ]
    # Someone else's edit in between is its own line.
    rows = [bank[0], _raw(9, "field_edit", "daniel", field="BPBankAccounts[0].IBAN", old=1, new=2)]
    assert len(audit_view.entries(rows, {"amy": "Amy", "daniel": "Daniel"}, "customer")) == 2


def test_notification_dates_read_like_the_app():
    from datetime import datetime, timedelta, timezone

    assert clock.format_sgt(datetime(2026, 10, 7, 9, 0, tzinfo=clock.SGT)) == "Wed 7 Oct 2026, 9:00 am"
    utc = datetime(2026, 10, 7, 6, 5, tzinfo=timezone.utc)  # 2:05 pm in Singapore
    assert clock.format_sgt(utc) == "Wed 7 Oct 2026, 2:05 pm"
    assert clock.format_sgt(datetime(2026, 10, 8, 0, 30, tzinfo=clock.SGT) + timedelta(hours=12)) == (
        "Thu 8 Oct 2026, 12:30 pm"
    )
