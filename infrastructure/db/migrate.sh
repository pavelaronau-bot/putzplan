#!/usr/bin/env bash
# Применение миграций в документированном порядке. Повторяемо.
#   ./migrate.sh [база] — по умолчанию putzplan_dev
set -euo pipefail
DB="${1:-${DB_NAME:-putzplan_dev}}"
HOST="${DB_HOST:-127.0.0.1}"; PORT="${DB_PORT:-5432}"
DIR="$(cd "$(dirname "$0")" && pwd)"

MIG_PW="${DB_MIGRATION_PASSWORD:-test_migration}"
RUN_PW="${DB_RUNTIME_PASSWORD:-test_runtime}"
AUD_PW="${DB_AUDIT_PASSWORD:-test_audit}"
RO_PW="${DB_READONLY_PASSWORD:-test_readonly}"

echo "▶ База: $DB"
createdb "$DB" 2>/dev/null || echo "  база уже существует"

echo "▶ 00_platform_bootstrap.sql (суперпользователь: расширения и роли)"
psql -v ON_ERROR_STOP=1 -q -d "$DB" \
  -v mig_pw="$MIG_PW" -v run_pw="$RUN_PW" -v aud_pw="$AUD_PW" -v ro_pw="$RO_PW" \
  -f "$DIR/migrations/00_platform_bootstrap.sql"
psql -q -d "$DB" -c "GRANT CREATE ON DATABASE \"$DB\" TO putzplan_migration"

for f in 01_schema 02_reference_data 03_permissions; do
  echo "▶ $f.sql (роль putzplan_migration)"
  PGPASSWORD="$MIG_PW" psql -v ON_ERROR_STOP=1 -q -h "$HOST" -p "$PORT" \
    -U putzplan_migration -d "$DB" -f "$DIR/migrations/$f.sql"
done

echo "▶ Проверка структуры"
PGPASSWORD="$MIG_PW" psql -v ON_ERROR_STOP=1 -q -h "$HOST" -p "$PORT" \
  -U putzplan_migration -d "$DB" -f "$DIR/validate.sql"
echo "✅ Миграции применены"
