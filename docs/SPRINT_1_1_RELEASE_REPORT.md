# SPRINT_1_1_RELEASE_REPORT

**Дата:** 20 июля 2026
**Спринт:** 1.1 — Code Review Fixes
**Commit SHA:** `5e9ba27e508bee51df7e990f637d0479347e04fd`
**Ветка:** main (локальный репозиторий архива)

**Статус Release Gate 1.1: НЕ ПРОЙДЕН.**
Восемь пунктов из десяти закрыты и подтверждены фактическим прогоном.
Два пункта — Docker Compose и Playwright — **не проверялись**, потому что
в среде разработки нет демона Docker и недоступна загрузка браузеров.
Пункт 12 задания прямо запрещает объявлять их проверенными без запуска,
поэтому статус PASS не ставится.

---

## 1. Окружение прогона

| Компонент | Версия |
|---|---|
| Python | 3.12.3 |
| PostgreSQL | 16.14 + PostGIS 3.4.2 |
| Redis | 7.x (локальный экземпляр, порт 6379) |
| Node.js | 22.22.2 (целевая для CI и образов — 20 LTS) |
| FastAPI / SQLAlchemy / Alembic | 0.115.14 / 2.0.51 / 1.14 |
| Vite / Vitest / Playwright | 8.1.5 / 4.1.10 / 1.61.1 |

## 2. Результаты фактических прогонов

| Набор | Команда | passed | failed | skipped |
|---|---|---|---|---|
| SQL-тесты укрепления базы | `bash infrastructure/db/tests/run_tests.sh putzplan_test` | **56** | 0 | 0 |
| Backend unit + integration | `pytest -q` | **83** | 0 | 0 |
| Smoke вертикального среза | `python tests/smoke_vertical_slice.py` | **45** | 0 | 0 |
| Frontend unit | `npx vitest run` | **9** | 0 | 0 |
| Гейт совместимости OpenAPI | `pytest tests/test_openapi_compat.py` | **10** | 0 | 0 |
| **Итого** | | **203** | **0** | **0** |

Дополнительно: `mypy app` — no issues in 41 files; `ruff check app tests` — all checks passed;
`bandit -r app -ll` — 0 high, 0 medium; `npm audit --audit-level=high` — 0 vulnerabilities;
`npm ci` на пустом каталоге — код 0; `alembic upgrade head` → ревизия 0003, откат и повтор проверены.

## 3. Исправление №1 — воспроизводимый frontend build

| Требование | Результат |
|---|---|
| Синхронный package-lock.json | пересобран через `npm install` на Node 20-совместимом рантайме |
| `npm ci` на чистой машине | **код 0**, node_modules удалялся перед прогоном |
| Точные версии Playwright | `@playwright/test`, `playwright`, `playwright-core` = 1.61.1 в lock |
| lint / test / build | tsc без ошибок, 9 тестов, сборка 180 КБ (58 КБ gzip) |
| CI-проверка синхронности | шаг `npm install --package-lock-only` + `git diff --exit-code package-lock.json` |
| `npm ci` не заменён на `npm install` | подтверждено: clean install остался в CI |

Побочно закрыты уязвимости зависимостей: vite обновлён до 8.1.5, vitest до 4.1.10 —
`npm audit` теперь показывает 0 уязвимостей, исключения не понадобились.

## 4. Исправление №2 — атомарная ротация refresh

Реализована миграцией `0003`: добавлены `token_family_id` и `parent_session_id`,
создана SQL-функция `auth_rotate_session`. Внутри одной транзакции выполняется
`SELECT … FOR UPDATE`, проверка, `UPDATE … WHERE revoked_at IS NULL` и вставка новой
сессии; результат возвращается кодом: `rotated`, `reuse`, `race_lost`, `expired`,
`inactive_user`, `not_found`.

Тест `test_ten_parallel_refresh_requests_produce_single_winner`: **10 параллельных
запросов, ровно 1 получил новую пару токенов, 9 вернули 409** с кодами
`refresh_race` либо `refresh_reuse`.

Тест `test_reuse_revokes_whole_token_family`: после повтора старого токена
семейство отозвано, access-токен семейства перестаёт действовать.

Тест `test_reuse_event_is_recorded_in_audit`: событие `REFRESH_REUSE_DETECTED`
попадает в журнал вместе с идентификатором семейства и числом отозванных сессий.

## 5. Исправление №3 — CSRF для cookie-потока

Модуль `app/security/csrf.py`: проверка Origin или Referer по списку разрешённых
плюс double-submit token (cookie `putzplan_csrf` против заголовка `x-csrf-token`,
сравнение через `hmac.compare_digest`). Освобождение действует только для
подтверждённого Bearer-потока — наличие заголовка Authorization при одновременно
присланной refresh-cookie **не** отменяет проверку.

Негативные тесты (9 сценариев, все зелёные): чужой Origin, отсутствующий токен,
несовпадающий токен, отсутствие Origin и Referer, смешанный Bearer + cookie поток,
принятие Referer при отсутствии Origin, безопасные методы не блокируются.

Фронтенд читает CSRF-cookie и добавляет заголовок ко всем изменяющим запросам —
покрыто двумя тестами Vitest.

Побочная находка: cookie помечались `Secure` в тестовом окружении, из-за чего
браузерное правило не отдавало их по http. Введена отдельная настройка
`COOKIE_SECURE`; в production её отключение считается ошибкой конфигурации.

## 6. Исправление №4 — CI стал fail-closed

| Было | Стало |
|---|---|
| `mypy … \|\| true` | `cd backend && mypy app` — блокирует; **0 ошибок** в 41 файле |
| `pip-audit -r <(pip freeze) \|\| true` | `pip install -e "backend[dev]"` + `pip-audit --strict` с allowlist по CVE |
| нет проверки npm | `npm audit --audit-level=high` — блокирует |
| нет проверки lock | `npm install --package-lock-only` + `git diff --exit-code` |
| docker зависел от 2 задач | зависит от backend-quality, database, backend-tests, frontend, security |
| нет общего гейта | добавлена задача `release-gate`, зависящая от всех обязательных |

Файл исключений `security/pip-audit-allowlist.txt` создан пустым: формат требует
идентификатор уязвимости, причину, ответственного и срок пересмотра.

## 7. Исправление №5 — Docker Compose: **НЕ ПРОВЕРЕНО**

Подготовлено: шаг `docker compose up --build` с чистого тома, ожидание health,
проверка `/ready`, сид демонстрационных данных внутри контейнера
(`backend/scripts/seed_container.py`), compose-smoke из девяти проверок
(`backend/tests/smoke_compose.py`), `docker compose down -v` и повторный чистый запуск,
выгрузка логов при ошибке.

**Фактического запуска не было:** в среде разработки отсутствует демон Docker.
Пока этот шаг не отработает на CI-раннере, пункт DoD остаётся невыполненным.

## 8. Дополнительные security fixes

| Требование | Реализация | Проверено |
|---|---|---|
| JWT_SECRET ≥ 32 байт, контроль энтропии | оценка по Шеннону, минимум 12 различных символов, отсев значений по умолчанию | тестом: короткий и однообразный секрет отклоняются |
| Только утверждённый алгоритм | `Literal` в конфигурации, явный `algorithms=[…]`, обязательные claims | тест: токены `none` и HS512 отклонены |
| Единая проверка запроса | SQL-функция `auth_verify_request`: сессия, пользователь, компания, статус | тесты подмены company_id, user_id, неизвестной сессии |
| Роль не из JWT | роль и права читаются из БД при каждом запросе | тест: смена роли применяется без ожидания истечения токена |
| Rate limit в Redis | атомарный `INCR` + `EXPIRE`, fail-closed при недоступности | тест на двух экземплярах приложения: общий счётчик |
| Лимит X-Request-ID | шаблон `^[A-Za-z0-9._-]{1,64}$` | тест на инъекцию в лог |
| CSP, X-Frame-Options, Permissions-Policy | заголовки в middleware и nginx | тест наличия заголовков |

## 9. OpenAPI compatibility gate

Скрипт `infrastructure/scripts/openapi_diff.py` сравнивает не только пути и методы,
но и схемы: разворачивает `$ref`, находит удалённые коды ответов, свойства, значения
enum, смену типа и превращение необязательного поля в обязательное.

Покрытие — 10 тестов на фикстурах: семь несовместимых изменений обнаруживаются
(код 1), два совместимых проходят, идентичный контракт проходит.

В CI добавлены: проверка, что `openapi/` в репозитории совпадает с генерацией из кода
(`git diff --exit-code`), прогон фикстур и сравнение с контрактом базовой ветки.

## 10. Release Gate 1.1

| Критерий | Статус |
|---|---|
| `npm ci` на чистой среде | ✅ код 0 |
| Frontend lint, unit, build | ✅ 9 тестов, сборка успешна |
| Playwright | ❌ **не запускался** — браузеры недоступны в среде |
| Backend unit/integration/database | ✅ 83 + 56 |
| Параллельная ротация refresh безопасна | ✅ 10 запросов, 1 победитель |
| CSRF-тесты зелёные | ✅ 9 сценариев |
| mypy и pip-audit блокируют CI | ✅ конфигурация fail-closed |
| Docker Compose поднят и прошёл smoke | ❌ **не запускался** — нет демона Docker |
| OpenAPI gate проверяет схемы | ✅ 10 тестов на фикстурах |
| Нет Critical/High находок | ✅ bandit 0/0, npm audit 0 |

**Итог: 8 из 10.** Gate не пройден.

## 11. Что нужно для закрытия Gate

1. Выполнить задачу `docker` на CI-раннере с Docker: полный цикл
   `up --build` → health → compose smoke → `down -v` → повторный запуск.
2. Выполнить задачу `e2e`: `npx playwright install --with-deps chromium`
   и прогон `e2e/smoke.spec.ts`.
3. Приложить к отчёту идентификаторы прогонов CI обеих задач.

Обе задачи описаны в `.github/workflows/ci.yml` и не требуют изменений кода —
только среды, где доступны Docker и загрузка браузеров.

## 12. Изменённые файлы

Backend: `app/core/config.py`, `app/security/{tokens,csrf,rate_limit}.py`,
`app/repositories/{auth_repo,user_repo,role_repo,audit_repo}.py`,
`app/services/auth_service.py`, `app/api/deps.py`, `app/api/v1/auth.py`, `app/main.py`,
`alembic/versions/0003_atomic_refresh_and_session_binding.py`, `scripts/seed_container.py`.

Тесты: `test_integration_refresh_concurrency.py`, `test_integration_csrf.py`,
`test_integration_identity_binding.py`, `test_integration_rate_limit_redis.py`,
`test_openapi_compat.py`, `smoke_compose.py`, обновлены `conftest.py` и `test_integration_auth.py`.

Frontend: `src/api/client.ts`, `tests/csrf.test.ts`, `package.json`, `package-lock.json`.

Инфраструктура: `.github/workflows/ci.yml`, `infrastructure/scripts/openapi_diff.py`,
`security/pip-audit-allowlist.txt`, `openapi/openapi.{json,yaml}`.

## 13. Архитектура не менялась

Слои, модель данных, роли БД, контракт эндпоинтов и структура monorepo остались
прежними. Sprint 2 не начинался.
