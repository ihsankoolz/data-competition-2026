"""Pydantic models for the SAP B1 Service Layer mock. Contract: D-004, D-014.

Field names and enum members use the SAP spelling exactly. Enums are case-sensitive
(`tYES`, not `tyes`). Unknown properties are rejected, like the real Service Layer.

Field names cross-checked against the Service Layer $metadata field lists in
ballerina-platform/module-ballerinax-sap.businessone (BusinessPartner, BPAddress,
BPBankAccount) and the b1-api-cookbook Postman collection (ProfitCenters keys).
[verify $metadata] items are marked inline.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

YesNo = Literal["tYES", "tNO"]
CardTypeEnum = Literal["cCustomer", "cSupplier", "cLid"]
AddressTypeEnum = Literal["bo_BillTo", "bo_ShipTo"]
Entity = Literal["SPD", "QTS", "QTG"]


class _B1Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginRequest(_B1Model):
    CompanyDB: str
    UserName: str
    Password: str


class BPAddress(_B1Model):
    AddressName: str
    AddressType: AddressTypeEnum | None = None
    Street: str | None = None
    City: str | None = None
    ZipCode: str | None = None
    Country: str | None = Field(default=None, min_length=2, max_length=2, description="ISO-2")


class BPBankAccount(_B1Model):
    BankCode: str | None = None
    AccountNo: str | None = None
    AccountName: str | None = None
    BICSwiftCode: str | None = None
    IBAN: str | None = None
    Country: str | None = Field(default=None, min_length=2, max_length=2, description="ISO-2")


class BusinessPartner(_B1Model):
    CardCode: str = Field(min_length=1, max_length=15)
    CardName: str = Field(min_length=1, max_length=100)
    CardType: CardTypeEnum = "cCustomer"
    # CardForeignName: optional second name, e.g. an English name (D-014 note, 22 Oct).
    CardForeignName: str | None = Field(default=None, max_length=100)
    GroupCode: int | None = None
    FederalTaxID: str | None = Field(default=None, max_length=32)
    Currency: str | None = None
    PayTermsGrpCode: int | None = None
    CreditLimit: float | None = None
    EmailAddress: str | None = None
    Phone1: str | None = None
    # Frozen = "inactive until approved" workaround. [verify $metadata]
    Frozen: YesNo = "tNO"
    BPAddresses: list[BPAddress] | None = None
    BPBankAccounts: list[BPBankAccount] | None = None
    # User-defined fields [verify $metadata]
    U_MDM_ReqID: str | None = None
    U_GoldenID: str | None = None
    U_Entity: Entity | None = None


class Item(_B1Model):
    ItemCode: str = Field(min_length=1, max_length=20)
    ItemName: str = Field(min_length=1, max_length=100)
    ItemType: Literal["itItems"] = "itItems"
    ItemsGroupCode: int | None = None
    PurchaseItem: YesNo | None = None
    SalesItem: YesNo | None = None
    InventoryItem: YesNo | None = None
    Frozen: YesNo = "tNO"
    # User-defined fields [verify $metadata]
    U_MDM_ReqID: str | None = None
    U_IVD: YesNo | None = None
    U_RegSummary: str | None = None


class ProfitCenter(_B1Model):
    CenterCode: str = Field(min_length=1, max_length=8)
    CenterName: str = Field(min_length=1, max_length=30)
    EffectiveFrom: date | None = None
    InWhichDimension: int | None = None
    # `Active` spelling on ProfitCenters. [verify $metadata]
    Active: YesNo = "tYES"
