"""Журнал действий: запись отдельной ролью, чтение — обычной."""
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, *, company_id: UUID, request_id: str | None, user_id: UUID | None,
                     actor_role: str | None, action: str, entity: str | None,
                     entity_id: UUID | None, before: dict[str, Any] | None,
                     after: dict[str, Any] | None, reason: str | None, ip: str | None,
                     user_agent: str | None, http_status: int | None) -> dict:
        import json
        row = rows = (await self.session.execute(text(f"""  # nosec B608
            INSERT INTO audit_logs (company_id, request_id, user_id, actor_kind, actor_role,
                                    action, entity, entity_id, before, after, reason,
                                    ip, user_agent, http_status)
            VALUES (:c, :rid, :u, 'user', :role, :action, :entity, :eid,
                    CAST(:before AS jsonb), CAST(:after AS jsonb), :reason,
                    CAST(:ip AS inet), :ua, :status)
            RETURNING id, chain_seq"""),
            {"c": str(company_id), "rid": request_id, "u": str(user_id) if user_id else None,
             "role": actor_role, "action": action, "entity": entity,
             "eid": str(entity_id) if entity_id else None,
             "before": json.dumps(before, ensure_ascii=False) if before else None,
             "after": json.dumps(after, ensure_ascii=False) if after else None,
             "reason": reason, "ip": ip, "ua": (user_agent or "")[:300],
             "status": http_status})).mappings().first()
        if row is None:
            raise RuntimeError("вставка в журнал не вернула строку")
        return dict(row)

    async def list_entries(self, company_id: UUID, *, limit: int, offset: int,
                           action: str | None, user_id: UUID | None) -> tuple[list[dict], int]:
        where = ["company_id = :c"]
        params: dict[str, Any] = {"c": str(company_id), "limit": limit, "offset": offset}
        if action:
            where.append("action = :action")
            params["action"] = action
        if user_id:
            where.append("user_id = :u")
            params["u"] = str(user_id)
        clause = " AND ".join(where)
        # nosec B608: в clause попадают только фиксированные фрагменты из кода,
        # все пользовательские значения передаются параметрами (:status, :q, …)
        rows = (await self.session.execute(text(f"""
            SELECT chain_seq, id, server_time, request_id, user_id, actor_role, action,
                   entity, entity_id, reason, http_status,
                   before AS metadata_before, after AS metadata_after
              FROM audit_logs WHERE {clause}
             ORDER BY chain_seq DESC LIMIT :limit OFFSET :offset"""), params)).mappings().all()
        total = (await self.session.execute(
            text(f"SELECT count(*) FROM audit_logs WHERE {clause}"), params)).scalar_one()  # nosec B608
        return [dict(r) for r in rows], int(total)

    async def verify_chain(self, company_id: UUID) -> list[dict]:
        rows = (await self.session.execute(
            text("SELECT * FROM audit_verify_chain(:c)"), {"c": str(company_id)})).mappings().all()
        return [dict(r) for r in rows]
