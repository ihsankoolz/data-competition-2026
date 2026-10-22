import sqlite3
from datetime import timedelta

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from services.api import clock, crypto
from services.api.db import models as m
from services.api.db.session import (
    DB_PATH_ENV,
    DEFAULT_DB_PATH,
    create_schema,
    default_db_path,
    make_engine,
    make_session_factory,
    reset_schema,
)
from services.api.personas import PERSONAS
from tests.db_helpers import enc_key, sim_clock  # noqa: F401

pytestmark = pytest.mark.usefixtures("enc_key", "sim_clock")


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(tmp_path / "t.db")
    create_schema(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def factory(engine):
    return make_session_factory(engine)


def test_all_tables_are_created(engine):
    assert set(inspect(engine).get_table_names()) == {
        "users",
        "business_partners",
        "bank_accounts",
        "items",
        "item_registrations",
        "orders",
        "enquiries",
        "dirty_demand",
        "mdm_history",
        "emails",
        "requests",
        "audit_log",
        "audit_head",
        "approval_tasks",
        "notifications",
        "dedup_decisions",
        "app_state",
    }


def test_db_path_is_configurable(tmp_path, monkeypatch):
    monkeypatch.delenv(DB_PATH_ENV)  # tests/conftest.py points it at a throw-away path
    assert default_db_path() == DEFAULT_DB_PATH
    assert DEFAULT_DB_PATH.parts[-2:] == ("data", "app.db")
    monkeypatch.setenv(DB_PATH_ENV, str(tmp_path / "elsewhere" / "x.db"))
    assert default_db_path() == tmp_path / "elsewhere" / "x.db"
    eng = make_engine()  # creates the parent folder
    create_schema(eng)
    eng.dispose()
    assert (tmp_path / "elsewhere" / "x.db").exists()


def test_sap_field_names_are_exact(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("business_partners")}
    assert {
        "CardCode", "CardName", "CardForeignName", "CardType", "GroupCode", "FederalTaxID",
        "Currency", "PayTermsGrpCode", "CreditLimit", "EmailAddress", "Phone1", "City",
        "Country", "U_Entity", "CreateDate", "CreatedBy", "Frozen",
    } <= cols  # fmt: skip
    bank = {c["name"] for c in inspect(engine).get_columns("bank_accounts")}
    assert {"CardCode", "BankCode", "AccountNo", "AccountName", "BICSwiftCode", "IBAN"} <= bank
    assert "BankCountry" in bank


def test_no_table_has_a_golden_column(engine):
    insp = inspect(engine)
    for t in insp.get_table_names():
        assert not [c for c in insp.get_columns(t) if "golden" in c["name"].lower()], t


def test_foreign_keys_are_enforced(factory):
    with pytest.raises(IntegrityError), factory.begin() as s:
        s.add(m.BankAccount(CardCode="NOPE", AccountNo="123456"))


def test_bank_account_roundtrip_and_ciphertext_on_disk(engine, factory):
    with factory.begin() as s:
        s.add(m.BusinessPartner(CardCode="V1", CardName="Vendor", CardType="cSupplier"))
        s.flush()
        s.add(
            m.BankAccount(
                CardCode="V1", AccountNo="9876543210", IBAN="DE89370400440532013000", BankCode="42"
            )
        )
    with factory() as s:
        acct = s.scalars(select(m.BankAccount)).one()
        assert acct.AccountNo == "9876543210" and acct.IBAN == "DE89370400440532013000"
    raw = (
        sqlite3.connect(engine.url.database)
        .execute("select AccountNo, IBAN, BankCode from bank_accounts")
        .fetchone()
    )
    assert "9876543210" not in raw[0] and "DE89" not in raw[1]
    assert raw[2] == "42"
    assert crypto.mask(acct.AccountNo) == "****3210"


def test_missing_key_error_names_the_variable(engine, factory, monkeypatch):
    monkeypatch.delenv("FIELD_ENCRYPTION_KEY")
    with factory.begin() as s:
        s.add(m.BusinessPartner(CardCode="V1", CardName="Vendor", CardType="cSupplier"))
    with pytest.raises(StatementError, match="FIELD_ENCRYPTION_KEY") as exc, factory.begin() as s:
        s.add(m.BankAccount(CardCode="V1", AccountNo="5550001234"))
    assert isinstance(exc.value.orig, crypto.MissingEncryptionKeyError)
    assert "5550001234" not in str(exc.value)  # the error text never carries the bank number
    # Rows without bank numbers still work without a key.
    with factory.begin() as s:
        s.add(m.BankAccount(CardCode="V1", BankCode="7"))


def test_invalid_key_is_reported(monkeypatch):
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(crypto.EncryptionKeyError, match="not a valid Fernet key"):
        crypto.encrypt("x")


def test_no_default_key_exists_in_the_source():
    import pathlib

    src = pathlib.Path(crypto.__file__).read_text(encoding="utf-8")
    assert 'environ.get(KEY_ENV, "")' in src  # empty default means "missing", never a real key
    assert "gAAAA" not in src


def test_request_lifecycle_states_and_simulated_timestamps(factory):
    states = {s.value for s in m.RequestState}
    assert states == {
        "DRAFT", "SUBMITTED", "IN_APPROVAL", "INFO_REQUESTED", "REJECTED", "APPROVED",
        "PUBLISHED_INACTIVE", "ACTIVE", "LINKED_TO_EXISTING",
    }  # fmt: skip
    with factory.begin() as s:
        s.add(
            m.User(
                user_id="amy",
                name="Amy",
                title="PM",
                roles=["requestor"],
                entity="SPD",
                country="SG",
            )
        )
    clock.advance(hours=5)
    with factory.begin() as s:
        s.add(
            m.Request(
                req_id="REQ-0001",
                domain=m.RequestDomain.item,
                state=m.RequestState.SUBMITTED,
                requestor_user_id="amy",
                entity="SPD",
                country="SG",
                payload={"ItemName": "Malaria Pf/Pan Antigen Rapid Test Kit"},
                created_at=clock.now(),
                updated_at=clock.now(),
            )
        )
    with factory() as s:
        req = s.get(m.Request, "REQ-0001")
        assert req.state is m.RequestState.SUBMITTED
        assert req.created_at == clock.CLOCK_START + timedelta(hours=5)
        assert req.created_at.utcoffset() == timedelta(hours=8)
        assert req.payload["ItemName"].startswith("Malaria")


def test_request_rejects_unknown_state_and_unknown_requestor(factory):
    with factory.begin() as s:
        s.add(m.User(user_id="amy", name="Amy", title="PM", roles=[], entity="SPD", country="SG"))
    with pytest.raises(StatementError, match="HALF_DONE"), factory.begin() as s:
        s.add(
            m.Request(
                req_id="R1", domain="item", state="HALF_DONE", requestor_user_id="amy",
                entity="SPD", country="SG", created_at=clock.now(), updated_at=clock.now(),
            )
        )  # fmt: skip
    with pytest.raises(IntegrityError), factory.begin() as s:
        s.add(
            m.Request(
                req_id="R2", domain="item", state="DRAFT", requestor_user_id="ghost",
                entity="SPD", country="SG", created_at=clock.now(), updated_at=clock.now(),
            )
        )  # fmt: skip


def test_reset_schema_wipes_everything_including_unknown_tables(engine, factory):
    with factory.begin() as s:
        s.execute(text("CREATE TABLE leftover (x int)"))
        s.add(m.Item(ItemCode="I1", ItemName="One"))
    reset_schema(engine)
    names = set(inspect(engine).get_table_names())
    assert "leftover" not in names and "items" in names
    with factory() as s:
        assert s.scalars(select(m.Item)).all() == []
        head = s.get(m.AuditHead, 1)
        assert (head.last_id, head.last_hash) == (0, "0" * 64)


def test_personas_have_matching_user_ids_in_the_users_contract():
    # users.csv (D-015) must contain these ids; the seed test fixture uses the same list.
    from tests.db_helpers import USERS

    assert {p.user_id for p in PERSONAS} <= {u[0] for u in USERS}
