import sqlite3

import pytest
from sqlalchemy import inspect, select, text

from services.api.audit import verify_chain
from services.api.crypto import KEY_ENV, MissingEncryptionKeyError
from services.api.db import models as m
from services.api.db.seed import FILES, SeedError, main, seed_database
from services.api.db.session import make_engine, make_session_factory
from tests.db_helpers import count_lines, enc_key, make_fixture_dir, sim_clock  # noqa: F401

pytestmark = pytest.mark.usefixtures("enc_key", "sim_clock")


@pytest.fixture
def fixtures(tmp_path):
    return make_fixture_dir(tmp_path / "fixtures")


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "app.db"


def test_seed_row_counts_match_files(fixtures, db_path):
    counts = seed_database(fixtures, db_path)

    n_bp = count_lines(fixtures / "bp_records.csv") + count_lines(fixtures / "vendors.csv")
    assert counts["business_partners"] == n_bp
    assert counts["bank_accounts"] == count_lines(fixtures / "vendors.csv")  # one per vendor
    assert counts["items"] == count_lines(fixtures / "items.csv")
    assert counts["item_registrations"] == count_lines(fixtures / "item_registrations.csv")
    assert counts["users"] == count_lines(fixtures / "users.csv")
    assert counts["orders"] == count_lines(fixtures / "orders.csv") == 3
    assert counts["enquiries"] == 2
    assert counts["dirty_demand"] == 2
    assert counts["mdm_history"] == 2
    assert counts["emails"] == 2

    # The counts reported are what is really in the file.
    engine = make_engine(db_path)
    with make_session_factory(engine)() as s:
        for name, model in (
            ("business_partners", m.BusinessPartner),
            ("bank_accounts", m.BankAccount),
            ("users", m.User),
        ):
            assert len(s.scalars(select(model)).all()) == counts[name]
        assert verify_chain(s).ok
        first = s.scalars(select(m.AuditLog)).one()
        assert (first.action, first.actor) == ("seed", "system")
    engine.dispose()


def test_seed_is_idempotent(fixtures, db_path):
    first = seed_database(fixtures, db_path)
    second = seed_database(fixtures, db_path)
    assert first == second
    engine = make_engine(db_path)
    with make_session_factory(engine)() as s:
        assert len(s.scalars(select(m.AuditLog)).all()) == 1  # fresh chain, not appended to
        assert verify_chain(s).ok
    engine.dispose()


def test_golden_id_is_not_in_any_table(fixtures, db_path):
    assert (fixtures / "customers_golden.csv").exists()  # ground truth is in the folder ...
    seed_database(fixtures, db_path)
    engine = make_engine(db_path)
    insp = inspect(engine)
    for table in insp.get_table_names():
        for col in insp.get_columns(table):
            assert "golden" not in col["name"].lower(), f"{table}.{col['name']}"
    with engine.connect() as conn:  # ... and none of it reached the database
        ids = {r[0] for r in conn.execute(text("select CardCode from business_partners"))}
    assert ids  # sanity
    engine.dispose()


def test_ground_truth_files_are_never_read(fixtures, db_path):
    # Corrupt the ground truth: if the loader opened it, seeding would fail.
    (fixtures / "customers_golden.csv").write_bytes(b"\xff\xfe not csv")
    for f in (fixtures / "ground_truth").iterdir():
        f.write_bytes(b"\xff\xfe not csv")
    seed_database(fixtures, db_path)


def test_bank_account_numbers_are_encrypted_at_rest(fixtures, db_path):
    seed_database(fixtures, db_path)
    vendors = fixtures / "vendors.csv"
    import csv

    with vendors.open(encoding="utf-8") as fh:
        by_code = {r["CardCode"]: r for r in csv.DictReader(fh)}

    # Raw SQL, no decryption: ciphertext only.
    con = sqlite3.connect(db_path)
    raw = con.execute("select CardCode, AccountNo, IBAN, BankCode, BICSwiftCode from bank_accounts")
    rows = raw.fetchall()
    con.close()
    assert rows
    for code, account_no, iban, bank_code, bic in rows:
        src = by_code[code]
        assert account_no != src["AccountNo"]
        assert src["AccountNo"] not in account_no
        assert account_no.startswith("gAAAA")  # Fernet token
        if src["IBAN"]:
            assert iban.startswith("gAAAA") and src["IBAN"] not in iban
        else:
            assert iban is None
        # Public bank identifiers are not encrypted (documented in crypto.py).
        assert bank_code == src["BankCode"]
        assert bic == src["BICSwiftCode"]
    # The database file itself holds no plain account number.
    blob = db_path.read_bytes()
    for src in by_code.values():
        assert src["AccountNo"].encode() not in blob

    # With the key the ORM decrypts it.
    engine = make_engine(db_path)
    with make_session_factory(engine)() as s:
        accounts = {a.CardCode: a for a in s.scalars(select(m.BankAccount))}
    engine.dispose()
    assert accounts["V00001"].AccountNo == by_code["V00001"]["AccountNo"]
    assert accounts["V00002"].IBAN == by_code["V00002"]["IBAN"]


def test_decrypt_with_the_wrong_key_fails_clearly(fixtures, db_path, monkeypatch):
    from cryptography.fernet import Fernet

    from services.api.crypto import DecryptionError

    seed_database(fixtures, db_path)
    monkeypatch.setenv(KEY_ENV, Fernet.generate_key().decode())
    engine = make_engine(db_path)
    with make_session_factory(engine)() as s, pytest.raises(DecryptionError, match=KEY_ENV):
        s.scalars(select(m.BankAccount)).all()
    engine.dispose()


def test_missing_key_gives_clear_error_and_leaves_db_alone(fixtures, db_path, monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)
    with pytest.raises(MissingEncryptionKeyError, match="FIELD_ENCRYPTION_KEY"):
        seed_database(fixtures, db_path)
    assert not db_path.exists()  # nothing was created, nothing dropped


def test_missing_file_is_reported_by_name(fixtures, db_path):
    (fixtures / "orders.csv").unlink()
    (fixtures / "emails.jsonl").unlink()
    with pytest.raises(SeedError) as exc:
        seed_database(fixtures, db_path)
    assert "orders.csv" in str(exc.value) and "emails.jsonl" in str(exc.value)
    assert not db_path.exists()


def test_missing_folder_is_reported(tmp_path, db_path):
    with pytest.raises(SeedError, match="not found"):
        seed_database(tmp_path / "nope", db_path)


def test_missing_column_is_reported_with_columns_found(fixtures, db_path):
    p = fixtures / "orders.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("doc_date", "date_of_doc", 1), "utf-8")
    with pytest.raises(SeedError, match=r"orders\.csv: missing column\(s\) doc_date"):
        seed_database(fixtures, db_path)


def test_unknown_role_is_rejected(fixtures, db_path):
    p = fixtures / "users.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("finance", "wizard", 1), "utf-8")
    with pytest.raises(SeedError, match="unknown role"):
        seed_database(fixtures, db_path)


def test_bad_value_names_file_row_and_column(fixtures, db_path):
    p = fixtures / "orders.csv"
    p.write_text(p.read_text(encoding="utf-8").replace("2026-01-12", "12/01/2026"), "utf-8")
    with pytest.raises(SeedError, match=r"orders\.csv row 2, column doc_date"):
        seed_database(fixtures, db_path)


def test_failed_seed_does_not_wipe_existing_db(fixtures, db_path):
    seed_database(fixtures, db_path)
    (fixtures / "items.csv").unlink()
    with pytest.raises(SeedError):
        seed_database(fixtures, db_path)
    engine = make_engine(db_path)
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from users")).scalar() == 9
    engine.dispose()


def test_users_loaded_with_roles_and_backup(fixtures, db_path):
    seed_database(fixtures, db_path)
    engine = make_engine(db_path)
    with make_session_factory(engine)() as s:
        users = {u.user_id: u for u in s.scalars(select(m.User))}
    engine.dispose()
    assert users["daniel"].roles == ["bu_head", "requestor"]
    assert users["jun"].backup_for == "weijie"


def test_v2_tables_content(fixtures, db_path):
    seed_database(fixtures, db_path)
    engine = make_engine(db_path)
    with make_session_factory(engine)() as s:
        hist = s.get(m.MdmHistory, "H-0001")
        assert hist.bounced_for_missing_fields is True and hist.bounce_count == 1
        assert hist.extra == {
            "approval_1_at": "2025-01-10 10:00",
            "approval_2_at": "2025-01-15 11:00",
        }
        assert hist.submitted_at.utcoffset().total_seconds() == 8 * 3600
        assert s.get(m.MdmHistory, "H-0002").keyed_at is None
        email = s.get(m.Email, "DEMO-03")
        assert email.attachments == ["PO_118.pdf"] and email.to_address == "orders@lives.example"
        assert s.get(m.Enquiry, "EQ200002").kind == "purchase_request"
        assert s.scalars(select(m.DirtyDemand).where(m.DirtyDemand.leak_source == "enquiry")).one()
        reg = s.scalars(select(m.ItemRegistration).where(m.ItemRegistration.status == "expired"))
        assert reg.one().item_code == "A-CRP-QT"
    engine.dispose()


def test_every_file_has_a_spec_and_columns_use_sap_names():
    assert {s.filename for s in FILES.values()} == {
        "users.csv", "bp_records.csv", "vendors.csv", "items.csv", "item_registrations.csv",
        "orders.csv", "enquiries.csv", "dirty_demand.csv", "mdm_requests_history.csv",
        "emails.jsonl",
    }  # fmt: skip
    cols = {c.name for c in m.BusinessPartner.__table__.columns}
    assert {"CardCode", "CardName", "CardType", "FederalTaxID", "Frozen", "U_Entity"} <= cols


def test_cli_prints_counts_and_fails_loudly(fixtures, db_path, capsys):
    assert main(["--fixtures", str(fixtures), "--db", str(db_path)]) == 0
    out = capsys.readouterr().out
    assert "business_partners" in out and "bank_accounts" in out

    (fixtures / "orders.csv").unlink()
    assert main(["--fixtures", str(fixtures), "--db", str(db_path)]) == 1
    assert "orders.csv" in capsys.readouterr().err


def test_failure_mid_load_keeps_the_old_database(fixtures, db_path):

    seed_database(fixtures, db_path)
    before = db_path.read_bytes()
    # A vendor that reuses a customer's CardCode breaks the primary key part-way through the load.
    vendors = fixtures / "vendors.csv"
    first_customer = (fixtures / "bp_records.csv").read_text(encoding="utf-8").splitlines()[1]
    code = first_customer.split(",")[0]
    vendors.write_text(vendors.read_text(encoding="utf-8").replace("V00001", code, 1), "utf-8")
    with pytest.raises(SeedError, match="database rule"):
        seed_database(fixtures, db_path)
    assert db_path.read_bytes() == before  # the file was never touched
    assert sorted(p.name for p in db_path.parent.glob("app.db*")) == ["app.db"]  # no temp left
    engine = make_engine(db_path)
    with engine.connect() as conn:
        assert conn.execute(text("select count(*) from users")).scalar() == 9
    engine.dispose()


def test_cli_reports_a_malformed_key_instead_of_a_traceback(fixtures, db_path, monkeypatch, capsys):
    monkeypatch.setenv(KEY_ENV, "not-a-fernet-key")
    assert main(["--fixtures", str(fixtures), "--db", str(db_path)]) == 1
    assert "not a valid Fernet key" in capsys.readouterr().err
    assert not db_path.exists()
