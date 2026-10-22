# Lives Group MDM prototype: "Messy in, clean out"

SMU DSA Society 2026 Data Case Competition.

Messy, cross-border requests and emails are interpreted at the point of entry, de-duplicated into one golden record, approved in parallel, and published to SAP Business One. The same golden IDs then produce a trustworthy regional sales view.

All data is synthetic (see `docs/data-spec.md`). Real public hospital names are used for realism; all IDs, transactions, contacts and amounts are fictional.

## Layout

```
apps/web/            Next.js 16 web app (port 3000)
services/api/        FastAPI API (port 8000)
services/sap_mock/   SAP B1 Service Layer mock (port 8001, /b1s/v2)
ds/                  generator, dedup, interpreter, forecasting, analytics
data/fixtures/       frozen demo dataset + LLM replay cache
docs/                PRD, decisions, data spec, progress log
```

## Run

Needs `uv`, Node 22 and `pnpm`.

```bash
make setup   # install deps
make data    # generate synthetic data (SEED=42)
make dev     # api :8000, sap_mock :8001, web :3000
make test    # Python + web checks
```

Full README to follow.
