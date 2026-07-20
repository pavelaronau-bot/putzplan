"""Пользователи компании. Все запросы идут под RLS в контексте арендатора."""
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ALLOWED_SORT = {"created_at", "email", "status", "last_login_at", "full_name"}


def _require_row(row, message: str = "запрос не вернул строку"):
    """SQL-функции ниже всегда возвращают ровно одну строку; None означает
    нарушение контракта БД и должно падать явно, а не превращаться в None."""
    if row is None:
        raise RuntimeError(message)
    return row


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_users(self, *, limit: int, offset: int, status: str | None,
                         role: str | None, search: str | None,
                         sort: str, order: str) -> tuple[list[dict], int]:
        # Имя колонки берётся только из белого списка, значения передаются
        # параметрами: конкатенация в SQL здесь безопасна.
        sort_column = sort if sort in ALLOWED_SORT else "created_at"
        direction = "ASC" if order.lower() == "asc" else "DESC"
        where = ["u.deleted_at IS NULL"]
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            where.append("u.status::text = :status")
            params["status"] = status
        if role:
            where.append("r.key = :role")
            params["role"] = role
        if search:
            where.append("(u.email::text ILIKE :q OR u.full_name ILIKE :q OR u.position ILIKE :q)")
            params["q"] = f"%{search}%"
        clause = " AND ".join(where)
        # nosec B608: в clause попадают только фиксированные фрагменты из кода,
        # все пользовательские значения передаются параметрами (:status, :q, …)

        rows = (await self.session.execute(text(f"""
            SELECT u.id, u.email::text AS email, u.phone, u.full_name, u.position,
                   u.status::text AS status, r.key AS role, u.last_login_at, u.created_at
              FROM users u JOIN roles r ON r.id = u.role_id
             WHERE {clause}
             ORDER BY u.{sort_column} {direction} NULLS LAST
             LIMIT :limit OFFSET :offset"""), params)).mappings().all()
        total = (await self.session.execute(text(f"""
            SELECT count(*) AS n FROM users u JOIN roles r ON r.id = u.role_id
             WHERE {clause}"""), params)).scalar_one()
        return [dict(r) for r in rows], int(total)

    async def get_user(self, user_id: UUID) -> dict | None:
        row = (await self.session.execute(text("""
            SELECT u.id, u.email::text AS email, u.phone, u.full_name, u.position,
                   u.status::text AS status, u.status_reason, r.key AS role,
                   u.last_login_at, u.created_at
              FROM users u JOIN roles r ON r.id = u.role_id
             WHERE u.id = :id AND u.deleted_at IS NULL"""), {"id": str(user_id)})).mappings().first()
        return dict(row) if row else None

    async def get_role_id(self, role_key: str, company_id: UUID) -> UUID | None:
        row = (await self.session.execute(text("""
            SELECT id FROM roles
             WHERE key = :k AND (is_system OR company_id = :c) LIMIT 1"""),
            {"k": role_key, "c": str(company_id)})).mappings().first()
        return row["id"] if row else None

    async def create_user(self, *, company_id: UUID, role_id: UUID, email: str, full_name: str,
                          position: str | None, phone: str | None, password_hash: str | None,
                          status: str, created_by: UUID) -> dict:
        row = (await self.session.execute(text("""
            INSERT INTO users (company_id, role_id, email, full_name, position, phone,
                               password_hash, password_changed_at, status, created_by)
            VALUES (:c, :r, :e, :n, :p, :ph, CAST(:hash AS text),
                    CASE WHEN CAST(:hash AS text) IS NULL THEN NULL ELSE now() END,
                    CAST(:st AS user_status), :by)
            RETURNING id, email::text AS email, phone, full_name, position,
                      status::text AS status, last_login_at, created_at"""),
            {"c": str(company_id), "r": str(role_id), "e": email, "n": full_name,
             "p": position, "ph": phone, "hash": password_hash, "st": status,
             "by": str(created_by)})).mappings().first()
        return dict(_require_row(row))

    async def update_user(self, user_id: UUID, *, full_name: str | None, position: str | None,
                          phone: str | None, role_id: UUID | None, updated_by: UUID) -> dict | None:
        row = (await self.session.execute(text("""
            UPDATE users SET
                full_name = COALESCE(:n, full_name),
                position  = COALESCE(:p, position),
                phone     = COALESCE(:ph, phone),
                role_id   = COALESCE(:r, role_id),
                updated_by = :by
             WHERE id = :id AND deleted_at IS NULL
            RETURNING id, email::text AS email, phone, full_name, position,
                      status::text AS status, last_login_at, created_at"""),
            {"id": str(user_id), "n": full_name, "p": position, "ph": phone,
             "r": str(role_id) if role_id else None, "by": str(updated_by)})).mappings().first()
        return dict(row) if row else None

    async def set_status(self, user_id: UUID, status: str, reason: str | None,
                         updated_by: UUID) -> dict | None:
        row = (await self.session.execute(text("""
            UPDATE users SET status = CAST(:st AS user_status), status_reason = :reason, updated_by = :by
             WHERE id = :id AND deleted_at IS NULL
            RETURNING id, status::text AS status, status_reason"""),
            {"id": str(user_id), "st": status, "reason": reason,
             "by": str(updated_by)})).mappings().first()
        return dict(row) if row else None

    async def count_active_owners(self) -> int:
        return int((await self.session.execute(text("""
            SELECT count(*) FROM users u JOIN roles r ON r.id = u.role_id
             WHERE r.key = 'super_admin' AND u.status = 'active' AND u.deleted_at IS NULL"""))).scalar_one())

    async def role_key_of(self, user_id: UUID) -> str | None:
        row = (await self.session.execute(text("""
            SELECT r.key FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = :id"""),
            {"id": str(user_id)})).mappings().first()
        return row["key"] if row else None

    async def list_sessions(self, user_id: UUID) -> list[dict]:
        rows = (await self.session.execute(text("""
            SELECT s.id, host(s.ip) AS ip, s.user_agent, s.created_at, s.last_seen_at,
                   s.expires_at, s.revoked_at
              FROM sessions s JOIN users u ON u.id = s.user_id
             WHERE s.user_id = :u
             ORDER BY s.created_at DESC LIMIT 100"""), {"u": str(user_id)})).mappings().all()
        return [dict(r) for r in rows]

    async def revoke_session_of_user(self, user_id: UUID, session_id: UUID, reason: str) -> bool:
        row = (await self.session.execute(text("""
            UPDATE sessions SET revoked_at = now(), revoke_reason = :r
             WHERE id = :s AND user_id = :u AND revoked_at IS NULL
            RETURNING id"""),
            {"s": str(session_id), "u": str(user_id), "r": reason})).mappings().first()
        return row is not None
