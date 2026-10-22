import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from services.api.audit import verify_chain
from services.api.db import models as m
from services.api.db.session import create_schema, make_engine, make_session_factory
from services.api.sap_publisher import (
    SapAddress,
    SapBankAccount,
    SapBusinessPartner,
    SapItem,
    SapProfitCenter,
    SapPublisher,
    diff_payload,
)
from services.sap_mock.main import SESSION_TIMEOUT_MINUTES, create_app
from tests.db_helpers import sim_clock  # noqa: F401

pytestmark = pytest.mark.usefixtures("sim_clock")

BASE = "http://testserver/b1s/v2"
ACCOUNT_NO = "7270029477123"
IBAN = "DE15580643003041434261"


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance_minutes(self, minutes: float) -> None:
        self.t += minutes * 60


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def sap(clock):
    return create_app(clock=clock)


@pytest.fixture
def factory(tmp_path):
    engine = make_engine(tmp_path / "pub.db")
    create_schema(engine)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def pub(sap, factory):
    p = SapPublisher(session_factory=factory, base_url=BASE, client=TestClient(sap), retry_wait=0)
    yield p
    p.close()


def audit_rows(factory):
    with factory() as s:
        return s.scalars(select(m.AuditLog).order_by(m.AuditLog.id)).all()


def vendor(code="V90001", **kw):
    return SapBusinessPartner(
        CardCode=code,
        CardName="Lumira Medical Manufacturing Pte Ltd",
        CardType="cSupplier",
        FederalTaxID="199309000T",
        Currency="SGD",
        PayTermsGrpCode=2,
        CreditLimit=0.0,
        EmailAddress="ar@lumira.sg.example",
        U_Entity="QTS",
        U_MDM_ReqID="REQ-0042",
        BPAddresses=[
            SapAddress(AddressName="HQ", AddressType="bo_BillTo", City="Singapore", Country="SG")
        ],
        BPBankAccounts=[
            SapBankAccount(
                BankCode="6496",
                AccountNo=ACCOUNT_NO,
                AccountName="Lumira Medical Manufacturing Pte Ltd",
                BICSwiftCode="IRFESGBG",
                IBAN=IBAN,
                Country="SG",
            )
        ],
        **kw,
    )


# ---------------------------------------------------------------- happy paths


def test_business_partner_happy_path(pub, sap, factory):
    res = pub.publish(vendor(), request_id="REQ-0042")
    assert res.ok and res.stage == "done" and res.final_state == "active"
    assert res.error is None and res.mismatches == []
    assert res.resource == "BusinessPartners" and res.key == "V90001"
    stored = sap.state.stores["BusinessPartners"]["V90001"]
    assert stored["Frozen"] == "tNO"  # created tYES, activated by the PATCH
    assert stored["BPBankAccounts"][0]["AccountNo"] == ACCOUNT_NO  # SAP itself holds it
    assert stored["CardType"] == "cSupplier" and stored["U_MDM_ReqID"] == "REQ-0042"
    assert sap.state.sessions == {}  # logged out at the end

    paths = [(r.entity_type, json.loads(r.payload)) for r in audit_rows(factory)]
    flow = [(p["method"], p["path"], p["status"]) for _, p in paths]
    assert flow == [
        ("POST", "/Login", 200),
        ("POST", "/BusinessPartners", 201),
        ("GET", "/BusinessPartners('V90001')", 200),
        ("PATCH", "/BusinessPartners('V90001')", 204),
        ("POST", "/Logout", 204),
    ]
    assert res.calls == 5 and res.relogins == 0


def test_the_post_is_sent_inactive_whatever_the_caller_set(pub, sap, monkeypatch):
    seen = []
    orig = pub._client.request

    def spy(method, url, **kw):
        if method == "POST" and url.endswith("/BusinessPartners"):
            seen.append(kw["json"]["Frozen"])
        return orig(method, url, **kw)

    monkeypatch.setattr(pub._client, "request", spy)
    assert pub.publish(vendor()).ok
    assert seen == ["tYES"]


def test_item_happy_path(pub, sap):
    item = SapItem(
        ItemCode="A-MAL-PFPAN",
        ItemName="Malaria Pf/Pan Antigen Rapid Test Kit",
        ItemsGroupCode=101,
        PurchaseItem="tYES",
        SalesItem="tYES",
        InventoryItem="tYES",
        U_IVD="tYES",
        U_RegSummary="SG pending; MY pending; VN pending",
    )
    res = pub.publish(item, request_id="REQ-0043")
    assert res.ok and res.final_state == "active" and res.resource == "Items"
    stored = sap.state.stores["Items"]["A-MAL-PFPAN"]
    assert stored["Frozen"] == "tNO" and stored["U_IVD"] == "tYES"


def test_profit_center_uses_active_not_frozen(pub, sap, factory):
    pc = SapProfitCenter(
        CenterCode="CC-VN01", CenterName="VN Sales", EffectiveFrom="2026-10-05", InWhichDimension=1
    )
    res = pub.publish(pc, request_id="REQ-0044")
    assert res.ok and res.final_state == "active" and res.resource == "ProfitCenters"
    stored = sap.state.stores["ProfitCenters"]["CC-VN01"]
    assert stored["Active"] == "tYES" and "Frozen" not in stored
    bodies = [json.loads(r.payload)["body"] for r in audit_rows(factory)]
    assert {"Active": "tYES"} in bodies  # the activating PATCH
    created = next(b for b in bodies if b and b.get("CenterCode") == "CC-VN01")
    assert created["Active"] == "tNO"  # first created inactive


def test_entity_path_escapes_quotes_the_odata_way():
    from services.api.sap_publisher import _entity_path

    assert _entity_path("BusinessPartners", "C00123") == "/BusinessPartners('C00123')"
    assert _entity_path("ProfitCenters", "O'NEIL") == "/ProfitCenters('O%27%27NEIL')"
    assert _entity_path("Items", "A B/1") == "/Items('A%20B%2F1')"


# ---------------------------------------------------------------- failures


def test_duplicate_key_is_a_typed_failure(pub, sap, factory):
    assert pub.publish(vendor()).ok
    res = pub.publish(vendor(), request_id="REQ-0099")
    assert not res.ok and res.stage == "create" and res.final_state == "not_created"
    assert res.error.http_status == 400 and res.error.code == -5002
    assert "already exists" in res.error.message
    # the failed attempt was still audited, with the B1 code, and it logged out cleanly
    failed = [r for r in audit_rows(factory) if r.request_id == "REQ-0099"]
    post = next(
        json.loads(r.payload)
        for r in failed
        if json.loads(r.payload)["method"] == "POST"
        and json.loads(r.payload)["path"] == "/BusinessPartners"
    )
    assert post["status"] == 400 and post["b1_error_code"] == -5002
    assert sap.state.sessions == {}


def test_existing_record_is_left_untouched_by_a_duplicate_attempt(pub, sap):
    pub.publish(vendor())
    before = dict(sap.state.stores["BusinessPartners"]["V90001"])
    pub.publish(vendor())
    assert sap.state.stores["BusinessPartners"]["V90001"] == before


def test_login_failure_is_typed(sap, factory):
    p = SapPublisher(
        session_factory=factory, base_url=BASE, client=TestClient(sap), password="wrong"
    )
    res = p.publish(vendor())
    assert not res.ok and res.stage == "login" and res.final_state == "not_created"
    assert res.error.http_status == 401 and res.error.code == -304
    methods = [json.loads(r.payload)["path"] for r in audit_rows(factory)]
    assert methods == ["/Login"]  # no resource call and no logout after a failed login
    # the password never reaches the audit log
    assert "wrong" not in " ".join(r.payload for r in audit_rows(factory))


def test_expired_session_relogs_in_once_and_succeeds(sap, factory, clock):
    client = TestClient(sap)

    def expire_after_post(response: httpx.Response) -> None:
        if response.request.method == "POST" and response.request.url.path.endswith("/Items"):
            clock.advance_minutes(SESSION_TIMEOUT_MINUTES + 1)

    client.event_hooks["response"].append(expire_after_post)
    p = SapPublisher(session_factory=factory, base_url=BASE, client=client, retry_wait=0)
    res = p.publish(SapItem(ItemCode="X-EXP-1", ItemName="Session expiry test", U_IVD="tNO"))
    assert res.ok and res.final_state == "active"
    assert res.relogins == 1
    flow = [
        (
            json.loads(r.payload)["method"],
            json.loads(r.payload)["path"],
            json.loads(r.payload)["status"],
        )
        for r in audit_rows(factory)
    ]
    assert flow == [
        ("POST", "/Login", 200),
        ("POST", "/Items", 201),
        ("GET", "/Items('X-EXP-1')", 401),  # session had timed out
        ("POST", "/Login", 200),  # one re-login
        ("GET", "/Items('X-EXP-1')", 200),
        ("PATCH", "/Items('X-EXP-1')", 204),
        ("POST", "/Logout", 204),
    ]
    assert sap.state.stores["Items"]["X-EXP-1"]["Frozen"] == "tNO"


def test_second_401_is_not_retried_forever():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/Login"):
            return httpx.Response(200, json={"SessionId": "s", "SessionTimeout": 30})
        err = {"error": {"code": 301, "message": {"lang": "en-us", "value": "Invalid session."}}}
        return httpx.Response(401, json=err)

    engine_free_calls = calls
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as d:
        engine = make_engine(f"{d}/x.db")
        create_schema(engine)
        p = SapPublisher(
            session_factory=make_session_factory(engine),
            base_url=BASE,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        from services.api import clock as sim

        sim.reset()
        res = p.publish(SapItem(ItemCode="X", ItemName="y"))
        engine.dispose()
    assert not res.ok and res.stage == "create" and res.error.code == 301
    assert res.relogins == 1
    assert engine_free_calls.count(("POST", "/b1s/v2/Login")) == 2  # initial + one re-login
    assert engine_free_calls.count(("POST", "/b1s/v2/Items")) == 2  # the POST ran twice only
    assert engine_free_calls.count(("POST", "/b1s/v2/Logout")) == 1


def test_sap_unreachable_is_a_typed_failure(factory):
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        raise httpx.ConnectError("refused", request=request)

    p = SapPublisher(
        session_factory=factory,
        base_url=BASE,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        retry_wait=0,
        connect_retries=3,
    )
    res = p.publish(vendor())
    assert not res.ok and res.stage == "login" and res.error.http_status is None
    assert "could not be reached" in res.error.message
    assert len(attempts) == 3  # tenacity retried the connection, then gave up


def test_payload_models_reject_what_b1_would_reject():
    with pytest.raises(ValueError):
        SapBusinessPartner(CardCode="C" * 16, CardName="x")  # CardCode is at most 15 characters
    with pytest.raises(ValueError):
        SapItem(ItemCode="X", ItemName="y", SalesItem="tyes")  # tYES is case-sensitive
    with pytest.raises(ValueError):
        SapBusinessPartner(CardCode="C1", CardName="x", CardType="customer")


def test_readback_mismatch_leaves_record_inactive(pub, sap, factory, monkeypatch):
    orig = pub._client.request

    def tamper(method, url, **kw):
        resp = orig(method, url, **kw)
        if method == "POST" and url.endswith("/BusinessPartners"):
            sap.state.stores["BusinessPartners"]["V90001"]["CardName"] = "Changed in transit"
            sap.state.stores["BusinessPartners"]["V90001"]["BPBankAccounts"][0]["AccountNo"] = (
                "0000111122223333"
            )
        return resp

    monkeypatch.setattr(pub._client, "request", tamper)
    res = pub.publish(vendor())
    assert not res.ok and res.stage == "verify" and res.final_state == "inactive"
    fields = {mm.field for mm in res.mismatches}
    assert fields == {"CardName", "BPBankAccounts[0].AccountNo"}
    assert sap.state.stores["BusinessPartners"]["V90001"]["Frozen"] == "tYES"  # not activated
    # mismatch report masks bank values
    dump = res.model_dump_json()
    assert ACCOUNT_NO not in dump and "0000111122223333" not in dump
    assert "****3333" in dump
    assert "PATCH" not in " ".join(r.payload for r in audit_rows(factory))


# ---------------------------------------------------------------- audit and masking


def test_every_call_is_audited_and_no_bank_number_is_in_the_log(pub, factory):
    pub.publish(vendor(), request_id="REQ-0042")
    pub.publish(vendor(), request_id="REQ-0042")  # duplicate attempt as well
    rows = audit_rows(factory)
    assert len(rows) == 5 + 3  # full flow + login, failed POST, logout
    assert {r.actor for r in rows} == {"sap_publisher"}
    assert {r.action for r in rows} == {"sap_call"}
    assert {r.request_id for r in rows} == {"REQ-0042"}
    dump = " ".join(r.payload for r in rows)
    for secret in (ACCOUNT_NO, IBAN, "IRFESGBG", "6496", '"Password"', "demo"):
        assert secret not in dump, secret
    post = json.loads(next(r for r in rows if r.entity_type == "BusinessPartners").payload)
    acct = post["body"]["BPBankAccounts"][0]
    assert acct["AccountNo"] == "****7123" and acct["IBAN"] == "****4261"
    assert acct["Country"] == "SG" and acct["AccountName"] == "****"
    with factory() as s:
        assert verify_chain(s).ok


def test_audit_timestamps_follow_the_simulated_clock(pub, factory):
    from services.api import clock as sim

    pub.publish(SapItem(ItemCode="T-1", ItemName="One"))
    sim.advance(days=1)
    pub.publish(SapItem(ItemCode="T-2", ItemName="Two"))
    rows = audit_rows(factory)
    assert rows[0].ts == sim.CLOCK_START.isoformat()
    assert rows[-1].ts == (sim.CLOCK_START.replace(day=sim.CLOCK_START.day + 1)).isoformat()


# ---------------------------------------------------------------- compare helper


def test_diff_payload_compares_nested_fields_and_numbers():
    sent = {"CreditLimit": 1000, "BPAddresses": [{"City": "A"}], "Frozen": "tYES"}
    got = {"CreditLimit": 1000.0, "BPAddresses": [{"City": "B"}], "Frozen": "tYES", "extra": 1}
    assert [(d.field, d.sent, d.received) for d in diff_payload(sent, got)] == [
        ("BPAddresses[0].City", "A", "B")
    ]
    assert diff_payload({"A": "x"}, {})[0].received is None
    assert diff_payload({"L": [1, 2]}, {"L": [1]})[0].field == "L[]"


# ---------------------------------------------------------------- QA round: failures and masking


def _b1_error(status, code, value):
    return httpx.Response(
        status, json={"error": {"code": code, "message": {"lang": "en-us", "value": value}}}
    )


def test_patch_failure_after_good_read_back_leaves_record_inactive(pub, sap, factory, monkeypatch):
    orig = pub._client.request

    def fail_patch(method, url, **kw):
        if method == "PATCH":
            return _b1_error(400, -10, "Property 'Frozen' is invalid")
        return orig(method, url, **kw)

    monkeypatch.setattr(pub._client, "request", fail_patch)
    res = pub.publish(vendor(), request_id="REQ-7")
    assert not res.ok and res.stage == "activate" and res.final_state == "inactive"
    assert res.error.code == -10 and res.error.http_status == 400
    assert res.mismatches == []
    assert sap.state.stores["BusinessPartners"]["V90001"]["Frozen"] == "tYES"
    last = json.loads(audit_rows(factory)[-2].payload)  # the failed PATCH, then Logout
    assert (last["method"], last["status"], last["b1_error_code"]) == ("PATCH", 400, -10)


def test_b1_error_text_is_redacted_before_audit_and_result(factory):
    def handler(request):
        if request.url.path.endswith("/Login"):
            return httpx.Response(200, json={"SessionId": "s", "SessionTimeout": 30})
        if request.url.path.endswith("/Logout"):
            return httpx.Response(204)
        return _b1_error(400, -5002, "Account 7270029477123 and DE15580643003041434261 exist")

    p = SapPublisher(
        session_factory=factory,
        base_url=BASE,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    res = p.publish(vendor())
    assert res.error.code == -5002
    assert "7270029477123" not in res.error.message and "[redacted]" in res.error.message
    dump = " ".join(r.payload for r in audit_rows(factory))
    assert "7270029477123" not in dump and "15580643003041434261" not in dump


def test_unreadable_error_body_is_not_copied(factory):
    def handler(request):
        if request.url.path.endswith("/Login"):
            return httpx.Response(200, json={"SessionId": "s", "SessionTimeout": 30})
        if request.url.path.endswith("/Logout"):
            return httpx.Response(204)
        return httpx.Response(500, text="boom account 1234567890123456")

    p = SapPublisher(
        session_factory=factory,
        base_url=BASE,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    res = p.publish(vendor())
    assert res.error.http_status == 500 and res.error.code is None
    assert "1234567890123456" not in res.error.message
    assert "1234567890123456" not in " ".join(r.payload for r in audit_rows(factory))


def _fail_audit_from(monkeypatch, n):
    """Make the n-th and later audit writes fail (1-based)."""
    import services.api.sap_publisher as mod

    real, seen = mod.append_audit, {"n": 0}

    def flaky(*a, **kw):
        seen["n"] += 1
        if seen["n"] >= n:
            raise OperationalError("insert", None, Exception("database is locked"))
        return real(*a, **kw)

    monkeypatch.setattr(mod, "append_audit", flaky)


def test_audit_failure_at_login_stops_before_any_record_is_created(pub, sap, monkeypatch):
    _fail_audit_from(monkeypatch, 1)
    res = pub.publish(vendor())
    assert not res.ok and res.audit_failed and res.stage == "login"
    assert res.final_state == "not_created" and "audit log" in res.error.message
    assert sap.state.stores["BusinessPartners"] == {}


def test_audit_failure_after_create_leaves_record_inactive(pub, sap, monkeypatch):
    _fail_audit_from(monkeypatch, 2)  # Login audited; the POST's audit row fails
    res = pub.publish(vendor())
    assert not res.ok and res.audit_failed and res.stage == "create"
    assert res.final_state == "inactive"
    assert sap.state.stores["BusinessPartners"]["V90001"]["Frozen"] == "tYES"
    assert "7270029477123" not in res.model_dump_json()


def test_audit_failure_on_activation_reports_the_real_state(pub, sap, monkeypatch):
    _fail_audit_from(monkeypatch, 4)  # Login, POST, GET fine; PATCH's audit row fails
    res = pub.publish(vendor())
    assert not res.ok and res.audit_failed and res.stage == "activate"
    assert res.final_state == "active"  # SAP did activate it; the result says so
    assert sap.state.stores["BusinessPartners"]["V90001"]["Frozen"] == "tNO"


def test_publish_documents_the_transaction_rule():
    assert "OUTSIDE any open write transaction" in SapPublisher.publish.__doc__


def test_demo_password_only_for_local_hosts(monkeypatch):
    monkeypatch.delenv("SAP_PASSWORD", raising=False)
    for url in (
        "http://localhost:8001/b1s/v2",
        "http://127.0.0.1:8001/b1s/v2",
        "http://testserver/b1s/v2",
    ):
        SapPublisher(base_url=url).close()
    with pytest.raises(ValueError, match="SAP_PASSWORD"):
        SapPublisher(base_url="https://sap.lives.example:50000/b1s/v2")
    SapPublisher(base_url="https://sap.lives.example:50000/b1s/v2", password="real").close()
    monkeypatch.setenv("SAP_PASSWORD", "from-env")
    SapPublisher(base_url="https://sap.lives.example:50000/b1s/v2").close()


def test_card_type_is_required():
    with pytest.raises(ValueError, match="CardType"):
        SapBusinessPartner(CardCode="C1", CardName="No type")


def test_mismatch_report_masks_nested_bank_values():
    sent = {"BPBankAccounts": [{"AccountNo": "1111222233334444", "IBAN": "DE00111122223333"}]}
    got = {"BPBankAccounts": [{"AccountNo": {"digits": ["9999888877776666"]}, "IBAN": ["x"]}]}
    dump = " ".join(f"{d.field} {d.sent} {d.received}" for d in diff_payload(sent, got))
    for secret in ("1111222233334444", "9999888877776666", "DE00111122223333"):
        assert secret not in dump
    # a nested dict received under a non-bank field is scrubbed too
    d = diff_payload({"Note": "x"}, {"Note": {"IBAN": "DE00111122223333", "n": 1}})[0]
    assert "DE00111122223333" not in str(d.received) and d.received["n"] == 1
