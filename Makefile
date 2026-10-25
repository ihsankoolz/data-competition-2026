# Lives Group MDM prototype. Run from the repo root (Git Bash or any shell with GNU Make).
SEED ?= 42
SCENARIO ?= seasonal_trend
WEB := apps/web
# Web recipes call node on each tool's JS entry point instead of going through pnpm/.cmd shims:
# on Windows those shims run under cmd.exe, which may not see node even when Git Bash does
# ('"node"' is not recognized). Override if node is not on PATH: make dev NODE="/c/Program Files/nodejs/node"
NODE ?= node

# Load .env (never committed). Values are stripped because .env.example has inline comments,
# and only non-empty values are exported so an unset key still fails loudly.
ENV_VARS := LLM_MODE ANTHROPIC_API_KEY LLM_MODEL_FAST LLM_MODEL_JUDGE FIELD_ENCRYPTION_KEY \
	SAP_BASE_URL SAP_COMPANY_DB SAP_USER SAP_PASSWORD
-include .env
$(foreach v,$(ENV_VARS),$(eval $(v) := $(strip $($(v)))))
export $(foreach v,$(ENV_VARS),$(if $($(v)),$(v)))

.PHONY: setup data fixtures dev dev-api dev-sap dev-web reset-demo test test-py test-web e2e rehearse theme-shots eval api-types record stop

setup:            ## install Python (uv) and Node deps; writes .env from .env.example with a new FIELD_ENCRYPTION_KEY if it has none
	uv sync
	uv run python -m services.api.ensure_env
	cd $(WEB) && pnpm install

data:             ## run the generator with the default seed into data/generated/
	uv run python -m ds.generator --scenario $(SCENARIO) --seed $(SEED) --out data/generated/

fixtures:         ## freeze the demo dataset (seasonal_trend, seed 42) into data/fixtures/, then reseed data/app.db
	uv run python -m ds.generator.fixtures
	$(MAKE) reset-demo

dev:              ## api (8000), sap_mock (8001) and web (3000) together. Python services do not auto-reload (uvicorn reload hangs on Windows): restart to pick up changes.
	$(MAKE) -j3 dev-api dev-sap dev-web

# Keep-alive longer than the clients' idle pools (Node's agent behind the Next proxy and httpx
# both drop idle sockets at 5 s, uvicorn's default). Equal timeouts race: the proxy reuses a socket
# uvicorn is closing and the browser gets a 500 "socket hang up" (D-025). The client must close first.
UVICORN_KEEP_ALIVE ?= 75

dev-api:
	uv run uvicorn services.api.main:app --port 8000 --timeout-keep-alive $(UVICORN_KEEP_ALIVE)

dev-sap:
	uv run uvicorn services.sap_mock.main:app --port 8001 --timeout-keep-alive $(UVICORN_KEEP_ALIVE)

dev-web:
	cd $(WEB) && "$(NODE)" node_modules/next/dist/bin/next dev --port 3000

reset-demo:       ## restore the seeded demo state: asks the running API (same code as the Reset demo button), else reloads data/app.db directly (needs FIELD_ENCRYPTION_KEY in .env)
	uv run python -m services.api.db.seed --fixtures data/fixtures/seasonal_trend

test: test-py test-web   ## all Python and web tests

test-py:
	uv run pytest

test-web:
	cd $(WEB) && "$(NODE)" node_modules/next/dist/bin/next typegen && "$(NODE)" node_modules/typescript/bin/tsc --noEmit && "$(NODE)" node_modules/eslint/bin/eslint.js

e2e:              ## Playwright suite: starts its own SAP mock, API and web on 8101/8100/3100, then stops them. One spec: make e2e E2E_ARGS=dup-panel
	cd $(WEB) && "$(NODE)" e2e/run.mjs $(E2E_ARGS)

rehearse:         ## timed 2:30 demo walkthrough + 1440x900 screenshots -> apps/web/test-results/rehearse (not in make e2e)
	cd $(WEB) && REHEARSE=1 "$(NODE)" e2e/run.mjs walkthrough

theme-shots:      ## 1440x900 screenshots of theme variants A/B -> apps/web/screenshots/themes (not in make e2e)
	cd $(WEB) && THEME_SHOTS=1 "$(NODE)" e2e/run.mjs theme-shots

eval:             ## dedup, classifier and forecast evaluations -> docs/results.md (offline, LLM_MODE=replay)
	@# always regenerate: stale seeds from an older generator silently skew the scores (D-022)
	rm -rf data/generated/eval
	LLM_MODE=replay uv run python notebooks/eval_dedup.py
	LLM_MODE=replay uv run python notebooks/eval_interpreter.py
	LLM_MODE=replay uv run python notebooks/eval_holdout.py
	@for s in flat_noisy intermittent; do $(MAKE) --no-print-directory data SCENARIO=$$s; done
	uv run python notebooks/eval_forecast.py
	uv run python notebooks/eval_regional.py
	uv run python notebooks/eval_ops.py

api-types:        ## regenerate the typed API client from the FastAPI OpenAPI spec
	uv run python -m services.api.export_openapi $(WEB)/lib/api/openapi.json
	cd $(WEB) && "$(NODE)" node_modules/openapi-typescript/bin/cli.js lib/api/openapi.json -o lib/api/schema.d.ts --default-non-nullable false

record:           ## record the LLM replay cache: 88 emails + dedup judge cases (needs ANTHROPIC_API_KEY; prints a cost estimate, stops over US$5)
	LLM_MODE=record uv run python -m ds.interpreter.record

stop:             ## stop whatever is listening on 8000, 8001, 3000 (Windows-friendly)
	-@for p in 8000 8001 3000; do \
		for pid in $$(netstat -ano | grep -E "[:.]$$p .*LISTENING" | awk '{print $$5}' | sort -u); do \
			taskkill //PID $$pid //T //F >/dev/null 2>&1 && echo "stopped :$$p (pid $$pid)"; \
		done; \
	done
