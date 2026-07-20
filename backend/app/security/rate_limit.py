"""Ограничение частоты попыток входа.

Два хранилища:
  * memory — счётчик в процессе, годится для одного экземпляра и тестов;
  * redis  — атомарный INCR с TTL, общий для всех реплик.

Выбор задаётся RATE_LIMIT_BACKEND. При недоступности Redis приложение
не «открывается»: запрос отклоняется, а не пропускается.
"""
import logging
import time
from collections import defaultdict
from threading import Lock

from app.core.config import get_settings

settings = get_settings()
log = logging.getLogger("putzplan.ratelimit")

_hits: dict[str, list[float]] = defaultdict(list)
_lock = Lock()
_redis_client = None


def _redis():
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as redis_asyncio
        _redis_client = redis_asyncio.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def check_and_count_async(key: str, limit: int, window_seconds: int) -> bool:
    """True — запрос разрешён. В режиме redis счётчик общий для всех реплик."""
    if settings.rate_limit_backend == "redis":
        try:
            client = _redis()
            redis_key = f"rl:{key}"
            current = await client.incr(redis_key)
            if current == 1:
                await client.expire(redis_key, window_seconds)
            return current <= limit
        except Exception as exc:  # noqa: BLE001
            # fail-closed: недоступность Redis не должна снимать защиту
            log.error("rate_limit_backend_unavailable", extra={"event": "rate_limit"}, exc_info=exc)
            raise
    return check_and_count(key, limit, window_seconds)


def check_and_count(key: str, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    with _lock:
        fresh = [t for t in _hits[key] if now - t < window_seconds]
        fresh.append(now)
        _hits[key] = fresh
        return len(fresh) <= limit


def reset(key: str | None = None) -> None:
    with _lock:
        if key is None:
            _hits.clear()
        else:
            _hits.pop(key, None)


async def reset_async(key: str | None = None) -> None:
    reset(key)
    if settings.rate_limit_backend == "redis":
        try:
            client = _redis()
            if key:
                await client.delete(f"rl:{key}")
            else:
                async for k in client.scan_iter("rl:*"):
                    await client.delete(k)
        except Exception as exc:  # noqa: BLE001
            log.warning("rate_limit_reset_failed", exc_info=exc)
