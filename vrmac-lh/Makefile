# VRMAC-LH prototype — common commands. Run `make help`.
SHELL := /bin/bash
COMPOSE ?= docker compose
PY ?= backend/.venv/bin/python
PYTEST ?= backend/.venv/bin/pytest

.PHONY: help env up up-prod down logs ps seed test test-backend test-frontend kpi export grounding openapi audit venv dev-api dev-web

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

env: ## Create .env from .env.example with random secrets
	@test -f .env || (cp .env.example .env \
		&& sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$$(openssl rand -hex 32)/" .env \
		&& sed -i "s/^EVENT_PSEUDONYM_KEY=.*/EVENT_PSEUDONYM_KEY=$$(openssl rand -hex 32)/" .env \
		&& echo ".env created with random SECRET_KEY and EVENT_PSEUDONYM_KEY")

up: env ## Start the whole stack (db, redis, ollama, api, worker, scheduler, web)
	$(COMPOSE) up --build -d
	@echo "web: http://localhost:3000   api docs: http://localhost:8000/api/docs"

up-prod: env ## Start with the Caddy TLS reverse proxy (set DOMAIN in .env)
	$(COMPOSE) --profile proxy up --build -d

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Tail logs
	$(COMPOSE) logs -f --tail=100

ps: ## Service status
	$(COMPOSE) ps

seed: ## (Re)load seed data inside the running api container
	$(COMPOSE) exec api python -m app.cli seed --reset

kpi: ## Compute the KPI aggregates now (normally nightly at 02:00 UTC)
	$(COMPOSE) exec api python -m app.cli kpi-compute

export: ## Export approved POIs as NGSI-LD + DCAT-AP into ./exports
	$(COMPOSE) exec api python -m app.cli export-ngsi-ld --out /data/exports
	$(COMPOSE) cp api:/data/exports/. ./exports/

grounding: ## Run the grounding test (20 answerable + 10 unanswerable per language)
	$(COMPOSE) exec api python -m app.cli grounding-test --out /data/exports/grounding_results.json

review-sample: ## Export the monthly human review sheet (30 random answers)
	$(COMPOSE) exec api python -m app.cli review-sample --out /data/exports
	$(COMPOSE) cp api:/data/exports/. ./exports/

stt-eval: ## Measure the speech-to-text word error rate on the Montenegrin sample set
	$(COMPOSE) exec api python -m app.cli stt-eval

budget: ## Show this month's model spend against LLM_MONTHLY_CAP_EUR
	$(COMPOSE) exec api python -m app.cli budget

openapi: ## Write docs/openapi.json from the running code
	cd backend && SECRET_KEY=$${SECRET_KEY:-docs-only-secret-key-0000} AUTO_INIT_DB=false ../$(PY) -m app.cli openapi --out ../docs/openapi.json

venv: ## Local Python 3.12 virtualenv for tests
	python3.12 -m venv backend/.venv && backend/.venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt

test: test-backend test-frontend ## Run all tests

test-backend: ## Backend tests (needs PostgreSQL+pgvector; TEST_DATABASE_URL)
	cd backend && ../$(PYTEST) -q

test-frontend: ## Frontend type-check + production build
	cd frontend && npm run typecheck && npm run build

audit: ## Dependency vulnerability scan
	cd backend && ../$(PY) -m pip_audit -r requirements.txt
	cd frontend && npm audit --audit-level=high

dev-api: ## Run the API locally with auto-reload
	cd backend && ../$(PY) -m uvicorn app.main:app --reload --port 8000 --no-access-log

dev-web: ## Run the Next.js app locally
	cd frontend && npm run dev
