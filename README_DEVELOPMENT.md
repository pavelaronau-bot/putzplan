# README_DEVELOPMENT

Проверено на Python 3.12.3, PostgreSQL 16.14 + PostGIS 3.4, Node.js 20.

## Структура

```
putzplan/
├── backend/
│   ├── app/
│   │   ├── api/            роутеры v1 и зависимости прав
│   │   ├── core/           конфигурация и ошибки
│   │   ├── db/             сессии, схемы Pydantic
│   │   ├── domain/         доменные объекты
│   │   ├── repositories/   доступ к данным
│   │   ├── security/       пароли, токены, лимиты
│   │   ├── services/       сценарии: auth, users, roles, audit
│   │   └── observability/  логи и метрики
│   ├── alembic/versions/   0001 базовая схема, 0002 Sprint 1
│   └── tests/              unit, integration, smoke
├── frontend/
│   ├── src/{api,app,features,pages,shared}
│   ├── tests/              Vitest
│   └── e2e/                Playwright
├── infrastructure/
│   ├── db/                 SQL-миграции укрепления и 56 автотестов
│   ├── docker/             Dockerfile и nginx
│   └── scripts/            seed_dev.py, export_openapi.py
├── openapi/                openapi.yaml, openapi.json
└── .github/workflows/ci.yml
```

## Локальный запуск без Docker

```bash
# 1. Роли и расширения (один раз, суперпользователем)
createdb putzplan_dev
psql -v ON_ERROR_STOP=1 -d putzplan_dev \
  -v mig_pw=test_migration -v run_pw=test_runtime \
  -v aud_pw=test_audit -v ro_pw=test_readonly \
  -f infrastructure/db/migrations/00_platform_bootstrap.sql
psql -d putzplan_dev -c "GRANT CREATE ON DATABASE putzplan_dev TO putzplan_migration"

# 2. Миграции и данные
make migrate
make seed

# 3. Backend и frontend
cd backend && DB_NAME=putzplan_dev uvicorn app.main:app --reload
cd frontend && npm ci && npm run dev
```

## Команды

```bash
make up          # вся среда в Docker
make migrate     # alembic upgrade head
make seed        # демонстрационные данные (не для production)
make test        # SQL-тесты + pytest + Vitest
make smoke       # 43 проверки вертикального среза по живому API
make lint        # ruff, mypy, tsc
make openapi     # выгрузка контракта
make reset-db    # пересоздать базу с нуля
```

## Миграции

- `0001_baseline_hardened_schema` — схема после Database Hardening: 55 таблиц,
  составные межарендаторные ключи, партиции, RLS, хеш-цепочка журнала.
- `0002_sprint1_users_and_permissions` — колонка `users.full_name` и права
  спринта: `users.read/create/update/deactivate`, `roles.read/create/update`,
  `roles.permissions.manage`, `security.sessions.read/revoke`,
  `profile.security`, `audit.read`.

Файл `00_platform_bootstrap.sql` выполняется отдельно суперпользователем:
он создаёт расширения и роли кластера, что вне полномочий Alembic.
Откат последней миграции проверяется в CI (`downgrade -1` и обратно).

## Роли базы данных

| Роль | Права |
|---|---|
| `putzplan_migration` | владелец схемы, DDL, BYPASSRLS, провижининг арендаторов |
| `putzplan_runtime` | SELECT/INSERT/UPDATE; без DELETE при мягком удалении; без записи в журнал |
| `putzplan_audit` | INSERT/SELECT только в `audit_logs` |
| `putzplan_readonly` | SELECT |

## Контекст арендатора

```python
async with tenant_session(company_id) as session:
    # SET LOCAL app.company_id действует до COMMIT,
    # соединение возвращается в пул без контекста
    rows = await session.execute(text("SELECT * FROM users"))
```

`company_id` берётся исключительно из access-токена. Значение из тела запроса
игнорируется — это проверяется тестом `test_company_id_from_body_is_ignored`.

Вход выполняется до появления контекста, поэтому используются узкие
`SECURITY DEFINER`-функции (`auth_find_user`, `auth_session_lookup`,
`auth_user_permissions` и другие), а не выдача рабочей роли `BYPASSRLS`.

## Права

Проверка централизована: `Depends(require("users.read"))`. Отсутствие права —
403 и запись `ACCESS_DENIED` в журнал. Права читаются из БД
(`roles → role_permissions → permissions` плюс индивидуальные grant/deny).
Интерфейс скрывает недоступные действия, но источник истины — сервер.

## Переменные окружения

Полный список — `.env.example`. Обязательные в production: `JWT_SECRET`,
пароли ролей БД, `CORS_ORIGINS`, `TRUSTED_HOSTS`. Без собственного
`JWT_SECRET` приложение в production не стартует (fail-closed).

## Соглашения

- Новый эндпоинт добавляется вместе с правом в `permissions` и записью в OpenAPI.
- Изменение схемы — только миграцией Alembic, никаких ручных правок.
- Каждое изменяющее действие пишет событие в журнал.
- Отказ в доступе покрывается негативным тестом.
- `TODO` в миграциях запрещены — CI падает.
