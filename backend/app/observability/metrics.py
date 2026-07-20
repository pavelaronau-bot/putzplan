"""Минимальные счётчики в памяти: запросы, ошибки, входы, отзывы сессий.
В следующем спринте заменяются на Prometheus-экспортер."""
from collections import Counter
from threading import Lock

_lock = Lock()
_counters: Counter[str] = Counter()
_latency: list[float] = []


def inc(name: str, value: int = 1) -> None:
    with _lock:
        _counters[name] += value


def observe_latency(ms: float) -> None:
    with _lock:
        _latency.append(ms)
        if len(_latency) > 1000:
            del _latency[:500]


def snapshot() -> dict:
    with _lock:
        p95 = 0.0
        if _latency:
            ordered = sorted(_latency)
            p95 = ordered[int(len(ordered) * 0.95) - 1] if len(ordered) > 1 else ordered[0]
        return {"counters": dict(_counters), "latency_p95_ms": round(p95, 2),
                "samples": len(_latency)}
