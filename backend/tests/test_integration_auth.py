"""Интеграционные тесты аутентификации на реальной PostgreSQL."""
from httpx import AsyncClient

from tests.conftest import (
    DISPATCHER_EMAIL,
    DISPATCHER_PASSWORD,
    OWNER_EMAIL,
    OWNER_PASSWORD,
    auth,
    browser_headers,
)


async def test_health_and_readiness(client: AsyncClient):
    assert (await client.get("/health")).json()["status"] == "ok"
    ready = (await client.get("/ready")).json()
    assert ready["status"] == "ready"
    assert ready["checks"]["db_runtime"] == "ok"
    assert ready["checks"]["db_audit"] == "ok"


async def test_login_success_sets_httponly_cookie(client: AsyncClient):
    r = await client.post("/api/v1/auth/login",
                          json={"email": OWNER_EMAIL, "password": OWNER_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 900
    assert body["refresh_token"] is None, "refresh отдаётся только в HttpOnly-cookie"
    cookie = r.headers.get("set-cookie", "")
    assert "httponly" in cookie.lower() and "samesite=strict" in cookie.lower()


async def test_wrong_password_and_unknown_user_are_indistinguishable(client: AsyncClient):
    wrong = await client.post("/api/v1/auth/login",
                              json={"email": OWNER_EMAIL, "password": "falsch12345678"})
    unknown = await client.post("/api/v1/auth/login",
                                json={"email": "niemand@demo.putzplan.de", "password": "falsch12345678"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["code"] == unknown.json()["code"] == "invalid_credentials"
    assert wrong.json()["message"] == unknown.json()["message"]


async def test_protected_endpoint_requires_token(client: AsyncClient):
    r = await client.get("/api/v1/users")
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
    assert r.headers.get("x-request-id")


async def test_me_returns_permissions(client: AsyncClient, owner_token: str):
    r = await client.get("/api/v1/me", headers=auth(owner_token))
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "super_admin"
    keys = {p["key"] for p in body["permissions"]}
    assert {"users.read", "users.create", "roles.read", "audit.read"} <= keys


async def test_refresh_rotation_and_reuse_detection(client: AsyncClient):
    """Ротация, штатная гонка и настоящее повторное использование — разные случаи.

    Повтор сразу после ротации считается гонкой клиента и семейство не рвёт.
    Тот же повтор за пределами grace-window означает кражу токена.
    """
    login = await client.post("/api/v1/auth/login",
                              json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD})
    first_cookie = login.cookies.get("putzplan_refresh")
    assert first_cookie

    rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_cookie},
                                headers=browser_headers(client))
    assert rotated.status_code == 200
    second_cookie = rotated.cookies.get("putzplan_refresh")
    assert second_cookie and second_cookie != first_cookie

    # Повтор в пределах окна — штатная гонка
    race = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_cookie},
                             headers=browser_headers(client))
    assert race.status_code == 409 and race.json()["code"] == "refresh_race"

    # Преемник продолжает работать: гонка не отзывает семейство
    still_valid = await client.post("/api/v1/auth/refresh", json={"refresh_token": second_cookie},
                                    headers=browser_headers(client))
    assert still_valid.status_code == 200, "штатная гонка не должна ломать цепочку"
    third_cookie = still_valid.cookies.get("putzplan_refresh")

    # Сдвигаем момент замены в прошлое: теперь повтор — это кража
    from sqlalchemy import text

    from app.db.session import system_session
    from app.security.tokens import hash_refresh_token
    async with system_session() as session:
        await session.execute(text("""
            UPDATE sessions SET rotated_at = now() - interval '10 minutes'
             WHERE refresh_token_hash = :h"""), {"h": hash_refresh_token(second_cookie)})

    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": second_cookie},
                               headers=browser_headers(client))
    assert reused.status_code == 409 and reused.json()["code"] == "refresh_reuse"

    after_break = await client.post("/api/v1/auth/refresh", json={"refresh_token": third_cookie},
                                    headers=browser_headers(client))
    assert after_break.status_code in (401, 409), "после кражи семейство должно быть отозвано"


async def test_logout_revokes_session_immediately(client: AsyncClient):
    login = await client.post("/api/v1/auth/login",
                              json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD})
    token = login.json()["access_token"]
    refresh = login.cookies.get("putzplan_refresh")
    assert (await client.get("/api/v1/me", headers=auth(token))).status_code == 200

    await client.post("/api/v1/auth/logout", json={"refresh_token": refresh},
                      headers=browser_headers(client))
    after = await client.get("/api/v1/me", headers=auth(token))
    assert after.status_code == 401 and after.json()["code"] == "session_revoked"


async def test_logout_all_revokes_every_session(client: AsyncClient):
    tokens = []
    for _ in range(2):
        r = await client.post("/api/v1/auth/login",
                              json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD})
        tokens.append(r.json()["access_token"])
    r = await client.post("/api/v1/auth/logout-all", json={},
                          headers={**auth(tokens[-1]), **browser_headers(client)})
    assert r.status_code == 200 and r.json()["details"]["revoked"] >= 2
    for token in tokens:
        assert (await client.get("/api/v1/me", headers=auth(token))).status_code == 401


async def test_rate_limit_on_login(client: AsyncClient, monkeypatch):
    import app.services.auth_service as auth_service
    from app.security import rate_limit
    rate_limit.reset()
    monkeypatch.setattr(auth_service.settings, "login_rate_limit", 3)
    codes = []
    for _ in range(5):
        r = await client.post("/api/v1/auth/login",
                              json={"email": "brute@demo.putzplan.de", "password": "falsch12345678"})
        codes.append(r.status_code)
    assert 429 in codes, f"ожидался отказ по лимиту, получено {codes}"
    rate_limit.reset()


async def test_validation_error_shape(client: AsyncClient):
    r = await client.post("/api/v1/auth/login", json={"email": "не-адрес", "password": "x"})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "validation_error" and body["request_id"]
    assert body["details"] and body["details"][0]["field"] == "email"
