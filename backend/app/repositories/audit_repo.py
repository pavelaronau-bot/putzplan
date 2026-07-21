async def create(
    self,
    *,
    company_id: UUID,
    request_id: str,
    user_id: UUID | None,
    actor_role: str,
    action: str,
    entity: str,
    entity_id: str | None,
    before: dict | None,
    after: dict | None,
    reason: str | None,
    ip: str | None,
    user_agent: str | None,
    http_status: int | None,
) -> dict:
    import json

    row = (
        await self.session.execute(
            text(
                """
                INSERT INTO audit_logs (
                    company_id,
                    request_id,
                    user_id,
                    actor_kind,
                    actor_role,
                    action,
                    entity,
                    entity_id,
                    before,
                    after,
                    reason,
                    ip,
                    user_agent,
                    http_status
                )
                VALUES (
                    :c,
                    :rid,
                    :u,
                    'user',
                    :role,
                    :action,
                    :entity,
                    :eid,
                    CAST(:before AS jsonb),
                    CAST(:after AS jsonb),
                    :reason,
                    CAST(:ip AS inet),
                    :ua,
                    :status
                )
                RETURNING id, chain_seq
                """
            ),
            {
                "c": str(company_id),
                "rid": request_id,
                "u": str(user_id) if user_id else None,
                "role": actor_role,
                "action": action,
                "entity": entity,
                "eid": entity_id,
                "before": json.dumps(before) if before is not None else None,
                "after": json.dumps(after) if after is not None else None,
                "reason": reason,
                "ip": ip,
                "ua": (user_agent or "")[:300],
                "status": http_status,
            },
        )
    ).mappings().first()

    if row is None:
        raise RuntimeError("вставка в журнал не вернула строку")

    return dict(row)
