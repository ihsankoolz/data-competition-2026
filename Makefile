# Lives Group MDM prototype. Run from the repo root (Git Bash or any shell with GNU Make).
SEED ?= 42
SCENARIO ?= seasonal_trend
WEB := apps/web

# Load .env (never committed). Values are stripped because .env.example has inline comments,
# and only non-empty values are exported so an unset key still fails loudly.
ENV_VARS := LLM_MODE ANTHROPIC_API_KEY LLM_MODEL_FAST LLM_MODEL_JUDGE FIELD_ENCRYPTION_KEY \
	SAP_BASE_URL SAP_COMPANY_DB SAP_USER SAP_PASSWORD
-include .env
$(foreach v,$(ENV_VARS),$(eval $(v) := $(strip $($(v)))))
export $(foreach v,$(ENV_VARS),$(if $($(v)),$(v)))

.PHONY: setup data fixtures dev dev-api dev-sap dev-web reset-demo test test-py test-web eval api-types record stop

setup:            ## install Python (uv) and Node deps
	uv sync
	cd $(WEB) && pnpm install

data:             ## run the generator with the default seed into data/generated/
	uv run python -m ds.generator --scenario $(SCENARIO) --seed $(SEED) --out data/generated/

fixtures:         ## freeze the demo dataset (seasonal_trend, seed 42) into data/fixtures/, then reseed data/app.db
	uv run python -m ds.generator.fixtures
	$(MAKE) reset-demo

dev:              ## api (8000), sap_mock (8001) and web (3000) together. Python services do not auto-reload (uvicorn reload hangs on Windows): restart to pick up changes.
	$(MAKE) -j3 dev-api dev-sap dev-web

dev-api:
	uv run uvicorn services.api.main:app --port 8000

dev-sap:
	uv run uvicorn services.sap_mock.main:app --port 8001

dev-web:
	cd $(WEB) && pnpm dev --port 3000

reset-demo:       ## restore the seeded demo state: asks the running API (same code as the Reset demo button), else reloads data/app.db directly (needs FIELD_ENCRYPTION_KEY in .env)
	uv run python -m services.api.db.seed --fixtures data/fixtures/seasonal_trend

test: test-py test-web   ## all Python and web tests

test-py:
	uv run pytest

test-web:
	cd $(WEB) && pnpm typecheck && pnpm lint

eval:             ## dedup, classifier and forecast evaluations -> docs/results.md (offline, LLM_MODE=replay)
	LLM_MODE=replay uv run python notebooks/eval_dedup.py
	LLM_MODE=replay uv run python notebooks/eval_interpreter.py

api-types:        ## regenerate the typed API client from the FastAPI OpenAPI spec
	uv run python -m services.api.export_openapi $(WEB)/lib/api/openapi.json
	cd $(WEB) && pnpm gen:api

record:           ## record the LLM replay cache: 88 emails + dedup judge cases (needs ANTHROPIC_API_KEY; prints a cost estimate, stops over US$5)
	LLM_MODE=record uv run python -m ds.interpreter.record

stop:             ## stop whatever is listening on 8000, 8001, 3000 (Windows-friendly)
	-@for p in 8000 8001 3000; do \
		for pid in $$(netstat -ano | grep -E "[:.]$$p .*LISTENING" | awk '{print $$5}' | sort -u); do \
			taskkill //PID $$pid //T //F >/dev/null 2>&1 && echo "stopped :$$p (pid $$pid)"; \
		done; \
	done
