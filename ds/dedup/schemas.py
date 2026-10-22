"""Typed inputs and outputs of the duplicate check (D-005). Pydantic v2, so the API can use them."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

CardType = Literal["cCustomer", "cSupplier", "cLid"]
Verdict = Literal["likely", "possible"]
Layer = Literal["tax_id", "normalise", "dictionary", "fuzzy", "evidence", "rule", "judge"]

CONFIG_PATH = Path(__file__).with_name("config.yaml")


class BPRecord(BaseModel):
    """A business partner as the duplicate check sees it (SAP field names, D-004).

    Bank fields are deliberately absent: the duplicate check never needs them, and extra
    fields (e.g. a raw CSV row with BankCode/IBAN) are ignored on construction.
    """

    model_config = ConfigDict(extra="ignore")

    CardCode: str
    CardName: str
    CardForeignName: str | None = None
    CardType: CardType = "cCustomer"
    FederalTaxID: str | None = None
    Country: str
    City: str | None = None
    Phone1: str | None = None
    EmailAddress: str | None = None
    U_Entity: str | None = None
    group_id: str | None = Field(
        default=None, description="Cross-border group (domain rule 3). Business fact, optional."
    )


class BPQuery(BaseModel):
    """What the requester has typed so far. CardCode is empty for a new request."""

    model_config = ConfigDict(extra="ignore")

    CardName: str
    CardForeignName: str | None = None
    CardType: CardType = "cCustomer"
    FederalTaxID: str | None = None
    Country: str
    City: str | None = None
    Phone1: str | None = None
    EmailAddress: str | None = None
    U_Entity: str | None = None
    group_id: str | None = None
    CardCode: str | None = Field(
        default=None,
        description="Set when re-checking an existing record; it is never its own match.",
    )


class Reason(BaseModel):
    layer: Layer
    text: str = Field(description="Plain English, shown to the requester")
    weight: float = Field(default=0.0, description="Contribution to the score (+/-), for tooltips")


class Candidate(BaseModel):
    CardCode: str
    CardName: str
    CardForeignName: str | None = None
    CardType: CardType
    entity: str | None = None
    country: str
    city: str | None = None
    FederalTaxID: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    name_score: float = Field(ge=0.0, le=1.0)
    verdict: Verdict
    tax_id_match: bool = False
    reasons: list[Reason] = []


class RelatedRecord(BaseModel):
    """A record that looks similar but is NOT a duplicate by rule (C/V twin, other country)."""

    CardCode: str
    CardName: str
    CardType: CardType
    country: str
    rule: Literal["customer_vendor", "other_country", "same_group_other_country"]
    group_id: str | None = None
    explanation: str


class JudgeOpinion(BaseModel):
    status: Literal["not_needed", "ok", "offline", "error", "disabled"]
    selected_card_code: str | None = None
    reasons: list[str] = []
    model: str | None = None
    prompt_version: str | None = None
    message: str | None = None


class DedupResult(BaseModel):
    verdict: Literal["likely", "possible", "none"]
    message: str
    block_submit: bool = Field(
        description="True for 'likely': submit is blocked until a human links the record "
        "or overrides with a reason"
    )
    candidates: list[Candidate] = []
    related: list[RelatedRecord] = []
    grey_zone: bool = False
    judge: JudgeOpinion = JudgeOpinion(status="not_needed")
    elapsed_ms: float = 0.0


# --------------------------------------------------------------------------------------------
class Thresholds(BaseModel):
    likely: float = 0.92
    possible: float = 0.70
    related: float = 0.70


class NameWeights(BaseModel):
    w_soft_idf: float = 0.70
    w_token_set: float = 0.15
    w_jaro: float = 0.15
    token_jw_min: float = 0.88
    qualifier_weight: float = 0.35
    city_token_weight: float = 0.5
    acronym_score: float = 0.93
    number_mismatch_penalty: float = 0.25


class EvidenceWeights(BaseModel):
    tax_exact_floor: float = 0.97
    tax_conflict_penalty: float = 0.30
    phone_bonus: float = 0.06
    email_bonus: float = 0.05
    city_bonus: float = 0.02
    city_conflict_penalty: float = 0.10


class JudgeConfig(BaseModel):
    enabled: bool = True
    low: float = 0.70
    high: float = 0.92
    prompt_version: str = "dedup_judge_v1"


class DedupConfig(BaseModel):
    thresholds: Thresholds = Thresholds()
    max_candidates: int = 5
    name: NameWeights = NameWeights()
    evidence: EvidenceWeights = EvidenceWeights()
    judge: JudgeConfig = JudgeConfig()

    @classmethod
    def load(cls, path: Path | str = CONFIG_PATH) -> DedupConfig:
        with open(path, encoding="utf-8") as fh:
            return cls.model_validate(yaml.safe_load(fh) or {})
