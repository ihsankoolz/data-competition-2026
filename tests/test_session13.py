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


# ---------------------------------------------------------------- part 2: the Teams card


VENDOR_DEMO_07 = {
    "CardName": "Precision Diagnostics Asia Pte Ltd",
    "Country": "SG",
    "FederalTaxID": "201845123K",
    "Street": "10 Science Park Road",
    "City": "Singapore",
    "ZipCode": "117684",
    "EmailAddress": "ar@precisiondx.sg.example",
    "PayTermsGrpCode": 1,
    "BPBankAccounts": [
        {
            "BankCode": "DBS",
            "AccountNo": "072-123456-7",
            "AccountName": "Precision Diagnostics Asia Pte Ltd",
            "BICSwiftCode": "DBSSSGSG",
            "Country": "SG",
        }
    ],
}


def notes_for(client, user, req_id, kind=None):
    return [
        n
        for n in client.get("/notifications", headers=H(user)).json()
        if n["req_id"] == req_id and (kind is None or n["kind"] == kind)
    ]


def card_for(client, user, notification_id):
    return client.get(f"/notifications/{notification_id}/teams-card", headers=H(user))


def facts_of(card):
    return {
        f["title"]: f["value"] for b in card["body"] if b["type"] == "FactSet" for f in b["facts"]
    }


def test_teams_card_is_a_valid_adaptive_card_with_four_actions(client):
    d = ivd_item(client, "Teams Card Malaria Rapid Test")
    note = notes_for(client, "lan", d["req_id"], "task_assigned")[0]
    assert note["teams_card"] is True
    r = card_for(client, "lan", note["notification_id"])
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["type"] == "AdaptiveCard" and card["version"] == "1.5"
    assert card["$schema"] == "http://adaptivecards.io/schemas/adaptive-card.json"
    assert {b["type"] for b in card["body"]} <= {"TextBlock", "FactSet"}
    texts = [b["text"] for b in card["body"] if b["type"] == "TextBlock"]
    assert "Teams Card Malaria Rapid Test" in texts
    facts = facts_of(card)
    assert facts["Request"] == d["req_id"]
    assert facts["Your part"] == "Quality / Regulatory (VN)"
    assert facts["Decide by"] == "Wed 7 Oct 2026, 9:00 am SGT, 8:00 am in Vietnam"
    submits = [a for a in card["actions"] if a["type"] == "Action.Submit"]
    assert [a["title"] for a in submits] == ["Approve", "Ask for info", "Reject"]
    assert [a["data"]["action"] for a in submits] == ["approve", "ask_info", "reject"]
    task_id = tasks_by_role(d)[("quality_regulatory", "VN")]["task_id"]
    assert all(a["data"]["task_id"] == task_id for a in submits)
    (open_url,) = [a for a in card["actions"] if a["type"] == "Action.OpenUrl"]
    assert open_url["title"] == "Open" and open_url["url"].endswith(f"/requests/{d['req_id']}")
    assert len(card["actions"]) == 4
    # an SG approver's card shows SGT only
    daniel = notes_for(client, "daniel", d["req_id"], "task_assigned")[0]
    card = card_for(client, "daniel", daniel["notification_id"]).json()
    assert facts_of(card)["Decide by"] == "Wed 7 Oct 2026, 9:00 am"


def test_teams_card_never_carries_bank_details_for_the_demo07_vendor(client):
    req = new_request(client, "amy", "vendor", "SPD", "SG", VENDOR_DEMO_07)
    r = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy"))
    assert r.status_code == 200, r.text
    for user in ("weijie", "daniel", "meiling"):  # Finance too: the card is never unmasked
        note = notes_for(client, user, req["req_id"], "task_assigned")[0]
        r = card_for(client, user, note["notification_id"])
        assert r.status_code == 200, r.text
        for secret in ("072-123456-7", "0721234567", "DBSSSGSG", "BankCode", "AccountNo"):
            assert secret not in r.text
        assert "Bank details are not included" in r.text


def test_teams_card_404s_for_unknown_other_peoples_and_non_task_notifications(client):
    assert card_for(client, "lan", "NTF-99999").status_code == 404
    d = ivd_item(client, "Teams Card Not Yours Rapid Test")
    note = notes_for(client, "lan", d["req_id"], "task_assigned")[0]
    assert card_for(client, "daniel", note["notification_id"]).status_code == 404
    # the requestor's "needs more information" notification carries a task but is not an approval
    lan_task = tasks_by_role(d)[("quality_regulatory", "VN")]["task_id"]
    r = decide(client, lan_task, "lan", "ask_info", "Which lab ran the trial?")
    assert r.status_code == 200, r.text
    info = notes_for(client, "amy", d["req_id"], "info_requested")[0]
    assert info["task_id"] == lan_task and info["teams_card"] is False
    r = card_for(client, "amy", info["notification_id"])
    assert r.status_code == 404 and "not about an approval" in r.json()["detail"]


# ---------------------------------------------------------------- part 3: told when it's live


@pytest.mark.parametrize(
    ("domain", "tail"),
    [
        ("item", "so you can raise sales orders now."),
        ("customer", "so you can raise sales orders for them now."),
        ("vendor", "so you can raise purchase orders now."),
        ("cost_center", "so you can post costs to it now."),
    ],
)
def test_live_message_says_what_the_requestor_can_do_next(domain, tail):
    from services.api.workflow.publishing import live_message

    assert live_message(domain, "X", "CODE-1") == f"'X' is live in SAP as CODE-1, {tail}"


def test_amy_is_told_demo02_is_live_and_she_can_raise_sales_orders(client, sap_mock):
    import re

    from tests.test_route_snapshot import _from_email

    domain, fields = _from_email(client, "DEMO-02", "amy")
    assert domain == "item"
    fields = {
        **fields,
        "U_IVD": "tYES",
        "selling_countries": ["SG", "MY", "VN"],
        "registrations": [
            {"country": c, "reg_no": f"R-{c}", "expiry_date": "2030-12-31"}
            for c in ("SG", "MY", "VN")
        ],
        "product_family": "A",
    }
    req = new_request(client, "amy", "item", "SPD", "SG", fields)
    d = client.post(f"/requests/{req['req_id']}/submit", headers=H("amy")).json()
    for (role, country), t in tasks_by_role(d).items():
        if t["stage"] == 1:
            r = decide(client, t["task_id"], t["assignee_user_id"])
            assert r.status_code == 200, (role, country, r.text)
    r = client.post(f"/requests/{d['req_id']}/publish", headers=H("priya"))
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "ACTIVE"
    (note,) = notes_for(client, "amy", d["req_id"], "published")
    title = d["title"]
    assert title.startswith("Malaria")
    m = re.fullmatch(
        rf"'{re.escape(title)}' is live in SAP as (A-MAL-\d{{3}}), so you can raise sales "
        r"orders now\.",
        note["message"],
    )
    assert m, note["message"]
    code = m.group(1)
    assert client.get(f"/requests/{d['req_id']}", headers=H("amy")).json()["sap_publish"]
    assert code in client.get(f"/requests/{d['req_id']}/audit", headers=H("amy")).text


# ---------------------------------------------------------------- part 4: rules editor backup gap


@pytest.fixture
def two_hat_users(client):
    """Fixture people no one in users.csv matches: a BU Head who also raises requests, and a BU
    Head whose escalation backup raises requests."""
    from sqlalchemy import delete, text

    from services.api.db import models as m
    from services.api.db.session import session_scope

    ids = ("zz.twohat", "zz.lead", "zz.backup")
    with session_scope(write=True) as s:
        s.add_all(
            [
                m.User(user_id="zz.twohat", name="Tan Two Hats", title="BU Head and sales",
                       roles=["bu_head", "requestor"], entity="SPD", country="SG"),
                m.User(user_id="zz.lead", name="Lee Lead", title="BU Head",
                       roles=["bu_head"], entity="SPD", country="SG"),
                m.User(user_id="zz.backup", name="Bea Backup", title="Deputy and sales",
                       roles=["bu_head", "requestor"], entity="SPD", country="SG",
                       backup_for="zz.lead"),
            ]
        )  # fmt: skip
    yield
    with session_scope(write=True) as s:
        s.execute(text("DELETE FROM routing_overrides"))
        s.execute(delete(m.User).where(m.User.user_id.in_(ids)))


def put_rule(client, user_id):
    return client.put(
        "/admin/routing-rules",
        headers=H("priya"),
        json={
            "domain": "customer",
            "entity": "SPD",
            "country": "SG",
            "steps": [
                {"role": "bu_head", "user_id": user_id},
                {"role": "finance", "user_id": "weijie"},
            ],
        },
    )


def test_an_approver_who_also_raises_requests_is_refused(client, two_hat_users):
    r = put_rule(client, "zz.twohat")
    assert r.status_code == 422
    assert r.json()["detail"] == (
        "Tan Two Hats also raises requests, so they could be the person who raised the request. "
        "They cannot be an approver here. Choose someone else."
    )


def test_an_approver_whose_backup_raises_requests_is_refused(client, two_hat_users):
    r = put_rule(client, "zz.lead")
    assert r.status_code == 422
    assert r.json()["detail"] == (
        "Lee Lead's backup (Bea Backup) could be the person who raised the request, so Lee Lead "
        "cannot be an approver here. Choose someone else."
    )
    # the "who would approve this?" preview checks a draft the same way
    r = client.post(
        "/admin/routing-rules/preview",
        headers=H("priya"),
        json={
            "domain": "customer",
            "entity": "SPD",
            "country": "SG",
            "steps": [{"role": "bu_head", "user_id": "zz.lead"}],
        },
    )
    assert r.status_code == 422 and "Bea Backup" in r.json()["detail"]
    rules = client.get("/admin/routing-rules", headers=H("priya")).json()["rules"]
    assert not any(x["is_override"] for x in rules)  # nothing was saved


def test_the_people_in_users_csv_still_save(client, two_hat_users):
    r = put_rule(client, "kelvin")  # Kelvin Ong: BU Head; no backup who raises requests
    assert r.status_code == 200, r.text
