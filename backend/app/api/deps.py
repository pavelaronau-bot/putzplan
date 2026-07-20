"""Зависимости FastAPI: текущий пользователь и централизованная проверка прав.

Deny by default: без явного права доступ запрещён. Отзыв сессии действует
немедленно — при каждом запросе проверяется, что сессия ещё активна.
"""
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, Request

from app.core.errors import Forbidden, Unauthorized
from app.db.session import system_session
from app.domain.models import Actor
from app.observability import metrics
from app.repositories.auth_repo import AuthRepository
from app.security.tokens import decode_access_token
from app.services import audit_service

# Причины отказа, которые возвращает auth_verify_request
_UNAUTHORIZED_REASONS = {"session_not_found", "session_revoked", "session_expired",
                         "user_mismatch", "user_not_found", "company_mismatch"}


async def get_actor(request: Request) -> Actor:
    """Проверка запроса выполняется одной функцией БД: сессия активна,
    принадлежит пользователю из токена, пользователь активен и состоит
    в той же компании. Роль и права берутся из базы, а не из JWT."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise Unauthorized()
    claims = decode_access_token(header[7:])
    if claims is None:
        raise Unauthorized("Токен недействителен или истёк", code="invalid_token")

    async with system_session() as session:
        repo = AuthRepository(session)
        check = await repo.verify_request(claims.session_id, claims.user_id, claims.company_id)
        if not check.get("valid"):
            reason = check.get("reason") or "unknown"
            metrics.inc(f"auth.rejected.{reason}")
            if reason in _UNAUTHORIZED_REASONS:
                raise Unauthorized("Сессия недействительна", code=reason)
            raise Forbidden("Учётная запись недоступна", code=reason)
        permissions = await repo.load_permissions(claims.user_id)

    # Роль из БД имеет приоритет над значением в токене: изменение роли
    # применяется без ожидания истечения access-токена.
    actor = Actor(user_id=claims.user_id, company_id=claims.company_id,
                  role=check.get("role_key") or claims.role,
                  session_id=claims.session_id, permissions=frozenset(permissions))
    request.state.actor = actor
    return actor


CurrentActor = Annotated[Actor, Depends(get_actor)]


def require(permission: str) -> Callable[..., Coroutine[Any, Any, Actor]]:
    """Фабрика зависимости: требует конкретное право, иначе 403 и запись в журнал."""

    async def dependency(request: Request, actor: CurrentActor) -> Actor:
        if not actor.can(permission):
            metrics.inc("authz.denied")
            await audit_service.record(
                company_id=actor.company_id, user_id=actor.user_id, actor_role=actor.role,
                action="ACCESS_DENIED", entity="permission", reason=f"нет права {permission}",
                ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"), http_status=403,
                request_id=getattr(request.state, "request_id", None))
            raise Forbidden(f"Нет права {permission}", code="forbidden",
                            details=[{"field": "permission", "message": permission}])
        return actor

    return dependency
