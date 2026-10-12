# DoorLedger developer targets. Run `make help` for the list.
#
# Variables you can override:  make api PORT=9000   make demo SCENARIO=porch_cold SPEED=120
#                               make live ARGS="--trigger whep"   (options: scripts/live_demo.py)

UV        ?= uv
NPM       ?= npm
PORT      ?= 8787
API       ?= http://localhost:$(PORT)
SCENARIO  ?= full_day
SPEED     ?= 60
ARGS      ?=
LIVE       = $(UV) run $(ENV_FILE) python scripts/live_demo.py --port $(PORT)
DASHBOARD := web/dashboard
# Load .env into the API process when it exists (the API itself does not read .env).
ENV_FILE  := $(if $(wildcard .env),--env-file .env,)

.DEFAULT_GOAL := help
.PHONY: help install env api api-offline dashboard dashboard-mock demo demo-reset \
        webhook test lint sdk-build sdk-check dashboard-build ci \
        live-preflight live-probe live-rehearse live-dry live

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install Python workspace (core + ringpartner) and dashboard deps
	$(UV) sync --all-packages
	cd $(DASHBOARD) && $(NPM) ci

env: ## Create .env from .env.example if it does not exist
	@test -f .env && echo ".env already exists" || (cp .env.example .env && echo "created .env")

api: ## Run the FastAPI backend on :8787 (Bedrock vision + writer; needs AWS credentials)
	$(UV) run $(ENV_FILE) uvicorn doorledger.api:app --port $(PORT)

api-offline: ## Run the backend with no AWS and no network (template messages, scripted perception)
	DOORLEDGER_PERCEPTION=cache DOORLEDGER_WRITER=template \
	  $(UV) run $(ENV_FILE) uvicorn doorledger.api:app --port $(PORT)

dashboard: ## Run the Next.js dashboard on :3000 (uses the API if reachable, else mock data)
	cd $(DASHBOARD) && $(NPM) run dev

dashboard-mock: ## Run the dashboard with built-in mock data (no backend)
	cd $(DASHBOARD) && $(NPM) run dev:mock

demo: ## Start a demo scenario on the running API (SCENARIO=full_day|porch_cold|late_short_visit)
	curl -fsS -X POST $(API)/api/demo/run -H 'content-type: application/json' \
	  -d '{"scenario":"$(SCENARIO)","speed":$(SPEED)}' && echo

demo-reset: ## Reset the demo engine and ledger
	curl -fsS -X POST $(API)/api/demo/reset && echo

webhook: ## POST a signed simulated Ring motion webhook to the API (uses RING_HMAC_KEY from env/.env)
	$(UV) run $(ENV_FILE) sh -c 'test -n "$$RING_HMAC_KEY" || { echo "set RING_HMAC_KEY (same value as the API)"; exit 1; }; \
	  ringpartner simulate motion_detected --device demo-device --sub-type package_delivery \
	  --url $(API)/webhooks/ring --key "$$RING_HMAC_KEY"'

live-preflight: ## Live run: check Ring token/device, Bedrock, Connect + SNS config (sends nothing)
	$(LIVE) --preflight $(ARGS)

live-probe: ## Live run: read-only; click Package in the Playground and see what Ring records
	$(LIVE) --probe $(ARGS)

live-rehearse: ## Live run rehearsal: offline, recorded Playground data, never calls or texts
	$(LIVE) --rehearse $(ARGS)

live-dry: ## Live Ring + Bedrock, no call and no SMS (rehearse the take)
	$(LIVE) --dry-run $(ARGS)

live: ## THE TAKE: Playground "Package" click -> Rosa's call + SMS (max 1 each; asks first)
	$(LIVE) $(ARGS)

test: ## Run the Python test suite (no AWS, no network)
	$(UV) run pytest -q

lint: ## Lint the ringpartner SDK
	$(UV) run ruff check packages/ringpartner

sdk-build: ## Build the ringpartner sdist + wheel (written to ./dist)
	cd packages/ringpartner && $(UV) build

sdk-check: sdk-build ## Validate the built ringpartner distributions with twine
	uvx twine check --strict dist/ringpartner-*

dashboard-build: ## Production build of the dashboard
	cd $(DASHBOARD) && $(NPM) ci && $(NPM) run build

ci: test lint dashboard-build ## Run what CI runs
