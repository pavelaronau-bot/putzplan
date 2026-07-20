"""Доменные объекты слоя приложения. Не привязаны к транспортному слою."""
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class Actor:
    """Аутентифицированный пользователь текущего запроса."""
    user_id: UUID
    company_id: UUID
    role: str
    session_id: UUID
    permissions: frozenset[str] = field(default_factory=frozenset)

    def can(self, permission: str) -> bool:
        return permission in self.permissions


@dataclass(frozen=True)
class AuthenticatedUser:
    id: UUID
    company_id: UUID
    role_key: str
    status: str
    password_hash: str | None
    failed_attempts: int
    locked_until: datetime | None
    must_change_password: bool


@dataclass(frozen=True)
class SessionInfo:
    id: UUID
    user_id: UUID
    company_id: UUID
    role_key: str
    status: str
    revoked_at: datetime | None
    expires_at: datetime
