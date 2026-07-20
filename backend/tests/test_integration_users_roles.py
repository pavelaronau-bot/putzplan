"""Пользователи, роли, права и журнал: сквозные сценарии."""

from tests.conftest import auth


async def test_user_lifecycle(client, owner_token, unique):
    email = f"lifecycle-{unique}@demo.putzplan.de"
    created = await client.post("/api/v1/users", headers=auth(owner_token), json={
        "email": email, "full_name": "Lebens Zyklus", "role": "dispatcher",
        "password": "Zyklus12345678"})
    assert created.status_code == 201
    user = created.json()
    assert user["status"] == "active" and user["full_name"] == "Lebens Zyklus"

    duplicate = await client.post("/api/v1/users", headers=auth(owner_token), json={
        "email": email, "full_name": "Doppelt", "role": "worker"})
    assert duplicate.status_code == 409 and duplicate.json()["code"] == "email_exists"

    patched = await client.patch(f"/api/v1/users/{user['id']}", headers=auth(owner_token),
                                 json={"position": "Objektleiter", "full_name": "Neuer Name"})
    assert patched.status_code == 200 and patched.json()["position"] == "Objektleiter"

    login = await client.post("/api/v1/auth/login",
                              json={"email": email, "password": "Zyklus12345678"})
    assert login.status_code == 200

    sessions = await client.get(f"/api/v1/users/{user['id']}/sessions", headers=auth(owner_token))
    assert sessions.status_code == 200 and len(sessions.json()) >= 1

    revoked = await client.delete(
        f"/api/v1/users/{user['id']}/sessions/{sessions.json()[0]['id']}", headers=auth(owner_token))
    assert revoked.status_code == 200

    short_reason = await client.post(f"/api/v1/users/{user['id']}/deactivate",
                                     headers=auth(owner_token), json={"reason": "ok"})
    assert short_reason.status_code == 422

    deactivated = await client.post(f"/api/v1/users/{user['id']}/deactivate",
                                    headers=auth(owner_token),
                                    json={"reason": "расторжение договора"})
    assert deactivated.status_code == 200

    blocked = await client.post("/api/v1/auth/login",
                                json={"email": email, "password": "Zyklus12345678"})
    assert blocked.status_code == 403 and blocked.json()["code"] == "account_terminated"


async def test_weak_password_rejected(client, owner_token, unique):
    r = await client.post("/api/v1/users", headers=auth(owner_token), json={
        "email": f"weak-{unique}@demo.putzplan.de", "full_name": "Schwach Pass",
        "role": "worker", "password": "kurz1"})
    assert r.status_code == 422


async def test_deny_by_default_for_dispatcher(client, dispatcher_token, unique):
    for method, path, payload in [
        ("get", "/api/v1/users", None),
        ("get", "/api/v1/audit-logs", None),
        ("post", "/api/v1/users", {"email": f"x-{unique}@demo.putzplan.de",
                                   "full_name": "Nicht Erlaubt", "role": "worker"}),
        ("post", "/api/v1/roles", {"key": f"r{unique}", "name": "R", "permissions": []}),
    ]:
        request = getattr(client, method)
        r = await (request(path, headers=auth(dispatcher_token), json=payload)
                   if payload else request(path, headers=auth(dispatcher_token)))
        assert r.status_code == 403, f"{method.upper()} {path} должен быть запрещён"
        assert r.json()["code"] == "forbidden"


async def test_dispatcher_can_read_own_profile(client, dispatcher_token):
    r = await client.get("/api/v1/me", headers=auth(dispatcher_token))
    assert r.status_code == 200
    keys = {p["key"] for p in r.json()["permissions"]}
    assert "profile.security" in keys and "users.read" not in keys


async def test_role_creation_and_permission_assignment(client, owner_token, unique):
    created = await client.post("/api/v1/roles", headers=auth(owner_token), json={
        "key": f"objektleiter_{unique}", "name": "Objektleiter",
        "description": "Ведёт объекты", "permissions": ["planning.view", "users.read"]})
    assert created.status_code == 201
    role = created.json()
    assert role["permissions_count"] == 2 and role["is_system"] is False

    updated = await client.put(f"/api/v1/roles/{role['id']}/permissions",
                               headers=auth(owner_token),
                               json={"permissions": ["planning.view", "planning.edit", "users.read"]})
    assert updated.status_code == 200 and updated.json()["permissions_count"] == 3

    unknown = await client.put(f"/api/v1/roles/{role['id']}/permissions",
                               headers=auth(owner_token), json={"permissions": ["kein.recht"]})
    assert unknown.status_code == 422 and unknown.json()["code"] == "unknown_permissions"

    renamed = await client.patch(f"/api/v1/roles/{role['id']}", headers=auth(owner_token),
                                 json={"name": "Objektleiter Nord"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Objektleiter Nord"


async def test_system_role_is_protected(client, owner_token):
    roles = (await client.get("/api/v1/roles", headers=auth(owner_token))).json()
    system_role = next(r for r in roles if r["is_system"])
    r = await client.patch(f"/api/v1/roles/{system_role['id']}", headers=auth(owner_token),
                           json={"name": "Взлом"})
    assert r.status_code == 409 and r.json()["code"] == "system_role"


async def test_audit_records_all_required_events(client, owner_token, unique):
    email = f"audit-{unique}@demo.putzplan.de"
    created = await client.post("/api/v1/users", headers=auth(owner_token), json={
        "email": email, "full_name": "Audit Probe", "role": "worker", "password": "Audit12345678"})
    user_id = created.json()["id"]
    await client.patch(f"/api/v1/users/{user_id}", headers=auth(owner_token),
                       json={"position": "Reinigungskraft"})
    await client.post(f"/api/v1/users/{user_id}/deactivate", headers=auth(owner_token),
                      json={"reason": "проверка журнала"})
    await client.post("/api/v1/auth/login", json={"email": email, "password": "falsch12345678"})

    logs = await client.get("/api/v1/audit-logs?limit=100", headers=auth(owner_token))
    assert logs.status_code == 200
    actions = [e["action"] for e in logs.json()["data"]]
    for required in ("LOGIN_SUCCESS", "USER_CREATED", "USER_UPDATED", "USER_DEACTIVATED"):
        assert required in actions, f"событие {required} отсутствует в журнале"

    seqs = [e["chain_seq"] for e in logs.json()["data"]]
    assert seqs == sorted(seqs, reverse=True), "chain_seq должен быть монотонным"

    dump = logs.text
    for secret in ("Audit12345678", "password_hash", "refresh_token", "access_token"):
        assert secret not in dump, f"в журнале обнаружен секрет: {secret}"


async def test_audit_log_is_append_only(client, owner_token):
    import pytest as _pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    from app.db.session import tenant_session
    from tests.conftest import COMPANY_A
    with _pytest.raises((ProgrammingError, DBAPIError, Exception)):
        async with tenant_session(COMPANY_A) as session:
            await session.execute(text("UPDATE audit_logs SET action = 'ПОДМЕНА' WHERE true"))


async def test_audit_chain_is_valid(client, owner_token):
    from sqlalchemy import text

    from app.db.session import tenant_session
    from tests.conftest import COMPANY_A
    async with tenant_session(COMPANY_A) as session:
        problems = (await session.execute(
            text("SELECT count(*) FROM audit_verify_chain(:c)"), {"c": str(COMPANY_A)})).scalar_one()
    assert problems == 0, "хеш-цепочка журнала нарушена"


async def test_pagination_and_sorting(client, owner_token):
    first = await client.get("/api/v1/users?limit=2&offset=0&sort=created_at&order=desc",
                             headers=auth(owner_token))
    assert first.status_code == 200
    body = first.json()
    assert len(body["data"]) <= 2 and body["limit"] == 2 and body["total"] >= 3
    second = await client.get("/api/v1/users?limit=2&offset=2", headers=auth(owner_token))
    assert second.status_code == 200
    assert {u["id"] for u in body["data"]}.isdisjoint({u["id"] for u in second.json()["data"]})


async def test_invalid_sort_column_is_ignored_not_injected(client, owner_token):
    r = await client.get("/api/v1/users?sort=created_at;DROP TABLE users", headers=auth(owner_token))
    assert r.status_code == 200, "недопустимая сортировка не должна доходить до SQL"


async def test_search_parameter_is_not_injectable(client, owner_token):
    """Пользовательский ввод уходит параметром, а не конкатенацией в SQL."""
    payloads = ["'; DROP TABLE users; --", "%' OR '1'='1", "\\'; SELECT 1; --"]
    for payload in payloads:
        r = await client.get("/api/v1/users", params={"search": payload},
                             headers=auth(owner_token))
        assert r.status_code == 200, f"инъекция сломала запрос: {payload}"
        assert r.json()["total"] == 0 or all(
            payload.lower() not in (u["email"] or "").lower() for u in r.json()["data"])

    from sqlalchemy import text

    from app.db.session import tenant_session
    from tests.conftest import COMPANY_A
    async with tenant_session(COMPANY_A) as session:
        alive = (await session.execute(text("SELECT count(*) FROM users"))).scalar_one()
    assert alive > 0, "таблица users должна существовать после попыток инъекции"
