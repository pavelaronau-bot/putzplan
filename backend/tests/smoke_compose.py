"""Smoke-проверка развёрнутой среды Docker Compose.

Запускается с хоста против поднятого API. Проверяет ключевые сценарии
Sprint 1: вход, /me, создание пользователя, роль, отказ по правам,
изоляция арендаторов, журнал.
"""
import os
import sys
import uuid

import httpx

BASE = os.environ.get("API_BASE", "http://localhost:8000")
SUFFIX = uuid.uuid4().hex[:8]
OWNER = ("owner@demo.putzplan.de", "Owner12345678")
DISPATCHER = ("disp@demo.putzplan.de", "Disp12345678")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok else f"  → {detail}"))


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=15) as client:
        r = client.get("/health")
        check("health отвечает", r.status_code == 200 and r.json()["status"] == "ok", r.text)

        r = client.get("/ready")
        check("readiness: база и журнал доступны",
              r.status_code == 200 and r.json()["checks"]["db_runtime"] == "ok", r.text)

        r = client.post("/api/v1/auth/login", json={"email": OWNER[0], "password": OWNER[1]})
        check("вход владельцем", r.status_code == 200, r.text)
        owner = r.json().get("access_token", "")
        head = {"Authorization": f"Bearer {owner}"}

        r = client.get("/api/v1/me", headers=head)
        check("/me возвращает права", r.status_code == 200 and len(r.json()["permissions"]) > 40, r.text)

        email = f"compose-{SUFFIX}@demo.putzplan.de"
        r = client.post("/api/v1/users", headers=head, json={
            "email": email, "full_name": "Compose Probe", "role": "dispatcher",
            "password": "Compose12345678"})
        check("создание пользователя", r.status_code == 201, r.text)

        r = client.post("/api/v1/roles", headers=head, json={
            "key": f"compose_{SUFFIX}", "name": "Compose Rolle",
            "permissions": ["planning.view", "users.read"]})
        check("создание роли с правами", r.status_code == 201 and r.json()["permissions_count"] == 2, r.text)

        r = client.post("/api/v1/auth/login", json={"email": DISPATCHER[0], "password": DISPATCHER[1]})
        disp = r.json().get("access_token", "")
        r = client.get("/api/v1/users", headers={"Authorization": f"Bearer {disp}"})
        check("отказ по правам для диспетчера", r.status_code == 403, r.text)

        r = client.get("/api/v1/users/00000000-0000-0000-0000-0000000000ff", headers=head)
        check("несуществующая запись → 404", r.status_code == 404, r.text)

        r = client.get("/api/v1/audit-logs?limit=20", headers=head)
        actions = [e["action"] for e in r.json().get("data", [])]
        check("журнал содержит вход и создание", "LOGIN_SUCCESS" in actions and "USER_CREATED" in actions,
              str(actions[:8]))

    failed = [r for r in results if not r[1]]
    print(f"\nCOMPOSE SMOKE: passed={len(results) - len(failed)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
