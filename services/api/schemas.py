"""API contract. Every request and response body is a Pydantic v2 model."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from ds.interpreter.schemas import Category, Interpretation, MdmDomain, OrderLine, QuotedValue


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
    country: str | None = Field(
        default=None,
        description="ISO 3166 alpha-2 code. SG/MY/ID/VN/TH, or any other country for a vendor",
    )
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
    sap_note: str | None = Field(
        default=None, description="A one-line note about what SAP does with this record type"
    )


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


# ---------------------------------------------------------------- live AI trace (Stretch S1, D-023)
#
# POST /emails/{email_id}/interpret/stream answers `text/event-stream`: one `event: step` per
# InterpretStep, `data:` = the step as JSON. The steps REPLAY a finished Interpretation (the same
# one POST /emails/{id}/interpret returns), paced so the trace takes about 1.5 s. No step ever
# holds bank details: they come from the already-stripped Interpretation (rule 5).
#
# Order: start, [bank_stripped], field x n, line x m, category, [missing], [injection], done.


class TraceStart(BaseModel):
    kind: Literal["start"] = "start"
    email_id: str
    source: Literal["replay", "live", "keyword_fallback"] = Field(
        description="replay = a recorded AI answer (LLM_MODE=replay); live = answered just now; "
        "keyword_fallback = AI offline, keyword rules' guess"
    )
    total_steps: int = Field(description="Steps after this one, `done` included")
    step_ms: int = Field(description="Pause between steps the server is using")


class TraceBankStripped(BaseModel):
    kind: Literal["bank_stripped"] = "bank_stripped"


class TraceField(BaseModel):
    kind: Literal["field"] = "field"
    index: int
    field: QuotedValue


class TraceLine(BaseModel):
    kind: Literal["line"] = "line"
    index: int = Field(description="Matches the `line-{index}` highlight key the inbox uses")
    line: OrderLine


class TraceCategory(BaseModel):
    kind: Literal["category"] = "category"
    category: Category
    confidence: float
    domain: MdmDomain | None = None
    needs_review: bool
    method: Literal["llm", "keyword_fallback"]


class TraceMissing(BaseModel):
    kind: Literal["missing"] = "missing"
    missing_fields: list[str]
    questions_for_requester: list[str]


class TraceInjection(BaseModel):
    kind: Literal["injection"] = "injection"


class TraceDone(BaseModel):
    kind: Literal["done"] = "done"
    interpretation: Interpretation


InterpretStep = Annotated[
    TraceStart
    | TraceBankStripped
    | TraceField
    | TraceLine
    | TraceCategory
    | TraceMissing
    | TraceInjection
    | TraceDone,
    Field(discriminator="kind"),
]


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


class AuditVerifyResult(BaseModel):
    """Result of walking the whole audit hash chain (all requests), for the History check."""

    ok: bool
    checked: int = Field(description="How many entries were checked and found intact")
    first_broken_id: int | None = Field(
        default=None, description="Number of the first entry that was changed or removed"
    )
    message: str = Field(description="Plain-English result to show as it is")
    reason: str | None = Field(
        default=None, description="Technical reason, for the logs and tests; not for users"
    )


class AuditEntry(BaseModel):
    """One audit row for the status-page timeline (bank values are already masked)."""

    id: int
    ts: datetime
    actor: str
    action: str
    entity_type: str
    entity_id: str
    summary: str = Field(description="Plain English, e.g. 'Wei Jie approved (Finance)'")


# ---------------------------------------------------------------- approval rules (session 12)

StepRole = Literal["bu_head", "finance", "business_support", "quality_regulatory"]
RuleCountry = Literal["SG", "MY", "ID", "VN", "TH", "*"]


class RuleStepIn(BaseModel):
    role: StepRole
    user_id: str


class RuleStep(BaseModel):
    role: StepRole
    role_label: str = Field(description="Plain label, e.g. 'BU Head'")
    user_id: str
    name: str


class RuleKey(BaseModel):
    domain: Domain
    entity: EntityCode
    country: RuleCountry = Field(
        description="The record's country; '*' (all countries) for items and cost centers"
    )


class RoutingRule(RuleKey):
    steps: list[RuleStep] = Field(description="Who reviews in stage 1, in order")
    is_override: bool = Field(description="False: the standard route from the rule table applies")
    changed_by: str | None = Field(default=None, description="Name of who saved the override")
    changed_at: datetime | None = Field(default=None, description="Simulated clock")


class RuleRole(BaseModel):
    role: StepRole
    label: str
    people: list[Persona]


class RoutingRules(BaseModel):
    rules: list[RoutingRule]
    roles: list[RuleRole] = Field(description="Who can be chosen for each step role")
    publish_note: str = Field(description="The MDM publish stage is shown but not editable")


class RoutingRuleSave(RuleKey):
    steps: list[RuleStepIn]


class RulePreviewRequest(RuleKey):
    steps: list[RuleStepIn] | None = Field(
        default=None,
        description="An unsaved draft. Omit it to see the saved rule or the standard route",
    )


class RulePreviewTask(BaseModel):
    stage: int
    stage_name: str
    role: str
    role_label: str
    user_id: str
    name: str


class RulePreview(BaseModel):
    tasks: list[RulePreviewTask]
    source: Literal["draft", "saved", "standard"]


class ConfigChange(BaseModel):
    id: int
    at: datetime = Field(description="Simulated clock")
    who: str
    domain: Domain
    entity: EntityCode
    country: RuleCountry
    summary: str = Field(description="Plain English, e.g. 'Priya changed the approvers for ...'")
    before: list[str] = Field(description="'BU Head: Name' lines, in order")
    after: list[str]


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
    growth_12m_pct: float | None = Field(
        description="Headline growth (D-022): last 12 full months vs the 12 before, % change; "
        "None if the prior 12 months had no sales"
    )
    customers: int = Field(description="Customer count (records before merge, golden after)")


class CountryGrowth(BaseModel):
    """One country's 12-month growth, all products together (the Southeast Asia map, D-024 #5).
    A total, so it is the same before and after merge."""

    country: CountryCode
    value_usd: float = Field(
        description="Confirmed-PO value in the last 12 full months, in US dollars"
    )
    prior_value_usd: float = Field(
        description="Confirmed-PO value in the 12 months before that, in US dollars"
    )
    growth_12m_pct: float | None = Field(
        description="Last 12 full months compared with the 12 before, as a % change (rounded to "
        "0.1); None if the country had no sales in the 12 months before"
    )


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


class DropOffRisk(BaseModel):
    """A real customer (after merge) whose repeat orders are fading but not yet lost (PRD S1)."""

    card_code: str = Field(description="Golden (merged) customer id")
    name: str
    country: CountryCode
    last_order: str = Field(description="YYYY-MM-DD, latest confirmed PO")
    value_at_risk_usd: float = Field(
        ge=0,
        description="Repeat (Product A + C) confirmed-PO value in the same 3 months last year "
        "minus the last 3 months: how much less it ordered than a year earlier (year over year, "
        "so seasonal dips do not count). Listed when the last 3 months are at most half the "
        "same quarter last year, that quarter was at least US$5,000, the customer ordered in at "
        "least 3 of the 9 months before, and it is not on the lost list. Customers with no "
        "repeat orders in that quarter last year cannot be compared and are never listed.",
    )
    change_pct: float | None = Field(
        description="Last 3 months vs the same 3 months last year, % change in repeat spend "
        "(-100 = stopped)"
    )
    reason: str = Field(description="One plain sentence")


class WhitespaceOpportunity(BaseModel):
    """A real customer (after merge) that buys some product families but not one (PRD S1)."""

    card_code: str = Field(description="Golden (merged) customer id")
    name: str
    country: CountryCode
    buys: list[str] = Field(description="Product families (A/B/C) bought in the last 12 months")
    missing: str = Field(
        description="The repeat family (A test kits or C services) not bought with the highest "
        "estimate. Never B: equipment is a one-off capital purchase, not a yearly spend."
    )
    est_value_usd: float = Field(
        ge=0,
        description="Median 12-month confirmed-PO spend on the missing family by comparable "
        "customers: same country, already buying it and at least one family this customer "
        "buys (at least 3 such customers). An estimate, not a forecast.",
    )
    comparable_customers: int = Field(
        ge=0, description="How many comparable customers the median is based on"
    )
    low_confidence: bool = Field(
        description="True when the estimate rests on fewer than 10 comparable customers. "
        "Still listed, but left out of the US$ total."
    )
    reason: str = Field(description="One plain sentence")


class AccountListTotal(BaseModel):
    """Totals for one account list over ALL qualifying customers, not only the rows shown."""

    customers: int = Field(ge=0, description="Customers that qualify for the list")
    shown: int = Field(ge=0, description="Rows returned in the list (top 10)")
    total_usd: float = Field(
        ge=0,
        description="Drop-off: sum of value at risk. Whitespace: sum of estimates over rows that "
        "are NOT low confidence.",
    )
    low_confidence: int = Field(ge=0, description="Rows left out of total_usd (whitespace only)")
    caption: str = Field(
        description="One plain sentence for the UI, says what the total leaves out"
    )


class PanelCount(BaseModel):
    kind: Literal["confirmed_po", "enquiry", "purchase_request", "mdm_request"]
    label: str
    count: int
    value_usd: float | None = Field(description="None for MDM requests (never demand, rule 9)")
    caption: str


class LostAlertChange(BaseModel):
    """How the lost-customer alerts change when duplicates are merged (same in both views).

    after = before - duplicates + new_after_merge. Note: if two records that are both still lost
    merged into one customer, a third term would be needed; the demo data has none, and the
    tests check the sum per country.
    """

    before: int = Field(description="Alerts counting every SAP record as a customer")
    duplicates: int = Field(
        description="Before-merge alerts on a record whose customer is still ordering under "
        "another record (false alarms that merging removes)"
    )
    new_after_merge: int = Field(
        description="Merged customers flagged lost although none of their records was: "
        "together the records look like a more frequent buyer, so the same quiet spell counts"
    )
    after: int = Field(description="Alerts after merging duplicates")


class RegionalView(BaseModel):
    view: MergeView
    period: str = Field(description="e.g. 'Oct 2025 - Sep 2026 (last 12 full months)'")
    country: CountryCode | None = Field(default=None, description="Filter; None = all five")
    heatmap: list[HeatCell]
    country_growth: list[CountryGrowth] = Field(
        description="12-month growth per country, one row for each of the five countries "
        "whatever the country filter (it drives the map, which always shows all five)"
    )
    nrr_pct: float = Field(description="T3 revenue from customers active in P3 / P3 revenue")
    bridge: list[BridgeStep]
    cross_sell_pct: float = Field(description="% of customers active in 12 months buying >= 2")
    customer_count: int
    lost_customers: list[LostCustomer]
    lost_alert_change: LostAlertChange
    panels: list[PanelCount] = Field(description="POs, enquiries, PRs, MDM requests: separate")
    drop_off_risk: list[DropOffRisk] = Field(
        default_factory=list,
        description="After merge: top 10 fading customers by value at risk (country filter "
        "applies). Empty before merge: a customer split across records looks like it is "
        "fading when another record is still ordering, so the account is not known yet.",
    )
    cross_sell_whitespace: list[WhitespaceOpportunity] = Field(
        default_factory=list,
        description="After merge: top 10 cross-sell gaps, confident rows first, then by estimated "
        "value (country filter applies; lost "
        "and fading customers left out). Empty before merge: each record sees "
        "only the products bought under it, so the gaps are not real.",
    )
    drop_off_total: AccountListTotal | None = Field(
        default=None, description="After merge: totals over every fading customer. None before."
    )
    whitespace_total: AccountListTotal | None = Field(
        default=None,
        description="After merge: totals over every cross-sell gap; the US$ total excludes "
        "low-confidence rows. None before.",
    )
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
    # session 13 pipeline forecast (clean runs only; see the block below ForecastSummary)
    pipeline_note: str | None = Field(
        default=None,
        description="One plain line: Product B planned from purchase requests vs the averages",
    )
    pipeline_region: list["PipelineScore"] = Field(
        default=[], description="Product B, whole region: WAPE and bias of all five methods"
    )
    plan_next_3m: "ForecastPlan | None" = Field(
        default=None, description="Next 3 months plan per country x product (Oct-Dec 2026)"
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


# ---------------------------------------------------------------- session 13 pipeline forecast
# Product B planned from purchase requests x a conversion rate (ds/forecasting/pipeline.py),
# and the forward "Next 3 months plan" (ds/forecasting/plan.py). Attached to clean runs.


class PipelineScore(BaseModel):
    method: Literal["excel_6m", "excel_12m", "combination", "pipeline_pr", "pipeline_pr_enq"]
    label: str
    wape_pct: float = Field(description="Error as % of volume; lower is better")
    bias_pct: float = Field(description="+ = over-forecast, - = under-forecast")


class PlanRow(BaseModel):
    country: CountryCode
    country_name: str
    product: ProductFamily
    excel_6m: float = Field(description="Units, Oct-Dec together: 3 x the last 6 months' mean")
    excel_6m_monthly: list[float]
    combination: float = Field(description="Units, Oct-Dec together: our combination")
    combination_monthly: list[float]
    pipeline_pr: float | None = Field(
        default=None, description="Product B only: units from purchase requests x conversion"
    )
    pipeline_pr_enq: float | None = Field(
        default=None, description="Product B only: requests and enquiries, averaged"
    )
    growth_adjustment: float | None = Field(
        default=None,
        description="Fast-growing countries only (D-020): units to add on top of the Excel plan; "
        "never included in another column",
    )
    growth_adjustment_pct: float | None = Field(
        default=None,
        description="How far Excel's plan came out below actual orders in the backtest "
        "(% of actual orders, all products together)",
    )
    growth_adjustment_uplift_pct: float | None = Field(
        default=None,
        description="The adjustment as a % of Excel's plan: -b / (1 + b); what closes the gap",
    )
    growth_adjustment_caption: str | None = None


class ForecastPlan(BaseModel):
    scenario: Scenario
    origin: str = Field(description="Last full month used, YYYY-MM-01")
    months: list[str] = Field(description="The 3 planned months, YYYY-MM-01")
    fast_growing: list[CountryCode] = Field(description="D-020 fast-growing countries")
    rows: list[PlanRow]
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


# ---------------------------------------------------------------- clean-up queue (D-018 #5)


CleanupDecision = Literal["confirm", "not_same"]
CleanupStatus = Literal["not_reviewed", "confirmed", "not_same"]


class CleanupRecord(BaseModel):
    """One existing customer record in a proposed group. Plain master fields only: bank details
    are never part of this view."""

    CardCode: str
    CardName: str
    CardForeignName: str | None = None
    FederalTaxID: str | None = None
    City: str | None = None
    Country: str
    U_Entity: str | None = None
    Phone1: str | None = None
    EmailAddress: str | None = None
    CreateDate: str | None = Field(default=None, description="ISO date the record was created")
    CreatedBy: str | None = None
    group_name: str | None = Field(
        default=None, description="Cross-border hospital/lab group (rule 3), when known"
    )


class CleanupReason(BaseModel):
    text: str = Field(description="Plain English, from the duplicate check")
    against: bool = Field(description="True when this reason counts against the match")


class CleanupLink(BaseModel):
    """Two records the duplicate check calls 'Likely' the same customer."""

    a: str
    b: str
    score: float = Field(ge=0.0, le=1.0, description="Duplicate-check score, 0 to 1")
    tax_id_match: bool
    reasons: list[CleanupReason]


class CleanupDecisionIn(BaseModel):
    """A person's decision on one proposed group. The AI never makes it (rule 6)."""

    decision: CleanupDecision
    reason: str | None = Field(
        default=None,
        description="Required for not_same, at least 10 characters: why these are different "
        "customers",
    )


class CleanupDecisionOut(BaseModel):
    decision: CleanupDecision
    reason: str | None = None
    decided_by: str = Field(description="Name of the person who decided")
    decided_at: datetime = Field(description="Simulated-clock time of the decision")


class CleanupCluster(BaseModel):
    cluster_id: str = Field(description="Same id as the golden cluster in the after-merge view")
    certainty: str = Field(description="Plain-English summary of how certain the check is")
    all_tax_id_match: bool
    weakest_score: float = Field(ge=0.0, le=1.0)
    records: list[CleanupRecord]
    links: list[CleanupLink]
    status: CleanupStatus
    decision: CleanupDecisionOut | None = None


class CleanupQueue(BaseModel):
    clusters: list[CleanupCluster] = Field(description="Most certain first")
    reviewed: int
    total: int
    can_decide: bool = Field(description="True when the acting user may confirm or reject")
    note: str | None = Field(default=None, description="Why the acting user cannot decide")


class CleanupDecisionResult(BaseModel):
    cluster: CleanupCluster
    reviewed: int
    total: int


# ============================================================================================
# Session 13 cost center / required fields. Cost Center is now a schema-driven form like the
# other three (config/forms/cost_center.schema.json). Priya can switch a field between required
# and optional per record type x country; a request keeps the rules it was created with.
# ============================================================================================


class RequiredFieldRow(BaseModel):
    field: str = Field(description="Form field (SAP name), e.g. 'EmailAddress'")
    label: str = Field(description="Plain label, e.g. 'Email'")
    help: str | None = Field(default=None, description="The form's one-line hint for the field")
    required: bool = Field(description="True when the field is required right now")
    standard: bool = Field(description="True when the standard rules (YAML) require it")
    changed: bool = Field(description="True when this differs from the standard rules")
    locked: bool = Field(description="True when it can never be made optional")
    locked_reason: str | None = Field(
        default=None, description="One plain line on why a locked field must stay required"
    )


class RequiredFieldsView(BaseModel):
    domain: Domain
    country: CountryCode
    fields: list[RequiredFieldRow] = Field(description="In form order")
    note: str = Field(description="Plain-English caption: applies to new requests only")


class RequiredFieldSet(BaseModel):
    field: str
    required: bool


class RequiredFieldsSave(BaseModel):
    domain: Domain
    country: CountryCode
    fields: list[RequiredFieldSet] = Field(
        min_length=1, description="The fields to switch. Fields left out are not touched"
    )


class RequiredFieldChange(BaseModel):
    id: int
    at: datetime = Field(description="Simulated clock")
    who: str
    domain: Domain
    country: CountryCode
    field: str
    field_label: str
    now_required: bool
    summary: str = Field(
        description="Plain English, e.g. 'Priya made Email required for Singapore customers'"
    )


# Resolves the forward references on RequestDetail (FieldIssue, SapPublishView, InfoRequestView)
# and ForecastBacktest (CountryBias; PipelineScore and ForecastPlan, session 13).
RequestDetail.model_rebuild()
ForecastBacktest.model_rebuild()
ForecastSummary.model_rebuild()
