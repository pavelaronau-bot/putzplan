#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
# Аудит зависимостей Python на известные уязвимости.
#
# Один и тот же скрипт запускают CI и разработчик, поэтому расхождений
# «локально работает, в CI падает» не возникает.
#
#   bash infrastructure/scripts/audit_python_deps.sh
#
# Код возврата 0 — уязвимостей нет; 1 — найдены либо аудит невозможен.
# Проверка не отключается: исключения допускаются только через allowlist
# с идентификатором уязвимости, причиной и сроком пересмотра.
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${AUDIT_VENV:-/tmp/putzplan-audit-venv}"
ALLOWLIST="$ROOT/security/pip-audit-allowlist.txt"
REQUIREMENTS="${AUDIT_REQUIREMENTS:-/tmp/putzplan-audit-requirements.txt}"

echo "▶ Изолированное окружение: $VENV"
# Аудит только зависимостей проекта. В окружении раннера и в системе
# присутствуют посторонние пакеты, чьи уязвимости к продукту не относятся
# и делают проверку невоспроизводимой.
rm -rf "$VENV"
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet "$ROOT/backend[dev]"
"$VENV/bin/python" -m pip install --quiet pip-audit

echo "▶ Список зависимостей"
# Собственный пакет проекта отсутствует на PyPI: в режиме --strict он
# приводит к ошибке «Dependency not found on PyPI», поэтому исключается.
"$VENV/bin/pip" freeze --exclude-editable \
  | awk '!/^putzplan-backend/' > "$REQUIREMENTS"
echo "  пакетов к проверке: $(wc -l < "$REQUIREMENTS")"

# Разбор allowlist построчно. grep здесь неприменим: файл из одних
# комментариев даёт код 1 и под set -e обрывает шаг до запуска pip-audit.
IGNORES=()
if [ -f "$ALLOWLIST" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    id="${line%%#*}"
    id="$(echo "$id" | tr -d '[:space:]')"
    [ -z "$id" ] && continue
    IGNORES+=(--ignore-vuln "$id")
  done < "$ALLOWLIST"
fi
echo "  исключений из allowlist: $(( ${#IGNORES[@]} / 2 ))"

echo "▶ pip-audit --strict"
"$VENV/bin/pip-audit" --strict -r "$REQUIREMENTS" ${IGNORES[@]+"${IGNORES[@]}"}
echo "✅ Известных уязвимостей в зависимостях нет"
