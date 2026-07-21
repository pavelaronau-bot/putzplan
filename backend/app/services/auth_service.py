"""Сценарии аутентификации: вход, ротация refresh, выход, отзыв сессий."""
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.core.config import get_settings
from app.core.errors import Conflict, Forbidden, Locked, TooManyRequests, Unauthorized
from app.db.session import system_session
from app.domain.models import Actor
from app.observability import metrics
from app.repositories.auth_repo import AuthRepository
from app.security import rate_limit
from app.security.passwords import verify_password
from app.security.tokens import create_access_token, hash_refresh_token, new_refresh_token
from app.services import audit_service

settings = get_settings()
log = logging.getLogger("putzplan.auth")

LOGIN_FAILED_MESSAGE = "Неверный логин или пароль"   # одинаково для несуществующего логина


class LoginResult:
    def __init__(self, access_token: str, expires_in: int, refresh_token: str,
                 user_id: UUID, company_id: UUID, role: str) -> None:
        self.access_token = access_token
        self.expires_in = expires_in
        self.refresh_token = refresh_token
        self.user_id = user_id
        self.company_id = company_id
        self.role = role


async def login(*, email: str, password: str, ip: str | None, user_agent: str | None,
                request_id: str) -> LoginResult:
    for key in (f"ip:{ip}", f"login:{email.lower()}"):
        if not await rate_limit.check_and_count_async(key, settings.login_rate_limit,
                                                      settings.login_rate_window_seconds):
            metrics.inc("login.rate_limited")
            raise TooManyRequests(retry_after=settings.login_rate_window_seconds)

    async with system_session() as session:
        repo = AuthRepository(session)
        user = await repo.find_user_by_login(email)

        if user is None:
            await repo.record_attempt(company_id=None, user_id=None, login=email, ip=ip,
                                      user_agent=user_agent, success=False, reason="unknown_login")
            metrics.inc("login.failed")
            raise Unauthorized(LOGIN_FAILED_MESSAGE, code="invalid_credentials")

        if user.locked_until and user.locked_until > datetime.now(UTC):
            await repo.record_attempt(company_id=user.company_id, user_id=user.id, login=email,
                                      ip=ip, user_agent=user_agent, success=False, reason="locked")
            metrics.inc("login.locked")
            raise Locked()

        if user.status != "active":
            await repo.record_attempt(company_id=user.company_id, user_id=user.id, login=email,
                                      ip=ip, user_agent=user_agent, success=False,
                                      reason=f"status_{user.status}")
            await audit_service.record(company_id=user.company_id, user_id=user.id,
                                       action="LOGIN_FAILED", entity="user", entity_id=user.id,
                                       reason=f"статус {user.status}", ip=ip, user_agent=user_agent,
                                       http_status=403, request_id=request_id)
            metrics.inc("login.blocked_status")
            raise Forbidden("Учётная запись недоступна", code=f"account_{user.status}")

        if not verify_password(user.password_hash, password):
            failed, locked = await repo.register_failure(user.id, settings.max_failed_attempts,
                                                         settings.lock_minutes)
            await repo.record_attempt(company_id=user.company_id, user_id=user.id, login=email,
                                      ip=ip, user_agent=user_agent, success=False,
                                      reason="bad_password")
            await audit_service.record(
                company_id=user.company_id, user_id=user.id,
                action="ACCOUNT_LOCKED" if locked else "LOGIN_FAILED",
                entity="user", entity_id=user.id, reason=f"неверный пароль, попытка {failed}",
                ip=ip, user_agent=user_agent, http_status=401, request_id=request_id)
            metrics.inc("login.failed")
            raise Unauthorized(LOGIN_FAILED_MESSAGE, code="invalid_credentials")

        raw_refresh, token_hash = new_refresh_token()
        expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_ttl_days)
        session_id = await repo.create_session(user_id=user.id, token_hash=token_hash, ip=ip,
                                               user_agent=user_agent, expires_at=expires_at)
        await repo.register_success(user.id)
        await repo.record_attempt(company_id=user.company_id, user_id=user.id, login=email,
                                  ip=ip, user_agent=user_agent, success=True, reason=None)

    access, ttl = create_access_token(user.id, user.company_id, user.role_key, session_id)
    await audit_service.record(company_id=user.company_id, user_id=user.id,
                               actor_role=user.role_key, action="LOGIN_SUCCESS", entity="session",
                               entity_id=session_id, ip=ip, user_agent=user_agent,
                               http_status=200, request_id=request_id)
    metrics.inc("login.success")
    return LoginResult(access, ttl, raw_refresh, user.id, user.company_id, user.role_key)


async def refresh(*, raw_token: str, ip: str | None, user_agent: str | None,
                  request_id: str) -> LoginResult:
    """Ротация refresh-токена.

    Вся работа выполняется одной SQL-функцией под блокировкой строки, поэтому
    при параллельных запросах ровно один получает новую пару токенов.
    Повторное использование отозванного токена рвёт всё семейство сессий.
    """
    token_hash = hash_refresh_token(raw_token)
    raw_next, next_hash = new_refresh_token()

    async with system_session() as session:
        outcome = await AuthRepository(session).rotate_session(
            old_hash=token_hash, new_hash=next_hash, ip=ip, user_agent=user_agent,
            ttl_days=settings.refresh_ttl_days,
            grace_seconds=settings.refresh_grace_seconds)

    result = outcome.get("result")

    if result == "reuse":
        await audit_service.record(
            company_id=outcome["company_id"], user_id=outcome["user_id"],
            actor_role=outcome.get("role_key"), action="REFRESH_REUSE_DETECTED",
            entity="session", entity_id=outcome["session_id"],
            after={"token_family": str(outcome["family_id"]),
                   "revoked_sessions": outcome["revoked_count"]},
            reason="повторное использование отозванного токена: семейство отозвано",
            ip=ip, user_agent=user_agent, http_status=409, request_id=request_id)
        metrics.inc("refresh.reuse_detected")
        raise Conflict("Токен уже использован, все сессии отозваны", code="refresh_reuse")

    if result == "race":
        # Штатная гонка: тот же токен обновлён параллельным запросом секунду назад.
        # Семейство НЕ отзываем — иначе победитель гонки теряет доступ.
        await audit_service.record(
            company_id=outcome["company_id"], user_id=outcome["user_id"],
            actor_role=outcome.get("role_key"), action="REFRESH_RACE_DETECTED",
            entity="session", entity_id=outcome["session_id"],
            after={"replacement_session": str(outcome.get("replacement_session_id")),
                   "token_family": str(outcome["family_id"])},
            reason="параллельное обновление в пределах grace-window: сессии сохранены",
            ip=ip, user_agent=user_agent, http_status=409, request_id=request_id)
        metrics.inc("refresh.race")
        raise Conflict("Токен уже обновлён параллельным запросом, повторите с новым",
                       code="refresh_race")

    if result == "expired":
        raise Unauthorized("Сессия истекла", code="session_expired")
    if result == "inactive_user":
        raise Forbidden("Учётная запись недоступна", code="account_inactive")
    if result != "rotated":
        raise Unauthorized("Сессия не найдена", code="invalid_refresh")

    access, ttl = create_access_token(outcome["user_id"], outcome["company_id"],
                                      outcome["role_key"], outcome["session_id"])
    await audit_service.record(company_id=outcome["company_id"], user_id=outcome["user_id"],
                               actor_role=outcome["role_key"], action="SESSION_REFRESHED",
                               entity="session", entity_id=outcome["session_id"],
                               after={"token_family": str(outcome["family_id"])},
                               ip=ip, user_agent=user_agent, http_status=200,
                               request_id=request_id)
    metrics.inc("refresh.success")
    return LoginResult(access, ttl, raw_next, outcome["user_id"], outcome["company_id"],
                       outcome["role_key"])


async def logout(*, raw_token: str | None, actor: Actor | None, ip: str | None,
                 request_id: str) -> None:
    async with system_session() as session:
        repo = AuthRepository(session)
        if raw_token:
            info = await repo.find_session_by_token(hash_refresh_token(raw_token))
            if info:
                await repo.revoke_session(info.id, "logout")
                await audit_service.record(company_id=info.company_id, user_id=info.user_id,
                                           action="LOGOUT", entity="session", entity_id=info.id,
                                           ip=ip, http_status=200, request_id=request_id)
                metrics.inc("logout")
                return
        if actor:
            await repo.revoke_session(actor.session_id, "logout")
            await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                                       actor_role=actor.role, action="LOGOUT", entity="session",
                                       entity_id=actor.session_id, ip=ip, http_status=200,
                                       request_id=request_id)
            metrics.inc("logout")


async def logout_all(*, actor: Actor, ip: str | None, request_id: str) -> int:
    async with system_session() as session:
        revoked = await AuthRepository(session).revoke_all_user_sessions(actor.user_id, "logout_all")
    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="SESSIONS_REVOKED_ALL",
                               entity="user", entity_id=actor.user_id,
                               after={"revoked": revoked}, ip=ip, http_status=200,
                               request_id=request_id)
    metrics.inc("sessions.revoked_all", revoked)
    return revoked
