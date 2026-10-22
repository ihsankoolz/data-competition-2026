# PRD — Lives Group MDM: "Messy in, clean out" (Option D+)

## 1. Problem framing

- Lives Group runs 3 entities (SPD, QTS, QTG) on **one shared SAP Business One** across 5 countries.
- Master data requests arrive as free-text emails. Fields are missing. The same customer is spelled many ways, in different languages and scripts.
- Approvals run one after another by email. Amy's item request took **18 days**.
- Because records are messy and duplicated, the regional sales view is wrong: customers look "lost" when they were just re-created under a new name.
- **The organisers' hint:** the core challenge is *interpreting incomplete data — the same data with different wording* — and *cross-border issues*.

## 2. The solution spine

- **One idea:** clean the record at the point of entry, and both problems get fixed.
- Messy email or form → **interpreted** into a structured request → **checked against existing records** (one golden ID) → **approved in parallel** → **published to SAP B1**.
- The same golden IDs feed a **regional view** that is honest: real POs only, duplicates merged, forecast tested against the Excel average.

## 3. Cast (seeded users)

| Persona | Role | Entity / country | From brief? |
|---|---|---|---|
| Amy | Product Manager (requestor) | SPD, Singapore | Yes |
| Marcus | Regional Sales, new BU (requestor) | QTG, Vietnam | Yes |
| Wei Jie | Finance Manager (approver: credit terms, bank details) | Group, Singapore | Yes |
| Priya | MDM Analyst (final check, publish to SAP) | Group, Singapore | Yes |
| Daniel | BU Head (approver) | SPD | Invented |
| Nurul | Quality/Regulatory (approver, per country) | Group, Malaysia | Invented |
| Mei Ling | Business Support (approver) | Group, Singapore | Invented |
| Hui Min | Finance (second approver for bank changes) | Group, Singapore | Invented |

## 4. Target demo storyline (2:30 video)

1. **0:00 — The messy inbox.** Show 60 real-looking emails in mixed wording and languages. One click: each is classified (PO / purchase request / enquiry / follow-up / MDM request) and key fields are extracted with the source quote highlighted.
2. **0:25 — Marcus (new BU, Vietnam).** His email asks for a new customer "Benh vien Cho Ray". The interpreter pre-fills the form. The duplicate panel shows "Bệnh viện Chợ Rẫy (SPD, VN), same tax ID". He links to the existing record. The duplicate never reaches an approver.
3. **0:55 — Amy (item request).** The form requires the per-country registration fields. Quality/Regulatory is auto-routed. Approvers are notified **in parallel**. Amy's status page shows exactly who is pending.
4. **1:20 — Wei Jie.** Fast-forward the simulated clock to day 2. He gets a reminder. Bank details are masked for everyone except Finance. He approves. The audit log shows who, what, when.
5. **1:40 — Priya.** One click: publish to the SAP B1 mock (`POST /b1s/v2/BusinessPartners`). The read-back matches. No re-keying.
6. **1:55 — Regional view.** Toggle "before merge" vs "after merge". Fake "lost customers" disappear. Growth by country × product changes. The forecast panel shows Excel average vs our method, including the scenario where the Excel average wins.
7. **2:20 — Close.** "Amy's 18 days becomes about 4 (modelled). X of Y 'lost customers' were duplicates. Pilot one BU in 6 weeks; email stops for that BU on day 30."

## 5. Scope

### 5.1 Must (baseline D+) — with acceptance checks

| # | Feature | Acceptance check |
|---|---|---|
| M1 | **Synthetic data generator** (see `data-spec.md`) | `make data SEED=42` is deterministic. Produces all tables + ground-truth files. 3 scenarios. Generation rules documented in `docs/data-spec.md`. |
| M2 | **Messy-inbox interpreter** (one LLM module, two uses) | Classifies every fixture email into 5 classes and extracts fields to a schema with a `source_quote` per field and a `missing_fields` list. Runs fully in `replay` mode offline. Confusion matrix + macro-F1 written to `docs/results.md`. |
| M3 | **Schema-driven request form** | BP (customer, vendor) and Item forms render from config JSON Schema. Required fields come from config per domain × country. "Create from email" pre-fills the form. |
| M4 | **Layered duplicate check** | Runs on form change (debounced) and on submit. Layers: tax-ID exact → normalise + multilingual dictionary → rapidfuzz → LLM top-k select in grey zone. Shows candidates side by side with reasons. Respects the C/V rule and the cross-country group rule. Precision/recall on planted duplicates in `docs/results.md`. |
| M5 | **Parallel approvals + status page** | Rule table decides approvers. Approvals in a stage run in parallel. Requestor and approver both see live status. Reminder at 50% of SLA, escalation at 100%, driven by the simulated clock. Approve / reject / ask-for-info. |
| M6 | **Audit log** | Append-only table. Every state change, field edit (old → new), dedup decision, approval and SAP call is logged with actor and timestamp. Each row stores `prev_hash` and `hash` (verification UI is Stretch). |
| M7 | **SAP B1 Service Layer mock + publisher** | Mock on `/b1s/v2`: `POST /Login` sets `B1SESSION` + `ROUTEID`, 30-min idle timeout, `POST`/`GET`/`PATCH` for `BusinessPartners`, `Items`, `ProfitCenters`, B1-style error JSON, rejects duplicate keys. Publisher logs in, posts as inactive, reads back, verifies, then activates. |
| M8 | **Regional business view** | Stated period = last 12 full months. Country × product heatmap of confirmed-PO value (USD). Growth = NRR and a revenue bridge (new / expansion / contraction / lost), trailing 3 months vs prior 3. Cross-sell penetration. POs, enquiries and MDM requests in separate panels. **Before/after merge toggle.** 3–5 recommended actions generated from the data. |
| M9 | **Forecast backtest** | Rolling origin over the last 12 months, horizon 3. Baseline = exact Excel 6-month window average (also 12-month). Model = equal-weight combination (AutoETS, AutoTheta, SeasonalNaive) + TSB for intermittent customer series. WAPE and bias, per country × product, for all 3 scenarios. Clean-vs-dirty data comparison. |
| M10 | **Ops impact numbers** | Modelled cycle time (sequential vs parallel) for the brief's scenario, first-time-right rate, duplicates prevented. Shown on one summary card. |

### 5.2 Stretch backlog (only after all Must checks pass)

Ranked by rubric impact per hour. Pick from the top.

| Tier | Feature | Rubric lever | Est. |
|---|---|---|---|
| S1 | **Live "AI reading the email" trace:** fields light up with their source quotes as the interpreter works (SSE from FastAPI replaying cached steps; Vercel `ai-elements` reasoning/message components) | Innovation, communication — directly shows the organisers' core challenge | 3h |
| S1 | **Pipeline beam visual:** Magic UI `animated-beam` showing email → interpreted → golden record → approvals → SAP, lit per request state | Communication | 1h |
| S1 | Per-country regulatory rules: auto Q/R routing per selling country; **expired registration blocks publish** | Problem understanding | 1.5h |
| S1 | Ops KPI dashboard: cycle time, SLA breaches by approver, first-time-right %, requests via new path vs email | Business impact | 2h |
| S1 | Bank-field masking by role + second Finance approver for bank changes (maker-checker) | Governance | 1.5h |
| S1 | Drop-off risk list + cross-sell whitespace list with USD value per account | Business impact | 2h |
| S2 | Live config editor: add an approval step / onboard a new BU in 30 seconds | Flexibility, innovation | 2h |
| S2 | Auto-reply simulation: email in → reply with pre-filled form link listing only missing fields | Adoption | 1.5h |
| S2 | Prompt-injection demo: injected email extracted harmlessly, flagged | Innovation, trust | 0.5h |
| S2 | Steward cleanup queue: batch-review existing duplicate clusters in the current master | Priya, data quality | 2.5h |
| S2 | **Southeast Asia map** (react-simple-maps, SG/MY/ID/VN/TH choropleth of growth; click a country to filter) | Communication, cross-border story | 2h |
| S2 | Polish pack: confetti on first SAP publish, sonner toasts, number-flow KPIs, skeleton loaders | Communication | 1h |
| S3 | ⌘K command palette (shadcn Command) to jump to any record during the demo | Demo smoothness | 1h |
| S3 | Playwright visual regression (`toHaveScreenshot`) on status page + dashboard | Solution quality | 1h |
| S3 | Hash-chain "verify audit" button + tamper demo | Governance | 1h |
| S3 | Chronos-2 zero-shot challenger column in the backtest | Innovation | 2h |
| S3 | Hierarchical reconciliation (MinT `wls_struct`, non-negative) | Solution quality | 2h |
| S3 | Real Teams Incoming Webhook / Adaptive Card notification | M365 fit | 1.5h |
| S3 | M3 monthly sanity check of the backtest direction | Credibility | 0.5h |
| S3 | "Ask the regional view" natural-language Q&A | Innovation (risky) | 3h |

### 5.3 Won't build in v1 (state this in the deck)

- Real SAP B1 connection or real M365 tenant.
- Splink (evaluated; deferred to v2 when real data with more columns exists).
- LightGBM / global ML forecasting, model fine-tuning.
- Auto-merge or AI-made approvals.
- Full custom UI for Cost Center (config + mock endpoint only).
- Real authentication / SSO (production path: Microsoft Entra ID).

## 6. Architecture

```
            ┌──────────── Next.js web (3000) ─────────────┐
            │ Inbox │ Request form │ Status │ Approvals │  │
            │ Priya publish │ Regional view │ Admin/config  │
            └───────────────┬─────────────────────────────┘
                            │ typed REST (OpenAPI)
            ┌───────────────▼─────────────────────────────┐
            │ FastAPI api (8000)                           │
            │  workflow engine (state machine + rule table)│
            │  simulated clock, audit log, role masking    │
            │  ds.interpreter  ds.dedup  ds.analytics      │
            │  ds.forecasting (precomputed + on demand)    │
            └──────┬──────────────────────┬───────────────┘
                   │ SQLite               │ HTTP (httpx, cookies)
                   ▼                      ▼
             data/app.db        SAP B1 mock (8001, /b1s/v2)
                                 Login, BusinessPartners, Items, ProfitCenters
```

- **Production story (pitch, not built):** Teams/Outlook front door, Power Automate for notifications, rule tables in a SharePoint list the MDM team edits, one small hosted "MDM brain" service, real Service Layer behind an integration user.

## 7. Request lifecycle

```
DRAFT → SUBMITTED → IN_APPROVAL → APPROVED → PUBLISHED_INACTIVE → ACTIVE
           │             │
           │             ├→ INFO_REQUESTED → (requestor edits) → IN_APPROVAL
           │             └→ REJECTED
           └→ LINKED_TO_EXISTING (duplicate confirmed by requestor; no approval needed)
```

- Approvals are grouped in **stages**. Tasks in a stage run in parallel. The next stage opens when all tasks in the current stage are approved.
- Priya's publish is the final stage.

## 8. Numbers to compute for the pitch

- Modelled cycle time: brief scenario, sequential vs parallel (label assumptions).
- Duplicate check precision / recall on planted duplicates, overall and per duplicate type.
- Interpreter macro-F1 and field-level extraction accuracy.
- Forecast WAPE and bias: Excel average vs our method, per scenario, clean vs dirty data.
- Duplicate damage: false "lost customer" alerts, inflated customer counts, growth distortion by country × product.
- NRR and cross-sell penetration per country × product.

## 9. Timeline

| When | Goal |
|---|---|
| Thu 22 evening | Repo scaffold, Makefile, schemas, SAP mock skeleton. Generator v1. |
| Fri 23 evening | Generator complete + fixtures. Dedup pipeline + eval. Interpreter + replay cache. |
| Sat 24 | Workflow engine, approvals, audit, publisher. Forecast backtest + analytics. Frontend: form, inbox, status. |
| Sun 25 | Frontend: approvals, Priya publish, regional view. End-to-end demo flow working. |
| Mon 26 evening | Persona test pass, fixes, numbers into `docs/results.md`. **Freeze 23:59.** Stretch only if Must is green. |
| Tue 27 evening | Record video, upload to YouTube. 2-page summary. README. |
| Wed 28 morning | Buffer. Submit by 10:00. |

## 10. Open items

- ~~Repo public or private.~~ **Resolved (D-016):** the repo must be public at submission. Keep it private until Wed 28 Oct morning, run a secret scan, then flip it to public before the 10:00 submit.
- ~~Finals format.~~ **Resolved (D-016):** 15-minute presentation + 5-minute Q&A, with a live demo. So the demo must be robust: an in-app "Reset demo" button (`POST /admin/reset-demo`, also called by `make reset-demo`) restores the seeded state in under 10 seconds without stopping the API, and every demo step works in LLM replay mode with no network.
