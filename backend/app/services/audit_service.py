"""Запись в журнал через отдельное соединение роли putzplan_audit.

Секреты в журнал не попадают: полезная нагрузка чистится redact().
Ошибка записи журнала не роняет бизнес-операцию, но логируется как ошибка.
"""
import logging
from typing import Any
from uuid import UUID

from app.db.session import audit_session
from app.observability import metrics
from app.observability.logging import redact

log = logging.getLogger("putzplan.audit")


async def record(*, company_id: UUID, action: str, request_id: str | None = None,
                 user_id: UUID | None = None, actor_role: str | None = None,
                 entity: str | None = None, entity_id: UUID | None = None,
                 before: dict[str, Any] | None = None, after: dict[str, Any] | None = None,
                 reason: str | None = None, ip: str | None = None,
                 user_agent: str | None = None, http_status: int | None = None) -> dict | None:
    from app.repositories.audit_repo import AuditRepository
    try:
        async with audit_session(company_id) as session:
            entry = await AuditRepository(session).append(
                company_id=company_id, request_id=request_id, user_id=user_id,
                actor_role=actor_role, action=action, entity=entity, entity_id=entity_id,
                before=redact(before) if before else None,
                after=redact(after) if after else None,
                reason=reason, ip=ip, user_agent=user_agent, http_status=http_status)
        metrics.inc(f"audit.{action.lower()}")
        return entry
    except Exception as exc:  # noqa: BLE001 — журнал не должен ронять запрос
        metrics.inc("audit.write_failed")
        log.error("audit_write_failed", extra={"event": action, "request_id": request_id,
                                               "company_id": str(company_id)}, exc_info=exc)
        return None
