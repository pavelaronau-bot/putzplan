"""Параллельная ротация refresh-токена.

Проверяется, что при одновременных запросах ровно один получает новую пару
токенов, остальные детектируют гонку или повтор, а после повторного
использования отзывается всё семейство сессий.
"""
import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import DISPATCHER_EMAIL, DISPATCHER_PASSWORD, auth


async def _login() -> tuple[str, str]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/api/v1/auth/login",
                              json={"email": DISPATCHER_EMAIL, "password": DISPATCHER_PASSWORD})
        assert r.status_code == 200
        return r.json()["access_token"], r.cookies.get("putzplan_refresh")


async def _refresh(token: str) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        return r.status_code, r.json()


async def test_ten_parallel_refresh_requests_produce_single_winner():
    _, refresh_token = await _login()

    results = await asyncio.gather(*[_refresh(refresh_token) for _ in range(10)])
    codes = [status for status, _ in results]
    winners = [body for status, body in results if status == 200]
    losers = [(status, body) for status, body in results if status != 200]

    assert len(winners) == 1, f"новую пару токенов должен получить ровно один запрос, коды: {codes}"
    assert len(losers) == 9

    loser_codes = {body["code"] for _, body in losers}
    assert loser_codes <= {"refresh_race", "refresh_reuse"}, loser_codes
    assert all(status == 409 for status, _ in losers), codes


async def test_reuse_revokes_whole_token_family():
    access, first = await _login()

    status, body = await _refresh(first)
    assert status == 200
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        rotated = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    # Повторное использование первого токена
    assert rotated.status_code == 409 and rotated.json()["code"] == "refresh_reuse"

    # После обнаружения повтора вся цепочка недействительна
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        me = await client.get("/api/v1/me", headers=auth(access))
    assert me.status_code == 401, "access-токен семейства должен перестать действовать"


async def test_reuse_event_is_recorded_in_audit(client, owner_token):
    _, token = await _login()
    await _refresh(token)
    await _refresh(token)

    logs = await client.get("/api/v1/audit-logs?limit=50&action=REFRESH_REUSE_DETECTED",
                            headers=auth(owner_token))
    assert logs.status_code == 200
    entries = logs.json()["data"]
    assert entries, "событие REFRESH_REUSE_DETECTED должно попасть в журнал"
    assert "token_family" in str(entries[0]["metadata_after"])
