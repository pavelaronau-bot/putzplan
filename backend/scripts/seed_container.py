"""Демонстрационные данные внутри контейнера API.

Отличие от infrastructure/scripts/seed_dev.py — путь импорта и то,
что подключение берётся из переменных окружения контейнера.
В production выполнение запрещено проверкой окружения.
"""
import asyncio
import sys
from uuid import UUID

import asyncpg

from app.core.config import get_settings
from app.security.passwords import hash_password

settings = get_settings()
COMPANY = UUID("aaaa0000-0000-0000-0000-000000000001")
ACCOUNTS = [
    ("bbbb0000-0000-0000-0000-000000000001", "owner@demo.putzplan.de", "Stefan Brandt",
     "super_admin", "Inhaber", "Owner12345678"),
    ("bbbb0000-0000-0000-0000-000000000002", "admin@demo.putzplan.de", "Anna Müller",
     "admin", "Büroleitung", "Admin12345678"),
    ("bbbb0000-0000-0000-0000-000000000003", "disp@demo.putzplan.de", "Tomasz Wilk",
     "dispatcher", "Einsatzleiter", "Disp12345678"),
]


async def main() -> None:
    if settings.is_production:
        print("Сид демонстрационных данных запрещён в production", file=sys.stderr)
        raise SystemExit(1)
    import os
    conn = await asyncpg.connect(
        host=settings.db_host, port=settings.db_port, database=settings.db_name,
        user=os.environ.get("DB_MIGRATION_USER", "putzplan_migration"),
        password=os.environ.get("DB_MIGRATION_PASSWORD", "change_me_migration"))
    await conn.execute(
        "INSERT INTO companies (id,name,bundesland) VALUES ($1,'Demo Gebäudereinigung GmbH','Bayern')"
        " ON CONFLICT (id) DO NOTHING", COMPANY)
    for uid, email, full_name, role, position, password in ACCOUNTS:
        role_id = await conn.fetchval("SELECT id FROM roles WHERE key=$1 AND is_system", role)
        await conn.execute("""
            INSERT INTO users (id, company_id, role_id, email, full_name, position, status,
                               password_hash, password_changed_at)
            VALUES ($1,$2,$3,$4,$5,$6,'active',$7, now())
            ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email,
                password_hash = EXCLUDED.password_hash, full_name = EXCLUDED.full_name,
                status='active', failed_attempts=0, locked_until=NULL""",
            UUID(uid), COMPANY, role_id, email, full_name, position, hash_password(password))
        print(f"  {email} — {role}")
    await conn.close()


asyncio.run(main())
