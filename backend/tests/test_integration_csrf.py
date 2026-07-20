"""Матрица CSRF для cookie- и Bearer-потоков."""
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import DISPATCHER_EMAIL, DISPATCHER_PASSWORD

ALLOWED_ORIGIN = "http://localhost:5173"
FOREIGN_ORIGIN = "https://evil.example.com"


async def _login_with_cookies() -> tuple[AsyncClient, str, str]:
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://testserver")
    r = await client.post("/api/v1/auth/login",
                          json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD})
    assert r.status_code == 200
    return client, r.cookies.get("putzplan_refresh"), r.cookies.get("putzplan_csrf")


async def test_cookie_refresh_requires_allowed_origin():
    client, _, csrf = await _login_with_cookies()
    try:
        r = await client.post("/api/v1/auth/refresh", json={},
                              headers={"origin": FOREIGN_ORIGIN, "x-csrf-token": csrf})
        assert r.status_code == 403 and r.json()["code"] == "csrf_origin_rejected"
    finally:
        await client.aclose()


async def test_cookie_refresh_requires_csrf_token():
    client, _, _ = await _login_with_cookies()
    try:
        r = await client.post("/api/v1/auth/refresh", json={},
                              headers={"origin": ALLOWED_ORIGIN})
        assert r.status_code == 403 and r.json()["code"] == "csrf_token_missing"
    finally:
        await client.aclose()


async def test_cookie_refresh_rejects_mismatched_token():
    client, _, _ = await _login_with_cookies()
    try:
        r = await client.post("/api/v1/auth/refresh", json={},
                              headers={"origin": ALLOWED_ORIGIN, "x-csrf-token": "fremdes-token-12345"})
        assert r.status_code == 403 and r.json()["code"] == "csrf_token_mismatch"
    finally:
        await client.aclose()


async def test_cookie_refresh_rejects_missing_origin_and_referer():
    client, _, csrf = await _login_with_cookies()
    try:
        r = await client.post("/api/v1/auth/refresh", json={}, headers={"x-csrf-token": csrf})
        assert r.status_code == 403 and r.json()["code"] == "csrf_origin_rejected"
    finally:
        await client.aclose()


async def test_cookie_refresh_succeeds_with_origin_and_token():
    client, _, csrf = await _login_with_cookies()
    try:
        r = await client.post("/api/v1/auth/refresh", json={},
                              headers={"origin": ALLOWED_ORIGIN, "x-csrf-token": csrf})
        assert r.status_code == 200, r.text
    finally:
        await client.aclose()


async def test_referer_is_accepted_when_origin_absent():
    client, _, csrf = await _login_with_cookies()
    try:
        r = await client.post("/api/v1/auth/refresh", json={},
                              headers={"referer": f"{ALLOWED_ORIGIN}/users", "x-csrf-token": csrf})
        assert r.status_code == 200, r.text
    finally:
        await client.aclose()


async def test_bearer_only_flow_is_exempt_from_csrf():
    """Чистый Bearer-поток без cookie браузер не подставит автоматически."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        login = await client.post("/api/v1/auth/login",
                                  json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD})
        token = login.json()["access_token"]
        refresh_value = login.cookies.get("putzplan_refresh")
        client.cookies.clear()
        r = await client.post("/api/v1/auth/logout-all",
                              headers={"authorization": f"Bearer {token}"}, json={})
        assert r.status_code == 200, r.text
        assert refresh_value


async def test_mixed_bearer_and_cookie_flow_is_not_exempt():
    """Наличие Authorization не отменяет проверку, если пришла и refresh-cookie."""
    client, _, _ = await _login_with_cookies()
    try:
        login = await client.post("/api/v1/auth/login",
                                  json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD})
        token = login.json()["access_token"]
        r = await client.post("/api/v1/auth/logout", json={},
                              headers={"authorization": f"Bearer {token}",
                                       "origin": FOREIGN_ORIGIN})
        assert r.status_code == 403, "смешанный поток обязан проходить проверку CSRF"
    finally:
        await client.aclose()


async def test_safe_methods_are_not_blocked():
    client, _, _ = await _login_with_cookies()
    try:
        r = await client.get("/health", headers={"origin": FOREIGN_ORIGIN})
        assert r.status_code == 200
    finally:
        await client.aclose()