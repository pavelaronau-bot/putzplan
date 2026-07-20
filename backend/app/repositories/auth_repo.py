"""Доступ к данным аутентификации.

Вход выполняется до появления контекста арендатора, поэтому используются
узкие SECURITY DEFINER-функции базы (auth_find_user и другие), а не
выдача рабочей роли права BYPASSRLS.
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import AuthenticatedUser, SessionInfo


def _require_row(row, message: str = "запрос не вернул строку"):
    """SQL-функции ниже всегда возвращают ровно одну строку; None означает
    нарушение контракта БД и должно падать явно, а не превращаться в None."""
    if row is None:
        raise RuntimeError(message)
    return row


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_user_by_login(self, login: str) -> AuthenticatedUser | None:
        row = (await self.session.execute(
            text("SELECT * FROM auth_find_user(:login)"), {"login": login})).mappings().first()
        if not row:
            return None
        return AuthenticatedUser(
            id=row["id"], company_id=row["company_id"], role_key=row["role_key"],
            status=row["status"], password_hash=row["password_hash"],
            failed_attempts=row["failed_attempts"], locked_until=row["locked_until"],
            must_change_password=row["must_change_password"],
        )

    async def register_failure(self, user_id: UUID, max_attempts: int, lock_minutes: int) -> tuple[int, bool]:
        row = (await self.session.execute(
            text("SELECT * FROM auth_register_failure(:u, :m, :l)"),
            {"u": str(user_id), "m": max_attempts, "l": lock_minutes})).mappings().first()
        row = _require_row(row)
        return int(row["failed"]), bool(row["locked"])

    async def register_success(self, user_id: UUID) -> None:
        await self.session.execute(text("SELECT auth_register_success(:u)"), {"u": str(user_id)})

    async def record_attempt(self, *, company_id: UUID | None, user_id: UUID | None, login: str,
                             ip: str | None, user_agent: str | None, success: bool,
                             reason: str | None) -> None:
        await self.session.execute(
            text("SELECT auth_record_attempt(:c, :u, :login, CAST(:ip AS inet), :ua, :ok, :reason)"),
            {"c": str(company_id) if company_id else None,
             "u": str(user_id) if user_id else None, "login": login[:200],
             "ip": ip, "ua": (user_agent or "")[:300], "ok": success, "reason": reason})

    async def create_session(self, *, user_id: UUID, token_hash: str, ip: str | None,
                             user_agent: str | None, expires_at: datetime) -> UUID:
        row = (await self.session.execute(text("""
            INSERT INTO sessions (user_id, refresh_token_hash, ip, user_agent, expires_at, last_seen_at)
            VALUES (:u, :h, CAST(:ip AS inet), :ua, :exp, now())
            RETURNING id"""),
            {"u": str(user_id), "h": token_hash, "ip": ip,
             "ua": (user_agent or "")[:300], "exp": expires_at})).mappings().first()
        return _require_row(row)["id"]

    async def find_session_by_token(self, token_hash: str) -> SessionInfo | None:
        row = (await self.session.execute(
            text("SELECT * FROM auth_session_lookup(:h)"), {"h": token_hash})).mappings().first()
        if not row:
            return None
        return SessionInfo(
            id=row["session_id"], user_id=row["user_id"], company_id=row["company_id"],
            role_key=row["role_key"], status=row["status"],
            revoked_at=row["revoked_at"], expires_at=row["expires_at"])

    async def revoke_session(self, session_id: UUID, reason: str) -> None:
        await self.session.execute(text("""
            UPDATE sessions SET revoked_at = now(), revoke_reason = :r
             WHERE id = :s AND revoked_at IS NULL"""), {"s": str(session_id), "r": reason})

    async def rotate_session(self, *, old_hash: str, new_hash: str, ip: str | None,
                             user_agent: str | None, ttl_days: int) -> dict:
        """Атомарная ротация: lookup, проверка, отзыв и создание — одной операцией
        под блокировкой строки. Параллельные запросы получают race_lost или reuse."""
        row = (await self.session.execute(
            text("SELECT * FROM auth_rotate_session(:old, :new, CAST(:ip AS inet), :ua, :ttl)"),
            {"old": old_hash, "new": new_hash, "ip": ip,
             "ua": (user_agent or "")[:300], "ttl": ttl_days})).mappings().first()
        return dict(row) if row else {"result": "not_found"}

    async def revoke_family(self, family_id: UUID, reason: str) -> int:
        row = (await self.session.execute(
            text("SELECT auth_revoke_family(:f, :r) AS n"),
            {"f": str(family_id), "r": reason})).mappings().first()
        return int(_require_row(row)["n"])

    async def verify_request(self, session_id: UUID, user_id: UUID, company_id: UUID) -> dict:
        """Одна проверка на запрос: сессия активна, принадлежит пользователю,
        пользователь активен и состоит в той же компании. Роль берётся из БД."""
        row = (await self.session.execute(
            text("SELECT * FROM auth_verify_request(:s, :u, :c)"),
            {"s": str(session_id), "u": str(user_id), "c": str(company_id)})).mappings().first()
        return dict(row) if row else {"valid": False, "reason": "unknown"}

    async def revoke_all_user_sessions(self, user_id: UUID, reason: str) -> int:
        row = (await self.session.execute(
            text("SELECT auth_revoke_user_sessions(:u, :r) AS n"),
            {"u": str(user_id), "r": reason})).mappings().first()
        return int(_require_row(row)["n"])

    async def load_permissions(self, user_id: UUID) -> dict[str, str]:
        """Права роли плюс индивидуальные grant/deny. Deny имеет приоритет."""
        rows = (await self.session.execute(
            text("SELECT key, scope, source FROM auth_user_permissions(:u)"),
            {"u": str(user_id)})).mappings().all()
        allowed = {r["key"]: r["scope"] or "company" for r in rows if r["source"] != "deny"}
        for r in rows:
            if r["source"] == "deny":
                allowed.pop(r["key"], None)
        return allowed

    async def session_is_active(self, session_id: UUID) -> bool:
        """Немедленная инвалидация: отозванная сессия перестаёт действовать сразу."""
        row = (await self.session.execute(text("""
            SELECT 1 FROM sessions
             WHERE id = :s AND revoked_at IS NULL AND expires_at > now()"""),
            {"s": str(session_id)})).first()
        return row is not None
