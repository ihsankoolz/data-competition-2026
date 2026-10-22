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
