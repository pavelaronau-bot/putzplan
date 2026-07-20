from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

UserStatus = Literal["invited", "active", "temporarily_blocked", "on_leave",
                     "sick", "password_reset", "terminated", "archived"]


class UserOut(BaseModel):
    id: UUID
    email: EmailStr | None
    phone: str | None
    full_name: str | None
    position: str | None
    status: UserStatus
    role: str
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr = Field(examples=["neu@demo.putzplan.de"])
    full_name: str = Field(min_length=2, max_length=120, examples=["Anna Müller"])
    role: str = Field(examples=["dispatcher"])
    position: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    password: str | None = Field(default=None, min_length=12, max_length=128,
                                 description="Если не задан, пользователь создаётся в статусе invited")


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    position: str | None = Field(default=None, max_length=120)
    phone: str | None = Field(default=None, max_length=40)
    role: str | None = None


class DeactivateRequest(BaseModel):
    reason: str = Field(min_length=4, max_length=500, examples=["расторжение договора"])


class SessionOut(BaseModel):
    id: UUID
    ip: str | None
    user_agent: str | None
    created_at: datetime
    last_seen_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None
    is_current: bool = False
