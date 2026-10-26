# Lives Group MDM Prototype — "Messy in, clean out"

SMU DSA Society 2026 Data Case Competition. Solo builder (Ihsan) + Claude Code agents.

- **Deadline:** Wed 28 Oct 2026, 12:00 SGT. **Target submit:** 10:00.
- **Feature freeze:** Mon 26 Oct, 23:59. Tuesday is video, slides, README only.
- Before any task, read `docs/PRD.md`. Decisions live in `docs/decisions.md`. Data rules live in `docs/data-spec.md`.

## The product in one sentence

Messy, cross-border requests and emails are interpreted at the point of entry, de-duplicated into one golden record, approved in parallel, and published to SAP Business One. The same golden IDs then produce a trustworthy regional sales view.

## Repo layout

```
apps/web/            Next.js (App Router, TypeScript, Tailwind, shadcn/ui, Recharts)
services/api/        FastAPI app, port 8000: workflow, dedup, interpreter, analytics endpoints
services/sap_mock/   FastAPI SAP B1 Service Layer mock, port 8001, base path /b1s/v2
ds/                  Python package: generator/, dedup/, interpreter/, forecasting/, analytics/
data/generated/      Generator output (gitignored)
data/fixtures/       Frozen demo dataset + LLM replay cache (committed)
notebooks/           Evaluation: dedup precision/recall, classifier confusion matrix, backtest
docs/                PRD, decisions, data spec, demo script, progress log
```

## Commands (first agent to set these up keeps this section current)

- `make setup` — install Python (uv) and Node deps
- `make data` — run the generator with the default seed into `data/generated/`
- `make fixtures` — freeze the demo dataset into `data/fixtures/`
- `make dev` — run api (8000), sap_mock (8001) and web (3000) together
- `make reset-demo` — restore the database to the seeded demo state (same code path as the in-app "Reset demo" button, `POST /admin/reset-demo`; D-016)
- `make test` — all Python and web tests
- `make e2e` — Playwright suite; starts its own SAP mock, API and web on 8101/8100/3100 and stops them (`make e2e E2E_ARGS=dup-panel` for one spec)
- `make rehearse` — timed demo walkthrough with 1440x900 screenshots (not in `make e2e`)
- `make theme-shots` — 1440x900 screenshots of theme variants A/B (B is the default, D-023) into `apps/web/screenshots/themes/` (not in `make e2e`; the active variant is `THEME_VARIANT` in `apps/web/lib/theme.ts`)
- `make eval` — dedup, classifier and forecast evaluations; writes `docs/results.md`
- `make tamper-demo` — shows the history check catching an edit: changes one entry on a throwaway copy of `data/app.db` (the real file is never written) and prints before/after (not in `make e2e`)
- `make readme-shots` — 1440x900 README screenshots 05-08 (Start here, reply draft, approval rules, clean-up queue) into `docs/img/screens/` (not in `make e2e`)

## Stack rules

- Python 3.11+, managed with `uv`. Pydantic v2 for every schema. SQLAlchemy 2.0 on SQLite (`data/app.db`).
- Forecasting: Nixtla `statsforecast`. Fuzzy matching: `rapidfuzz`. LLM: `anthropic` SDK.
- The frontend talks to the API only through a typed client generated from the FastAPI OpenAPI spec (`openapi-typescript`).
- No real authentication. A persona switcher in the header sets the acting user. The backend still enforces role rules.
- The simulated clock lives in the API (`/clock`). All SLA logic uses it, never the wall clock.

## Tooling

- MCP servers in `.mcp.json`: `context7` (check current library docs before using an API you're unsure of), `shadcn`, `playwright`, `next-devtools`. Plugins and libraries are listed in `docs/decisions.md` D-013. Setup steps: `docs/tooling-setup.md`.
- Hooks auto-format every edited file and block edits to `.env`, lockfiles and `.git/`. Don't fight them; ask the human if a protected file must change.
- Do not add a dependency that isn't in D-013 without asking.

## Domain rules — never break these

1. **SAP field names** must match `docs/decisions.md` exactly (`CardCode`, `CardName`, `CardType`, `FederalTaxID`, `tYES`/`tNO`, etc.).
2. **Customer + vendor records for the same legal entity are NOT duplicates.** B1 requires two separate records.
3. **The same hospital group in different countries is NOT a duplicate.** Each is a separate legal entity. Link them with a `group_id`.
4. **Cost centers are `ProfitCenters`** in the Service Layer. The UI says "Cost Center".
5. **Bank details are never sent to the LLM**, never logged in plain text, and are masked by role.
6. **The AI never approves and never merges on its own.** A human confirms every merge and every approval.
7. **The email-reading model has no tools.** Its output is validated by Pydantic. Deterministic code does routing and publishing. Email text can never change approvers, bank details or credit terms.
8. **All LLM calls go through `ds/interpreter/llm.py`:** deterministic via the replay cache (the API takes no `temperature`; D-017), JSON-schema output, response cache keyed by `sha256(model + prompt_version + input)`. `LLM_MODE` is `replay` (default, demo), `record`, or `live`.
9. **Only confirmed customer POs feed demand.** Enquiries are a separate leading indicator. MDM requests are never demand.

## Scope discipline

- Build the **Must** list in `docs/PRD.md` §5 first.
- Do not start **Stretch** work until every Must acceptance check passes and the orchestrator says so.
- A thin working slice beats a polished half-module. If a task is growing, stop and report.

## Working agreement for agents

- **Orchestrator (main session):** plans, splits work, reviews diffs, merges, keeps `docs/progress.md`.
- **Subagents:** `backend-engineer`, `frontend-engineer`, `data-scientist`, `qa-reviewer`, `persona-tester` (see `.claude/agents/`).
- **Contracts first.** Change API shapes in `services/api/schemas.py`, regenerate the OpenAPI types, then build the UI.
- Every task ends with: tests passing, `make dev` still runs, one line added to `docs/progress.md`.
- Small commits with conventional messages (`feat:`, `fix:`, `test:`, `docs:`).
- Never commit secrets. Only `.env.example` is tracked.

## Definition of done (any feature)

- Works inside the demo flow with seeded data.
- Has at least one automated test.
- No console errors or unhandled API errors.
- All user-facing copy is plain English that a non-technical judge understands. No raw metric names without a one-line caption.
