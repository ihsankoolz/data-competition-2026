# First Claude Code session — paste this

You are the orchestrator for this repo. Read CLAUDE.md, docs/PRD.md, docs/decisions.md and docs/data-spec.md fully before doing anything.

Before anything: confirm `/mcp` shows context7, shadcn, playwright and next-devtools connected, and `/hooks` shows the two hooks. Tell me if any are missing.

Goal for this session (Thu evening, ~3 hours): a running skeleton and the start of the data layer.

1. Plan first. Show me a short task plan for tonight mapped to PRD Must items, and wait for my OK.
2. Scaffold the monorepo exactly as in CLAUDE.md "Repo layout": uv Python project with the `ds` package, FastAPI apps in services/api and services/sap_mock, Next.js app in apps/web (TypeScript, Tailwind, shadcn/ui, Recharts), Makefile with every command listed in CLAUDE.md (stubs are fine where the feature doesn't exist yet), pytest and a smoke test per service.
3. In parallel once the scaffold exists:
   - backend-engineer: SAP B1 mock per decisions D-004 (Login with B1SESSION + ROUTEID, idle timeout, BusinessPartners/Items/ProfitCenters POST/GET/PATCH, error shapes) with tests. Plus the simulated clock endpoint.
   - data-scientist: generator v1 per docs/data-spec.md sections 1–5 (customers, raw BP records with all duplicate types and hard negatives, vendors, items, registrations) with the sanity tests in §11 that apply.
   - frontend-engineer: app shell only (persona switcher, clock display, nav for the 8 screens as placeholders), plus the OpenAPI type generation script.
4. After each agent finishes, run qa-reviewer on its diff before moving on.
5. End of session: `make dev` runs all three services, `make test` passes, docs/progress.md updated, commit with conventional messages, and give me a 5-line summary plus the plan for Friday evening.

Rules: follow CLAUDE.md domain rules and scope discipline. Ask me before adding any dependency not named in the docs. If something in the docs is contradictory or unclear, stop and ask.
