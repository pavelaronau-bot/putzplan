"""Общие фикстуры. Интеграционные тесты работают с настоящей PostgreSQL:
mock-базы и подмены авторизации запрещены заданием."""
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DB_NAME", os.environ.get("DB_NAME", "putzplan_dev"))
os.environ.setdefault("LOGIN_RATE_LIMIT", "1000")   # лимит проверяется отдельным тестом

from app.core.config import get_settings  # noqa: E402
from app.main import app  # noqa: E402
from app.security.passwords import hash_password  # noqa: E402

settings = get_settings()

COMPANY_A = uuid.UUID("aaaa0000-0000-0000-0000-000000000001")
COMPANY_B = uuid.UUID("aaaa0000-0000-0000-0000-0000000000b2")
OWNER_EMAIL = "owner@demo.putzplan.de"
OWNER_PASSWORD = "Owner12345678"
DISPATCHER_EMAIL = "disp@demo.putzplan.de"
DISPATCHER_PASSWORD = "Disp12345678"


@pytest.fixture(autouse=True)
def reset_rate_limit():
    """Счётчик попыток входа не должен перетекать между тестами."""
    from app.security import rate_limit
    rate_limit.reset()
    yield
    rate_limit.reset()


@pytest_asyncio.fixture(autouse=True)
async def dispose_engines():
    """Каждый тест выполняется в своём цикле событий, поэтому пулы соединений
    закрываются после теста: иначе соединение остаётся привязанным к закрытому циклу."""
    yield
    from app.db.session import close_engines
    await close_engines()


async def _admin_conn() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=settings.db_host, port=settings.db_port, database=settings.db_name,
        user=os.environ.get("DB_MIGRATION_USER", "putzplan_migration"),
        password=os.environ.get("DB_MIGRATION_PASSWORD", "test_migration"))


@pytest_asyncio.fixture(scope="session", autouse=True)
async def seed_second_tenant():
    """Второй арендатор нужен для проверки межарендаторной изоляции."""
    conn = await _admin_conn()
    await conn.execute(
        "INSERT INTO companies (id,name) VALUES ($1,'Fremd GmbH') ON CONFLICT (id) DO NOTHING",
        COMPANY_B)
    role_id = await conn.fetchval("SELECT id FROM roles WHERE key='super_admin' AND is_system")
    await conn.execute("""
        INSERT INTO users (id, company_id, role_id, email, full_name, status, password_hash,
                           password_changed_at)
        VALUES ($1,$2,$3,'owner-b@demo.putzplan.de','Fremd Owner','active',$4, now())
        ON CONFLICT (id) DO UPDATE SET password_hash = EXCLUDED.password_hash, status='active'""",
        uuid.UUID("bbbb0000-0000-0000-0000-0000000000b2"), COMPANY_B, role_id,
        hash_password("Fremd12345678"))
    await conn.close()
    yield


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


@pytest_asyncio.fixture
async def owner_token(client: AsyncClient) -> str:
    r = await client.post("/api/v1/auth/login",
                          json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest_asyncio.fixture
async def dispatcher_token(client: AsyncClient) -> str:
    r = await client.post("/api/v1/auth/login",
                          json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


@pytest_asyncio.fixture
async def tenant_b_token(client: AsyncClient) -> str:
    r = await client.post("/api/v1/auth/login",
                          json={"email": "owner-b@demo.putzplan.de", "password": "Fremd12345678"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


ALLOWED_ORIGIN = "http://localhost:5173"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def browser_headers(client) -> dict[str, str]:
    """Заголовки, которые браузер отправляет при cookie-потоке:
    Origin из списка разрешённых и CSRF-токен двойной отправки."""
    return {"origin": ALLOWED_ORIGIN,
            "x-csrf-token": client.cookies.get("putzplan_csrf") or ""}


@pytest.fixture
def unique() -> str:
    return uuid.uuid4().hex[:10]
