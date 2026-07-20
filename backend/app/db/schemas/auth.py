from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr = Field(examples=["owner@demo.putzplan.de"])
    password: str = Field(min_length=1, max_length=256, examples=["Sicher12345!"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "Bearer"  # noqa: S105 — тип токена, не секрет
    expires_in: int = Field(examples=[900])
    refresh_token: str | None = Field(default=None,
                                      description="Отсутствует, если используется HttpOnly-cookie")


class RefreshRequest(BaseModel):
    refresh_token: str | None = Field(default=None, description="Или cookie putzplan_refresh")


class PermissionOut(BaseModel):
    key: str = Field(examples=["users.read"])
    scope: str = Field(examples=["company"])


class MeResponse(BaseModel):
    id: UUID
    company_id: UUID
    email: EmailStr | None
    full_name: str | None
    position: str | None
    status: str
    role: str
    last_login_at: datetime | None
    permissions: list[PermissionOut]
