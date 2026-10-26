# Decisions log

Each decision: what, why, and what we rejected. Agents must follow these. Change a decision only through the orchestrator, and add a new entry rather than editing an old one.

---

## D-001 Solution shape: Option D+ ("Messy in, clean out")

- **Decision:** One connected story. Interpret messy input at entry → golden record → parallel approvals → SAP B1 → honest regional view.
- **Why:** Judges reward one working causal chain over many thin features. Organisers said the core challenge is "interpreting incomplete data, same data but different wording" and asked us to highlight cross-border issues.
- **Rejected:** Option A (too broad for one person), Option B (ignores the approval pain that all four personas describe), Option C (M365-native build; kept only as the production story).

## D-002 Stack

- Next.js (App Router, TypeScript, Tailwind, shadcn/ui, Recharts) + FastAPI + Python `ds` package + SQLite.
- One repo. `uv` for Python, `pnpm` for Node.
- **Why:** Fastest for Claude Code agents, demo-friendly, GitHub-friendly.
- **Rejected:** Streamlit (looks like a data app, weak for multi-persona workflow), Power Platform (needs tenant + premium licences).

## D-003 Countries and currencies

| Code | Country | Currency | Tax ID name | Synthetic format | Language mess to model |
|---|---|---|---|---|---|
| SG | Singapore | SGD | UEN | `201912345K` (9–10 chars) | English, acronyms (NUH, TTSH, KKH) |
| MY | Malaysia | MYR | SSM reg. no. | `202001012345` (12 digits) | Malay/English mix ("Hospital"), Sdn Bhd / Bhd |
| ID | Indonesia | IDR | NPWP | `01.234.567.8-901.000` (15 digits, dots optional) | "Rumah Sakit" / "RS", PT … Tbk |
| VN | Vietnam | VND | MST | `0301234567` (10 digits) | Diacritics on/off ("Bệnh viện Chợ Rẫy" vs "Benh vien Cho Ray"), Công ty TNHH, JSC |
| TH | Thailand | THB | TIN | `0105556123456` (13 digits) | Thai script vs romanised ("โรงพยาบาลศิริราช" vs "Siriraj Hospital"), Co., Ltd / PCL |

- All money is reported in **USD** using fixed FX rates stored in config (labelled assumption): SGD 0.74, MYR 0.22, IDR 0.000064, VND 0.000040, THB 0.028.
- **Why these five:** maximum variety of scripts, suffixes, tax-ID formats and regulators. Directly answers the organisers' "cross-border issues" hint.

## D-004 SAP B1 Service Layer contract (mock must match)

- Base path: `/b1s/v2` (OData v4; v1/OData v3 is deprecated per SAP).
- **Login:** `POST /b1s/v2/Login` body `{"CompanyDB","UserName","Password"}`. Response body `{"SessionId","Version","SessionTimeout":30}`. Sets cookies `B1SESSION` and `ROUTEID` (both required on later calls). Idle timeout 30 minutes → 401.
- **Logout:** `POST /b1s/v2/Logout`.
- **BusinessPartners** (`POST`, `GET /BusinessPartners('C00123')`, `PATCH`, `GET` with `$filter` on `CardName` / `FederalTaxID`):
  - `CardCode` (str, ≤15), `CardName` (str, ≤100), `CardType` (`cCustomer` | `cSupplier` | `cLid`), `GroupCode` (int), `FederalTaxID` (str, ≤32), `Currency` (str), `PayTermsGrpCode` (int), `CreditLimit` (float), `EmailAddress`, `Phone1`.
  - `Frozen` (`tYES`/`tNO`) used for **inactive until approved**. Mark as `[verify $metadata]`.
  - `BPAddresses[]`: `AddressName`, `AddressType` (`bo_BillTo` | `bo_ShipTo`), `Street`, `City`, `ZipCode`, `Country` (ISO-2).
  - `BPBankAccounts[]`: `BankCode`, `AccountNo`, `AccountName`, `BICSwiftCode`, `IBAN`, `Country`.
  - UDFs: `U_MDM_ReqID`, `U_GoldenID`, `U_Entity` (`SPD`|`QTS`|`QTG`).
- **Items:** `ItemCode` (str, ≤20), `ItemName` (str, ≤100), `ItemType` (`itItems`), `ItemsGroupCode` (int), `PurchaseItem` / `SalesItem` / `InventoryItem` (`tYES`/`tNO`, case-sensitive), `Frozen`, UDFs `U_MDM_ReqID`, `U_IVD` (`tYES`/`tNO`), `U_RegSummary` (str). Per-country registrations live in our app DB (production: a B1 user-defined table).
- **ProfitCenters** (UI label "Cost Center"): `CenterCode` (str, ≤8), `CenterName` (str, ≤30), `EffectiveFrom` (date), `InWhichDimension` (int), `Active` (`tYES`/`tNO`). Note in UI: adding a profit center auto-creates a distribution rule in B1.
- **Errors:** `{"error":{"code":-10,"message":{"lang":"en-us","value":"..."}}}` with HTTP 400 (validation), 401 (session), 404, 409-style duplicate key reported as 400 with message "This entry already exists in the following tables". Exact v2 error shape is `[unverified]`.
- **Publisher flow:** Login → POST with `Frozen=tYES` → GET read-back → field-by-field compare → PATCH `Frozen=tNO` → Logout. Every call goes to the audit log.
- README must list `[verify $metadata]` fields. Production swap = change base URL + integration user (needs SAP indirect-access licence).

## D-005 Duplicate check design

- **Layers, in order:**
  1. **Exact keys:** normalised `FederalTaxID` + country. Same tax ID + same country + same `CardType` → strong match.
  2. **Normalise:** lowercase, Unicode NFKD, strip diacritics (keep the original for display), strip punctuation, strip legal suffixes (per-country list in `ds/dedup/suffixes.yaml`).
  3. **Multilingual dictionary** (`ds/dedup/terms.yaml`): `rumah sakit|rs` → `hospital`; `benh vien` → `hospital`; `โรงพยาบาล` → `hospital`; `phong kham` → `clinic`; `klinik` → `clinic`; `univ|university`; `natl|national`; etc. Plus an alias table (`NUH` ↔ `National University Hospital`, `TTSH`, `KKH`, `RSCM` …) and generated acronyms.
  4. **Fuzzy score:** rapidfuzz `token_set_ratio` + `JaroWinkler`, with rarity weighting (common tokens like "hospital", "medical", "centre" down-weighted via IDF over the master).
  5. **Combine:** weighted score in [0, 1] from name score, tax ID, city, phone, email domain.
  6. **LLM judge (grey zone only):** if top score in `[0.70, 0.92)`, send the request + top-5 candidates; the LLM **selects** one or "none" with reasons (Wang et al., COLING 2025, "Match, Compare, or Select?").
- **Thresholds (config):** ≥0.92 or tax-ID exact → "Likely duplicate" (block submit until requestor links or overrides with a reason). 0.70–0.92 → "Possible duplicate" (warn + LLM judge). <0.70 → pass.
- **Never flag:** a `cCustomer` vs `cSupplier` pair for the same entity (domain rule 2); same `group_id` in a **different country** (domain rule 3).
- **Thai script:** the generator stores a romanised alias for each Thai name; dictionary + LLM judge handle script mismatch. No transliteration library required.
- **Rejected:** Splink (evaluated; deferred to v2 when real data with more populated columns exists), embeddings-only matching (over-matches generic names).

## D-006 Interpreter (one LLM module, two uses)

- Input: email subject + body (+ sender domain). Output Pydantic model:
  - `category`: `purchase_order` | `purchase_request` | `enquiry` | `follow_up` | `mdm_request`
  - `confidence` (0–1)
  - For `mdm_request`: `domain` (`customer`|`vendor`|`item`|`cost_center`) + extracted fields
  - For `purchase_order` / `purchase_request`: customer name as written, PO number, lines (product A/B/C, qty), requested date
  - Every extracted field has `value` + `source_quote` (exact substring). **Any value without a matching source quote is dropped.**
  - `missing_fields` (from config required fields) and `questions_for_requester`.
  - `injection_suspected` (bool) — flagged, never acted on.
- **Models (env-configurable):** `claude-haiku-5-5` for classify/extract; `claude-sonnet-5-5` for the dedup judge. Temperature 0. Structured JSON output.
- Confidence < 0.6 → "Needs human review" queue.
- Bank details are stripped from email text before any LLM call (regex for account/IBAN/SWIFT patterns) and must be entered in the secure form field.
- **Baseline to beat:** a keyword rule classifier, so we can show what the LLM adds.

## D-007 Workflow and approvals

- Plain state machine (see PRD §7). **No LLM in the workflow.** No LangGraph, no BPMN engine.
- Rule table (`config/routing_rules.yaml`, editable later in the admin UI):

| Domain | Condition | Stage 1 (parallel) | Stage 2 |
|---|---|---|---|
| Customer | always | BU Head, Finance (credit terms), Business Support | MDM publish |
| Vendor | always | BU Head, Finance (bank details), Business Support | MDM publish |
| Vendor | bank details present | + second Finance approver (Stretch S1) | |
| Item | always | BU Head, Business Support | MDM publish |
| Item | IVD or regulated in any selling country | + Quality/Regulatory (per country) | |
| Cost Center | always | Finance, BU Head | MDM publish |

- SLA per approval task: 2 simulated business days. Reminder at 50%, escalation to backup approver at 100%.
- Maker-checker: requestor can never approve own request; the publisher can't be the Finance approver.
- Simulated clock: `GET/POST /clock` (`advance` by hours/days, `reset`).

## D-008 Forecasting design

- **Data:** 36 months generated. **Stated regional period = last 12 full months.** The pitch point: SAP holds years of history; the 6–12 month window is a spreadsheet habit.
- **Target:** monthly confirmed-PO **units** per country × product (15 series). Value in USD for display.
- **Baseline (the "Excel method"):** mean of the last 6 months (`WindowAverage(6)`); also report 12.
- **Our method:** equal-weight mean of `AutoETS(season_length=12)`, `AutoTheta(season_length=12)`, `SeasonalNaive(12)` ("a simple combination in the spirit of SCUM", Petropoulos & Svetunkov 2020). Customer × product intermittent series (ADI > 1.32) use `TSB` (Teunter, Syntetos & Babai 2011).
- **Backtest:** rolling origin over the last 12 months, horizon 3, step 1 (`cross_validation(h=3, n_windows=10, step_size=1)`). Origins, horizon, metrics and baseline are fixed before the first run.
- **Metrics:** WAPE (judge-facing: "error as % of volume") and bias (over/under %). MASE in appendix only.
- **Scenarios:** `seasonal_trend`, `flat_noisy` (baseline should tie or win), `intermittent`. Report all three honestly.
- **Important nuance:** merging duplicate customers does **not** change country × product totals. It changes **customer-level** analytics (lost-customer alerts, customer counts, NRR bridge, customer-level forecasts). Enquiry leakage into "POs" **does** change totals. Report both effects separately and never claim dedup improves the country-level forecast.
- **Clean vs dirty comparison:** dirty = raw customer records + spreadsheet-style leakage (some enquiries and MDM requests counted as orders, per `data-spec.md`). Clean = golden IDs + confirmed POs only.
- Stretch: Chronos-2 column, MinT `wls_struct` reconciliation, M3 sanity check.

## D-009 Growth and customer metrics (definitions shown in UI)

- **Window:** trailing 3 months (T3) vs prior 3 months (P3), monthly confirmed-PO value in USD. Also a 12-month total for the stated period.
- **NRR** = T3 revenue from customers active in P3 ÷ P3 revenue.
- **Revenue bridge:** New (0 in P3, >0 in T3) + Expansion (retained, up) − Contraction (retained, down) − Lost (>0 in P3, 0 in T3).
- **Cross-sell penetration** = % of customers active in the last 12 months buying ≥2 of Products A/B/C.
- **Lost-customer alert:** no PO for more than max(90 days, 2 × the customer's median gap between orders).
- **Skip:** CAGR (meaningless on 12 months), share-of-wallet (unknown total spend).

## D-010 LLM determinism and demo safety

- `LLM_MODE=replay` by default. All demo inputs are pre-recorded into `data/fixtures/llm_cache/`.
- `make record` re-records with a real API key. Missing cache entry in replay mode → deterministic rule-based fallback + visible "AI offline" badge.
- Anthropic API key needed only for `record`/`live` (separate from the Claude Max plan).

## D-011 Things we say honestly in the deck

- All numbers come from synthetic data with a published generator. One scenario shows the Excel average winning.
- Cycle-time reduction is modelled from the brief's scenario with labelled assumptions.
- SAP Joule does not reach Business One per third-party sources (no SAP statement).
- Malaysia, Thailand regulatory details are assumptions; SG (HSA), VN (Decree 98/2021), ID (AKL/NIE) are researched.

## D-012 Citations (use these exact attributions)

- Wang et al., "Match, Compare, or Select? An Investigation of LLMs for Entity Matching", COLING 2025.
- Peeters, Steiner & Bizer, "Entity Matching using Large Language Models", EDBT 2025.
- Petropoulos & Svetunkov, "A simple combination of univariate models", IJF 2020.
- Syntetos & Boylan, IJF 2005 (SBA). Teunter, Syntetos & Babai, EJOR 2011 (TSB).
- Hyndman & Koehler, IJF 2006 (MASE). Tashman, IJF 2000 (rolling origin).
- SAP Community: no approval templates for BP/Item master data; inactive-until-approved workaround.

## D-013 Tooling (adopted 22 Oct after tooling research)

- **Claude Code plugins (official marketplace):** `frontend-design`, `typescript-lsp`, `pyright-lsp`, `pr-review-toolkit`, `commit-commands`. Later in the week: `security-guidance` (Mon evening only; it burns tokens).
- **MCP servers (`.mcp.json`, project scope):** `context7` (current library docs), `shadcn` (component registry), `playwright` (browser testing), `next-devtools` (runtime/hydration errors, Next 16).
- **Hooks (`.claude/settings.json`):** auto-format after every edit (ruff / prettier); block edits to `.env`, lockfiles and `.git/`. Scripts are Python so they work on Windows.
- **Frontend libraries:** shadcn/ui (Radix base) + Magic UI registry only; shadcn charts (Recharts v3); ECharts only for heatmap + waterfall; `motion`; `@number-flow/react`; `sonner`; `react-diff-viewer-continued`. Palette from tweakcn.
- **Python libraries:** `rapidfuzz`, `cleanco` + own suffix list, `anyascii`, `jellyfish`, `statsforecast`, `utilsforecast`, `faker`, `anthropic`, `pydantic`, `sqlalchemy`, `fastapi`, `uvicorn`, `httpx`, `tenacity`, `cryptography`, `pandas`, `ruff`, `pytest`.
- **Presentation:** Cap (free screen recorder with auto-zoom) for the video; D2 or Mermaid for the architecture diagram; Marp CLI or the pptx skill for the 2-pager.
- **Rejected:** 21st.dev Magic MCP (paid), Tremor (frozen), Figma/Stitch MCP (no designs exist), GitHub MCP (`gh` CLI is enough; token leak risk), sequential-thinking / memory MCPs (no gain), Chrome DevTools MCP (duplicates Playwright), big generic subagent packs (context noise), instructor / pydantic-ai (redundant), sentence-transformers (torch weight), Remotion, mixing more UI registries (Aceternity, Origin UI — AGPL now).

## D-014 Corrections and additions from tooling research

- **Excel baseline stays a 6-month window** (and 12). The research suggested `WindowAverage(3)`; the brief says the team uses 6–12 months, so we match the brief.
- **Backtest stays `h=3, n_windows=10`** (D-008), not `h=1, n_windows=3`. More origins, and 3 months matches planning horizons.
- **"≥0.92 = auto" does not mean auto-merge.** It means "Likely duplicate: block submit until a human links or overrides". Domain rule 6 still holds.
- **SAP mock additions to D-004:**
  - Add `CardForeignName` on BusinessPartners for the native-script name (Thai script, Vietnamese with diacritics). `CardName` holds the romanised legal name.
  - Error codes (mark `[unverified]` in README): duplicate key → HTTP 400, `code: -5002`; missing/expired session → HTTP 401, `code: 301`. `POST` create → 201; `PATCH` → 204.
- **shadcn init uses `-b radix`** because the CLI now defaults to Base UI and Magic UI is Radix-based.
- **Structured outputs:** use `client.messages.parse(output_format=PydanticModel)` (GA in the Anthropic SDK). No instructor.
- **Faker:** no `en_SG` or `ms_MY` locale. Generator templates SG and MY names itself.
- **anyascii** replaces unidecode (licence) for diacritic stripping and rough Thai romanisation.
- **Windows:** stdio MCP servers in `.mcp.json` run through `cmd /c npx`. `statsforecast` uses `n_jobs=1`.
- **Note (22 Oct, orchestrator; replaces the `CardName`/`CardForeignName` bullet above):** `CardName` holds whatever the creating entity typed, so it can be romanised **or** native script / diacritics. That inconsistency is the realistic mess the dedup check must handle. `CardForeignName` is optional (e.g. an English name). The existing SPD Chợ Rẫy record has `CardName` = "Bệnh viện Chợ Rẫy" **with** diacritics and `FederalTaxID` = `0301234567`, so DEMO-01 ("Benh vien Cho Ray") matches only via diacritic stripping + the MST.
- **Next.js is pinned to 16** (next-devtools MCP requires it).
- **PyYAML added** (22 Oct, approved by Ihsan) for `params.yaml`, `suffixes.yaml`, `terms.yaml` and `config/*.yaml`.

## D-015 Session 2 decisions (22 Oct, Ihsan)

- **DEMO-02 is a NEW item: "Malaria Pf/Pan Antigen Rapid Test Kit"** (IVD, needs per-country registration, so Q/R routing applies). It is clearly distinct from both dengue items (`A-DEN-NS1`, `A-DEN-IGM`), which stay as existing items. An **item duplicate check is Stretch (S3)**, not Must.
- **`U_Entity` = the entity that CREATED the record.** Orders carry their own `entity` from the product family (A→SPD, B→QTS, C→QTG). So a migrated record created by QTS can carry SPD Product A orders. Keep the mismatch: it is realistic for one shared B1.
- **Per-entity copies are true duplicates.** In one shared B1, the per-entity copies of the same customer (`record_role=entity_record`) are TRUE duplicates (the easy kind). The M4 evaluation scores by `golden_id` via `ground_truth/bp_golden_map.csv`: every same-golden customer record pair is a true match. Report "existing per-entity copies" as its own row next to the labelled `dup_type`s. These copies also count as inflated customers in the before-merge regional view. (Domain rule 2, customer vs vendor, is unchanged: a `cSupplier` twin is never a duplicate.)
- **Evaluation scripts are percent-format `.py` files** (`# %%` cells) in `notebooks/`, run by `make eval`. No Jupyter dependency.
- **Fixtures layout (contract between generator and seed loader):** `data/fixtures/seasonal_trend/` mirrors the `data-spec.md` §10 layout exactly (all CSVs, `emails.jsonl`, `users.csv`, `ground_truth/`); `data/fixtures/llm_cache/` holds the replay cache (`.gitkeep` until recorded). `users.csv` columns: `user_id, name, title, roles` (pipe-separated `Role` values from `services/api/schemas.py`), `entity, country, backup_for` (nullable `user_id`). User IDs match `services/api/personas.py` (`amy, marcus, weijie, priya, daniel, nurul, meiling, huimin`) plus one backup per approver role. Ground-truth files are never loaded into the app database.
- **Field encryption:** bank fields are encrypted at rest with `cryptography` Fernet. The key is read from env `FIELD_ENCRYPTION_KEY` at runtime only; tests generate a key at test time. No key is ever hard-coded or committed.

## D-016 Submission and finals constraints (22 Oct, organisers via Ihsan)

- **The GitHub repo must be public at submission.** It stays private until Wed 28 Oct morning, then we run a secret scan and flip it to public before the 10:00 submit. Only `.env.example` is tracked; no keys, tokens or real bank data anywhere in the history.
- **Finals are a 15-minute presentation + 5-minute Q&A,** with a live demo. The demo must be robust:
  - **In-app reset is the actual requirement:** a "Reset demo" button in the app header, backed by `POST /admin/reset-demo`, restores the seeded demo state in **under 10 seconds WITHOUT stopping the API** (no restart, no file lock errors on Windows). `make reset-demo` calls the same code path.
  - **Every demo step works in LLM replay mode with no network** (`LLM_MODE=replay`, cache in `data/fixtures/llm_cache/`, see D-010).

## D-017 Session 3 decisions (22 Oct, Ihsan)

- **CLAUDE.md rule 8 reworded:** LLM calls are **deterministic via the replay cache**, not via temperature 0. `client.messages.parse` on the current API has no `temperature` parameter, so it is not sent (see `ds/interpreter/llm.py`). This replaces "Temperature 0" in D-006. JSON-schema output and the `sha256(model + prompt_version + input)` cache key are unchanged.
- **Product B stays lumpy as generated.** We do not smooth the generator to make the forecast look better.
- **Report Product B at product/regional level as well as per country.** Per-country B series are too sparse to judge a forecast on alone.
- **Insight for the pitch and M8:** equipment demand (Product B) should be planned from the **enquiry / purchase-request pipeline**, not from a moving average of past POs. This becomes one of the 3–5 recommended actions in the M8 regional view. Enquiries stay a separate leading indicator (rule 9): they inform the plan, they are never counted as demand.

## D-018 Session 4 decisions (22 Oct, Ihsan)

1. **Held-out email test.** The 88/88 interpreter score is tuned on the same templates. A data-scientist writes a short style brief that never sees our templates (varied tone, languages, forwarded threads, missing fields, all 5 classes). Sonnet generates ~24 NEW emails from it (through `ds/interpreter/llm.py`, so they replay), saved as `data/fixtures/holdout_emails.jsonl` with intended labels. Labels are written and committed **before** the interpreter sees the emails. The interpreter `prompt_version` (and prompt hash) is **frozen** before the run; a test pins it. Ihsan spot-checks the labels before final numbers are reported. `docs/results.md` shows "tuned set" and "unseen emails" side by side.
2. **Dedup framing.** `docs/results.md` lists which duplicate types the AI judge rescued, with one concrete example. Pitch line: **"rules where rules work, AI only where they fail".** Never overclaim AI gains in dedup.
3. **Field validation is Must** (the brief asks how incomplete submissions are stopped before an approver). Server-side: values against the form schema, per-country tax-ID formats (D-003), required fields per domain x country, registration expiry dates (against the simulated clock). Plain-English errors next to each field in the form. Submit answers 422 `{detail, issues: [FieldIssue]}`. No new dependency: our own checker reads the existing JSON Schemas. An expired registration blocks submit for that selling country. **The expired-registration demo uses a different item from DEMO-02's malaria kit**, so the main demo path is never blocked; it is an optional demo beat ("lapsed licence stopped at submit").
4. **M10 owner: data-scientist** computes the modelled cycle time in `ds/analytics/cycle_time.py`: old process (sequential approvals, bounce loops) from `mdm_requests_history.csv` vs new process (one parallel stage, reminder at 1 business day, escalation at 2, no missing-field bounces). Median and P90 business days before vs after, plus the brief's Amy scenario (18 days -> ?). Every assumption labelled with its source.
5. **After-merge view uses our own dedup clusters** (`ds/analytics/golden.py`), not the ground-truth golden map; ground truth is used only to score them.
6. **Session 4 defers** the M8 regional-view screen and the M10 summary card to session 5 (APIs and numbers land now).
7. **Note (22 Oct, orchestrator):** the M10 model is stricter than #4's "no missing-field bounces": it removes only bounces for fields the form checks at entry; bounces for fields it does not check (credit terms, risk class ...) stay (about 21% of requests). Its new-process median is set mostly by our SLA caps, and results.md quantifies that. Forecast endpoints read `data/fixtures/derived/` (the backtest module adds `forecast/`).

## D-019 Plan against the judging rubric (22 Oct, Ihsan + orchestrator)

Source: the brief's §8 Evaluation Criteria (`Data Case Competition 2026 Brief.pdf`, p. 8) and §7 Deliverables. Session 5 onwards plans from this table.

| Criterion | Weight | Where we stand (end of session 4) | What closes the gap |
|---|---|---|---|
| Problem understanding | 20% | Strong: every §4 pain point maps to a feature; personas and Amy's 18 days used directly. | Answer the §6 constraints head on: M365 backbone, no dedicated IT team. |
| Solution quality | 30% | Strong working prototype, end to end to an SAP B1-shaped mock with read-back. | A feasibility slide: what the MDM team configures themselves vs what needs outside help, with the production path (Teams/Outlook front door, Power Automate notifications, rule tables the MDM team edits, one small hosted service, real Service Layer). |
| Business impact | 25% | Numbers exist (30 of 63 lost alerts were duplicates; Amy 18 -> ~4 business days, modelled; NRR 80.7% -> 91.0%), but no screen yet. | **The regional business view screen (compulsory, §7)** and the ops-impact card. Adoption plan in the summary. |
| Innovation | 15% | Strong: email interpreter with source quotes, held-out test, "rules where rules work, AI only where they fail". | Keep it honest; no new AI features needed. |
| Communication | 10% | Not started: video, 2-page summary, slides. | Five-beat demo with one number on screen per beat; plain English for non-technical judges. |

Decisions:
1. **Forecasting is a supporting result, not the headline.** §7 asks how data science or AI improves "forecasting *or productivity*". The productivity story (email intake, duplicates stopped at entry, parallel approvals) carries that requirement. The forecast is presented as an honest backtest: the Excel average ties at country level; ours helps on Product C at region level; leakage wrecks Product B planning, so plan equipment from the enquiry pipeline (D-017).
2. **Adoption answer (scored in Business impact, asked for in §7):** "keep emailing if you want; the system turns your email into a clean, pre-filled request". The messy inbox is the bridge off email, not a replacement users must learn first.
3. **"Without going back to IT" (§5 design prompt):** routing rules and required fields already live in `config/routing_rules.yaml` and `config/forms/`. Build at least a read-only Admin/config view that shows where an approval step or required field is added; the live editor stays Stretch (S2).
4. **Session 5 priority order:** (1) regional business view screen: country x product, stated 12-month period, growth measure defined, before/after merge toggle, lost customers that were duplicates, POs vs enquiries vs MDM requests separated, recommended actions; (2) ops-impact card; (3) Admin/config view; (4) 2-page summary with cost/effort sized for no dedicated IT team and the adoption plan; (5) 2-3 minute video in five beats.
5. **Finals logistics from the brief:** submission 28 Oct 12:00 SGT via the form in §9; Top 10 announced 29 Oct; live finals 30 Oct 2-7 PM.

## D-020 Session 5 decisions (22 Oct, Ihsan)

1. **Forecast framing.** Our combination ties the Excel average at country level. **We do not change the data to make it win** (also D-017). The pitch is: (a) "the biggest forecast error is the data, not the model": Product B error goes from 28% to 271% when spreadsheet leakage is counted as orders; (b) our method wins on Product C; (c) the brief allows "forecasting *or* productivity", and the productivity evidence is strong (D-019 #1). **Bias analysis by country:** does the Excel 6-month average systematically under-forecast the fast-growing markets? "Fast-growing" is measured from the data (units, last 12 months vs the 12 before), not assumed to be VN and ID. Reported honestly whatever it shows, with a plain-English caption, in `docs/results.md` and in the forecast payload (`ForecastBacktest.bias_by_country`, `bias_note`).
2. **Vendors may be in any country** (IVD manufacturers are often in Europe, the US or Japan). **Customers stay within our 5 countries.** Validation for a foreign vendor: country code (ISO 3166 alpha-2) + name + address are required; the tax ID is optional and the five-country tax-ID formats (D-003) are not applied. The request's own `country` (the operating country that routes approvals) stays one of the five; only the vendor's address `Country` field widens.
3. **Session 5 contract notes (orchestrator):** the edit-and-resubmit screen reuses `POST /requests/{id}/submit` from `INFO_REQUESTED` (no new endpoint); `RequestDetail.info_request` carries the approver's question. On resubmit, approvals already given stay given; only the task that asked for information reopens. `RequestDetail.linked_card_name` replaces the browser-side workaround. Item prefill of product family and item group is **deterministic** (`RequestDetail.prefill_suggested` holds the reason); the frozen interpreter prompt is not changed.
4. **Resubmit governance (orchestrator, after QA, 22 Oct):** on resubmit from `INFO_REQUESTED`, (a) an edit to an identity field (`CardName`, `FederalTaxID`, `Country`, `ItemName`, or the request's operating country) reopens **all** earlier stage-1 approvals; (b) an edit to bank details, `CreditLimit` or `PayTermsGrpCode` reopens Finance; (c) other edits keep approvals already given; (d) if an edit cancels the task that asked the question (e.g. the item is no longer IVD, so the Q/R reviewer drops out), all other stage-1 approvals reopen, so a human always looks again and the request never jumps to APPROVED. The resubmit audit row lists changed field names, never values. `decide_duplicate` is also allowed in `INFO_REQUESTED`.
5. **Foreign-vendor rules live in `config/foreign_vendors.yaml`** (name, country, street, city, bank account) because `config/required_fields.yaml` is pinned by the frozen-interpreter test. The ISO country list is `config/countries.json` (hand-written, no new dependency). Currency is left blank for countries outside the five.

## D-021 Session 6 decisions (23 Oct, Ihsan)

1. **Wei Jie's demo beat uses the DEMO-07 vendor request** (Precision Diagnostics Asia), not Amy's item. Routing stays as designed: Finance sees customer and vendor requests only, so Wei Jie is never routed on an item. The beat shows: bank details stripped from the email before the AI reads it; bank rows entered in the secure form; bank details visible **only to Finance** (Wei Jie, and Hui Min as the second Finance approver), masked for everyone else; a reminder after the simulated clock moves to day 2. PRD section 4 and `docs/demo-script.md` updated, including **88 emails (not 60)** and the merge-toggle narration.
2. **Cross-sell "0% before merge" is a feature.** The regional view shows the after-merge cross-sell % prominently next to it, captioned: "Before the golden record, you can't see who your cross-sell customers are."
3. **Forecast bias:** a recommended action "add an explicit growth adjustment for markets flagged as growing", with the Vietnam number (the Excel average planned about 13% too low). We do not claim our model fixes it.
4. **The timed walkthrough spec is a rehearsal tool:** `make rehearse` runs it (with 1440x900 screenshots into `apps/web/test-results/rehearse/`); `make e2e` ignores it unless `REHEARSE=1`.
5. **Theme:** tweakcn "Sage Green" (theme `cmlf6yp47000104ld4ijt51m7`, source copy in `docs/theme-tweakcn.css`), pasted by hand into `apps/web/app/globals.css`, not installed from the tweakcn registry URL (D-013 registry rule). Changes from the file: `--radius: 0.75rem` (not 1.4rem); Tailwind's default `--spacing: 0.25rem` is kept (not 0.27rem). Fonts: Plus Jakarta Sans (sans) and IBM Plex Mono (mono) via `next/font/google`. Added `--success` and `--warning` tokens (light + dark) matching the sage palette for approved / pending / overdue states. The heatmap uses a single-hue sequential green ramp, not `--chart-1..5`. The demo is recorded in light mode.
6. **Pipeline beam (Stretch S1) moves to Saturday** with the live AI trace. Tonight: theme, three layout fixes, cross-sell caption, drop-off risk and cross-sell whitespace lists.

## D-022 Session 7 decisions (24 Oct, Ihsan)

1. **Invented names for private hospital chains.** Real private brands in `ds/generator/curated.py` are replaced: Mount Elizabeth (+ Novena) -> Mount Serene (+ Novena); Gleneagles, Thomson Medical Centre, Farrer Park, Parkway East -> Kingsmead, Rivervale Medical Centre, Tanjong Park, Eastpoint; Pantai -> Seroja; KPJ Damansara / Ampang Puteri -> Anggerik Bandar Utama / Anggerik Ampang; Columbia Asia -> Damansara Jaya Medical Centre; Siloam Kebon Jeruk / Lippo Village -> Cendrawasih Kebon Jeruk / Karawaci; Mitra Keluarga -> Nusa Keluarga; Hermina -> Puri Kencana; Hoàn Mỹ -> Ngọc Lan; Vinmec Times City / Central Park -> Cẩm Tú Long Biên / Thủ Đức; Bangkok Hospital -> Saeng Tawan (แสงตะวัน); Samitivej -> Bua Khao (บัวขาว); Phyathai -> Phiman (พิมาน). Public demo anchors (NUH, Chợ Rẫy, Siriraj, RSCM, HKL and the other public hospitals) stay. Each name was web-checked (no established hospital brand; small coincidental clinics allowed) and avoids the generator's synthetic word lists (`MY_WORDS`, `ID_WORDS`, `VN_WORDS`, `TH_WORDS` in `ds/generator/names.py`), so no accidental near-duplicates. Ihsan's "Cahaya Medika" (nearly the synthetic "Abdi Cahaya Medika Indonesia"), "Keluarga Sehat" (a real hospital in Pati; "Sehat" is a word-list stem), "Taman Sari" (RSUD Taman Sari, Jakarta) and "Chaimongkol" (surname of a hospital-group director) were swapped. Same-brand-different-site pairs keep their shared brand token, so the hard negatives stay hard.
   - Effect: only names and PO-reference initials changed; the answer key (`bp_golden_map.csv`) and all quantities and dates are byte-identical. Regional and interpreter numbers unchanged. Dedup held-out (seed 7) Likely recall 97.4% -> 97.0%, F1 98.3% -> 98.1%; grey-zone judge 8 of 10 -> 10 of 12; name-only + judge F1 97.0% -> 96.6%.
   - 5 interpreter and 16 judge cache entries re-recorded (about US$0.40); the 11 orphaned entries holding real brand names were deleted.
   - **Exception:** the dedup judge's system prompt (`ds/dedup/judge.py`) still uses "Mount Elizabeth" as its example of a different site of one brand. Changing it would invalidate every cached judge answer (system-prompt hash) and need a full re-record; it is a prompt example, never shown in the app.
   - `make eval` now regenerates its seeds and scenarios every run: stale `data/generated/eval/` seeds from 22 Oct had silently kept the old names.
2. **No git history rewrite.** Earlier commits keep the old names.
3. **Growth measure for the brief:** the heatmap's growth is **12-month** (last 12 full months vs the 12 before, `HeatCell.growth_12m_pct`) and is the headline growth measure. NRR and the revenue bridge stay "last 3 months vs the 3 before". Each has its own plain-English caption so they cannot be confused. Product B carries the note "Lumpy: plan from the enquiry pipeline" (D-017).
4. **Track 2 lists:** drop-off risk compares a customer's quarter with the **same quarter last year** (removes seasonality). Cross-sell whitespace rows with **fewer than 10 comparable customers** are marked "low confidence" and left out of the US$ total.
5. **UI polish:** Next.js dev indicator off; toasts last about 3 s, dismiss on navigation and never cover the revenue bridge or status-page history; theme variants A (current), B (light, sage-tinted page, white cards, dark olive sidebar, olive primary) and C (dark, from the theme file) are CSS-variable blocks; **A stays active until Ihsan chooses**.

## D-023 Session 8 decisions (24 Oct, Ihsan)

1. **Theme B is the default** (`THEME_VARIANT = "b"`, the `data-variant` attribute on `<html>`). The header's logo block takes the sidebar colours, so the dark olive sidebar reads as one column. Variant C's code paths are removed (type, `dark`-class toggling, preview script, theme shots); A stays as a fallback attribute and preview. The shadcn `.dark` CSS block stays, unused.
2. **"Mount Elizabeth" stays in the dedup judge's system prompt** (D-022 #1 exception confirmed): it is never shown in the app and changing it would need a full judge re-record.
3. **Live AI trace (Stretch S1).** `POST /emails/{id}/interpret/stream` answers server-sent events (`event: step`, `data:` one `InterpretStep`). It **replays** the finished interpreter result (the same `Interpretation` as `POST /emails/{id}/interpret`; no network in `LLM_MODE=replay`), paced at about 1.5 s in total; `step_ms=0` sends everything at once (reduced motion, tests). Step order: start, bank details stripped (if any), each extracted field with its source quote, order lines, category, missing fields, the prompt-injection warning (DEMO-06) last, then `done` with the full result. POST, not GET, because `EventSource` cannot send `X-Acting-User`; the browser reads the stream with `fetch`. The UI says so plainly with a badge "Replaying a recorded AI response" and a tooltip: the answer was recorded earlier for this exact email so the demo behaves the same every time without the internet. If the stream fails the inbox falls back to the plain POST. "Sort all" stays unstreamed. Steps never carry bank details (they come from the already-stripped result, rule 5).
4. **Pipeline beam (Stretch S1)** on the status page: Magic UI `animated-beam` (shadcn CLI, needs `motion`, both in D-013): Email -> Read by AI -> Golden record -> Approvals -> In SAP, each node lit from the request's real state (derived in the browser from `RequestDetail`; no API change). One sweep per state change, at most 400 ms; no looping; none under reduced motion.
5. **Southeast Asia map (Stretch S2, only if time allows):** no `react-simple-maps` (React 19 peer risk). ECharts `registerMap` with a small committed GeoJSON of SG/MY/ID/VN/TH trimmed from Natural Earth (public domain; source noted in the README). Singapore gets a dot marker so it is visible and clickable. Coloured by 12-month growth; clicking a country filters the regional view.
6. **Map library (24 Oct, Ihsan):** add `echarts` (already allowed by D-013) for the S2 map; the regional page is the only place it loads.

## D-024 Session 9 decisions (25 Oct, Ihsan + orchestrator)

1. **Order of work:** merge the live AI trace (`s1-trace`, after the frontend QA notes), then the Southeast Asia map (Stretch S2) on `/regional`. The judge-ready README is written in parallel.
2. **README is for non-technical judges first, engineers second.** Every headline number links to `docs/results.md` and carries an honest one-line caption (synthetic data, modelled not measured, the forecast ties the Excel average at country level).
3. **Diagrams:** Mermaid in the README (GitHub renders it), sources in `docs/img/*.mmd`, PNGs rendered with mermaid-cli (`mmdc`, D-013) for slides and video. D2 was not used: it is not installed and Mermaid covers both diagrams. The architecture diagram shows the prototype and the production path: a Teams/Outlook front door, one small hosted "MDM brain" service, rule tables in SharePoint, Power Automate notifications, and the SAP B1 Service Layer behind an integration user. Every Mermaid block is rendered locally to check its syntax; nothing is pushed.
4. **README screenshots** (1440x900) are copied from the final `make rehearse` run into `docs/img/` and committed. `apps/web/test-results/` stays out of git.
5. **Map growth is computed in the browser** from the heatmap cells: a country's 12-month growth = sum of last-12-month value / sum of prior-12-month value (`value_usd / (1 + growth_12m_pct/100)`) - 1. No contract change, unless `growth_12m_pct` turns out to be rounded, in which case an API field is added instead.
   - **Resolved (orchestrator):** `growth_12m_pct` is rounded to 0.1 (`ds/analytics/regional.py::_growth`), so the map reads a new `RegionalView.country_growth` (one row per country, all five whatever the country filter: last-12-month value, prior-12-month value, 12-month growth %), computed in `ds/analytics/regional.py` and checked against the country totals in `docs/results.md` (Vietnam +45.9%).
6. **Licence:** MIT, "Copyright (c) 2026 Ihsan Alfian". Data sources: Natural Earth (public domain) for the map shapes.
7. **Branch hygiene:** worktrees and branches are removed only when fully merged (`git branch -d`). `d022-hospital-names` was deleted (no diff against main).

## D-025 Session 10 decisions (25 Oct, orchestrator under Ihsan's polish brief)

1. **Root cause of the intermittent `500 GET /api/clock` during Reset demo:** a keep-alive race, not the clock or the table reload. Node's agent behind the Next rewrite proxy keeps idle sockets for 5 s, and uvicorn's default keep-alive is also 5 s. When a socket has idled about 5 s and the Next dev server's event loop is busy (compiling, `router.refresh()` after a reset), the proxy reuses a socket uvicorn has just closed: `ECONNRESET`, "socket hang up", 500, and the header shows "Demo server offline". Reset made it likely because the other sockets go idle for the length of the reset. Reproduced deterministically (idle 4.6-4.9 s + 800 ms busy loop: 6/6 reused sockets reset with the default; 0/6 with the fix). A 50-reset soak through the proxy while polling `/clock` and `/notifications` was clean before and after (the race needs a busy event loop, which a plain client does not create).
2. **Fix:** every uvicorn launch (Makefile `UVICORN_KEEP_ALIVE ?= 75`, `e2e/start-api.mjs`, the e2e SAP mock) runs with `--timeout-keep-alive 75`, so the client always closes an idle socket first (the standard rule for proxies in front of an app server). **Defence in depth:** the typed client retries a GET once after 300 ms when the connection drops or the proxy answers a non-JSON 5xx, before reporting the server offline. Writes (POST/PUT/PATCH/DELETE) are never repeated.
3. **Regression tests:** `tests/test_keep_alive.py` (every launch has the flag and it is over 10 s; live: the same socket, idle 5.5 s, is still served; red with 5 s) and `e2e/reset-under-poll.spec.ts` (three real resets after 5 s idle gaps with no `/api` 5xx, offline notice or error toast; one injected proxy 500 on `/clock` is retried silently).
4. **Singapore's -16.2% (results.md "Why is Singapore down 16.2%?", generated by `notebooks/eval_regional.py` from `ds/analytics/change.py`):** mostly one-off equipment (Product B is 106% of the drop; repeat business is up 1.4%), so no formal recommended action, only a "worth a call anyway" line for the test-kit dip. That line gives the count and US$ total of the 5 biggest repeat-business drops, **not customer names**: some are real Singapore public hospitals, and printing invented spending drops next to their names goes against the spirit of D-022 #1. The names stay in the data structure only.

## D-026 Session 12 decisions (26 Oct, Ihsan; final feature day)

1. **Scope:** Stretch items built on the last feature day, each on its own branch and merged only after `make test`, `make e2e` and `make rehearse` passed on the merged result (run one branch at a time) and `docs/results.md` was unchanged: A reply-to-sender draft (S2 auto-reply), B editable approval rules (S2 config editor), C clean-up queue (S2 steward queue), D history check + `make tamper-demo` (S3), E "Start here" home page. Nothing was cut.
2. **Reply draft (A):** a fixed template, no AI; shown only for new-record requests after the reading finishes, and **not** for an email flagged as giving the AI orders (DEMO-06). It lists only `missing_fields` and links to the pre-filled form. Nothing is sent; production sends it via Power Automate from the MDM mailbox. The interpreter has no new-vs-change distinction, so "new record request" = `mdm_request`.
3. **Approval rules (B):** an override replaces the stage-1 approver steps for one record type x entity x country (items and cost centers: all countries); the MDM publish stage is fixed; the IVD and bank add-ons still apply on top. Only `mdm_analyst` may edit; zero approvers, an unknown person or a person without the role are refused. Each request stores the override it was routed with (`requests.routing_override`), so in-flight requests and their resubmits keep their route. With no override rows routing is unchanged: `tests/test_route_snapshot.py` compares DEMO-01, DEMO-02, DEMO-07 and an ask-for-info resubmit against a snapshot taken on 5b0d37f before any code change. Every save writes a `config_change` audit row. Known gap, not fixed: an override can name a backup approver or someone who will later publish; maker-checker still applies at decision time.
4. **Clean-up queue (C):** the 277 Likely links from `ds/analytics/golden.py` (`likely_pairs`, which `likely_links` is now built on), grouped into 168 groups, most certain first (all links on the same tax ID, then by the weakest link's score). Priya confirms or marks "not the same" with a reason; decisions are audit-logged and **never feed the regional numbers** (a caption under the merge toggle says the after-merge view uses the proposed links). Tax-ID acronyms are shown as "tax ID (MST)".
5. **History check (D):** `GET /audit/verify` for every persona; the request page says "Checks the whole history log (all requests): N entries intact." because the chain is global. `make tamper-demo` edits one approval a person made in a throwaway copy and never writes `data/app.db`. No tamper control in the UI.
6. **Start here (E):** `/` is the landing page (the `/` -> `/inbox` redirect is gone); numbers come from `/analytics/ops-impact`, `/merge-impact` and `/regional`; the cycle-time number is captioned "Modelled, not measured". "Duplicates stopped" is left off because it is a live count that reads 0 after a reset.
7. **Docs:** README gains "From the brief to the build", "Try it in 5 minutes" (`docs/judge-walkthrough.md`), a pilot plan and screens 05-08 (`make readme-shots`, not in `make e2e`). The Ops page does not yet show the share of requests through the form vs plain email; the pilot plan lists it as a measure to add.
8. **Existing `data/app.db`** must be reseeded once after this merge (new `routing_overrides`, `cleanup_decisions` tables and `requests.routing_override` column).

## D-027 Session 13 decisions (26 Oct, Ihsan; closing the gaps against the brief)

1. **Scope and gate:** six items from the brief, in priority order, each on its own branch and merged only after `make test`, `make e2e` and `make rehearse` passed on the merged result, run one branch at a time. Existing `docs/results.md` numbers do not change (new sections only). (1) equipment forecast from the request pipeline; (2) Cost Center requests and required-field switches; (3) item duplicate check; (4) approvers' local due times; (5) Teams card preview; (6) the requestor is told what they can do once the record is live. Plus: the rules editor refuses an approver who could be the requestor. Nothing was cut.
2. **Pipeline forecast (Product B):** the method and constants were committed before the first run (`b4b7e1e`: `LMAX = 2`, 12-month conversion window, unseen request months = 6-month request average, Excel 6-month fallback, floor 0) and not changed afterwards. Conversion is estimated from monthly totals only (units ordered / pipeline units); the request-to-order link (`converted_doc_num`) is never read, because real SAP data would not have it. Two variants declared in advance: requests only, and requests + enquiries. **Result, reported as is:** it ties the 12-month Excel average in the demo market (region 26.5% vs 26.1% error) and loses in the flat and sparse markets, even though the generator builds requests from later orders (about 45% of B orders have one), which favours the method. A pilot must measure the conversion rate on real data. The forecast panel shows one plain line and a "Next 3 months plan" table (Excel 6-month, ours, the pipeline for B), with the fast-growing market adjustment (Vietnam in the demo) as its own column: Excel ran 13% low there in the backtest, so the column adds 15% on Excel's plan, never folded into another column.
3. **Cost Center is now built** (reverses PRD 5.3 "Full custom UI for Cost Center: won't build"). It is a schema-driven form like the other three: `config/forms/cost_center.schema.json` (43 lines of config: CenterName, EffectiveFrom, InWhichDimension, purpose); about 25 lines of code added and 45 removed, because the old Cost Center special cases were deleted. A further record type needs the schema, a required-fields entry and routing stages in config, a handful of label lines, and about 30 lines for its SAP publish payload and mock resource. The UI says "Cost Center"; SAP gets `ProfitCenters` with `Active` tNO, read-back, then tYES (rule 4).
4. **Required-field switches:** Priya only (403 for anyone else), per record type x country, every change in the history log, new requests only (`requests.required_snapshot`), cleared by Reset demo. Locked, with the reason shown: the name of every record type, country and tax ID (customers, vendors), vendor bank details, the IVD flag, selling countries and registrations (they decide Quality/Regulatory routing), and the Cost Center start date. The switches never change the AI prompt or the replay cache; they apply after the AI's answer, in plain code. Known gap: the reply-to-sender draft still lists only the standard missing fields.
5. **Item duplicate check:** rules only, no AI (rule 6): a normalised name (pack sizes, units and punctuation stripped; generic words such as "rapid test kit" count little), an exact catalogue number (existing ItemCode or a **synthetic** manufacturer catalogue list, `config/item_catalogue.yaml`), and the same registration number in the same country. Likely pauses submit until a person links to the existing item or says "not the same" with a reason; both are audited. The generator plants no item duplicates, so it is scored on a hand-made set of 50 pairs written by us (thresholds committed before the set), reported as a sanity check, not a measured accuracy. DEMO-02's malaria kit shows no match. The optional "lapsed licence" beat reuses A-CRP-QT's own name and registrations, so it is now (correctly) a Likely duplicate first.
6. **Time zones:** display only, SLA logic unchanged. Fixed offsets in `config/timezones.yaml` (SG, MY +8; VN, TH, ID +7, Indonesia shown as Jakarta time); none of the five uses daylight saving, and Windows has no system time-zone database, so no new dependency. The local time is shown only when it differs from SGT.
7. **Teams card:** built on the server as an Adaptive Card 1.5 (`GET /notifications/{id}/teams-card`), only for an approver's own task notifications, never with bank details, shown with plain components and downloadable as JSON. The preview's buttons do nothing; a decided task's card shows only Open. Production: Power Automate posts it. Nothing is sent from the prototype.
8. **Rules editor:** refuses, at save, an approver who also raises requests or whose escalation backup does (closes the D-026 #3 gap for that case; nobody in the seeded users holds both roles).
9. **Existing `data/app.db`** must be reseeded once after this merge (new `required_field_overrides` table, `requests.required_snapshot` column).
