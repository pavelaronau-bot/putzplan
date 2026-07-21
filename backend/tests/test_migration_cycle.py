"""Цикл миграций: работоспособность приложения на каждом шаге.

Проверяется последовательность upgrade → downgrade → upgrade, и на каждом
шаге выполняется настоящий сценарий: вход и обновление токена по HTTP.
Откат не должен оставлять базу в состоянии, при котором приложение падает.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import DISPATCHER_EMAIL, DISPATCHER_PASSWORD

BACKEND_DIR = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.serial


def alembic(*args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "DB_NAME": os.environ.get("DB_NAME", "putzplan_dev")}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND_DIR,
                          env=env, capture_output=True, text=True, check=False)


def current_revision() -> str:
    result = alembic("current")
    assert result.returncode == 0, result.stderr
    return result.stdout.strip().split()[0] if result.stdout.strip() else ""


async def login_and_refresh() -> tuple[int, int, str]:
    """Возвращает (код входа, код обновления, код ошибки обновления)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        login = await client.post("/api/v1/auth/login",
                                  json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD})
        if login.status_code != 200:
            return login.status_code, 0, login.text[:200]
        token = login.cookies.get("putzplan_refresh")
        # Cookie-поток защищён CSRF: воспроизводим заголовки браузера
        headers = {"origin": "http://localhost:5173",
                   "x-csrf-token": login.cookies.get("putzplan_csrf") or ""}
        rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": token},
                                    headers=headers)
        code = rotated.json().get("code", "") if rotated.status_code != 200 else ""
        return login.status_code, rotated.status_code, code


async def test_upgrade_downgrade_upgrade_keeps_application_working():
    from app.db.session import close_engines

    # ── Этап 1: актуальная схема ──────────────────────────────────────
    assert alembic("upgrade", "head").returncode == 0
    assert current_revision().startswith("0004")
    login_code, refresh_code, error = await login_and_refresh()
    assert login_code == 200, f"вход на 0004: {error}"
    assert refresh_code == 200, f"обновление токена на 0004: {error}"
    await close_engines()

    # ── Этап 2: откат последней миграции ──────────────────────────────
    result = alembic("downgrade", "-1")
    assert result.returncode == 0, result.stderr
    assert current_revision().startswith("0003")

    login_code, refresh_code, error = await login_and_refresh()
    assert login_code == 200, f"после отката вход сломан: {error}"
    assert refresh_code == 200, f"после отката обновление токена сломано: {error}"
    await close_engines()

    # ── Этап 3: повторное применение ──────────────────────────────────
    assert alembic("upgrade", "head").returncode == 0
    assert current_revision().startswith("0004")
    login_code, refresh_code, error = await login_and_refresh()
    assert login_code == 200, f"после повторного применения вход сломан: {error}"
    assert refresh_code == 200, f"после повторного применения обновление сломано: {error}"
    await close_engines()


async def test_downgrade_restores_real_function_not_stub():
    """После отката функция обязана работать, а не возвращать заглушку."""
    from sqlalchemy import text

    from app.db.session import close_engines, system_session

    assert alembic("downgrade", "-1").returncode == 0
    try:
        async with system_session() as session:
            source = (await session.execute(text("""
                SELECT prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE p.proname = 'auth_rotate_session' AND n.nspname = 'public'
                 ORDER BY pronargs LIMIT 1"""))).scalar_one()
            columns = (await session.execute(text("""
                SELECT count(*) FROM information_schema.columns
                 WHERE table_name = 'sessions' AND column_name IN ('rotated_at','replaced_by_session_id')
            """))).scalar_one()

        # Заглушка вернула бы только not_found; настоящая реализация содержит все состояния
        for state in ("'rotated'", "'reuse'", "'expired'", "'inactive_user'", "'not_found'"):
            assert state in source, f"после отката отсутствует состояние {state}"
        assert "INSERT INTO sessions" in source, "после отката функция не создаёт новую сессию"
        assert columns == 0, "колонки ревизии 0004 должны быть удалены при откате"

        login_code, refresh_code, error = await login_and_refresh()
        assert login_code == 200 and refresh_code == 200, error
    finally:
        await close_engines()
        assert alembic("upgrade", "head").returncode == 0
        await close_engines()
