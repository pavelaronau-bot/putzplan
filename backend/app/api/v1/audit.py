from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import require
from app.db.schemas.audit import AuditEntryOut
from app.db.schemas.common import ErrorResponse, Page
from app.db.session import tenant_session
from app.domain.models import Actor
from app.repositories.audit_repo import AuditRepository

router = APIRouter(tags=["audit"])


@router.get("/audit-logs", response_model=Page[AuditEntryOut],
            responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
            summary="Журнал действий компании")
async def list_audit(actor: Annotated[Actor, Depends(require("audit.read"))],
                     limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                     action: str | None = None, user_id: UUID | None = None
                     ) -> Page[AuditEntryOut]:
    async with tenant_session(actor.company_id) as session:
        rows, total = await AuditRepository(session).list_entries(
            actor.company_id, limit=limit, offset=offset, action=action, user_id=user_id)
    next_offset = offset + limit if offset + limit < total else None
    return Page[AuditEntryOut](data=[AuditEntryOut(**r) for r in rows], total=total,
                               limit=limit, offset=offset, next_offset=next_offset)
