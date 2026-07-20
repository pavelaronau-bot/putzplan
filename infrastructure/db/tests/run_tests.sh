#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Полный автоматический прогон тестов базы данных PUTZPLAN.
# Возвращает 0 только если все тесты пройдены; иначе ненулевой код,
# и CI падает. Ручной просмотр вывода не требуется.
#
#   ./run_tests.sh [имя_тестовой_бд]
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

DB="${1:-putzplan_test}"
HOST="${PGHOST:-127.0.0.1}"
PORT="${PGPORT:-5432}"
DIR="$(cd "$(dirname "$0")" && pwd)"
MIG="$DIR/../migrations"

MIG_PW="${PUTZPLAN_MIGRATION_PW:-test_migration}"
RUN_PW="${PUTZPLAN_RUNTIME_PW:-test_runtime}"
AUD_PW="${PUTZPLAN_AUDIT_PW:-test_audit}"
RO_PW="${PUTZPLAN_READONLY_PW:-test_readonly}"

psql_as () { local user="$1" pw="$2"; shift 2
  PGPASSWORD="$pw" psql -v ON_ERROR_STOP=1 -h "$HOST" -p "$PORT" -U "$user" -d "$DB" -q "$@"
}

echo "▶ 1/6 Пересоздание тестовой базы $DB"
dropdb --if-exists "$DB"
createdb "$DB"

echo "▶ 2/6 Миграции"
psql -v ON_ERROR_STOP=1 -d "$DB" -q \
     -v mig_pw="$MIG_PW" -v run_pw="$RUN_PW" -v aud_pw="$AUD_PW" -v ro_pw="$RO_PW" \
     -f "$MIG/00_platform_bootstrap.sql"
psql_as putzplan_migration "$MIG_PW" -f "$MIG/01_schema.sql"
psql_as putzplan_migration "$MIG_PW" -f "$MIG/02_reference_data.sql"
psql_as putzplan_migration "$MIG_PW" -f "$MIG/03_permissions.sql"

echo "▶ 3/6 Каркас тестов и данные"
psql -v ON_ERROR_STOP=1 -d "$DB" -q -c "GRANT CREATE ON DATABASE $DB TO putzplan_migration"
psql_as putzplan_migration "$MIG_PW" -f "$DIR/00_test_framework.sql"
psql_as putzplan_migration "$MIG_PW" -f "$DIR/01_seed.sql"
psql_as putzplan_migration "$MIG_PW" -f "$DIR/10_cross_tenant.sql"

echo "▶ 4/6 Тесты под рабочей ролью putzplan_runtime"
psql_as putzplan_runtime "$RUN_PW" -f "$DIR/20_rls_and_context.sql"

echo "▶ 5/6 Тесты журнала под ролью putzplan_audit"
psql_as putzplan_audit "$AUD_PW" -f "$DIR/30_audit_chain.sql"

echo "▶ 5b Параллельные вставки в журнал (8 потоков × 25 записей)"
psql_as putzplan_migration "$MIG_PW" -c \
  "INSERT INTO companies (id,name) VALUES ('33333333-3333-3333-3333-333333333333','Concurrency Co')
   ON CONFLICT DO NOTHING" >/dev/null
for i in $(seq 1 8); do
  PGPASSWORD="$AUD_PW" psql -v ON_ERROR_STOP=1 -h "$HOST" -p "$PORT" -U putzplan_audit -d "$DB" -q -c \
    "INSERT INTO audit_logs (company_id,action,entity)
     SELECT '33333333-3333-3333-3333-333333333333','ПАРАЛЛЕЛЬНО','поток $i' FROM generate_series(1,25)" &
done
wait
psql_as putzplan_audit "$AUD_PW" -f "$DIR/40_concurrency.sql"

echo "▶ 6/6 Итог"
psql_as putzplan_migration "$MIG_PW" -f "$DIR/90_summary.sql"
echo "✅ Все тесты пройдены"
