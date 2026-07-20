# PUTZPLAN

Система управления клининговой фирмой: планирование уборок, объекты, сотрудники,
табель, финансы. Промышленная разработка ведётся вертикальными срезами.

**Текущее состояние — Sprint 1:** аутентификация, контекст арендатора,
пользователи, роли и права, журнал действий. Остальные модули описаны
в архитектуре и запланированы (`docs/DEVELOPMENT_ROADMAP.md`).

## Запуск одной командой

```bash
cp .env.example .env
docker compose up --build
```

Готово: API — http://localhost:8000/docs, интерфейс — http://localhost:8080.
Порядок поднятия соблюдается автоматически: база → миграции отдельным
шагом → API → фронтенд.

Демонстрационные учётные записи создаются только вне production:

| Логин | Пароль | Роль |
|---|---|---|
| `owner@demo.putzplan.de` | `Owner12345678` | Owner / Super Admin |
| `admin@demo.putzplan.de` | `Admin12345678` | Administrator |
| `disp@demo.putzplan.de` | `Disp12345678` | Dispatcher |

## Состав

| Каталог | Содержимое |
|---|---|
| `backend/` | FastAPI, SQLAlchemy 2 async, Alembic, тесты |
| `frontend/` | React + TypeScript + Vite, Vitest, Playwright |
| `infrastructure/db/` | SQL-миграции укрепления базы и 56 автотестов |
| `infrastructure/docker/` | Dockerfile бэкенда и фронтенда, nginx |
| `openapi/` | сгенерированный контракт OpenAPI 3.1 |
| `docs/` | архитектура, безопасность, отчёты |

## Технологии

Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic, PostgreSQL 16 + PostGIS,
Redis (готовность инфраструктуры), React 18, TypeScript 5, Vite 5,
Docker Compose, GitHub Actions.

## Безопасность

Argon2id для паролей, access-токен 15 минут в памяти вкладки, refresh
в HttpOnly + Secure + SameSite=Strict cookie с ротацией и обнаружением
повторного использования, ограничение частоты входов, блокировка после
5 неудачных попыток, deny-by-default в правах, изоляция арендаторов
через RLS, журнал действий с хеш-цепочкой и append-only на уровне СУБД.

Подробности: `docs/SECURITY_REQUIREMENTS.md`, `README_DEVELOPMENT.md`.

## Разработка

См. `README_DEVELOPMENT.md`: структура, миграции, тесты, переменные окружения,
соглашения. Команды — через `make help`.

## Статус

Sprint 1 завершён и проверен запуском. Готовым к продаже продукт
не является: реализован один вертикальный срез из запланированных пяти этапов.
Честная сводка — `docs/SPRINT_1_RELEASE_REPORT.md`.
