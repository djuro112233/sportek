# MILA developer targets. Everything runs from the repository root with the project venv.
#   make venv install   # one-time setup
#   make test lint      # what CI runs
#   make ingest         # load kb/manifest.yaml into the local SQLite DB
#   make demo-data      # seed synthetic sessions so /api/metrics/public has data (dev only)
#   make measure        # write reports/<today>_measurement.{md,json} (dry run with mock providers)
#   make up / make down # docker compose stack

PYTHON ?= python3.11
VENV   ?= .venv
PY     := $(VENV)/bin/python
RUFF   := $(VENV)/bin/ruff
DATE   ?= $(shell date -u +%Y-%m-%d)
SESSIONS ?= 40
DAYS     ?= 14
SEED     ?= 42
MEASURE_ARGS ?=
COMPOSE  ?= docker compose

.PHONY: help venv install test test-unit lint lint-fix ingest demo-data measure export-metrics up down logs clean

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | sort

venv: ## Create the virtual environment (.venv) if missing
	@test -x $(PY) || $(PYTHON) -m venv $(VENV)
	@$(PY) -m pip install --quiet --upgrade pip

install: venv ## Install MILA with the dev extras (editable)
	$(PY) -m pip install -e '.[dev]'

test: ## Run the whole backend test suite
	$(PY) -m pytest backend/tests -q

test-unit: ## Run only the unit tests
	$(PY) -m pytest backend/tests/unit -q

lint: ## ruff check over backend and scripts
	$(RUFF) check backend scripts

lint-fix: ## ruff with --fix (imports, unused names)
	$(RUFF) check --fix backend scripts

ingest: ## Ingest kb/manifest.yaml into the configured database (no downloads)
	$(PY) scripts/ingest_kb.py

demo-data: ## Seed referral points, demo KB and synthetic sessions (refuses when MILA_APP_ENV=prod)
	$(PY) scripts/make_demo_data.py --sessions $(SESSIONS) --days $(DAYS) --seed $(SEED)

measure: ## Run the evaluation datasets and write reports/$(DATE)_measurement.{md,json}
	$(PY) scripts/measure.py --date $(DATE) $(MEASURE_ARGS)

export-metrics: ## Dump k-anonymised public metrics to reports/metrics_$(DATE).{json,csv}
	$(PY) scripts/export_metrics.py --date $(DATE)

up: ## Build and start db, redis, api, web
	$(COMPOSE) up --build -d
	@echo "web: http://localhost:3000   api: http://localhost:8000/api/health"

down: ## Stop the stack (volumes are kept; add -v by hand to drop them)
	$(COMPOSE) down

logs: ## Follow api and web logs
	$(COMPOSE) logs -f api web

clean: ## Remove caches, local databases and temporary audio
	rm -rf .pytest_cache .ruff_cache .audio_tmp .measure.db mila.db backend/tests/.pytest_cache
	find backend scripts -name __pycache__ -type d -prune -exec rm -rf {} +
