"""SAP B1 publisher (PRD M7, second half). Deterministic code only: no LLM in this path.

Publisher flow (D-004), one `publish()` call:

    Login -> POST with Frozen=tYES (ProfitCenters: Active=tNO) -> GET read-back
          -> field-by-field compare -> PATCH Frozen=tNO (Active=tYES) -> Logout

* Uses an `httpx.Client` with a cookie jar (`B1SESSION` and `ROUTEID` travel as cookies).
* A 401 on a resource call means the session expired: log in again once and repeat that call.
* Connection failures are retried with `tenacity` (only errors raised before the request was
  sent, so a POST can never be sent twice).
* B1 errors (for example -5002 duplicate key) come back as a typed `PublishResult`, never as an
  exception. If the read-back differs from what was sent, the record is left inactive and the
  differences are reported.
* Every HTTP call writes an `audit_log` row (`sap_call`) in its own short transaction, so the
  trail survives a failed publish. Bodies are masked before they are written: bank values never
  reach the audit log, and nothing here logs request bodies (domain rule 5).

Mapping an MDM request to these payload models comes with M3/M5.
"""

from __future__ import annotations

import os
import re
from typing import Any, Literal
from urllib.parse import quote, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed

from services.api.audit import AuditAction, append_audit, scrub
from services.api.db.session import get_session_factory

DEFAULT_BASE_URL = "http://localhost:8001/b1s/v2"
ACTOR = "sap_publisher"
DEMO_HOSTS = frozenset({"localhost", "127.0.0.1", "testserver"})

YesNo = Literal["tYES", "tNO"]

# ---------------------------------------------------------------- B1 payload models (D-004)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SapAddress(_Payload):
    AddressName: str
    AddressType: Literal["bo_BillTo", "bo_ShipTo"] | None = None
    Street: str | None = None
    City: str | None = None
    ZipCode: str | None = None
    Country: str | None = Field(default=None, min_length=2, max_length=2)


class SapBankAccount(_Payload):
    BankCode: str | None = None
    AccountNo: str | None = None
    AccountName: str | None = None
    BICSwiftCode: str | None = None
    IBAN: str | None = None
    Country: str | None = Field(default=None, min_length=2, max_length=2)


class SapBusinessPartner(_Payload):
    CardCode: str = Field(min_length=1, max_length=15)
    CardName: str = Field(min_length=1, max_length=100)
    # Required on purpose: customer and vendor are separate records (domain rule 2).
    CardType: Literal["cCustomer", "cSupplier", "cLid"]
    CardForeignName: str | None = Field(default=None, max_length=100)
    GroupCode: int | None = None
    FederalTaxID: str | None = Field(default=None, max_length=32)
    Currency: str | None = None
    PayTermsGrpCode: int | None = None
    CreditLimit: float | None = None
    EmailAddress: str | None = None
    Phone1: str | None = None
    BPAddresses: list[SapAddress] | None = None
    BPBankAccounts: list[SapBankAccount] | None = None
    U_MDM_ReqID: str | None = None
    U_GoldenID: str | None = None
    U_Entity: Literal["SPD", "QTS", "QTG"] | None = None


class SapItem(_Payload):
    ItemCode: str = Field(min_length=1, max_length=20)
    ItemName: str = Field(min_length=1, max_length=100)
    ItemType: Literal["itItems"] = "itItems"
    ItemsGroupCode: int | None = None
    PurchaseItem: YesNo | None = None
    SalesItem: YesNo | None = None
    InventoryItem: YesNo | None = None
    U_MDM_ReqID: str | None = None
    U_IVD: YesNo | None = None
    U_RegSummary: str | None = None


class SapProfitCenter(_Payload):
    """UI label: Cost Center."""

    CenterCode: str = Field(min_length=1, max_length=8)
    CenterName: str = Field(min_length=1, max_length=30)
    EffectiveFrom: str | None = Field(default=None, description="YYYY-MM-DD")
    InWhichDimension: int | None = None


SapPayload = SapBusinessPartner | SapItem | SapProfitCenter


class _Resource(BaseModel):
    name: str
    key_field: str
    flag: str  # field that holds the active/inactive state
    inactive: str
    active: str


_RESOURCES: dict[type[BaseModel], _Resource] = {
    SapBusinessPartner: _Resource(
        name="BusinessPartners", key_field="CardCode", flag="Frozen", inactive="tYES", active="tNO"
    ),
    SapItem: _Resource(
        name="Items", key_field="ItemCode", flag="Frozen", inactive="tYES", active="tNO"
    ),
    # ProfitCenters have no Frozen: they use Active, with the opposite sense.
    SapProfitCenter: _Resource(
        name="ProfitCenters", key_field="CenterCode", flag="Active", inactive="tNO", active="tYES"
    ),
}

# ---------------------------------------------------------------- results


class B1Failure(BaseModel):
    """A failed SAP call, as the Service Layer reported it."""

    http_status: int | None = Field(description="None when SAP could not be reached")
    code: int | None = Field(description="B1 error code, e.g. -5002 duplicate key, 301 session")
    message: str


class FieldMismatch(BaseModel):
    field: str
    sent: Any
    received: Any


Stage = Literal["login", "create", "read_back", "verify", "activate", "done"]


class PublishResult(BaseModel):
    ok: bool
    resource: str
    key: str
    stage: Stage = Field(description="Where it stopped; 'done' when everything succeeded")
    final_state: Literal["active", "inactive", "not_created"]
    error: B1Failure | None = None
    mismatches: list[FieldMismatch] = Field(default_factory=list)
    relogins: int = 0
    calls: int = 0
    audit_failed: bool = Field(
        default=False, description="True if an audit row could not be written for a SAP call"
    )
    # The payload as sent and the record as read back, for the read-back view. They can hold
    # bank values, so they never serialise or print (`exclude`, `repr=False`).
    sent: dict[str, Any] = Field(default_factory=dict, exclude=True, repr=False)
    read_back: dict[str, Any] | None = Field(default=None, exclude=True, repr=False)


class _Abort(Exception):
    def __init__(self, stage: Stage | None, failure: B1Failure) -> None:
        super().__init__(failure.message)
        self.stage = stage
        self.failure = failure


# ---------------------------------------------------------------- helpers


_DIGIT_RUN = re.compile(r"\d{8,}")


def redact_digits(text: str) -> str:
    """Hide runs of 8+ digits (account numbers, IBAN bodies) in free text from SAP."""
    return _DIGIT_RUN.sub("[redacted]", text)


def _failure(resp: httpx.Response) -> B1Failure:
    """Typed failure from a B1 error response. Messages are redacted; an unreadable body is
    never copied, only described."""
    code: int | None = None
    message = f"Unreadable response from SAP B1 (HTTP {resp.status_code})."
    try:
        err = resp.json()["error"]
        code = int(err["code"])
        msg = err["message"]
        message = redact_digits(str(msg["value"] if isinstance(msg, dict) else msg))[:300]
    except (ValueError, KeyError, TypeError):
        pass
    return B1Failure(http_status=resp.status_code, code=code, message=message)


def _same(sent: Any, got: Any) -> bool:
    if isinstance(sent, (int, float)) and isinstance(got, (int, float)):
        return not isinstance(sent, bool) and float(sent) == float(got)
    return sent == got


def diff_payload(sent: Any, got: Any, path: str = "") -> list[FieldMismatch]:
    """Fields in `sent` that are missing or different in `got`. Bank values are masked."""
    out: list[FieldMismatch] = []
    if isinstance(sent, dict):
        got = got if isinstance(got, dict) else {}
        for k, v in sent.items():
            out.extend(diff_payload(v, got.get(k), f"{path}.{k}" if path else k))
    elif isinstance(sent, list):
        got = got if isinstance(got, list) else []
        if len(sent) != len(got):
            out.append(FieldMismatch(field=f"{path}[]", sent=len(sent), received=len(got)))
        for i, v in enumerate(sent):
            out.extend(diff_payload(v, got[i] if i < len(got) else None, f"{path}[{i}]"))
    elif not _same(sent, got):
        leaf = path.rsplit(".", 1)[-1]
        out.append(
            FieldMismatch(
                field=path, sent=scrub({leaf: sent})[leaf], received=scrub({leaf: got})[leaf]
            )
        )
    return out


def _entity_path(resource: str, key: str) -> str:
    return f"/{resource}('{quote(key.replace(chr(39), chr(39) * 2), safe='')}')"


# ---------------------------------------------------------------- the publisher


class SapPublisher:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session] | None = None,
        base_url: str | None = None,
        company_db: str | None = None,
        user: str | None = None,
        password: str | None = None,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
        connect_retries: int = 3,
        retry_wait: float = 0.2,
    ) -> None:
        """`client` lets tests pass a Starlette `TestClient` wired to the mock in-process.
        Defaults come from SAP_BASE_URL / SAP_COMPANY_DB / SAP_USER / SAP_PASSWORD, and fall back
        to the mock's demo values. The demo password is only allowed when the host is
        localhost, 127.0.0.1 or testserver; any other host needs a real password."""
        self._factory = session_factory
        self.base_url = (base_url or os.environ.get("SAP_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        real_password = password or os.environ.get("SAP_PASSWORD")
        host = urlparse(self.base_url).hostname or ""
        if not real_password and host not in DEMO_HOSTS:
            raise ValueError(
                "No SAP password: set SAP_PASSWORD. The demo password is only used for the "
                f"mock on {', '.join(sorted(DEMO_HOSTS))}, not for host {host!r}."
            )
        self._creds = {
            "CompanyDB": company_db or os.environ.get("SAP_COMPANY_DB") or "LIVES_DEMO",
            "UserName": user or os.environ.get("SAP_USER") or "mdm_integration",
            "Password": real_password or "demo",
        }
        self._client = client or httpx.Client(timeout=timeout)
        self._retrying = Retrying(
            retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
            stop=stop_after_attempt(connect_retries),
            wait=wait_fixed(retry_wait),
            reraise=True,
        )
        self._request_id: str | None = None
        self._calls = 0
        self._relogins = 0
        self._audit_error: SQLAlchemyError | None = None

    # -- audit -----------------------------------------------------------------

    def _audit(
        self,
        entity_type: str,
        entity_id: str,
        method: str,
        path: str,
        status: int | None,
        body: Any,
        error: B1Failure | None,
    ) -> None:
        payload = {
            "method": method,
            "path": path,
            "status": status,
            "b1_error_code": error.code if error else None,
            "b1_error_message": error.message if error else None,
            "body": body,  # masked by append_audit; login bodies never include the password
        }
        factory = self._factory or get_session_factory()
        with factory.begin() as session:
            append_audit(
                session,
                actor=ACTOR,
                action=AuditAction.sap_call,
                entity_type=entity_type,
                entity_id=entity_id,
                request_id=self._request_id,
                payload=payload,
            )

    def _audit_safely(self, *args: Any) -> None:
        """Audit one call. A failure here must not hide what SAP just did, so it is remembered
        and `publish()` turns it into a typed result at the next checkpoint."""
        try:
            self._audit(*args)
        except SQLAlchemyError as exc:
            self._audit_error = self._audit_error or exc

    def _checkpoint(self, stage: Stage) -> None:
        if self._audit_error is not None:
            raise _Abort(
                stage,
                B1Failure(
                    http_status=None,
                    code=None,
                    message="The audit log could not be written "
                    f"({type(self._audit_error).__name__}), so publishing was stopped.",
                ),
            )

    # -- HTTP --------------------------------------------------------------------

    def _once(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        entity_type: str,
        entity_id: str,
        audit_body: Any,
    ) -> httpx.Response:
        self._calls += 1
        try:
            resp = self._retrying(self._client.request, method, f"{self.base_url}{path}", json=body)
        except httpx.TransportError as exc:
            failure = B1Failure(
                http_status=None,
                code=None,
                message=f"SAP B1 could not be reached ({type(exc).__name__}).",
            )
            self._audit_safely(entity_type, entity_id, method, path, None, audit_body, failure)
            raise _Abort("login" if path == "/Login" else None, failure) from None
        failure = _failure(resp) if resp.status_code >= 400 else None
        self._audit_safely(
            entity_type, entity_id, method, path, resp.status_code, audit_body, failure
        )
        return resp

    def _login(self) -> None:
        resp = self._once(
            "POST",
            "/Login",
            self._creds,
            "SapSession",
            self._creds["CompanyDB"],
            {"CompanyDB": self._creds["CompanyDB"], "UserName": self._creds["UserName"]},
        )
        if resp.status_code >= 400:
            raise _Abort("login", _failure(resp))

    def _call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        *,
        resource: str,
        key: str,
        stage: Stage,
    ) -> httpx.Response:
        """A resource call. On 401, log in again once and repeat it."""
        audit_body = scrub(body) if body is not None else None
        resp = self._once(method, path, body, resource, key, audit_body)
        if resp.status_code == 401:
            self._relogins += 1
            self._login()
            resp = self._once(method, path, body, resource, key, audit_body)
        if resp.status_code >= 400:
            raise _Abort(stage, _failure(resp))
        return resp

    def _logout(self) -> None:
        try:
            self._once("POST", "/Logout", None, "SapSession", self._creds["CompanyDB"], None)
        except _Abort:
            pass  # nothing to undo: the session is gone either way
        self._client.cookies.clear()

    # -- the flow ------------------------------------------------------------------

    def publish(self, payload: SapPayload, *, request_id: str | None = None) -> PublishResult:
        """Publish one record. Never raises for SAP or audit problems: see `PublishResult`.

        Call this OUTSIDE any open write transaction on the app database. Each SAP call writes
        its audit row in its own short transaction, which needs the audit write lock; holding
        a write transaction in the caller would make that wait.
        """
        res = _RESOURCES[type(payload)]
        sent = payload.model_dump(mode="json", exclude_none=True)
        sent[res.flag] = res.inactive  # always created inactive, whatever the caller said
        key = str(sent[res.key_field])
        self._request_id, self._calls, self._relogins = request_id, 0, 0
        self._audit_error = None

        stage: Stage = "login"
        final_state: Literal["active", "inactive", "not_created"] = "not_created"
        mismatches: list[FieldMismatch] = []
        got: dict[str, Any] | None = None
        error: B1Failure | None = None
        logged_in = False
        try:
            self._login()
            logged_in = True
            self._checkpoint("login")
            stage = "create"
            self._call("POST", f"/{res.name}", sent, resource=res.name, key=key, stage=stage)
            final_state = "inactive"
            self._checkpoint(stage)

            stage = "read_back"
            got = self._call(
                "GET", _entity_path(res.name, key), None, resource=res.name, key=key, stage=stage
            ).json()
            self._checkpoint(stage)

            stage = "verify"
            mismatches = diff_payload(sent, got)
            if mismatches:
                error = B1Failure(
                    http_status=None,
                    code=None,
                    message=f"Read-back differs from what was sent in {len(mismatches)} field(s); "
                    "the record was left inactive.",
                )
            else:
                stage = "activate"
                self._call(
                    "PATCH",
                    _entity_path(res.name, key),
                    {res.flag: res.active},
                    resource=res.name,
                    key=key,
                    stage=stage,
                )
                final_state = "active"
                self._checkpoint(stage)
                stage = "done"
        except _Abort as abort:
            stage, error = abort.stage or stage, abort.failure
        finally:
            if logged_in:
                self._logout()
        if self._audit_error is not None and error is not None and "audit log" not in error.message:
            error = error.model_copy(
                update={"message": error.message + " The audit log could not be written."}
            )
        return PublishResult(
            ok=stage == "done",
            resource=res.name,
            key=key,
            stage=stage,
            final_state=final_state,
            error=error,
            mismatches=mismatches,
            relogins=self._relogins,
            calls=self._calls,
            audit_failed=self._audit_error is not None,
            sent=sent,
            read_back=got,
        )

    def close(self) -> None:
        self._client.close()
