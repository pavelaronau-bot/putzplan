"""Access-токен JWT и refresh-токен.

Refresh хранится в базе только как SHA-256 хеш: утечка таблицы сессий
не даёт возможности предъявить токен.
"""
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt

from app.core.config import get_settings

settings = get_settings()


@dataclass(frozen=True)
class AccessClaims:
    user_id: UUID
    company_id: UUID
    role: str
    session_id: UUID
    expires_at: datetime


def create_access_token(user_id: UUID, company_id: UUID, role: str, session_id: UUID) -> tuple[str, int]:
    now = datetime.now(UTC)
    exp = now + timedelta(seconds=settings.access_ttl_seconds)
    payload = {
        "sub": str(user_id), "cid": str(company_id), "role": role,
        "sid": str(session_id), "iat": int(now.timestamp()), "exp": int(exp.timestamp()),
        "typ": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, settings.access_ttl_seconds


def decode_access_token(token: str) -> AccessClaims | None:
    try:
        # Список алгоритмов задан явно: подделка заголовка alg (в том числе "none")
        # приводит к отказу, а не к принятию неподписанного токена.
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
                             options={"require": ["exp", "iat", "sub", "cid", "sid"]})
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != "access":
        return None
    try:
        return AccessClaims(
            user_id=UUID(payload["sub"]), company_id=UUID(payload["cid"]),
            role=payload["role"], session_id=UUID(payload["sid"]),
            expires_at=datetime.fromtimestamp(payload["exp"], UTC),
        )
    except (KeyError, ValueError):
        return None


def new_refresh_token() -> tuple[str, str]:
    """Возвращает пару (значение для клиента, хеш для базы)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
