# HushMoney — common developer commands.
# Run `make` or `make help` to list targets.
#
# Python tooling runs through the forwarder uv project (same as CI).
# Stack commands delegate to scripts/dev.sh (plain podman compose, no OpenShell).

UV := uv run --project forwarder

.DEFAULT_GOAL := help
.PHONY: help sync lint fmt fmt-check typecheck test check \
        run run-no-telemetry run-openshell run-no-openshell-with-telemetry run-local-models \
        down logs smoke ollama-pull eval-local-models

# Local SLM candidates benchmarked by evals/model_selection/run.py --local.
# Keep in sync with LOCAL_MODELS in evals/lib/models.py (Gemma 4 E2B/E4B/12B).
OLLAMA_MODELS := gemma4:e2b gemma4:e4b gemma4:12b

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Quality (mirrors .github/workflows/ci.yml) ──────────────────────────────

sync: ## Install/sync dev dependencies
	uv sync --project forwarder --frozen

lint: ## Ruff lint the whole tree
	$(UV) ruff check .

fmt: ## Ruff auto-format the whole tree
	$(UV) ruff format .

fmt-check: ## Ruff format check (no writes)
	$(UV) ruff format --check .

typecheck: ## Pyright strict (forwarder/src + gateway_server.py + llm_proxy.py)
	cd forwarder && $(UV) pyright
	$(UV) pyright

test: ## Run the test suite
	scripts/run_tests.sh

check: lint fmt-check typecheck test ## Run everything CI runs

# ── Local stack (podman compose via scripts/dev.sh) ─────────────────────────

run: ## Start the full stack with telemetry (OpenObserve at :5080)
	./scripts/dev.sh --no-openshell

run-local-models: ## Start full stack: telemetry + no OpenShell + local Ollama models
	./scripts/dev.sh --no-openshell --local-models

run-no-telemetry: ## Start the full stack without the OpenObserve sink
	./scripts/dev.sh --no-openshell --no-telemetry

run-openshell: ## Start via the OpenShell sandbox (no local proxy/telemetry)
	./scripts/dev.sh

run-no-openshell-with-telemetry: ## Start the full stack with telemetry (OpenObserve at :5080)
	./scripts/dev.sh --no-openshell

down: ## Stop and remove the stack
	./scripts/dev.sh --down

logs: ## Tail hermes + forwarder logs
	./scripts/dev.sh --logs

smoke: ## POST a test transaction to the running gateway (drives one LLM call)
	@set -a; . ./.env; set +a; \
	curl -s -X POST http://localhost:8081/gateway \
	  -H "Authorization: Bearer $$HERMES_GATEWAY_SECRET" \
	  -H 'Content-Type: application/json' \
	  -d '{"transaction_type":"debit","amount":45000,"currency":"COP","merchant":"RAPPI","date":"2026-11-03T12:00:00Z","channel":"email","account_type":"checking","bank":"bancolombia"}'; \
	echo

# ── Local SLM evals (Ollama) ────────────────────────────────────────────────

ollama-pull: ## Pull local SLM candidates for `model_selection/run.py --local`
	@for model in $(OLLAMA_MODELS); do echo ">>> ollama pull $$model"; ollama pull $$model; done

eval-local-models: ## Run + auto-score the local SLMs on the golden CO merchant set
	python3 evals/model_selection/run.py --local
