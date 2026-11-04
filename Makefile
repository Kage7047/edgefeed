.PHONY: install test lint web scan run up down monitoring service

install:            ## venv + package + dev tools
	uv venv && uv pip install -e ".[dev]"

test:               ## unit tests (Postgres tests run when EDGEFEED_TEST_PG_URL is set)
	.venv/bin/pytest -q --cov=edgefeed

live:               ## contract tests against the real venue APIs
	.venv/bin/pytest -q -m live

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy

web:                ## rebuild the dashboard bundle into src/edgefeed/static
	cd web && npm ci && npm run lint && npm run build

scan:               ## one-off table: curated pairs + today's games
	.venv/bin/edgefeed scan --sports

run:                ## collector + dashboard locally on SQLite (http://127.0.0.1:8090)
	.venv/bin/edgefeed collect & .venv/bin/edgefeed serve; kill %1

up:                 ## collector + API + Postgres in Docker
	docker compose up -d --build

monitoring:         ## + Prometheus (:9090) and Grafana (:3000)
	docker compose --profile monitoring up -d --build

down:
	docker compose --profile monitoring down

service:            ## run the collector and dashboard as systemd user services (no root)
	ops/install-user-service.sh
