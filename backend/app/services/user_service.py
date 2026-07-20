"""Пользователи компании: список, создание, изменение, деактивация, сессии."""
from uuid import UUID

from app.core.errors import Conflict, Forbidden, NotFound, UnprocessableEntity
from app.db.session import tenant_session
from app.domain.models import Actor
from app.observability import metrics
from app.repositories.user_repo import UserRepository
from app.security.passwords import hash_password, validate_policy
from app.services import audit_service

# Роль владельца не выдаётся никем, кроме владельца, и не снимается с последнего активного
OWNER_ROLE = "super_admin"


async def list_users(actor: Actor, *, limit: int, offset: int, status: str | None,
                     role: str | None, search: str | None, sort: str, order: str):
    async with tenant_session(actor.company_id) as session:
        return await UserRepository(session).list_users(
            limit=limit, offset=offset, status=status, role=role,
            search=search, sort=sort, order=order)


async def get_user(actor: Actor, user_id: UUID) -> dict:
    async with tenant_session(actor.company_id) as session:
        user = await UserRepository(session).get_user(user_id)
    if not user:
        # Чужая компания и несуществующий пользователь неразличимы: 404
        raise NotFound("Пользователь не найден")
    return user


async def create_user(actor: Actor, payload, *, request_id: str, ip: str | None) -> dict:
    if payload.role == OWNER_ROLE and actor.role != OWNER_ROLE:
        raise Forbidden("Роль владельца может назначить только владелец",
                        code="role_escalation_denied")
    if payload.password:
        problems = validate_policy(payload.password)
        if problems:
            raise UnprocessableEntity("Пароль не соответствует политике", code="weak_password",
                                      details=[{"field": "password", "message": p} for p in problems])

    async with tenant_session(actor.company_id) as session:
        repo = UserRepository(session)
        role_id = await repo.get_role_id(payload.role, actor.company_id)
        if not role_id:
            raise UnprocessableEntity("Неизвестная роль", code="unknown_role",
                                      details=[{"field": "role", "message": payload.role}])
        try:
            created = await repo.create_user(
                company_id=actor.company_id, role_id=role_id, email=payload.email,
                full_name=payload.full_name, position=payload.position, phone=payload.phone,
                password_hash=hash_password(payload.password) if payload.password else None,
                status="active" if payload.password else "invited", created_by=actor.user_id)
        except Exception as exc:  # noqa: BLE001
            if "unique" in str(exc).lower() or "23505" in str(exc):
                raise Conflict("Пользователь с таким e-mail уже существует",
                               code="email_exists") from exc
            raise
    created["role"] = payload.role
    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="USER_CREATED", entity="user",
                               entity_id=created["id"],
                               after={"email": payload.email, "role": payload.role,
                                      "status": created["status"]},
                               ip=ip, http_status=201, request_id=request_id)
    metrics.inc("users.created")
    return created


async def update_user(actor: Actor, user_id: UUID, payload, *, request_id: str,
                      ip: str | None) -> dict:
    async with tenant_session(actor.company_id) as session:
        repo = UserRepository(session)
        before = await repo.get_user(user_id)
        if not before:
            raise NotFound("Пользователь не найден")

        role_id = None
        if payload.role and payload.role != before["role"]:
            if payload.role == OWNER_ROLE and actor.role != OWNER_ROLE:
                raise Forbidden("Роль владельца может назначить только владелец",
                                code="role_escalation_denied")
            if user_id == actor.user_id:
                raise Forbidden("Нельзя изменить собственную роль", code="self_role_change_denied")
            if before["role"] == OWNER_ROLE and await repo.count_active_owners() < 2:
                raise Conflict("Нельзя снять роль с единственного активного владельца",
                               code="last_owner")
            role_id = await repo.get_role_id(payload.role, actor.company_id)
            if not role_id:
                raise UnprocessableEntity("Неизвестная роль", code="unknown_role")

        updated = await repo.update_user(
            user_id, full_name=payload.full_name, position=payload.position,
            phone=payload.phone, role_id=role_id, updated_by=actor.user_id)
        if not updated:
            raise NotFound("Пользователь не найден")
        updated["role"] = payload.role or before["role"]

    changed_before = {k: before[k] for k in ("full_name", "position", "phone", "role")
                      if before.get(k) != updated.get(k)}
    changed_after = {k: updated.get(k) for k in changed_before}
    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="USER_UPDATED", entity="user",
                               entity_id=user_id, before=changed_before or None,
                               after=changed_after or None, ip=ip, http_status=200,
                               request_id=request_id)
    metrics.inc("users.updated")
    return updated


async def deactivate_user(actor: Actor, user_id: UUID, reason: str, *, request_id: str,
                          ip: str | None) -> dict:
    if user_id == actor.user_id:
        raise Forbidden("Нельзя деактивировать собственную учётную запись",
                        code="self_deactivation_denied")
    async with tenant_session(actor.company_id) as session:
        repo = UserRepository(session)
        before = await repo.get_user(user_id)
        if not before:
            raise NotFound("Пользователь не найден")
        if before["role"] == OWNER_ROLE and await repo.count_active_owners() < 2:
            raise Conflict("Нельзя деактивировать последнего активного владельца",
                           code="last_owner")
        result = await repo.set_status(user_id, "terminated", reason, actor.user_id)
        if result is None:
            raise NotFound("Пользователь не найден")

    from app.db.session import system_session
    from app.repositories.auth_repo import AuthRepository
    async with system_session() as session:
        revoked = await AuthRepository(session).revoke_all_user_sessions(user_id, "user_disabled")

    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="USER_DEACTIVATED", entity="user",
                               entity_id=user_id, before={"status": before["status"]},
                               after={"status": "terminated", "sessions_revoked": revoked},
                               reason=reason, ip=ip, http_status=200, request_id=request_id)
    metrics.inc("users.deactivated")
    return {**result, "sessions_revoked": revoked}


async def list_sessions(actor: Actor, user_id: UUID) -> list[dict]:
    async with tenant_session(actor.company_id) as session:
        repo = UserRepository(session)
        if not await repo.get_user(user_id):
            raise NotFound("Пользователь не найден")
        sessions = await repo.list_sessions(user_id)
    return [{**s, "is_current": s["id"] == actor.session_id} for s in sessions]


async def revoke_session(actor: Actor, user_id: UUID, session_id: UUID, *, request_id: str,
                         ip: str | None) -> None:
    async with tenant_session(actor.company_id) as session:
        repo = UserRepository(session)
        if not await repo.get_user(user_id):
            raise NotFound("Пользователь не найден")
        ok = await repo.revoke_session_of_user(user_id, session_id, "revoked_by_admin")
    if not ok:
        raise NotFound("Активная сессия не найдена")
    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="SESSION_REVOKED", entity="session",
                               entity_id=session_id, after={"target_user": str(user_id)},
                               ip=ip, http_status=200, request_id=request_id)
    metrics.inc("sessions.revoked")
