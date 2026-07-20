"""Защита от CSRF для эндпоинтов, работающих по cookie.

Два независимых слоя:
  1. Origin или Referer обязаны совпадать со списком разрешённых источников.
  2. Double-submit token: значение из cookie должно совпасть с заголовком.

SameSite=Strict остаётся третьим слоем, но единственным не является.
Освобождение действует только для подтверждённого Bearer-flow: наличие
заголовка Authorization само по себе не отменяет проверку, если запрос
одновременно принёс refresh-cookie.
"""
import hmac
import secrets
from urllib.parse import urlparse

from fastapi import Request

from app.core.config import get_settings
from app.core.errors import Forbidden

settings = get_settings()
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def _origin_allowed(request: Request) -> tuple[bool, str]:
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    source = origin or referer
    if not source:
        # Ни Origin, ни Referer: для cookie-flow это подозрительно
        return False, "нет заголовков Origin и Referer"
    parsed = urlparse(source)
    normalized = f"{parsed.scheme}://{parsed.netloc}"
    if normalized in settings.cors_list:
        return True, ""
    return False, f"источник {normalized} не входит в список разрешённых"


def verify_csrf(request: Request) -> None:
    """Бросает 403, если cookie-запрос не проходит проверку CSRF."""
    if request.method.upper() in SAFE_METHODS:
        return

    has_refresh_cookie = settings.refresh_cookie_name in request.cookies
    authorization = request.headers.get("authorization", "")
    bearer_only = authorization.lower().startswith("bearer ") and not has_refresh_cookie

    if bearer_only:
        # Токен передаётся заголовком, браузер не подставит его автоматически
        return
    if not has_refresh_cookie:
        return

    allowed, reason = _origin_allowed(request)
    if not allowed:
        raise Forbidden(f"CSRF: {reason}", code="csrf_origin_rejected")

    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get(CSRF_HEADER)
    if not cookie_token or not header_token:
        raise Forbidden("CSRF: отсутствует токен двойной отправки", code="csrf_token_missing")
    if not hmac.compare_digest(cookie_token, header_token):
        raise Forbidden("CSRF: токен не совпадает", code="csrf_token_mismatch")
