"""Email interpreter contract (D-006). `Interpretation` is what the API returns; it is a fixed
contract between ds.interpreter, services/api and the web app. The model-facing output schema
(what the LLM is asked to fill) is private to ds.interpreter and may differ.

Every extracted value carries the exact substring it came from. A value whose `source_quote`
is not found in the (bank-stripped) email text is dropped and listed in `dropped_fields`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["purchase_order", "purchase_request", "enquiry", "follow_up", "mdm_request"]
MdmDomain = Literal["customer", "vendor", "item", "cost_center"]


class QuotedValue(BaseModel):
    """One extracted field. `key` is an extract key from config/required_fields.yaml
    (`name`, `tax_id`, `registration_number_SG`, ...) or an order key (`customer_name`,
    `po_number`, `requested_date`)."""

    key: str
    value: str | float | bool | list[str]
    source_quote: str = Field(description="Exact substring of the email the value came from")


class OrderLine(BaseModel):
    item_code: str | None = Field(default=None, description="Catalogue code if recognised")
    product_text: str | None = Field(default=None, description="Product as written")
    qty: float | None = None
    source_quote: str


class Interpretation(BaseModel):
    email_id: str
    category: Category
    confidence: float = Field(ge=0.0, le=1.0)
    domain: MdmDomain | None = Field(default=None, description="Set for mdm_request only")
    fields: list[QuotedValue] = []
    lines: list[OrderLine] = Field(default=[], description="purchase_order / request / enquiry")
    missing_fields: list[str] = Field(
        default=[], description="Required extract keys not found (ds.forms.missing_keys)"
    )
    questions_for_requester: list[str] = Field(
        default=[], description="Plain-English questions, one per missing field"
    )
    dropped_fields: list[str] = Field(
        default=[], description="Keys the model returned without a matching source quote"
    )
    bank_details_stripped: bool = Field(
        default=False, description="Bank details were removed before any LLM call (rule 5)"
    )
    injection_suspected: bool = Field(
        default=False, description="Flagged for a human; never acted on (rule 7)"
    )
    needs_review: bool = Field(
        default=False,
        description="confidence < 0.6, or the email looks like it is instructing the AI "
        "-> human review queue",
    )
    method: Literal["llm", "keyword_fallback"] = Field(
        description="keyword_fallback = AI offline (no cached answer); show the badge"
    )
    ai_status: Literal["ok", "offline", "error"]
    ai_message: str | None = None
    prompt_version: str | None = None
