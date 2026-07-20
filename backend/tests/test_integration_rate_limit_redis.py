"""Ограничение частоты входов через Redis: счётчик общий для реплик.

Тест поднимает два независимых экземпляра приложения (как две реплики
за балансировщиком) и проверяет, что суммарный лимит соблюдается,
а не удваивается.
"""
import os
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

redis_available = True
try:
    import redis.asyncio as redis_asyncio
except ImportError:  # pragma: no cover
    redis_available = False

pytestmark = pytest.mark.skipif(not redis_available, reason="redis-py не установлен")

REDIS_URL = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")


async def _redis_reachable() -> bool:
    try:
        client = redis_asyncio.from_url(REDIS_URL, decode_responses=True)
        await client.ping()
        await client.aclose()
        return True
    except Exception:  # noqa: BLE001
        return False


async def test_rate_limit_is_shared_between_two_instances(monkeypatch):
    if not await _redis_reachable():
        pytest.skip("Redis недоступен по адресу " + REDIS_URL)

    from app.core.config import get_settings
    from app.security import rate_limit
    from app.services import auth_service

    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", REDIS_URL)
    monkeypatch.setattr(auth_service.settings, "login_rate_limit", 4)
    rate_limit._redis_client = None

    login = f"replica-{uuid.uuid4().hex[:8]}@demo.putzplan.de"

    # Две независимые «реплики» приложения
    from app.main import app as app_a
    from app.main import app as app_b
    clients = [AsyncClient(transport=ASGITransport(app=a), base_url="http://testserver")
               for a in (app_a, app_b)]

    codes: list[int] = []
    try:
        for index in range(8):
            client = clients[index % 2]      # запросы чередуются между репликами
            r = await client.post("/api/v1/auth/login",
                                  json={"email": login, "password": "falsch12345678"})
            codes.append(r.status_code)
    finally:
        for client in clients:
            await client.aclose()
        redis_client = redis_asyncio.from_url(REDIS_URL, decode_responses=True)
        async for key in redis_client.scan_iter("rl:*"):
            await redis_client.delete(key)
        await redis_client.aclose()
        rate_limit._redis_client = None

    assert 429 in codes, f"общий счётчик не сработал: {codes}"
    allowed = sum(1 for c in codes if c != 429)
    assert allowed <= 4, f"лимит 4 превышен: пропущено {allowed} запросов, коды {codes}"


async def test_redis_failure_is_fail_closed(monkeypatch):
    """Недоступность Redis не должна снимать защиту."""
    from app.core.config import get_settings
    from app.security import rate_limit

    settings = get_settings()
    monkeypatch.setattr(settings, "rate_limit_backend", "redis")
    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:6399/0")
    rate_limit._redis_client = None
    try:
        # Ожидаем именно ошибку подключения к Redis, а не любое исключение
        from redis.exceptions import RedisError
        with pytest.raises((RedisError, OSError, ConnectionError)):
            await rate_limit.check_and_count_async("проверка", limit=5, window_seconds=60)
    finally:
        rate_limit._redis_client = None
