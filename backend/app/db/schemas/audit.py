from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AuditEntryOut(BaseModel):
    chain_seq: int = Field(examples=[42])
    id: int
    server_time: datetime
    request_id: str | None
    user_id: UUID | None
    actor_role: str | None
    action: str = Field(examples=["LOGIN_SUCCESS"])
    entity: str | None
    entity_id: UUID | None
    reason: str | None
    http_status: int | None
    metadata_before: dict[str, Any] | None = None
    metadata_after: dict[str, Any] | None = None
