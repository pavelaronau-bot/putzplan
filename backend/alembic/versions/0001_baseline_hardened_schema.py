"""Базовая схема после Database Hardening (Gate 1).

Применяет проверенные SQL-файлы: структура, справочные данные, права.
Файл 00_platform_bootstrap.sql выполняется отдельно суперпользователем,
поскольку создаёт расширения и роли кластера.

Revision ID: 0001
Revises:
"""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parents[3] / "infrastructure" / "db" / "migrations"


def _run(file_name: str) -> None:
    sql = (SQL_DIR / file_name).read_text(encoding="utf-8")
    # psql-мета-команды в Alembic не нужны
    cleaned = "\n".join(line for line in sql.splitlines() if not line.startswith("\\"))
    op.execute(cleaned)


def upgrade() -> None:
    _run("01_schema.sql")
    _run("02_reference_data.sql")
    _run("03_permissions.sql")


def downgrade() -> None:
    # Базовая миграция необратима: откат означает удаление схемы целиком.
    op.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
