"""Session 13: local time zones on due times, the Teams card preview, the "it's live" message and
the approval-rules backup check. Offline; reuses the module database of `test_workflow_api.py`.
"""

# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
from __future__ import annotations

from datetime import datetime

import pytest

from services.api import clock
from tests.test_workflow_api import (  # noqa: F401 - fixtures are used by name
    H,
    _clock,
    client,
    decide,
    new_request,
    sap_mock,
    tasks_by_role,
)

OWNS_APP_DB = True  # see tests/conftest.py


def sgt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=clock.SGT)


# ---------------------------------------------------------------- part 1: local time helper


@pytest.mark.parametrize(
    ("country", "local"),
    [
        ("VN", "8:00 am in Vietnam"),
        ("TH", "8:00 am in Thailand"),
        ("ID", "8:00 am Jakarta time"),
    ],
)
def test_vietnam_thailand_and_indonesia_are_one_hour_earlier(country, local):
    when = sgt(7, 9)
    assert clock.format_local(when, country) == local
    assert clock.format_due(when, country) == f"Wed 7 Oct 2026, 9:00 am SGT, {local}"


@pytest.mark.parametrize("country", ["SG", "MY", "sg", None, "XX"])
def test_singapore_malaysia_and_unknown_countries_just_see_sgt(country):
    when = sgt(7, 9)
    assert clock.format_local(when, country) is None
    assert clock.format_due(when, country) == clock.format_sgt(when) == "Wed 7 Oct 2026, 9:00 am"


def test_just_after_midnight_sgt_is_the_previous_day_locally():
    when = sgt(8, 0, 30)
    assert clock.format_local(when, "VN") == "Wed 7 Oct, 11:30 pm in Vietnam"
    assert clock.format_due(when, "ID") == (
        "Thu 8 Oct 2026, 12:30 am SGT, Wed 7 Oct, 11:30 pm Jakarta time"
    )


def test_a_naive_time_is_read_as_sgt():
    assert clock.format_local(datetime(2026, 10, 7, 9, 0), "TH") == "8:00 am in Thailand"


# ---------------------------------------------------------------- part 1: on tasks and messages


def ivd_item(client, name: str, countries=("SG", "MY", "VN")):
    fields = {
        "ItemName": name,
        "U_IVD": "tYES",
        "selling_countries": list(countries),
        "registrations": [
            {"country": c, "reg_no": f"R-{c}", "expiry_date": "2030-12-31"} for c in countries
        ],
        "product_family": "A",
    }
    req = new_request(client, "amy", "item", "SPD", "SG", fields)
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 200, r.text
    return r.json()


def test_lan_in_vietnam_sees_her_due_time_in_vietnam_time(client):
    d = ivd_item(client, "Timezone Malaria Rapid Test")
    by = tasks_by_role(d)
    lan, nurul, daniel = (
        by[("quality_regulatory", "VN")],
        by[("quality_regulatory", "MY")],
        by[("bu_head", None)],
    )
    assert lan["assignee_user_id"] == "lan"
    due = datetime.fromisoformat(lan["due_at"])
    sgt_words = clock.format_sgt(due)
    assert sgt_words == "Wed 7 Oct 2026, 9:00 am"  # two business days from Mon 9:00 am
    assert lan["due_local"] == "8:00 am in Vietnam"
    assert nurul["due_local"] is None and daniel["due_local"] is None  # MY and SG: SGT only

    # the same words in her inbox and in her notification
    inbox = client.get("/approvals/inbox", headers=H("lan")).json()
    mine = next(i for i in inbox if i["request"]["req_id"] == d["req_id"])
    assert mine["task"]["due_local"] == lan["due_local"]
    note = next(
        n
        for n in client.get("/notifications", headers=H("lan")).json()
        if n["req_id"] == d["req_id"] and n["kind"] == "task_assigned"
    )
    assert f"Please decide by {sgt_words} SGT, {lan['due_local']}." in note["message"]
    # an SG approver's message is unchanged: no "SGT" suffix, no local part
    note = next(
        n
        for n in client.get("/notifications", headers=H("daniel")).json()
        if n["req_id"] == d["req_id"] and n["kind"] == "task_assigned"
    )
    assert note["message"].endswith(f"Please decide by {clock.format_sgt(due)}.")


def test_the_reminder_carries_the_local_time_too(client):
    d = ivd_item(client, "Timezone Reminder Rapid Test", countries=("SG", "TH"))
    clock.advance(days=1, hours=1)  # past 50% of two business days
    r = client.get("/notifications", headers=H("pornthip"))
    reminder = next(n for n in r.json() if n["req_id"] == d["req_id"] and n["kind"] == "reminder")
    assert "SGT, " in reminder["message"] and reminder["message"].endswith("in Thailand.")
