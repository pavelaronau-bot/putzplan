from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import audit_engine, runtime_engine
from app.observability import metrics

settings = get_settings()
router = APIRouter(tags=["system"])


@router.get("/health", summary="Liveness: процесс жив")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "version": settings.app_version,
            "env": settings.app_env}


@router.get("/ready", summary="Readiness: доступны PostgreSQL и зависимости")
async def ready(response: Response) -> dict:
    checks: dict[str, object] = {}
    ready_flag = True
    for name, engine in (("db_runtime", runtime_engine), ("db_audit", audit_engine)):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks[name] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks[name] = f"fail: {type(exc).__name__}"
            ready_flag = False
    try:
        async with runtime_engine.connect() as conn:
            value = (await conn.execute(text("SELECT min(days_left) FROM partition_headroom()"))).scalar()
        checks["partitions_days_left"] = int(value) if value is not None else None
    except Exception:  # noqa: BLE001
        checks["partitions_days_left"] = None
    if not ready_flag:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready_flag else "not_ready", "checks": checks}


@router.get("/metrics-lite", summary="Счётчики приложения (внутренний эндпоинт)")
async def metrics_lite() -> dict:
    return metrics.snapshot()
