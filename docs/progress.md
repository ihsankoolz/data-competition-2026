# Progress log

One line per finished task: `YYYY-MM-DD HH:MM | agent | what changed | status`.

## Must checklist (PRD §5.1)

- [x] M1 Synthetic data generator
- [x] M2 Messy-inbox interpreter (API done; inbox screen next session)
- [x] M3 Schema-driven request form
- [x] M4 Layered duplicate check (engine, eval, API, live panel)
- [ ] M5 Parallel approvals + status page (engine + API done; approvals inbox, status page, Priya publish screens pending)
- [x] M6 Audit log (hooked into every workflow event; timeline UI with M5 screens)
- [x] M7 SAP B1 mock + publisher
- [ ] M8 Regional business view
- [ ] M9 Forecast backtest
- [ ] M10 Ops impact numbers

## Log

2026-10-22 | orchestrator | Docs, agent definitions and data spec written | done
2026-10-22 11:29 | orchestrator | Monorepo scaffold: uv + ds package, FastAPI api/sap_mock stubs, Next.js 16 + shadcn (radix), Makefile, smoke tests; clock + persona contract; make stop | done
2026-10-22 11:35 | backend-engineer | SAP B1 mock per D-004/D-014 + clock router; 53 tests; QA PASS WITH NOTES | done
2026-10-22 11:44 | frontend-engineer | App shell: typed client (X-Acting-User, /api proxy), persona switcher, clock controls, 8 placeholder screens; QA PASS WITH NOTES | done
2026-10-22 11:56 | data-scientist | Generator v1 (data-spec §1-5, seasonal_trend): 350 golden, 571 raw BP, 80 dup pairs, 88 hard negatives, 21 migrations (5 VN-A), deterministic; 12 tests; QA PASS WITH NOTES | done (M1 partial)
2026-10-22 11:56 | orchestrator | End of Thu session: make test green (69 py + web typecheck/lint), make dev serves all 3 | done
2026-10-22 15:00 | orchestrator | D-015 (DEMO-02 malaria item, U_Entity = creator, per-entity copies are true dups, fixtures contract, FIELD_ENCRYPTION_KEY); data-spec §4/§8.1/§12 | done
2026-10-22 15:40 | backend-engineer | SQLAlchemy models + seed loader (make reset-demo, temp-DB swap, ground truth never loaded), Fernet bank fields, append-only hash-chained audit log, SAP publisher (login/POST frozen/read-back/activate, 1 re-login on 401); QA PASS WITH NOTES, all 6 fixed | done
2026-10-22 15:42 | data-scientist (B) | M4 dedup engine + grey-zone judge + llm.py replay cache; eval by golden_id: Likely P/R seed42 100/98.9, held-out seed7 99.2/97.4 (rules only, synthetic, optimistic); QA PASS WITH NOTES, fixed | done (M4 engine)
2026-10-22 15:47 | data-scientist (A) | Generator v2: orders/enquiries/dirty_demand/mdm history/users (80)/88 emails incl. DEMO-01..08, 3 scenarios, make fixtures (2.5 MB); §1-5 byte-identical; QA fixes (subject-only baseline 88/88 -> 57%, approver coverage, A leakage 8.6%) | done (M1)
2026-10-22 15:51 | orchestrator | Merged 3 tracks; Makefile loads .env, wires fixtures/reset-demo/eval; seed fix for multi-line POs; .gitattributes LF for fixtures; make fixtures + make eval + make test green (237 py + web) | done
2026-10-22 16:00 | orchestrator | D-016 (public repo, finals format, in-app reset <10s without API stop) + D-017 (rule 8 = deterministic via replay cache, Product B lumpy + regional-level reporting, plan B from enquiry pipeline -> M8 action); CLAUDE.md rule 8; removed 3 merged worktrees | done
2026-10-22 16:12 | orchestrator | Session 3 contract: config/forms/*.schema.json, required_fields.yaml (matches all MDM email labels), routing_rules.yaml (D-007), ds/forms.py, ds/interpreter/schemas.py + api.py signature, schemas.py (forms/emails/dedup/requests/approvals/notifications/admin), 501 router stubs, GET /forms live, api-types regenerated | done
2026-10-22 16:45 | frontend-engineer (C) | M3 schema-driven form at /requests/new (customer/vendor/item, IVD per-country registrations, bank rows Finance-only), Create from email with source quotes, M4 duplicate panel (debounced, side by side, link / not-duplicate dialog, related, AI judge/offline), Reset demo dialog + toast, minimal /requests/[id]; self-contained Playwright (8101/8100/3100): dup-panel, from-email, reset-demo green; demo-01 pending backend merge | done (UI; needs backend endpoints)
2026-10-22 17:00 | data-scientist (A) | M2 interpreter (one Haiku call/email, quote check, keyword baseline + offline fallback), make record (88 emails + 105 judge cases, est <= US$1.92), eval_interpreter: macro-F1 AI 1.000 vs rules 0.944, fields 96.5%, DEMO-06 flagged, 0 bank leaks; dedup ablation held-out name-only F1 Likely 95.8 -> 97.0 with judge | done (M2)
2026-10-22 16:55 | backend-engineer (session 3 B) | M3-M6 backend: requests/drafts/from-email, live dedup check + link/override, parallel stage routing from routing_rules.yaml, maker-checker, SLA sweep (reminder 1 bd, escalate 2 bd, weekends skipped), publish to SAP mock, audit summaries, bank masking by role; in-app POST /admin/reset-demo reloads the DB in place via WAL (~0.7 s, no restart), clock persisted; 27 new tests | done
2026-10-22 17:29 | orchestrator | Session 3 merged (A interpreter+ablation, B workflow+reset, C form+dup panel), each QA'd and fixed (B: reset-under-write + double-publish blockers fixed); api-types regenerated; 313 py tests, web typecheck/lint, 8/8 Playwright incl. real DEMO-01, make eval offline + stable, in-app reset 3.8 s | done
2026-10-22 20:33 | orchestrator | make dev on Windows Git Bash: web recipes (dev-web, test-web, api-types) call node on the JS entry points instead of pnpm/.cmd shims, which run under cmd.exe and can miss node ('"node"' is not recognized); NODE= override; verified 40 s self-stopping make dev from a fresh Git Bash login shell (8000/3000 200, 8001 up) + make test-web green | done
2026-10-22 20:46 | orchestrator | Session 4 contract: D-018; schemas.py (FieldIssue/ValidationReport, SapPublishView read-back, RegionalView/MergeImpact, ForecastBacktest/Summary, OpsImpact; RequestDetail.issues + sap_publish); 501 stubs /analytics/*, /requests/{id}/validate, /sap-readback; ds signatures (analytics.regional/golden/cycle_time, forecasting.backtest); api-types regenerated | done
2026-10-22 22:10 | frontend-engineer (session 4 C) | Workflow screens: approvals inbox (SLA badges, approve/reject/ask-for-info with required comment, API maker-checker sentences), status page (parallel stage lanes, reminders/escalations, audit timeline), header notifications bell (per-persona unread, polls + clock), Priya's publish screen (read-back table, graceful 'not available yet' until sap-readback lands), messy inbox (read with AI / sort all, category chips, highlighted source quotes, injection + AI-offline + needs-review badges, create request via /requests/new?email=), My requests list, field issues next to form fields (submit 422 {detail, issues}); fixed typed requests blocked by the hidden Country field; e2e ports overridable; 6 new specs, 15 pass + 1 skips until sap-readback | done
