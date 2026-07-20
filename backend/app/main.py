"""Точка входа FastAPI: middleware, обработчики ошибок, роутеры."""
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1 import audit, auth, health, roles, users
from app.core.config import get_settings
from app.core.errors import AppError
from app.observability import metrics
from app.observability.logging import configure_logging

settings = get_settings()
log = logging.getLogger("putzplan.http")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    log.info("startup", extra={"event": "startup"})
    yield
    from app.db.session import close_engines
    await close_engines()
    log.info("shutdown", extra={"event": "shutdown"})


app = FastAPI(
    title=settings.app_name, version=settings.app_version, lifespan=lifespan,
    description="Sprint 1: аутентификация, контекст арендатора, пользователи, роли, права, журнал.",
    openapi_url="/openapi.json", docs_url="/docs", redoc_url=None,
)

app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_host_list)
app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["authorization", "content-type", "x-request-id", "x-csrf-token"],
    expose_headers=["x-request-id"],
)


# Идентификатор запроса приходит извне, поэтому ограничен по длине и формату:
# иначе он попадает в логи и позволяет их засорять или подделывать строки.
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@app.middleware("http")
async def request_context(request: Request, call_next):
    incoming = request.headers.get("x-request-id")
    request_id = (incoming if incoming and REQUEST_ID_PATTERN.match(incoming)
                  else f"req_{uuid.uuid4().hex[:12]}")
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        metrics.inc("http.5xx")
        log.exception("unhandled_error", extra={"request_id": request_id,
                                                "path": request.url.path})
        return JSONResponse(status_code=500, headers={"x-request-id": request_id},
                            content={"code": "internal_error", "message": "Внутренняя ошибка",
                                     "request_id": request_id, "details": []})
    duration = (time.perf_counter() - started) * 1000
    metrics.observe_latency(duration)
    metrics.inc("http.requests")
    if response.status_code >= 500:
        metrics.inc("http.5xx")
    elif response.status_code >= 400:
        metrics.inc("http.4xx")
    response.headers["x-request-id"] = request_id
    response.headers["cache-control"] = "no-store"
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
    response.headers["x-frame-options"] = "DENY"
    response.headers["permissions-policy"] = "geolocation=(), camera=(), microphone=(), payment=()"
    response.headers["content-security-policy"] = (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
    log.info("request", extra={"request_id": request_id, "method": request.method,
                              "path": request.url.path, "status": response.status_code,
                              "duration_ms": round(duration, 2)})
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    headers = {"x-request-id": getattr(request.state, "request_id", "")}
    if exc.status_code == 429 and hasattr(exc, "retry_after"):
        headers["retry-after"] = str(exc.retry_after)
    return JSONResponse(status_code=exc.status_code, headers=headers,
                        content={"code": exc.code, "message": exc.message,
                                 "request_id": headers["x-request-id"], "details": exc.details})


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"field": ".".join(str(p) for p in e["loc"][1:]) or None, "message": e["msg"]}
               for e in exc.errors()]
    return JSONResponse(status_code=422,
                        headers={"x-request-id": getattr(request.state, "request_id", "")},
                        content={"code": "validation_error", "message": "Проверьте поля запроса",
                                 "request_id": getattr(request.state, "request_id", ""),
                                 "details": details})


app.include_router(health.router)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(roles.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
