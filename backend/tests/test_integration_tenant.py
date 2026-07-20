"""Изоляция арендаторов, RLS и утечка контекста через пул соединений."""
import uuid

import pytest
from sqlalchemy import text

from app.db.session import RuntimeSession, tenant_session
from tests.conftest import COMPANY_A, COMPANY_B, auth


async def test_cross_tenant_user_is_not_visible(client, owner_token, tenant_b_token):
    mine = await client.get("/api/v1/users?limit=100", headers=auth(owner_token))
    other = await client.get("/api/v1/users?limit=100", headers=auth(tenant_b_token))
    assert mine.status_code == other.status_code == 200
    my_ids = {u["id"] for u in mine.json()["data"]}
    other_ids = {u["id"] for u in other.json()["data"]}
    assert my_ids and other_ids
    assert my_ids.isdisjoint(other_ids), "арендаторы не должны видеть пользователей друг друга"


async def test_cross_tenant_direct_access_returns_404(client, owner_token, tenant_b_token):
    other = await client.get("/api/v1/users?limit=1", headers=auth(tenant_b_token))
    foreign_id = other.json()["data"][0]["id"]
    r = await client.get(f"/api/v1/users/{foreign_id}", headers=auth(owner_token))
    assert r.status_code == 404, "чужая запись неотличима от несуществующей"
    assert r.json()["code"] == "not_found"


async def test_company_id_from_body_is_ignored(client, owner_token):
    """company_id не принимается из тела запроса как доверенный источник."""
    payload = {"email": f"inject-{uuid.uuid4().hex[:8]}@demo.putzplan.de",
               "full_name": "Injection Probe", "role": "worker",
               "company_id": str(COMPANY_B)}
    r = await client.post("/api/v1/users", json=payload, headers=auth(owner_token))
    assert r.status_code == 201
    async with tenant_session(COMPANY_A) as session:
        found = (await session.execute(
            text("SELECT company_id FROM users WHERE id = :id"), {"id": r.json()["id"]})).scalar_one()
    assert str(found) == str(COMPANY_A), "company_id берётся только из сессии"


async def test_rls_blocks_query_without_tenant_context():
    """Без app.company_id рабочая роль не видит ни одной строки."""
    async with RuntimeSession() as session:
        async with session.begin():
            count = (await session.execute(text("SELECT count(*) FROM users"))).scalar_one()
    assert count == 0


async def test_tenant_context_does_not_leak_through_pool():
    """SET LOCAL живёт только внутри транзакции: следующее использование
    того же соединения не видит данных предыдущего арендатора."""
    async with tenant_session(COMPANY_A) as session:
        visible = (await session.execute(text("SELECT count(*) FROM users"))).scalar_one()
    assert visible > 0

    async with RuntimeSession() as session:
        async with session.begin():
            leaked_setting = (await session.execute(
                text("SELECT current_setting('app.company_id', true)"))).scalar_one()
            leaked_rows = (await session.execute(text("SELECT count(*) FROM users"))).scalar_one()
    assert leaked_setting in (None, ""), f"контекст утёк: {leaked_setting}"
    assert leaked_rows == 0


async def test_runtime_role_is_not_superuser_and_respects_rls():
    async with RuntimeSession() as session:
        async with session.begin():
            row = (await session.execute(text("""
                SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"""))).first()
    assert row.rolsuper is False and row.rolbypassrls is False


async def test_runtime_role_cannot_write_audit_log():
    from sqlalchemy.exc import ProgrammingError
    with pytest.raises((ProgrammingError, Exception)):
        async with tenant_session(COMPANY_A) as session:
            await session.execute(text("""
                INSERT INTO audit_logs (company_id, action) VALUES (:c, 'ПОПЫТКА')"""),
                {"c": str(COMPANY_A)})


async def test_runtime_role_cannot_hard_delete_soft_deleted_entity():
    from sqlalchemy.exc import ProgrammingError
    with pytest.raises((ProgrammingError, Exception)):
        async with tenant_session(COMPANY_A) as session:
            await session.execute(text("DELETE FROM clients WHERE true"))
