# Lives Group MDM prototype. Run from the repo root (Git Bash or any shell with GNU Make).
SEED ?= 42
SCENARIO ?= seasonal_trend
WEB := apps/web

.PHONY: setup data fixtures dev dev-api dev-sap dev-web reset-demo test test-py test-web eval api-types record stop

setup:            ## install Python (uv) and Node deps
	uv sync
	cd $(WEB) && pnpm install

data:             ## run the generator with the default seed into data/generated/
	uv run python -m ds.generator --scenario $(SCENARIO) --seed $(SEED) --out data/generated/

fixtures:         ## freeze the demo dataset into data/fixtures/
	@echo "make fixtures: not yet implemented (Fri)"

dev:              ## api (8000), sap_mock (8001) and web (3000) together. Python services do not auto-reload (uvicorn reload hangs on Windows): restart to pick up changes.
	$(MAKE) -j3 dev-api dev-sap dev-web

dev-api:
	uv run uvicorn services.api.main:app --port 8000

dev-sap:
	uv run uvicorn services.sap_mock.main:app --port 8001

dev-web:
	cd $(WEB) && pnpm dev --port 3000

reset-demo:       ## restore the database to the seeded demo state
	@echo "make reset-demo: not yet implemented (Sat)"

test: test-py test-web   ## all Python and web tests

test-py:
	uv run pytest

test-web:
	cd $(WEB) && pnpm typecheck && pnpm lint

eval:             ## dedup, classifier and forecast evaluations -> docs/results.md
	@echo "make eval: not yet implemented (Fri/Sat)"

api-types:        ## regenerate the typed API client from the FastAPI OpenAPI spec
	uv run python -m services.api.export_openapi $(WEB)/lib/api/openapi.json
	cd $(WEB) && pnpm gen:api

record:           ## re-record the LLM replay cache (needs ANTHROPIC_API_KEY)
	@echo "make record: not yet implemented (Fri)"

stop:             ## stop whatever is listening on 8000, 8001, 3000 (Windows-friendly)
	-@for p in 8000 8001 3000; do \
		for pid in $$(netstat -ano | grep -E "[:.]$$p .*LISTENING" | awk '{print $$5}' | sort -u); do \
			taskkill //PID $$pid //T //F >/dev/null 2>&1 && echo "stopped :$$p (pid $$pid)"; \
		done; \
	done
