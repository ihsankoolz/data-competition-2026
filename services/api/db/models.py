"""SQLAlchemy 2.0 models for the app database.

Business partner, bank account, item and profit-centre columns use the SAP B1 spelling from
D-004/D-014 (`CardCode`, `FederalTaxID`, `Frozen` ...) so mapping to the Service Layer is 1:1.

Ground truth (`customers_golden.csv`, everything under `ground_truth/`) is never loaded here and
no table has a golden-ID column: duplicates are found by the dedup pipeline, not read from labels.

Bank fields: `AccountNo` and `IBAN` are encrypted at rest (`services/api/crypto.py`).
`audit_log` is append-only, enforced by SQLite triggers created together with the table.
"""

from __future__ import annotations

import enum
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from services.api.crypto import EncryptedString

SGT = timezone(timedelta(hours=8))
GENESIS_HASH = "0" * 64


class SimTimestamp(TypeDecorator[datetime]):
    """Timezone-aware timestamp stored as ISO text in SGT (the simulated clock's zone).

    Naive values are taken to be SGT. Text keeps the offset (SQLite DateTime would drop it)
    and sorts correctly because every value shares one offset.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=SGT)
        return value.astimezone(SGT).isoformat()

    def process_result_value(self, value: Any, dialect: Any) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value)


class Base(DeclarativeBase):
    pass


class RequestDomain(enum.StrEnum):
    customer = "customer"
    vendor = "vendor"
    item = "item"
    cost_center = "cost_center"


class RequestState(enum.StrEnum):
    """PRD §7 lifecycle."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_APPROVAL = "IN_APPROVAL"
    INFO_REQUESTED = "INFO_REQUESTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    PUBLISHED_INACTIVE = "PUBLISHED_INACTIVE"
    ACTIVE = "ACTIVE"
    LINKED_TO_EXISTING = "LINKED_TO_EXISTING"


# ---------------------------------------------------------------- people


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(100))
    roles: Mapped[list[str]] = mapped_column(JSON)
    entity: Mapped[str] = mapped_column(String(8))
    country: Mapped[str] = mapped_column(String(2))
    backup_for: Mapped[str | None] = mapped_column(ForeignKey("users.user_id"), nullable=True)


# ---------------------------------------------------------------- SAP master


class BusinessPartner(Base):
    """Customers (`cCustomer`) and vendors (`cSupplier`) in the one shared B1."""

    __tablename__ = "business_partners"

    CardCode: Mapped[str] = mapped_column(String(15), primary_key=True)
    CardName: Mapped[str] = mapped_column(String(100))
    CardForeignName: Mapped[str | None] = mapped_column(String(100))
    CardType: Mapped[str] = mapped_column(String(10), index=True)
    GroupCode: Mapped[int | None] = mapped_column(Integer)
    FederalTaxID: Mapped[str | None] = mapped_column(String(32), index=True)
    Currency: Mapped[str | None] = mapped_column(String(3))
    PayTermsGrpCode: Mapped[int | None] = mapped_column(Integer)
    CreditLimit: Mapped[float | None] = mapped_column(Float)
    EmailAddress: Mapped[str | None] = mapped_column(String(100))
    Phone1: Mapped[str | None] = mapped_column(String(32))
    City: Mapped[str | None] = mapped_column(String(64))
    Country: Mapped[str | None] = mapped_column(String(2), index=True)
    U_Entity: Mapped[str | None] = mapped_column(String(3))
    CreateDate: Mapped[date | None] = mapped_column(Date)
    CreatedBy: Mapped[str | None] = mapped_column(String(32))
    # "inactive until approved" (D-004). Existing records are active (tNO).
    Frozen: Mapped[str] = mapped_column(String(3), default="tNO")
    U_MDM_ReqID: Mapped[str | None] = mapped_column(String(32))


class BankAccount(Base):
    """Vendor bank details. `AccountNo` and `IBAN` are ciphertext in the database file."""

    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    CardCode: Mapped[str] = mapped_column(ForeignKey("business_partners.CardCode"), index=True)
    BankCode: Mapped[str | None] = mapped_column(String(32))
    AccountNo: Mapped[str | None] = mapped_column(EncryptedString)
    AccountName: Mapped[str | None] = mapped_column(String(100))
    BICSwiftCode: Mapped[str | None] = mapped_column(String(11))
    IBAN: Mapped[str | None] = mapped_column(EncryptedString)
    BankCountry: Mapped[str | None] = mapped_column(String(2))


class Item(Base):
    __tablename__ = "items"

    ItemCode: Mapped[str] = mapped_column(String(20), primary_key=True)
    ItemName: Mapped[str] = mapped_column(String(100))
    ItemType: Mapped[str] = mapped_column(String(10), default="itItems")
    ItemsGroupCode: Mapped[int | None] = mapped_column(Integer)
    PurchaseItem: Mapped[str | None] = mapped_column(String(3))
    SalesItem: Mapped[str | None] = mapped_column(String(3))
    InventoryItem: Mapped[str | None] = mapped_column(String(3))
    U_IVD: Mapped[str | None] = mapped_column(String(3))
    Frozen: Mapped[str] = mapped_column(String(3), default="tNO")
    U_MDM_ReqID: Mapped[str | None] = mapped_column(String(32))
    # Not SAP fields: catalogue facts the app needs (family A/B/C, owning entity, price).
    product_family: Mapped[str | None] = mapped_column(String(1))
    entity: Mapped[str | None] = mapped_column(String(3))
    sales_unit: Mapped[str | None] = mapped_column(String(32))
    unit_price_usd: Mapped[float | None] = mapped_column(Float)


class ItemRegistration(Base):
    """Per item x country regulatory registration (production: a B1 user-defined table)."""

    __tablename__ = "item_registrations"
    __table_args__ = (UniqueConstraint("item_code", "country"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_code: Mapped[str] = mapped_column(ForeignKey("items.ItemCode"), index=True)
    country: Mapped[str] = mapped_column(String(2))
    is_ivd: Mapped[bool] = mapped_column(Boolean)
    risk_class: Mapped[str | None] = mapped_column(String(2))
    reg_no: Mapped[str | None] = mapped_column(String(64))
    assumed_format: Mapped[bool] = mapped_column(Boolean, default=False)
    reg_holder_entity: Mapped[str | None] = mapped_column(String(3))
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(10))  # active | pending | expired


# ---------------------------------------------------------------- transactions


class Order(Base):
    """Confirmed customer POs. The only table that feeds demand (domain rule 9)."""

    __tablename__ = "orders"

    # One row per document line: a PO with several items repeats its doc_num.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_num: Mapped[str] = mapped_column(String(32), index=True)
    card_code: Mapped[str] = mapped_column(String(15), index=True)
    entity: Mapped[str] = mapped_column(String(3))
    country: Mapped[str] = mapped_column(String(2))
    item_code: Mapped[str] = mapped_column(String(20), index=True)
    qty: Mapped[float] = mapped_column(Float)
    unit_price_usd: Mapped[float | None] = mapped_column(Float)
    doc_date: Mapped[date] = mapped_column(Date, index=True)
    po_ref: Mapped[str | None] = mapped_column(String(64))
    source_email_id: Mapped[str | None] = mapped_column(String(32))


class Enquiry(Base):
    """Enquiries and purchase requests: a leading indicator, never demand."""

    __tablename__ = "enquiries"

    # One row per document line, like orders.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_num: Mapped[str] = mapped_column(String(32), index=True)
    card_code: Mapped[str] = mapped_column(String(15), index=True)
    entity: Mapped[str] = mapped_column(String(3))
    country: Mapped[str] = mapped_column(String(2))
    item_code: Mapped[str] = mapped_column(String(20), index=True)
    qty: Mapped[float] = mapped_column(Float)
    unit_price_usd: Mapped[float | None] = mapped_column(Float)
    doc_date: Mapped[date] = mapped_column(Date, index=True)
    po_ref: Mapped[str | None] = mapped_column(String(64))
    source_email_id: Mapped[str | None] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(20))  # enquiry | purchase_request
    converted_doc_num: Mapped[str | None] = mapped_column(String(32))


class DirtyDemand(Base):
    """Today's spreadsheet view of demand: orders plus leaked enquiries / MDM emails."""

    __tablename__ = "dirty_demand"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    doc_num: Mapped[str | None] = mapped_column(String(32))
    card_code: Mapped[str] = mapped_column(String(15), index=True)
    entity: Mapped[str | None] = mapped_column(String(3))
    country: Mapped[str | None] = mapped_column(String(2))
    item_code: Mapped[str | None] = mapped_column(String(20))
    qty: Mapped[float] = mapped_column(Float)
    unit_price_usd: Mapped[float | None] = mapped_column(Float)
    doc_date: Mapped[date] = mapped_column(Date)
    po_ref: Mapped[str | None] = mapped_column(String(64))
    source_email_id: Mapped[str | None] = mapped_column(String(32))
    leak_source: Mapped[str | None] = mapped_column(String(32))  # null = a real order


class MdmHistory(Base):
    """MDM requests under the old email process (for the 'before' ops numbers)."""

    __tablename__ = "mdm_history"

    req_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    domain: Mapped[str] = mapped_column(String(20))
    entity: Mapped[str] = mapped_column(String(3))
    country: Mapped[str] = mapped_column(String(2))
    requestor: Mapped[str] = mapped_column(String(64))
    submitted_at: Mapped[datetime] = mapped_column(SimTimestamp)
    keyed_at: Mapped[datetime | None] = mapped_column(SimTimestamp)
    bounced_for_missing_fields: Mapped[bool] = mapped_column(Boolean)
    bounce_count: Mapped[int] = mapped_column(Integer)
    # Every other column in the file (one timestamp per sequential approval), as written.
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Email(Base):
    __tablename__ = "emails"

    email_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(SimTimestamp, index=True)
    from_name: Mapped[str | None] = mapped_column(String(100))
    from_address: Mapped[str] = mapped_column(String(100))
    to_address: Mapped[str | None] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    attachments: Mapped[list[str]] = mapped_column(JSON, default=list)
    thread_id: Mapped[str | None] = mapped_column(String(32))


# ---------------------------------------------------------------- workflow


class Request(Base):
    """An MDM request. `payload` holds the form fields (SAP names). Bank values inside it
    (`BPBankAccounts[].AccountNo` / `IBAN`) are Fernet ciphertext (`services/api/bankfields.py`)."""

    __tablename__ = "requests"

    req_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    domain: Mapped[RequestDomain] = mapped_column(
        Enum(RequestDomain, native_enum=False, length=20, validate_strings=True)
    )
    state: Mapped[RequestState] = mapped_column(
        Enum(RequestState, native_enum=False, length=24, validate_strings=True),
        default=RequestState.DRAFT,
        index=True,
    )
    requestor_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"))
    entity: Mapped[str] = mapped_column(String(3))
    country: Mapped[str] = mapped_column(String(2))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(SimTimestamp)
    updated_at: Mapped[datetime] = mapped_column(SimTimestamp)
    source_email_id: Mapped[str | None] = mapped_column(String(32))
    prefill_quotes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    linked_card_code: Mapped[str | None] = mapped_column(String(15))
    published_by: Mapped[str | None] = mapped_column(String(32))
    published_key: Mapped[str | None] = mapped_column(
        String(32)
    )  # CardCode / ItemCode / CenterCode


class ApprovalTaskRow(Base):
    """One approval task. Stage-1 tasks open together; stage 2 stays `waiting` until they pass."""

    __tablename__ = "approval_tasks"

    task_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    req_id: Mapped[str] = mapped_column(ForeignKey("requests.req_id"), index=True)
    stage: Mapped[int] = mapped_column(Integer)
    stage_name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(2))
    assignee_user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(SimTimestamp)
    due_at: Mapped[datetime | None] = mapped_column(SimTimestamp)
    reminded_at: Mapped[datetime | None] = mapped_column(SimTimestamp)
    escalated_at: Mapped[datetime | None] = mapped_column(SimTimestamp)
    escalated_to_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.user_id"), index=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(SimTimestamp)
    decided_by: Mapped[str | None] = mapped_column(String(32))
    comment: Mapped[str | None] = mapped_column(Text)


class NotificationRow(Base):
    """In-app stand-in for Teams / Outlook messages."""

    __tablename__ = "notifications"

    notification_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.user_id"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    req_id: Mapped[str] = mapped_column(String(32), index=True)
    task_id: Mapped[str | None] = mapped_column(String(32))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(SimTimestamp)


class DedupDecisionRow(Base):
    """A human decision on a duplicate warning. The newest row per request is the current one."""

    __tablename__ = "dedup_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    req_id: Mapped[str] = mapped_column(ForeignKey("requests.req_id"), index=True)
    action: Mapped[str] = mapped_column(String(24))
    card_code: Mapped[str | None] = mapped_column(String(15))
    reason: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[str] = mapped_column(String(32))
    decided_at: Mapped[datetime] = mapped_column(SimTimestamp)
    verdict_at_decision: Mapped[str] = mapped_column(String(8))
    # CardCodes the check offered when the human decided. A "not a duplicate" decision only
    # covers those records: a different candidate showing up later needs a new decision.
    covered_codes: Mapped[list[str]] = mapped_column(JSON, default=list)


class SapPublishRecord(Base):
    """What Priya sees after publishing: the SAP read-back, field by field (D-018 item 3 / M7).

    `rows` is a list of {field, sent, read_back, match}. Bank values are already masked here, so
    no bank number is stored in the clear; Finance sees them through the request itself.
    """

    __tablename__ = "sap_publish_results"

    req_id: Mapped[str] = mapped_column(ForeignKey("requests.req_id"), primary_key=True)
    resource: Mapped[str] = mapped_column(String(20))
    sap_code: Mapped[str] = mapped_column(String(32))
    published_at: Mapped[datetime] = mapped_column(SimTimestamp)
    published_by: Mapped[str] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean)
    all_match: Mapped[bool] = mapped_column(Boolean)
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class AppState(Base):
    """Small key/value store: the simulated clock and the id counters."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))


# ---------------------------------------------------------------- audit (M6)


class AuditLog(Base):
    """Append-only, hash-chained. Written only by `services.api.audit.append_audit`."""

    __tablename__ = "audit_log"
    __table_args__ = (UniqueConstraint("prev_hash"), UniqueConstraint("hash"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[str] = mapped_column(String(40))  # ISO-8601 from the simulated clock
    actor: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(32), index=True)
    payload: Mapped[str] = mapped_column(Text)  # canonical JSON text (bank values masked)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


class AuditHead(Base):
    """One row: the id and hash of the newest audit row. It is the write lock for the chain
    (every append updates it first) and lets `verify_chain` detect a truncated tail."""

    __tablename__ = "audit_head"
    __table_args__ = (CheckConstraint("id = 1"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_id: Mapped[int] = mapped_column(Integer, default=0)
    last_hash: Mapped[str] = mapped_column(String(64), default=GENESIS_HASH)


_AUDIT_TRIGGERS = (
    "CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only: UPDATE is not allowed'); END",
    "CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only: DELETE is not allowed'); END",
    # INSERT OR REPLACE would delete the old row without firing the DELETE trigger (unless
    # recursive_triggers is on), so new ids must always be higher than every existing id.
    "CREATE TRIGGER audit_log_insert_only_new BEFORE INSERT ON audit_log "
    "WHEN NEW.id IS NULL OR NEW.id <= (SELECT COALESCE(MAX(id), 0) FROM audit_log) "
    "BEGIN SELECT RAISE(ABORT, 'audit_log is append-only: id must be higher than all existing "
    "rows'); END",
)
for _ddl in _AUDIT_TRIGGERS:
    event.listen(AuditLog.__table__, "after_create", DDL(_ddl).execute_if(dialect="sqlite"))
event.listen(
    AuditHead.__table__,
    "after_create",
    DDL(
        f"INSERT INTO audit_head (id, last_id, last_hash) VALUES (1, 0, '{GENESIS_HASH}')"
    ).execute_if(dialect="sqlite"),
)
