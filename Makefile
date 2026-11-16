# CodeCompass developer commands. See specs/001-code-assistant/quickstart.md.
DATASET ?= eval/datasets/fastapi-template-v1.yaml

.PHONY: init-env up down pull test test-backend test-frontend lint fmt migrate eval

init-env:            ## create .env with generated dev secrets
	python3 scripts/init-env.py

pull:                ## one-time image download (reported separately from setup time, SC-001)
	docker compose pull

up:                  ## start the whole app (NFR-003)
	docker compose up --build

down:
	docker compose down

test: test-backend test-frontend   ## run by spec-reviewer (Quality Gate 2)

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm test

lint:
	cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy src
	cd frontend && npm run lint && npm run typecheck

fmt:
	cd backend && uv run ruff format . && uv run ruff check --fix .

migrate:
	cd backend && uv run alembic upgrade head

eval:                ## FR-042: needs a working LLM key and the compose stack
	docker compose --profile eval run --rm eval python -m codecompass.eval $(DATASET)
