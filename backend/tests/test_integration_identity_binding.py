"""Связывание запроса с сессией: деактивация, смена роли, подмена claims."""
import uuid

import pytest
from sqlalchemy import text

from app.db.session import tenant_session
from app.security.tokens import create_access_token
from tests.conftest import COMPANY_A, COMPANY_B, auth


async def test_deactivated_user_loses_access_immediately(client, owner_token, unique):
    email = f"deact-{unique}@demo.putzplan.de"
    created = await client.post("/api/v1/users", headers=auth(owner_token), json={
        "email": email, "full_name": "Deakt User", "role": "dispatcher",
        "password": "Deakt12345678"})
    user_id = created.json()["id"]

    login = await client.post("/api/v1/auth/login",
                              json={"email": email, "password": "Deakt12345678"})
    victim_token = login.json()["access_token"]
    assert (await client.get("/api/v1/me", headers=auth(victim_token))).status_code == 200

    await client.post(f"/api/v1/users/{user_id}/deactivate", headers=auth(owner_token),
                      json={"reason": "проверка немедленного отзыва"})

    # Access-токен ещё не истёк, но пользователь деактивирован
    after = await client.get("/api/v1/me", headers=auth(victim_token))
    assert after.status_code in (401, 403), "деактивация должна действовать немедленно"


async def test_role_change_applies_without_waiting_for_token_expiry(client, owner_token, unique):
    email = f"rolechg-{unique}@demo.putzplan.de"
    created = await client.post("/api/v1/users", headers=auth(owner_token), json={
        "email": email, "full_name": "Rollen Wechsel", "role": "dispatcher",
        "password": "Rolle12345678"})
    user_id = created.json()["id"]

    login = await client.post("/api/v1/auth/login",
                              json={"email": email, "password": "Rolle12345678"})
    token = login.json()["access_token"]

    before = await client.get("/api/v1/users", headers=auth(token))
    assert before.status_code == 403, "у диспетчера нет права users.read"

    await client.patch(f"/api/v1/users/{user_id}", headers=auth(owner_token),
                       json={"role": "admin"})

    after = await client.get("/api/v1/me", headers=auth(token))
    assert after.status_code == 200
    assert after.json()["role"] == "admin", "роль берётся из БД, а не из токена"
    keys = {p["key"] for p in after.json()["permissions"]}
    assert "users.read" in keys


async def test_token_with_foreign_company_claim_is_rejected(client, owner_token):
    """Подмена company_id в claims не даёт доступа к чужому арендатору."""
    me = (await client.get("/api/v1/me", headers=auth(owner_token))).json()
    async with tenant_session(COMPANY_A) as session:
        session_id = (await session.execute(text("""
            SELECT id FROM sessions WHERE user_id = :u AND revoked_at IS NULL
             ORDER BY created_at DESC LIMIT 1"""), {"u": me["id"]})).scalar_one()

    forged, _ = create_access_token(uuid.UUID(me["id"]), COMPANY_B, "super_admin", session_id)
    r = await client.get("/api/v1/users", headers=auth(forged))
    assert r.status_code == 401 and r.json()["code"] == "company_mismatch"


async def test_token_with_foreign_user_claim_is_rejected(client, owner_token):
    me = (await client.get("/api/v1/me", headers=auth(owner_token))).json()
    async with tenant_session(COMPANY_A) as session:
        session_id = (await session.execute(text("""
            SELECT id FROM sessions WHERE user_id = :u AND revoked_at IS NULL
             ORDER BY created_at DESC LIMIT 1"""), {"u": me["id"]})).scalar_one()

    forged, _ = create_access_token(uuid.uuid4(), COMPANY_A, "super_admin", session_id)
    r = await client.get("/api/v1/users", headers=auth(forged))
    assert r.status_code == 401 and r.json()["code"] == "user_mismatch"


async def test_token_with_unknown_session_is_rejected(client, owner_token):
    me = (await client.get("/api/v1/me", headers=auth(owner_token))).json()
    forged, _ = create_access_token(uuid.UUID(me["id"]), COMPANY_A, "super_admin", uuid.uuid4())
    r = await client.get("/api/v1/users", headers=auth(forged))
    assert r.status_code == 401 and r.json()["code"] == "session_not_found"


@pytest.mark.parametrize("algorithm", ["none", "HS512"])
async def test_token_signed_with_other_algorithm_is_rejected(client, algorithm):
    import jwt

    from app.core.config import get_settings
    settings = get_settings()
    payload = {"sub": str(uuid.uuid4()), "cid": str(COMPANY_A), "role": "super_admin",
               "sid": str(uuid.uuid4()), "iat": 0, "exp": 9999999999, "typ": "access"}
    if algorithm == "none":
        token = jwt.encode(payload, key="", algorithm="none")
    else:
        token = jwt.encode(payload, settings.jwt_secret, algorithm="HS512")
    r = await client.get("/api/v1/users", headers=auth(token))
    assert r.status_code == 401, f"токен с алгоритмом {algorithm} должен быть отклонён"


async def test_request_id_is_sanitized(client):
    """Внешний X-Request-ID ограничен по формату: защита от засорения логов."""
    r = await client.get("/health", headers={"x-request-id": "bad id;INJECTED " + "x" * 200})
    assert r.status_code == 200
    returned = r.headers["x-request-id"]
    assert returned.startswith("req_") and len(returned) <= 64
    assert "\n" not in returned


async def test_security_headers_present(client):
    r = await client.get("/health")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert "geolocation=()" in r.headers["permissions-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
