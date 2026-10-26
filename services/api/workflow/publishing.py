"""Stage 2: Priya publishes an approved request to SAP B1 (PRD M7, D-004).

Deterministic code only. The record is built from the approved form fields, created inactive in
the SAP mock, read back and compared, then activated (see `services/api/sap_publisher.py`). On
success the request ends in ACTIVE, the new record also lands in our `business_partners` /
`items` tables, and the duplicate-check index is rebuilt so the next check sees it.
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from services.api import bankfields, clock, dedup_service, sap_readback
from services.api.db import models as m
from services.api.db.session import session_scope
from services.api.deps import Actor
from services.api.formfields import title_of
from services.api.ids import next_number
from services.api.sap_publisher import (
    PublishResult,
    SapAddress,
    SapBankAccount,
    SapBusinessPartner,
    SapItem,
    SapPayload,
    SapProfitCenter,
    SapPublisher,
)
from services.api.validation import ValidationFailed, expired_sentence, registration_issues
from services.api.views import tasks_for
from services.api.workflow import engine

CURRENCY = {"SG": "SGD", "MY": "MYR", "ID": "IDR", "VN": "VND", "TH": "THB"}
MAX_CODE_ATTEMPTS = 5


def make_publisher() -> SapPublisher:
    """The one place a publisher is created (tests replace it with one wired to the mock)."""
    return SapPublisher(client=httpx.Client(timeout=10.0))


# What the requestor can do once the record is live (session 13), one plain sentence each.
NEXT_STEP = {
    "item": "you can raise sales orders now",
    "customer": "you can raise sales orders for them now",
    "vendor": "you can raise purchase orders now",
    "cost_center": "you can post costs to it now",
}


def live_message(domain: str, title: str, code: str) -> str:
    """"'Malaria Pf/Pan Antigen Rapid Test Kit' is live in SAP as A-MAL-001, so you can raise
    sales orders now." The requestor's notification after a publish."""
    return f"'{title}' is live in SAP as {code}, so {NEXT_STEP[domain]}."


def _next_code(session: Session, prefix: str, column: Any, width: int) -> int:
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    numbers = [
        int(mo.group(1))
        for (code,) in session.execute(select(column).where(column.like(f"{prefix}%"))).all()
        if (mo := pattern.match(code))
    ]
    return max(numbers, default=0) + 1


def _item_abbr(name: str) -> str:
    letters = re.sub(r"[^A-Za-z]", "", name.split()[0] if name.split() else "")
    return (letters[:3] or "NEW").upper()


def build_payload(
    session: Session, req: m.Request, plain: dict[str, Any], attempt: int
) -> tuple[SapPayload, str]:
    """(SAP payload, the new code) for the request. `attempt` skips codes SAP already holds."""
    f = plain
    domain = req.domain.value
    try:
        if domain in ("customer", "vendor"):
            prefix = "C" if domain == "customer" else "V"
            n = _next_code(session, prefix, m.BusinessPartner.CardCode, 5) + attempt
            code = f"{prefix}{n:05d}"
            country = str(f.get("Country") or req.country)
            bank = None
            if domain == "vendor":
                bank = [
                    SapBankAccount(
                        BankCode=r.get("BankCode"),
                        AccountNo=r.get("AccountNo"),
                        AccountName=r.get("AccountName"),
                        BICSwiftCode=r.get("BICSwiftCode"),
                        IBAN=r.get("IBAN") or None,
                        Country=r.get("Country"),
                    )
                    for r in f.get("BPBankAccounts") or []
                ] or None
            payload: SapPayload = SapBusinessPartner(
                CardCode=code,
                CardName=str(f.get("CardName") or ""),
                CardType="cCustomer" if domain == "customer" else "cSupplier",
                CardForeignName=f.get("CardForeignName") or None,
                FederalTaxID=f.get("FederalTaxID") or None,
                Currency=CURRENCY.get(country),
                PayTermsGrpCode=f.get("PayTermsGrpCode"),
                CreditLimit=f.get("CreditLimit") if domain == "customer" else None,
                EmailAddress=f.get("EmailAddress") or None,
                Phone1=f.get("Phone1") or None,
                BPAddresses=[
                    SapAddress(
                        AddressName="Billing" if domain == "customer" else "Main",
                        AddressType="bo_BillTo",
                        Street=f.get("Street") or None,
                        City=f.get("City") or None,
                        ZipCode=f.get("ZipCode") or None,
                        Country=country,
                    )
                ],
                BPBankAccounts=bank,
                U_MDM_ReqID=req.req_id,
                U_Entity=req.entity,  # type: ignore[arg-type]
            )
            return payload, code
        if domain == "item":
            family = str(
                f.get("product_family") or {"SPD": "A", "QTS": "B", "QTG": "C"}[req.entity]
            )
            existing = set(session.scalars(select(m.Item.ItemCode)))
            n = attempt + 1
            code = f"{family}-{_item_abbr(str(f.get('ItemName') or ''))}-{n:03d}"
            while code in existing:
                n += 1
                code = f"{family}-{_item_abbr(str(f.get('ItemName') or ''))}-{n:03d}"
            regs = "; ".join(
                f"{r.get('country')}: {r.get('reg_no')}"
                for r in f.get("registrations") or []
                if isinstance(r, dict)
            )
            payload = SapItem(
                ItemCode=code,
                ItemName=str(f.get("ItemName") or ""),
                ItemsGroupCode=f.get("ItemsGroupCode"),
                PurchaseItem="tYES",
                SalesItem="tYES",
                InventoryItem="tYES",
                U_MDM_ReqID=req.req_id,
                U_IVD=f.get("U_IVD") or "tNO",
                U_RegSummary=regs or None,
            )
            return payload, code
        n = next_number(session, "cost_center")  # cost centres have no local table
        code = f"PC{n + attempt:04d}"
        return (
            SapProfitCenter(
                CenterCode=code,
                CenterName=str(f.get("CenterName") or ""),
                EffectiveFrom=str(f.get("EffectiveFrom") or "") or None,
                InWhichDimension=1,
            ),
            code,
        )
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False, include_context=False)
        )
        raise HTTPException(
            422, f"The approved details can't be turned into a valid SAP record ({problems})."
        ) from None


def _record_locally(session: Session, req: m.Request, plain: dict[str, Any], code: str) -> None:
    """Mirror the new SAP record in our own tables (active), so it counts as master data."""
    domain = req.domain.value
    if domain in ("customer", "vendor"):
        country = str(plain.get("Country") or req.country)
        session.add(
            m.BusinessPartner(
                CardCode=code,
                CardName=str(plain.get("CardName")),
                CardForeignName=plain.get("CardForeignName") or None,
                CardType="cCustomer" if domain == "customer" else "cSupplier",
                FederalTaxID=plain.get("FederalTaxID") or None,
                Currency=CURRENCY.get(country),
                PayTermsGrpCode=plain.get("PayTermsGrpCode"),
                CreditLimit=plain.get("CreditLimit"),
                EmailAddress=plain.get("EmailAddress") or None,
                Phone1=plain.get("Phone1") or None,
                City=plain.get("City") or None,
                Country=country,
                U_Entity=req.entity,
                CreateDate=clock.now().date(),
                CreatedBy=req.requestor_user_id,
                Frozen="tNO",
                U_MDM_ReqID=req.req_id,
            )
        )
        session.flush()
        for r in plain.get("BPBankAccounts") or []:
            session.add(
                m.BankAccount(
                    CardCode=code,
                    BankCode=r.get("BankCode"),
                    AccountNo=r.get("AccountNo"),
                    AccountName=r.get("AccountName"),
                    BICSwiftCode=r.get("BICSwiftCode"),
                    IBAN=r.get("IBAN") or None,
                    BankCountry=r.get("Country"),
                )
            )
    elif domain == "item":
        session.add(
            m.Item(
                ItemCode=code,
                ItemName=str(plain.get("ItemName")),
                ItemsGroupCode=plain.get("ItemsGroupCode"),
                PurchaseItem="tYES",
                SalesItem="tYES",
                InventoryItem="tYES",
                U_IVD=plain.get("U_IVD") or "tNO",
                Frozen="tNO",
                U_MDM_ReqID=req.req_id,
                product_family=plain.get("product_family"),
                entity=req.entity,
                sales_unit=plain.get("SalesUnit"),
                unit_price_usd=plain.get("unit_price_usd"),
            )
        )
        session.flush()
        for r in plain.get("registrations") or []:
            if isinstance(r, dict) and r.get("country"):
                session.add(
                    m.ItemRegistration(
                        item_code=code,
                        country=r["country"],
                        is_ivd=plain.get("U_IVD") == "tYES",
                        risk_class=r.get("risk_class"),
                        reg_no=r.get("reg_no"),
                        assumed_format=False,
                        reg_holder_entity=req.entity,
                        status="pending",
                    )
                )


def _failure_text(result: PublishResult) -> str:
    err = result.error
    if err is None:
        return "SAP did not accept the record."
    where = {
        "login": "SAP could not be reached or refused the login.",
        "create": "SAP rejected the new record.",
        "read_back": "The record was created but could not be read back.",
        "verify": "The record read back from SAP does not match what was sent.",
        "activate": "The record was created but could not be activated.",
    }.get(result.stage, "SAP did not accept the record.")
    return f"{where} {err.message} The request is still approved; you can try again."


def _claim(req_id: str, actor: Actor) -> None:
    """Reserve the request for this publisher before SAP is called (committed at once), so two
    publishes can never both create the record. Zero rows updated = someone else has it."""
    with session_scope(write=True) as session:
        claimed = session.execute(
            update(m.Request)
            .where(
                m.Request.req_id == req_id,
                m.Request.state == m.RequestState.APPROVED,
                m.Request.published_by.is_(None),
            )
            .values(published_by=actor.user_id)
        ).rowcount
    if claimed != 1:
        raise HTTPException(409, "Already being published (or already published) by someone else.")


def _release_claim(req_id: str) -> None:
    with session_scope(write=True) as session:
        session.execute(
            update(m.Request)
            .where(m.Request.req_id == req_id, m.Request.state == m.RequestState.APPROVED)
            .values(published_by=None)
        )


def publish(req_id: str, actor: Actor) -> None:
    """Validate, claim, call SAP outside any open write transaction, then record the outcome."""
    # 1. read and validate
    with session_scope() as session:
        req = session.get(m.Request, req_id)
        if req is None:
            raise HTTPException(404, f"There is no request {req_id}.")
        engine.check_publish_allowed(req, tasks_for(session, req_id), actor)
        if req.domain.value == "item":  # a licence can lapse between approval and publish
            lapsed = [
                i
                for i in registration_issues(bankfields.unseal(req.payload), clock.now().date())
                if i.kind == "expired"
            ]
            if lapsed:
                raise ValidationFailed(expired_sentence(lapsed), lapsed, status_code=409)
    _claim(req_id, actor)
    sap_done = False
    try:
        with session_scope() as session:
            req = session.get(m.Request, req_id)
            assert req is not None
            plain = bankfields.unseal(req.payload)
            payloads: list[tuple[SapPayload, str]] = [
                build_payload(session, req, plain, attempt) for attempt in range(MAX_CODE_ATTEMPTS)
            ]

        # 2. SAP calls (each one is audited by the publisher in its own short transaction)
        publisher = make_publisher()
        result: PublishResult | None = None
        try:
            for payload, _code in payloads:
                result = publisher.publish(payload, request_id=req_id)
                if result.ok or not (result.error and result.error.code == -5002):
                    break  # -5002 = that code already exists in SAP: try the next one
        finally:
            publisher.close()
        if result is None or not result.ok:
            if result is None:
                raise HTTPException(502, "SAP did not answer. The request is still approved.")
            raise HTTPException(502, _failure_text(result))
        sap_done = True
        code = result.key
    except BaseException:
        if not sap_done:
            _release_claim(req_id)  # nothing was created in SAP: the next try may go ahead
        raise

    # 3. record the outcome. The claim stays if this fails: SAP already holds the record.
    with session_scope(write=True) as session:
        req = session.get(m.Request, req_id)
        if req is None or req.state != m.RequestState.APPROVED:
            raise HTTPException(
                409,
                f"SAP accepted the record as {code}, but the request changed while it was being "
                "published. Ask an administrator to check it.",
            )
        engine.audit_state(
            session, req, actor.user_id, m.RequestState.PUBLISHED_INACTIVE,
            f"{actor.name} sent the record to SAP as {code} (inactive until verified)",
        )  # fmt: skip
        _record_locally(session, req, plain, code)
        for task in tasks_for(session, req_id):
            if task.stage == 2 and task.status == "pending":
                task.status = "approved"
                task.decided_at, task.decided_by = clock.now(), actor.user_id
                engine._audit_task(
                    session, actor.user_id, req, task, f"{actor.name} published to SAP ({code})",
                    action="publish", key=code,
                )  # fmt: skip
        req.published_by, req.published_key = actor.user_id, code
        session.add(sap_readback.record_from_result(req, result, actor.user_id, clock.now()))
        engine.audit_state(
            session, req, actor.user_id, m.RequestState.ACTIVE,
            f"SAP read-back matched; {code} is now active",
        )  # fmt: skip
        engine.notify(
            session, req.requestor_user_id, "published", req,
            live_message(req.domain.value, title_of(req.domain.value, plain), code),
        )  # fmt: skip
    dedup_service.rebuild_index()
