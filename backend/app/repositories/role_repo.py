"""Роли и права компании."""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _require_row(row, message: str = "запрос не вернул строку"):
    """SQL-функции ниже всегда возвращают ровно одну строку; None означает
    нарушение контракта БД и должно падать явно, а не превращаться в None."""
    if row is None:
        raise RuntimeError(message)
    return row


class RoleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_roles(self, company_id: UUID) -> list[dict]:
        rows = (await self.session.execute(text("""
            SELECT r.id, r.key, r.name, r.description, r.is_system,
                   count(rp.permission_id)::int AS permissions_count
              FROM roles r LEFT JOIN role_permissions rp ON rp.role_id = r.id
             WHERE r.company_id IS NULL OR r.company_id = :c
             GROUP BY r.id ORDER BY r.is_system DESC, r.name"""),
            {"c": str(company_id)})).mappings().all()
        return [dict(r) for r in rows]

    async def get_role(self, role_id: UUID, company_id: UUID) -> dict | None:
        row = (await self.session.execute(text("""
            SELECT r.id, r.key, r.name, r.description, r.is_system,
                   count(rp.permission_id)::int AS permissions_count
              FROM roles r LEFT JOIN role_permissions rp ON rp.role_id = r.id
             WHERE r.id = :id AND (r.company_id IS NULL OR r.company_id = :c)
             GROUP BY r.id"""), {"id": str(role_id), "c": str(company_id)})).mappings().first()
        if not row:
            return None
        perms = (await self.session.execute(text("""
            SELECT p.key FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id
             WHERE rp.role_id = :id ORDER BY p.key"""), {"id": str(role_id)})).scalars().all()
        return {**dict(row), "permissions": list(perms)}

    async def create_role(self, *, company_id: UUID, key: str, name: str,
                          description: str | None, created_by: UUID) -> dict:
        row = (await self.session.execute(text("""
            INSERT INTO roles (company_id, key, name, description, is_system, created_by)
            VALUES (:c, :k, :n, :d, false, :by)
            RETURNING id, key, name, description, is_system, 0 AS permissions_count"""),
            {"c": str(company_id), "k": key, "n": name, "d": description,
             "by": str(created_by)})).mappings().first()
        return dict(_require_row(row))

    async def update_role(self, role_id: UUID, company_id: UUID, *, name: str | None,
                          description: str | None) -> dict | None:
        row = (await self.session.execute(text("""
            UPDATE roles SET name = COALESCE(:n, name), description = COALESCE(:d, description)
             WHERE id = :id AND company_id = :c AND NOT is_system
            RETURNING id, key, name, description, is_system"""),
            {"id": str(role_id), "c": str(company_id), "n": name,
             "d": description})).mappings().first()
        return dict(row) if row else None

    async def set_role_permissions(self, role_id: UUID, keys: list[str]) -> int:
        await self.session.execute(text("DELETE FROM role_permissions WHERE role_id = :r"),
                                   {"r": str(role_id)})
        if not keys:
            return 0
        await self.session.execute(text("""
            INSERT INTO role_permissions (role_id, permission_id, scope)
            SELECT :r, p.id, p.default_scope FROM permissions p WHERE p.key = ANY(:keys)"""),
            {"r": str(role_id), "keys": keys})
        assigned = (await self.session.execute(
            text("SELECT count(*) FROM role_permissions WHERE role_id = :r"),
            {"r": str(role_id)})).scalar_one()
        return int(assigned)

    async def list_permissions(self) -> list[dict]:
        rows = (await self.session.execute(text("""
            SELECT key, module, action, default_scope, description
              FROM permissions ORDER BY module, key"""))).mappings().all()
        return [dict(r) for r in rows]

    async def unknown_permissions(self, keys: list[str]) -> list[str]:
        if not keys:
            return []
        known = set((await self.session.execute(
            text("SELECT key FROM permissions WHERE key = ANY(:k)"), {"k": keys})).scalars().all())
        return sorted(set(keys) - known)

    async def users_with_role(self, role_id: UUID) -> int:
        return int((await self.session.execute(
            text("SELECT count(*) FROM users WHERE role_id = :r AND deleted_at IS NULL"),
            {"r": str(role_id)})).scalar_one())
