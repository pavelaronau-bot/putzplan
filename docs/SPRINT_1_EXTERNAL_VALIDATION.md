# SPRINT_1_EXTERNAL_VALIDATION

Документ для внешней проверки Sprint 1 на GitHub-hosted runner.
Всё, что нельзя было проверить в среде разработки, вынесено сюда
с точными командами и критериями.

**Commit SHA:** `3eacb316000ad1cfd460c9382c17c3552a3373fc`
**Ветка для проверки:** `main`
**Ветка Sprint 2 (не проверяется, не сливать):** `feature/sprint-2`

---

## 1. Зачем нужна внешняя проверка

Три позиции Sprint 1 невозможно подтвердить в среде разработки:

| Позиция | Причина |
|---|---|
| Docker Compose | реестр образов отвечает `403 Forbidden` на `registry-1.docker.io` |
| Playwright Chromium | загрузка браузеров с CDN заблокирована, системный Chromium в Ubuntu 24.04 — только snap |
| Release Gate | GitHub Actions недоступен из среды |

Всё остальное проверено фактическим запуском: 56 SQL-тестов, 92 backend-теста,
45 smoke-проверок, 9 тестов фронтенда, mypy, ruff, bandit, npm audit.

## 2. Ожидаемые задачи пайплайна

Файл `.github/workflows/ci.yml`, восемь задач:

| Задача | Что делает | Зависит от |
|---|---|---|
| `backend-quality` | ruff, mypy (обе блокируют) | — |
| `database` | bootstrap ролей, 56 SQL-тестов, `validate.sql` | — |
| `backend-tests` | Alembic upgrade/downgrade/upgrade, seed, pytest, OpenAPI-гейт | backend-quality, database |
| `frontend` | `npm ci`, tsc, Vitest, сборка, npm audit, синхронность lock | — |
| `e2e` | API + Vite preview + Playwright Chromium | backend-tests, frontend |
| `security` | bandit, pip-audit, поиск секретов, запрет TODO | — |
| `docker` | сборка образов, compose up, /health, /ready, smoke, down -v, повторный запуск | backend-quality, database, backend-tests, frontend, security |
| `release-gate` | разбирает результаты всех семи задач | все перечисленные |

## 3. Команды, которые выполняет CI

### database
```bash
psql -v ON_ERROR_STOP=1 -d putzplan_ci -v mig_pw=… -v run_pw=… -v aud_pw=… -v ro_pw=… \
     -f infrastructure/db/migrations/00_platform_bootstrap.sql
bash infrastructure/db/tests/run_tests.sh putzplan_ci      # 56 тестов, exit 1 при провале
psql -v ON_ERROR_STOP=1 -U putzplan_migration -d putzplan_ci -f infrastructure/db/validate.sql
```

### backend-tests
```bash
pip install -e "backend[dev]" psycopg2-binary pyyaml
cd backend && python -m alembic upgrade head
python -m alembic downgrade -1 && python -m alembic upgrade head
PYTHONPATH=. python ../infrastructure/scripts/seed_dev.py
python -m pytest -q --junitxml=../pytest-report.xml                 # 92 теста
PYTHONPATH=. python ../infrastructure/scripts/export_openapi.py
git diff --exit-code openapi/                                        # контракт не устарел
python -m pytest tests/test_openapi_compat.py -q                     # 10 фикстур гейта
python infrastructure/scripts/openapi_diff.py /tmp/base.json openapi/openapi.json
```

### frontend
```bash
cd frontend && npm ci && npm run lint && npx vitest run && npm run build
npm audit --audit-level=high
npm install --package-lock-only --ignore-scripts && git diff --exit-code package-lock.json
```

### e2e
```bash
python -m uvicorn app.main:app --port 8000 &                        # ожидание /health
python backend/tests/smoke_vertical_slice.py                         # 45 проверок
cd frontend && npx playwright install --with-deps chromium
npm run build && npx vite preview --port 5173 &
npx playwright test                                                  # e2e/smoke.spec.ts
```

### docker
```bash
cp .env.example .env
docker compose config
docker build -f infrastructure/docker/backend.Dockerfile  -t putzplan-api:ci .
docker build -f infrastructure/docker/frontend.Dockerfile -t putzplan-ui:ci .
docker compose up --build -d
curl -fsS http://localhost:8000/health | grep '"status":"ok"'
curl -fsS http://localhost:8000/ready  | grep '"status":"ready"'     # + db_runtime, db_audit
docker compose exec -T api python -m scripts.seed_container
python backend/tests/smoke_compose.py                                # 9 проверок
curl -fsS http://localhost:8080/ | grep -i "<!doctype html"          # фронтенд за nginx
docker compose down -v
docker compose up --build -d                                         # повторный чистый запуск
curl -fsS http://localhost:8000/ready | grep '"status":"ready"'
```

## 4. Secrets и переменные

**Секреты не обязательны.** У каждого задано значение по умолчанию для CI,
поэтому пайплайн запускается на форке и в приватном репозитории без настройки.

| Secret | Назначение | Значение по умолчанию |
|---|---|---|
| `CI_DB_MIGRATION_PASSWORD` | пароль роли `putzplan_migration` | `ci_migration` |
| `CI_DB_RUNTIME_PASSWORD` | пароль роли `putzplan_runtime` | `ci_runtime` |
| `CI_DB_AUDIT_PASSWORD` | пароль роли `putzplan_audit` | `ci_audit` |
| `CI_DB_READONLY_PASSWORD` | пароль роли `putzplan_readonly` | `ci_readonly` |

Переменная репозитория (Variables, не Secrets):

| Variable | Когда нужна |
|---|---|
| `ALLOW_MISSING_OPENAPI_BASELINE` | только при первой загрузке, когда в базовой ветке ещё нет `openapi/openapi.json`. Значение `true`. После первого успешного прогона — удалить |

Секреты БД в CI одноразовые: база поднимается из образа и уничтожается вместе
с раннером. Реальные production-пароли сюда не вносятся.

## 5. Критерии PASS

Sprint 1 считается подтверждённым **только** при выполнении всех условий:

1. Задача `release-gate` завершилась зелёной.
2. Задача `docker` зелёная, и в её логах видно:
   - `docker compose up --build` без ошибок;
   - `{"status":"ok"}` от `/health`;
   - `{"status":"ready"}` от `/ready` с `db_runtime: ok` и `db_audit: ok`;
   - `COMPOSE SMOKE: passed=9 failed=0`;
   - успешный `docker compose down -v`;
   - повторный запуск с чистого тома снова отдаёт `ready`.
3. Задача `e2e` зелёная, Playwright прошёл оба сценария из `e2e/smoke.spec.ts`.
4. Задача `database`: `ИТОГО: passed=56 failed=0`.
5. Задача `backend-tests`: `92 passed`, миграции применяются и откатываются.
6. Задача `frontend`: `9 passed`, сборка успешна, `npm audit` без находок high.
7. Задача `security`: bandit и pip-audit без блокирующих находок.
8. Ни одна задача не пропущена (`skipped`) и не завершилась `cancelled`.

## 6. Критерии FAIL

Любой из пунктов означает, что Sprint 1 остаётся **NOT READY**:

- `release-gate` красный или пропущен;
- `docker` или `e2e` красные, пропущены или отменены;
- `/ready` вернул `not_ready` либо `db_audit` не `ok`;
- `COMPOSE SMOKE` показал `failed` больше нуля;
- повторный запуск после `down -v` не поднялся;
- Playwright упал или браузер не установился;
- любое падение миграции, теста или проверки контракта;
- обнаружены секреты в коде или `TODO` в миграциях.

## 7. Доказательства, которые нужно сохранить

Для аудита передайте:

1. **URL прогона** целиком: `https://github.com/<владелец>/<репозиторий>/actions/runs/<RUN_ID>`
2. **Run ID** и **Run attempt** (число вверху страницы прогона).
3. **Commit SHA**, на котором выполнялся прогон: должен совпадать с `3eacb31`.
4. Ссылки на отдельные задачи `docker`, `e2e`, `release-gate`.
5. Скачанные логи: кнопка *Download log archive* на странице прогона.
6. Артефакт `pytest-report` (JUnit XML) и, при наличии, `playwright-report`.
7. Скриншот сводки прогона со списком восьми задач и их статусами.

Этих данных достаточно, чтобы независимо подтвердить: проверка выполнена
на конкретном коммите, все задачи зелёные, ничего не пропущено.

## 8. После получения зелёного прогона

1. Внести Run ID и ссылки в `docs/SPRINT_1_2_RELEASE_REPORT.md`, раздел «Docker и Playwright».
2. Заменить статус отчёта на **PASS**.
3. Только после этого допустимо написать
   *PUTZPLAN Sprint 1 — Approved for Sprint 2* и продолжить ветку `feature/sprint-2`.

До получения зелёного прогона статус остаётся **NOT READY** — это относится
и к Docker, и к Playwright, и к Sprint 1 в целом.
