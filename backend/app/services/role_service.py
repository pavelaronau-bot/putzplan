"""Роли и права компании. Запрет повышения собственных прав."""
from uuid import UUID

from app.core.errors import Conflict, Forbidden, NotFound, UnprocessableEntity
from app.db.session import tenant_session
from app.domain.models import Actor
from app.observability import metrics
from app.repositories.role_repo import RoleRepository
from app.services import audit_service

# Права владельца не делегируются пользовательским ролям
OWNER_ONLY = {"company.delete", "company.export", "security.manage", "system.settings",
              "roles.manage", "roles.permissions.manage", "api_keys.manage",
              "users.delete", "users.reset_password", "billing.manage", "billing.cancel"}


async def list_roles(actor: Actor) -> list[dict]:
    async with tenant_session(actor.company_id) as session:
        return await RoleRepository(session).list_roles(actor.company_id)


async def get_role(actor: Actor, role_id: UUID) -> dict:
    async with tenant_session(actor.company_id) as session:
        role = await RoleRepository(session).get_role(role_id, actor.company_id)
    if not role:
        raise NotFound("Роль не найдена")
    return role


async def create_role(actor: Actor, payload, *, request_id: str, ip: str | None) -> dict:
    _assert_no_escalation(actor, payload.permissions)
    async with tenant_session(actor.company_id) as session:
        repo = RoleRepository(session)
        unknown = await repo.unknown_permissions(payload.permissions)
        if unknown:
            raise UnprocessableEntity("Неизвестные права", code="unknown_permissions",
                                      details=[{"field": "permissions", "message": k} for k in unknown])
        try:
            role = await repo.create_role(company_id=actor.company_id, key=payload.key,
                                          name=payload.name, description=payload.description,
                                          created_by=actor.user_id)
        except Exception as exc:  # noqa: BLE001
            if "unique" in str(exc).lower() or "23505" in str(exc):
                raise Conflict("Роль с таким ключом уже существует", code="role_exists") from exc
            raise
        count = await repo.set_role_permissions(role["id"], payload.permissions)
        role["permissions_count"] = count
        role["permissions"] = payload.permissions

    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="ROLE_CREATED", entity="role",
                               entity_id=role["id"],
                               after={"key": payload.key, "permissions": payload.permissions},
                               ip=ip, http_status=201, request_id=request_id)
    metrics.inc("roles.created")
    return role


async def update_role(actor: Actor, role_id: UUID, payload, *, request_id: str,
                      ip: str | None) -> dict:
    async with tenant_session(actor.company_id) as session:
        repo = RoleRepository(session)
        before = await repo.get_role(role_id, actor.company_id)
        if not before:
            raise NotFound("Роль не найдена")
        if before["is_system"]:
            raise Conflict("Системную роль изменить нельзя", code="system_role")
        updated = await repo.update_role(role_id, actor.company_id, name=payload.name,
                                         description=payload.description)
        if not updated:
            raise NotFound("Роль не найдена")
        updated["permissions_count"] = before["permissions_count"]

    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="ROLE_UPDATED", entity="role",
                               entity_id=role_id, before={"name": before["name"]},
                               after={"name": updated["name"]}, ip=ip, http_status=200,
                               request_id=request_id)
    metrics.inc("roles.updated")
    return updated


async def set_permissions(actor: Actor, role_id: UUID, keys: list[str], *, request_id: str,
                          ip: str | None) -> dict:
    _assert_no_escalation(actor, keys)
    async with tenant_session(actor.company_id) as session:
        repo = RoleRepository(session)
        before = await repo.get_role(role_id, actor.company_id)
        if not before:
            raise NotFound("Роль не найдена")
        if before["is_system"]:
            raise Conflict("Права системной роли изменить нельзя", code="system_role")
        unknown = await repo.unknown_permissions(keys)
        if unknown:
            raise UnprocessableEntity("Неизвестные права", code="unknown_permissions",
                                      details=[{"field": "permissions", "message": k} for k in unknown])
        count = await repo.set_role_permissions(role_id, keys)
        role = await repo.get_role(role_id, actor.company_id)
        if role is None:
            raise NotFound("Роль не найдена")
        role["permissions_count"] = count

    await audit_service.record(company_id=actor.company_id, user_id=actor.user_id,
                               actor_role=actor.role, action="ROLE_PERMISSIONS_UPDATED",
                               entity="role", entity_id=role_id,
                               before={"permissions": before["permissions"]},
                               after={"permissions": keys}, ip=ip, http_status=200,
                               request_id=request_id)
    metrics.inc("roles.permissions_updated")
    return role


async def list_permissions(actor: Actor) -> list[dict]:
    async with tenant_session(actor.company_id) as session:
        return await RoleRepository(session).list_permissions()


def _assert_no_escalation(actor: Actor, keys: list[str]) -> None:
    """Нельзя выдать роли право, которого нет у самого администратора,
    и нельзя делегировать критические права владельца."""
    forbidden = OWNER_ONLY.intersection(keys)
    if forbidden and actor.role != "super_admin":
        raise Forbidden("Эти права не делегируются", code="permission_not_delegatable",
                        details=[{"field": "permissions", "message": k} for k in sorted(forbidden)])
    missing = [k for k in keys if not actor.can(k)]
    if missing and actor.role != "super_admin":
        raise Forbidden("Нельзя выдать право, которого нет у вас", code="privilege_escalation",
                        details=[{"field": "permissions", "message": k} for k in sorted(missing)])
