.DEFAULT_GOAL := help
SHELL := /bin/bash
DB ?= putzplan_dev

help:  ## Список команд
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-14s %s\n", $$1, $$2}'

up:  ## Поднять всю среду (db, redis, миграции, api, frontend)
	docker compose up --build -d
	@echo "API: http://localhost:8000/docs · UI: http://localhost:8080"

down:  ## Остановить среду
	docker compose down

migrate:  ## Применить миграции локально
	cd backend && DB_NAME=$(DB) python3 -m alembic upgrade head

seed:  ## Создать демонстрационную компанию и пользователей (не для production)
	cd backend && DB_NAME=$(DB) PYTHONPATH=. python3 ../infrastructure/scripts/seed_dev.py

test:  ## Все тесты: база, backend, frontend
	bash infrastructure/db/tests/run_tests.sh putzplan_test
	cd backend && DB_NAME=$(DB) python3 -m pytest -q
	cd frontend && npx vitest run

test-db:  ## Только SQL-тесты укрепления базы
	bash infrastructure/db/tests/run_tests.sh putzplan_test

test-api:  ## Только backend-тесты
	cd backend && DB_NAME=$(DB) python3 -m pytest -q

smoke:  ## Smoke вертикального среза по живому API
	cd backend && DB_NAME=$(DB) python3 tests/smoke_vertical_slice.py

lint:  ## Проверки стиля и типов
	cd backend && python3 -m ruff check app tests && python3 -m mypy app || true
	cd frontend && npm run lint

openapi:  ## Выгрузить контракт OpenAPI 3.1
	cd backend && DB_NAME=$(DB) PYTHONPATH=. python3 ../infrastructure/scripts/export_openapi.py

reset-db:  ## Пересоздать базу с нуля и накатить миграции
	dropdb --if-exists $(DB) && createdb $(DB)
	psql -q -d $(DB) -v ON_ERROR_STOP=1 -v mig_pw=test_migration -v run_pw=test_runtime \
	     -v aud_pw=test_audit -v ro_pw=test_readonly \
	     -f infrastructure/db/migrations/00_platform_bootstrap.sql
	psql -q -d $(DB) -c "GRANT CREATE ON DATABASE $(DB) TO putzplan_migration"
	$(MAKE) migrate seed

.PHONY: help up down migrate seed test test-db test-api smoke lint openapi reset-db
