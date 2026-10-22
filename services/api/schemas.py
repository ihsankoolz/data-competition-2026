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
    prefill_suggested: dict[str, str] = Field(
        default={},
        description="Form field -> plain-English reason, for values suggested by deterministic "
        "rules rather than quoted from the email (e.g. item group, product family; session 5)",
    )
    dedup_decision: DedupDecisionOut | None = None
    linked_card_code: str | None = None
    linked_card_name: str | None = Field(
        default=None, description="CardName of the linked existing record (session 5)"
    )
    info_request: "InfoRequestView | None" = Field(
        default=None,
        description="Set while the request is INFO_REQUESTED: who asked what. The requestor edits "
        "and resubmits with POST /requests/{id}/submit (session 5)",
    )
    stages: list[Stage] = []
    allowed_actions: list[
        Literal["edit", "submit", "decide_duplicate", "approve", "reject", "ask_info", "publish"]
    ] = Field(default=[], description="For the acting user; the backend still enforces them")
    issues: list["FieldIssue"] = Field(
        default=[], description="Validation problems with the current fields (D-018 item 3)"
    )
    sap_publish: "SapPublishView | None" = Field(
        default=None, description="Set once published: the SAP read-back check"
    )


class InfoRequestView(BaseModel):
    """The approver's question shown above the edit-and-resubmit form."""

    task_id: str
    asked_by_user_id: str
    asked_by_name: str
    role: Role
    question: str
    asked_at: datetime


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


# ============================================================================================
# Session 4 contract (D-018). M8 regional view, M9 forecast backtest, M10 ops impact, field
# validation, SAP read-back. Money is USD (D-003 fixed FX). Every metric carries a caption.
# ============================================================================================

# ---------------------------------------------------------------- field validation (D-018 item 3)


class FieldIssue(BaseModel):
    """One problem with one form field, in plain English. Never echoes bank values."""

    field: str = Field(description="Form field (SAP name), or 'registrations.<CC>.<sub_field>'")
    label: str = Field(description="Human label, e.g. 'Tax ID (MST)'")
    message: str = Field(description="e.g. 'A Vietnamese MST has 10 digits, like 0301234567.'")
    kind: Literal["missing", "format", "too_long", "not_allowed", "expired", "date_order"]


class ValidationReport(BaseModel):
    """Returned by POST /requests/{req_id}/validate. Submit's 422 body is
    {"detail": "<one sentence>", "issues": [FieldIssue, ...]}."""

    ok: bool
    issues: list[FieldIssue] = []


class ValidationBlocked(BaseModel):
    """The 422 body of POST /requests/{req_id}/submit when validation fails. `detail` stays a
    plain string so a client that only reads `detail` keeps working."""

    detail: str
    issues: list[FieldIssue]


# ---------------------------------------------------------------- SAP read-back (M7, Priya)


class ReadBackRow(BaseModel):
    field: str = Field(description="SAP field name, e.g. 'CardName' or 'BPAddresses[0].City'")
    sent: str | None = Field(description="Bank values masked")
    read_back: str | None = Field(description="Bank values masked")
    match: bool


class SapPublishView(BaseModel):
    """What Priya sees after publish: the record in the SAP mock and the field-by-field check.
    Served as RequestDetail.sap_publish and GET /requests/{req_id}/sap-readback."""

    resource: Literal["BusinessPartners", "Items", "ProfitCenters"]
    sap_code: str = Field(description="CardCode / ItemCode / CenterCode")
    published_at: datetime
    published_by: str
    active: bool = Field(description="False while Frozen=tYES (inactive until verified)")
    all_match: bool
    rows: list[ReadBackRow]


# ---------------------------------------------------------------- M8 regional view (D-009)

ProductFamily = Literal["A", "B", "C"]
MergeView = Literal["before", "after"]


class Caption(BaseModel):
    """A metric's plain-English definition, shown under it in the UI."""

    title: str
    caption: str


class HeatCell(BaseModel):
    country: CountryCode
    product: ProductFamily
    value_usd: float = Field(description="Confirmed-PO value, last 12 full months")
    growth_pct: float | None = Field(description="T3 vs P3, % change; None if P3 = 0")
    customers: int = Field(description="Customer count (records before merge, golden after)")


class BridgeStep(BaseModel):
    step: Literal["start", "new", "expansion", "contraction", "lost", "end"]
    value_usd: float = Field(description="start/end = P3/T3 revenue; others signed deltas")
    customers: int


class LostCustomer(BaseModel):
    card_code: str = Field(description="Raw record before merge, golden id after")
    name: str
    country: CountryCode
    last_order: str = Field(description="YYYY-MM-DD")
    is_duplicate_artefact: bool = Field(
        description="Before merge only: this 'lost' customer is really ordering under another "
        "record of the same customer"
    )


class RecommendedAction(BaseModel):
    title: str
    detail: str = Field(description="One or two plain sentences with the number behind it")
    evidence: str = Field(description="Which panel/metric this comes from")


class PanelCount(BaseModel):
    kind: Literal["confirmed_po", "enquiry", "purchase_request", "mdm_request"]
    label: str
    count: int
    value_usd: float | None = Field(description="None for MDM requests (never demand, rule 9)")
    caption: str


class RegionalView(BaseModel):
    view: MergeView
    period: str = Field(description="e.g. 'Oct 2025 - Sep 2026 (last 12 full months)'")
    country: CountryCode | None = Field(default=None, description="Filter; None = all five")
    heatmap: list[HeatCell]
    nrr_pct: float = Field(description="T3 revenue from customers active in P3 / P3 revenue")
    bridge: list[BridgeStep]
    cross_sell_pct: float = Field(description="% of customers active in 12 months buying >= 2")
    customer_count: int
    lost_customers: list[LostCustomer]
    panels: list[PanelCount] = Field(description="POs, enquiries, PRs, MDM requests: separate")
    actions: list[RecommendedAction] = Field(description="3-5, generated from the data")
    captions: dict[str, Caption] = Field(description="Metric key -> definition")


class MergeImpactCountry(BaseModel):
    country: CountryCode
    lost_before: int
    lost_after: int
    lost_that_were_duplicates: int


class MergeImpact(BaseModel):
    """Before vs after merge, side by side (the pitch numbers)."""

    customers_before: int
    customers_after: int
    lost_before: int
    lost_after: int
    lost_that_were_duplicates: int
    by_country: list[MergeImpactCountry]
    nrr_before_pct: float
    nrr_after_pct: float
    caption: str


# ---------------------------------------------------------------- M9 forecast backtest (D-008)

Scenario = Literal["seasonal_trend", "flat_noisy", "intermittent"]


class ForecastScore(BaseModel):
    method: Literal["excel_6m", "excel_12m", "combination", "tsb"]
    label: str = Field(description="e.g. 'Excel average (last 6 months)'")
    wape_pct: float = Field(description="Error as % of volume; lower is better")
    bias_pct: float = Field(description="+ = over-forecast, - = under-forecast")


class ForecastSeriesResult(BaseModel):
    level: Literal["country_product", "product", "customer_product"]
    country: CountryCode | None = None
    product: ProductFamily
    scores: list[ForecastScore]
    winner: str = Field(description="Method with the lowest WAPE")


class ForecastPoint(BaseModel):
    month: str = Field(description="YYYY-MM-01")
    actual: float | None
    excel_6m: float | None
    combination: float | None


class ForecastBacktest(BaseModel):
    scenario: Scenario
    data: Literal["clean", "dirty"]
    setup: str = Field(description="Rolling origin, h=3, n_windows=10, step 1 (plain English)")
    overall: list[ForecastScore]
    series: list[ForecastSeriesResult]
    chart: list[ForecastPoint] = Field(
        description="One example series for the panel (default VN x A), actuals vs both methods"
    )
    chart_series: str = Field(description="e.g. 'Vietnam, Product A (units)'")
    honest_note: str = Field(description="e.g. 'In flat_noisy the Excel average wins.'")
    bias_by_country: list["CountryBias"] = Field(
        default=[], description="D-020 item 1: does each method run high or low per country?"
    )
    bias_note: str | None = Field(
        default=None, description="Plain-English caption for bias_by_country, whatever it shows"
    )


class CountryBias(BaseModel):
    """D-020 item 1: forecast bias per country, next to how fast that market grew."""

    country: CountryCode
    product: ProductFamily | None = Field(
        default=None, description="None = all products of the country added up"
    )
    growth_pct: float | None = Field(
        description="Units ordered, last 12 full months vs the 12 before (% change)"
    )
    scores: list[ForecastScore] = Field(description="WAPE and bias for each method")


class ForecastSummary(BaseModel):
    """All scenarios x clean/dirty, for the scenario switcher and results table."""

    runs: list[ForecastBacktest]
    captions: dict[str, Caption]


# ---------------------------------------------------------------- M10 ops impact (D-018 item 4)


class CycleTimeStat(BaseModel):
    process: Literal["old_email_sequential", "new_parallel"]
    label: str
    median_bd: float = Field(description="Business days, submitted -> live in SAP")
    p90_bd: float


class Assumption(BaseModel):
    name: str
    value: str
    source: Literal["brief", "generated_history", "our_design", "assumption"]


class OpsImpact(BaseModel):
    cycle_time: list[CycleTimeStat]
    amy_before_bd: float = Field(description="The brief's scenario: 18 days")
    amy_after_bd: float
    amy_explanation: str
    first_time_right_before_pct: float = Field(description="Not bounced for missing fields")
    first_time_right_after_pct: float
    duplicates_prevented: int = Field(description="Requests linked to an existing record")
    assumptions: list[Assumption]
    caption: str = Field(description="'Modelled, not measured' framing in plain English")


# Resolves the forward references on RequestDetail (FieldIssue, SapPublishView, InfoRequestView)
# and ForecastBacktest (CountryBias).
RequestDetail.model_rebuild()
ForecastBacktest.model_rebuild()
