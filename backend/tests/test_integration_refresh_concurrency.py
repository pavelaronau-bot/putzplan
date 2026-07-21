"""Параллельная ротация refresh-токена и разделение гонки с кражей.

Ключевая проверка: после гонки токены победителя обязаны остаться
действительными. Одного лишь кода 409 у проигравших недостаточно.
"""
import asyncio
import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.session import system_session
from app.main import app
from app.security.tokens import decode_access_token, hash_refresh_token
from tests.conftest import COMPANY_A, DISPATCHER_EMAIL, DISPATCHER_PASSWORD, auth


def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")


async def login() -> tuple[str, str]:
    """Возвращает (access_token, raw_refresh_token)."""
    async with client() as c:
        r = await c.post("/api/v1/auth/login",
                         json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD})
        assert r.status_code == 200, r.text
        return r.json()["access_token"], r.cookies.get("putzplan_refresh")


async def refresh(raw: str) -> tuple[int, dict, str | None]:
    async with client() as c:
        r = await c.post("/api/v1/auth/refresh", json={"refresh_token": raw})
        return r.status_code, r.json(), r.cookies.get("putzplan_refresh")


async def me(access: str) -> int:
    async with client() as c:
        return (await c.get("/api/v1/me", headers=auth(access))).status_code


async def test_parallel_refresh_winner_keeps_valid_tokens():
    """10 параллельных запросов: ровно один получает 200, и после завершения
    всех остальных его access и refresh остаются рабочими."""
    _, token = await login()

    results = await asyncio.gather(*[refresh(token) for _ in range(10)])
    winners = [(body, cookie) for status, body, cookie in results if status == 200]
    losers = [(status, body) for status, body, _ in results if status != 200]

    assert len(winners) == 1, f"победитель должен быть один, коды: {[s for s, _, _ in results]}"
    assert len(losers) == 9
    assert all(status == 409 for status, _ in losers)
    assert {body["code"] for _, body in losers} == {"refresh_race"}, \
        "штатная гонка не должна трактоваться как кража"

    winner_body, winner_cookie = winners[0]

    # Главная проверка: токены победителя пережили гонку
    assert await me(winner_body["access_token"]) == 200, \
        "access-токен победителя отозван проигравшими — дефект вернулся"

    status, body, _ = await refresh(winner_cookie)
    assert status == 200, f"refresh победителя должен работать, получено {status}: {body}"


async def test_benign_race_does_not_revoke_family():
    """Гонка не отзывает ни одной сессии семейства."""
    _, token = await login()
    status, _, new_cookie = await refresh(token)
    assert status == 200

    async with system_session() as session:
        family = (await session.execute(text("""
            SELECT token_family_id FROM sessions WHERE refresh_token_hash = :h"""),
            {"h": hash_refresh_token(new_cookie)})).scalar_one()
        alive_before = (await session.execute(text("""
            SELECT count(*) FROM sessions WHERE token_family_id = :f AND revoked_at IS NULL"""),
            {"f": str(family)})).scalar_one()

    status, body, _ = await refresh(token)          # повтор старого токена сразу
    assert status == 409 and body["code"] == "refresh_race"

    async with system_session() as session:
        alive_after = (await session.execute(text("""
            SELECT count(*) FROM sessions WHERE token_family_id = :f AND revoked_at IS NULL"""),
            {"f": str(family)})).scalar_one()
    assert alive_after == alive_before, "штатная гонка отозвала живые сессии"


async def test_real_reuse_after_grace_window_revokes_family():
    """Повтор заменённого токена вне grace-window — кража: семейство отзывается."""
    _, token = await login()
    status, _, new_cookie = await refresh(token)
    assert status == 200

    # Сдвигаем отметку замены в прошлое: имитируем истёкшее окно
    async with system_session() as session:
        await session.execute(text("""
            UPDATE sessions SET rotated_at = now() - interval '10 minutes'
             WHERE refresh_token_hash = :h"""), {"h": hash_refresh_token(token)})

    status, body, _ = await refresh(token)
    assert status == 409 and body["code"] == "refresh_reuse", body

    # Преемник тоже отозван
    status, body, _ = await refresh(new_cookie)
    assert status in (401, 409), f"семейство должно быть отозвано, получено {status}: {body}"


async def test_new_access_token_is_bound_to_new_session():
    access_before, token = await login()
    claims_before = decode_access_token(access_before)
    status, body, _ = await refresh(token)
    assert status == 200
    claims_after = decode_access_token(body["access_token"])

    assert claims_after is not None and claims_before is not None
    assert claims_after.session_id != claims_before.session_id, \
        "после ротации access-токен должен указывать на новую сессию"
    assert claims_after.user_id == claims_before.user_id
    assert claims_after.company_id == claims_before.company_id

    from app.db.session import tenant_session
    async with tenant_session(COMPANY_A) as session:
        row = (await session.execute(text("""
            SELECT s.id, s.revoked_at, u.company_id, u.id AS user_id
              FROM sessions s JOIN users u ON u.id = s.user_id
             WHERE s.id = :s"""), {"s": str(claims_after.session_id)})).mappings().one()
    assert row["revoked_at"] is None, "новая сессия не должна быть отозвана"
    assert row["company_id"] == COMPANY_A and row["user_id"] == claims_after.user_id


async def test_old_session_revocation_does_not_touch_new_one():
    _, token = await login()
    status, body, _ = await refresh(token)
    assert status == 200
    claims = decode_access_token(body["access_token"])

    async with system_session() as session:
        old = (await session.execute(text("""
            SELECT revoked_at, revoke_reason, replaced_by_session_id
              FROM sessions WHERE refresh_token_hash = :h"""),
            {"h": hash_refresh_token(token)})).mappings().one()
        new = (await session.execute(text("""
            SELECT revoked_at FROM sessions WHERE id = :s"""),
            {"s": str(claims.session_id)})).mappings().one()

    assert old["revoked_at"] is not None and old["revoke_reason"] == "rotated"
    assert old["replaced_by_session_id"] == claims.session_id
    assert new["revoked_at"] is None


async def test_logout_after_rotation_revokes_only_current_session():
    _, token = await login()
    status, body, new_cookie = await refresh(token)
    assert status == 200
    access = body["access_token"]

    async with client() as c:
        r = await c.post("/api/v1/auth/logout", json={"refresh_token": new_cookie})
        assert r.status_code == 200
    assert await me(access) == 401, "после выхода сессия должна быть недействительна"


async def test_logout_all_after_rotation_revokes_every_session():
    _, first = await login()
    status, body, _ = await refresh(first)
    assert status == 200
    access_rotated = body["access_token"]

    access_second, _ = await login()

    async with client() as c:
        r = await c.post("/api/v1/auth/logout-all", json={}, headers=auth(access_rotated))
        assert r.status_code == 200, r.text
        assert r.json()["details"]["revoked"] >= 2

    assert await me(access_rotated) == 401
    assert await me(access_second) == 401


async def test_audit_records_race_and_reuse_separately(client, owner_token):
    _, token = await login()
    await refresh(token)
    await refresh(token)                       # гонка в пределах окна

    _, token2 = await login()
    _, _, _ = await refresh(token2)
    async with system_session() as session:
        await session.execute(text("""
            UPDATE sessions SET rotated_at = now() - interval '10 minutes'
             WHERE refresh_token_hash = :h"""), {"h": hash_refresh_token(token2)})
    await refresh(token2)                      # реальная кража

    logs = await client.get("/api/v1/audit-logs?limit=100", headers=auth(owner_token))
    actions = [e["action"] for e in logs.json()["data"]]
    assert "REFRESH_RACE_DETECTED" in actions, "гонка должна фиксироваться отдельным событием"
    assert "REFRESH_REUSE_DETECTED" in actions, "кража должна фиксироваться отдельным событием"
    assert "SESSION_REFRESHED" in actions


async def test_rotation_states_are_exhaustive():
    """Состояние race_lost удалено: под блокировкой строки оно недостижимо."""
    async with system_session() as session:
        source = (await session.execute(text("""
            SELECT prosrc FROM pg_proc WHERE proname = 'auth_rotate_session'"""))).scalar_one()
    assert "race_lost" not in source, "недостижимое состояние осталось в функции"
    for state in ("'race'", "'reuse'", "'rotated'", "'expired'", "'inactive_user'", "'not_found'"):
        assert state in source, f"состояние {state} отсутствует"


async def test_unknown_token_is_not_found():
    status, body, _ = await refresh(uuid.uuid4().hex)
    assert status == 401 and body["code"] == "invalid_refresh"
