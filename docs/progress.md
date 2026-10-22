# Progress log

One line per finished task: `YYYY-MM-DD HH:MM | agent | what changed | status`.

## Must checklist (PRD §5.1)

- [x] M1 Synthetic data generator
- [ ] M2 Messy-inbox interpreter
- [ ] M3 Schema-driven request form
- [ ] M4 Layered duplicate check (engine + eval done; API endpoint + form panel pending)
- [ ] M5 Parallel approvals + status page
- [ ] M6 Audit log (append-only hash chain done; hook into workflow events with M5)
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
2026-10-22 16:55 | backend-engineer (session 3 B) | M3-M6 backend: requests/drafts/from-email, live dedup check + link/override, parallel stage routing from routing_rules.yaml, maker-checker, SLA sweep (reminder 1 bd, escalate 2 bd, weekends skipped), publish to SAP mock, audit summaries, bank masking by role; in-app POST /admin/reset-demo reloads the DB in place via WAL (~0.7 s, no restart), clock persisted; 27 new tests | done
