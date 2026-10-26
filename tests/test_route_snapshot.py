"""No-change guard for approval routing (session 12, item B).

Drives the real API for the demo requests (DEMO-01 customer, DEMO-02 item, DEMO-07 vendor with
bank rows) and for a request that gets "ask for info", is edited and resubmitted. It records the
approval tasks of each (stage, stage name, role, country, assignee, status) and compares them with
`tests/fixtures/routes_main_5b0d37f.json`, generated once on unchanged main.

The snapshot must never be regenerated after routing code changes: with no override saved, routing
has to produce exactly what it produced on main. To (re)create the file from scratch on a commit
whose routing is known good, set `WRITE_ROUTE_SNAPSHOT=1`.
"""

# ruff: noqa: F811  (fixtures imported from test_workflow_api are used by name)
from __future__ import annotations

import json
import os
from pathlib import Path

from ds.interpreter.schemas import Interpretation
from services.api.formfields import prefill_from_interpretation
from tests.test_workflow_api import (  # noqa: F401 - fixtures are used by name
    H,
    _clock,
    client,
    decide,
    new_request,
    sap_mock,
)

OWNS_APP_DB = True  # see tests/conftest.py
SNAPSHOT = Path(__file__).parent / "fixtures" / "routes_main_5b0d37f.json"

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
SG_REG = {"country": "SG", "reg_no": "S-1", "expiry_date": "2030-12-31"}
VN_REG = {"country": "VN", "reg_no": "V-1", "expiry_date": "2030-12-31"}


def tasks(detail) -> list[list]:
    rows = [
        [t["stage"], st["name"], t["role"], t["country"], t["assignee_user_id"], t["status"]]
        for st in detail["stages"]
        for t in st["tasks"]
    ]
    return sorted(rows, key=lambda r: [str(x) for x in r])


def _from_email(client, email_id, user):
    r = client.post(f"/emails/{email_id}/interpret", headers=H(user))
    assert r.status_code == 200, r.text
    interp = Interpretation.model_validate(r.json())
    fields, _ = prefill_from_interpretation(interp.domain, interp)
    return interp.domain, fields


def _submit(client, req_id, user):
    r = client.post(f"/requests/{req_id}/submit", headers=H(user))
    assert r.status_code == 200, r.text
    return r.json()


def record_routes(client) -> dict[str, list]:
    out: dict[str, list] = {}

    # DEMO-01: Marcus, customer, QTG Vietnam. A likely duplicate: a human says it is not.
    domain, fields = _from_email(client, "DEMO-01", "marcus")
    assert domain == "customer"
    # what Marcus types into the form after the email is read
    fields = {
        **fields,
        "Street": "201B Nguyen Chi Thanh",
        "EmailAddress": "mua@choray.example",
    }
    req = new_request(client, "marcus", "customer", "QTG", "VN", fields)
    r = client.post(
        f"/requests/{req['req_id']}/dedup-decision",
        headers=H("marcus"),
        json={"action": "not_duplicate", "reason": "Different hospital, different tax ID"},
    )
    assert r.status_code == 200, r.text
    out["DEMO-01"] = tasks(_submit(client, req["req_id"], "marcus"))

    # DEMO-02: Amy, the malaria kit item, SPD Singapore, sold in SG, MY and VN.
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
    }
    req = new_request(client, "amy", "item", "SPD", "SG", fields)
    out["DEMO-02"] = tasks(_submit(client, req["req_id"], "amy"))

    # DEMO-07: the vendor with bank rows, as the rehearse pre-stage creates it.
    req = new_request(client, "amy", "vendor", "SPD", "SG", VENDOR_DEMO_07)
    out["DEMO-07"] = tasks(_submit(client, req["req_id"], "amy"))

    # Ask for info, then the requestor edits (a new selling country) and resubmits.
    item = {
        "ItemName": "Snapshot Resubmit Rapid Test",
        "U_IVD": "tYES",
        "selling_countries": ["SG"],
        "registrations": [SG_REG],
    }
    req = new_request(client, "amy", "item", "SPD", "SG", item)
    d = _submit(client, req["req_id"], "amy")
    rid = d["req_id"]
    out["info-1-submitted"] = tasks(d)
    by_role = {(t["role"], t["country"]): t for st in d["stages"] for t in st["tasks"]}
    assert decide(client, by_role[("bu_head", None)]["task_id"], "daniel").status_code == 200
    r = decide(
        client,
        by_role[("quality_regulatory", "SG")]["task_id"],
        "joanne",
        "ask_info",
        "Are you selling this anywhere else?",
    )
    assert r.status_code == 200, r.text
    out["info-2-asked"] = tasks(r.json())
    r = client.patch(
        f"/requests/{rid}",
        headers=H("amy"),
        json={"fields": {"selling_countries": ["SG", "VN"], "registrations": [SG_REG, VN_REG]}},
    )
    assert r.status_code == 200, r.text
    out["info-3-resubmitted"] = tasks(_submit(client, rid, "amy"))
    return out


def test_demo_routes_match_the_snapshot_taken_on_main(client):
    got = record_routes(client)
    if os.environ.get("WRITE_ROUTE_SNAPSHOT") == "1":
        SNAPSHOT.write_text(
            json.dumps(got, indent=1, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    want = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert got == want
