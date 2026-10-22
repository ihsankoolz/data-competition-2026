"""API contract. Every request and response body is a Pydantic v2 model."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Health(BaseModel):
    status: str
    service: str


class ClockState(BaseModel):
    """Simulated clock. All SLA logic uses `now`, never the wall clock."""

    now: datetime = Field(description="Current simulated time (timezone-aware, SGT)")
    started_at: datetime = Field(description="Simulated time after the last reset")
    elapsed_hours: float = Field(description="Simulated hours since the last reset")


class ClockAdvance(BaseModel):
    hours: float = Field(default=0, ge=0)
    days: float = Field(default=0, ge=0)


Role = Literal[
    "requestor", "bu_head", "finance", "quality_regulatory", "business_support", "mdm_analyst"
]


class Persona(BaseModel):
    """A seeded demo user. The web app sends the chosen `user_id` in the X-Acting-User header."""

    user_id: str
    name: str
    title: str
    roles: list[Role]
    entity: str = Field(description="SPD | QTS | QTG | Group")
    country: str = Field(description="ISO-2")


# ============================================================================================
# Session 3 contract (D-005, D-006, D-007, D-016). Change shapes here first, then `make api-types`.
# Field names inside `fields` are form fields from config/forms/<domain>.schema.json (SAP names).
# ============================================================================================

Domain = Literal["customer", "vendor", "item", "cost_center"]
EntityCode = Literal["SPD", "QTS", "QTG"]
CountryCode = Literal["SG", "MY", "ID", "VN", "TH"]
RequestStateName = Literal[
    "DRAFT",
    "SUBMITTED",
    "IN_APPROVAL",
    "INFO_REQUESTED",
    "REJECTED",
    "APPROVED",
    "PUBLISHED_INACTIVE",
    "ACTIVE",
    "LINKED_TO_EXISTING",
]


# ---------------------------------------------------------------- forms (M3)


class FormSpec(BaseModel):
    """Everything the web app needs to render a request form for one domain x country."""

    domain: Domain
    country: CountryCode | None = None
    json_schema: dict[str, Any] = Field(description="config/forms/<domain>.schema.json")
    required: list[str] = Field(
        description="Required form fields (SAP names) for this country, in display order"
    )
    required_per_selling_country: list[str] = Field(
        default=[],
        description="Item only: sub-fields of `registrations` required for each regulated "
        "selling country when U_IVD = tYES",
    )
    regulated_countries: list[CountryCode] = []


# ---------------------------------------------------------------- emails / interpreter (M2)


class EmailSummary(BaseModel):
    email_id: str
    received_at: datetime
    from_name: str | None = None
    from_address: str
    subject: str
    snippet: str = Field(description="First ~160 characters of the body")
    has_attachments: bool = False


class EmailDetail(EmailSummary):
    to_address: str | None = None
    body: str = Field(description="Bank details are masked unless the acting user is Finance")
    attachments: list[str] = []
    thread_id: str | None = None


# ---------------------------------------------------------------- duplicate check (M4)


class DedupCheckRequest(BaseModel):
    """What the requester has typed so far (debounced on change, and again on submit)."""

    domain: Literal["customer", "vendor"]
    entity: EntityCode
    fields: dict[str, Any] = Field(description="Partial customer/vendor form fields")
    request_id: str | None = Field(
        default=None, description="Set when checking an existing draft; the check is logged"
    )


class DedupDecisionIn(BaseModel):
    """The human decision on a duplicate warning. The AI never makes it (rule 6)."""

    action: Literal["link_to_existing", "not_duplicate"]
    card_code: str | None = Field(default=None, description="Required for link_to_existing")
    reason: str | None = Field(
        default=None,
        description="Required for not_duplicate, at least 10 characters (checked by the API with "
        "a plain-English message): why this is a different customer/vendor",
    )


class DedupDecisionOut(BaseModel):
    action: Literal["link_to_existing", "not_duplicate"]
    card_code: str | None = None
    reason: str | None = None
    decided_by: str
    decided_at: datetime
    verdict_at_decision: Literal["likely", "possible", "none"]


# ---------------------------------------------------------------- requests and approvals (M5)


class RequestCreate(BaseModel):
    domain: Domain
    entity: EntityCode
    country: CountryCode
    fields: dict[str, Any] = {}
    source_email_id: str | None = None


class RequestUpdate(BaseModel):
    """Partial update of a DRAFT or INFO_REQUESTED request. Every changed field is audited."""

    fields: dict[str, Any] = {}
    country: CountryCode | None = None


TaskStatus = Literal["waiting", "pending", "approved", "rejected", "info_requested", "cancelled"]


class ApprovalTask(BaseModel):
    task_id: str
    req_id: str
    stage: int = Field(description="1-based stage number")
    role: Role
    country: CountryCode | None = Field(default=None, description="Quality/Regulatory tasks")
    assignee_user_id: str
    assignee_name: str
    status: TaskStatus = Field(description="waiting = its stage has not opened yet")
    assigned_at: datetime | None = None
    due_at: datetime | None = Field(default=None, description="Simulated clock, SLA end")
    reminded_at: datetime | None = None
    escalated_at: datetime | None = None
    escalated_to_user_id: str | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None
    comment: str | None = None
    sla_state: Literal["on_track", "reminded", "overdue", "done"] = "on_track"


class Stage(BaseModel):
    number: int
    name: str
    status: Literal["waiting", "open", "done", "rejected"]
    tasks: list[ApprovalTask]


class RequestSummary(BaseModel):
    req_id: str
    domain: Domain
    state: RequestStateName
    title: str = Field(description="CardName / ItemName / CenterName, or 'Untitled'")
    entity: EntityCode
    country: CountryCode
    requestor_user_id: str
    requestor_name: str
    created_at: datetime
    updated_at: datetime
    pending_with: list[str] = Field(default=[], description="Names of people the request waits on")


class RequestDetail(RequestSummary):
    fields: dict[str, Any] = Field(description="Bank fields are masked unless the actor is Finance")
    missing_fields: list[str] = Field(default=[], description="Required form fields still empty")
    source_email_id: str | None = None
    prefill_quotes: dict[str, str] = Field(
        default={}, description="Form field -> source quote, when created from an email"
    )
    dedup_decision: DedupDecisionOut | None = None
    linked_card_code: str | None = None
    stages: list[Stage] = []
    allowed_actions: list[
        Literal["edit", "submit", "decide_duplicate", "approve", "reject", "ask_info", "publish"]
    ] = Field(default=[], description="For the acting user; the backend still enforces them")


class ApprovalDecisionIn(BaseModel):
    action: Literal["approve", "reject", "ask_info"]
    comment: str | None = Field(default=None, description="Required for reject and ask_info")


class ApprovalInboxItem(BaseModel):
    task: ApprovalTask
    request: RequestSummary


NotificationKind = Literal[
    "task_assigned", "reminder", "escalated", "info_requested", "approved", "rejected", "published"
]


class Notification(BaseModel):
    """In-app stand-in for Teams/Outlook messages. Created on the simulated clock."""

    notification_id: str
    user_id: str
    kind: NotificationKind
    req_id: str
    task_id: str | None = None
    message: str = Field(description="Plain English, e.g. 'Reminder: Amy's item request ...'")
    created_at: datetime


# ---------------------------------------------------------------- admin (D-016)


class ResetResult(BaseModel):
    ok: bool
    duration_ms: float
    counts: dict[str, int] = Field(description="Rows per table after the reset")
    clock: ClockState
    sap_mock_reset: bool = Field(description="False if the SAP mock was not reachable")


class AuditEntry(BaseModel):
    """One audit row for the status-page timeline (bank values are already masked)."""

    id: int
    ts: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    summary: str = Field(description="Plain English, e.g. 'Wei Jie approved (Finance)'")
