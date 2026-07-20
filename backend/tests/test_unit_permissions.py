"""Модульные тесты вычисления прав и инвариантов ролей."""
import uuid

import pytest

from app.core.errors import Forbidden
from app.domain.models import Actor
from app.services.role_service import OWNER_ONLY, _assert_no_escalation


def actor(role: str, permissions: set[str]) -> Actor:
    return Actor(user_id=uuid.uuid4(), company_id=uuid.uuid4(), role=role,
                 session_id=uuid.uuid4(), permissions=frozenset(permissions))


def test_actor_can_checks_exact_permission():
    a = actor("admin", {"users.read", "roles.read"})
    assert a.can("users.read") is True
    assert a.can("users.create") is False
    assert a.can("users") is False, "префикс не должен давать право"


def test_owner_only_permissions_are_not_delegatable_by_admin():
    admin = actor("admin", {"roles.create", "security.manage"})
    with pytest.raises(Forbidden) as exc:
        _assert_no_escalation(admin, ["security.manage"])
    assert exc.value.code == "permission_not_delegatable"


def test_admin_cannot_grant_permission_he_lacks():
    admin = actor("admin", {"roles.create", "users.read"})
    with pytest.raises(Forbidden) as exc:
        _assert_no_escalation(admin, ["finance.view"])
    assert exc.value.code == "privilege_escalation"


def test_admin_can_grant_permission_he_has():
    admin = actor("admin", {"roles.create", "users.read", "planning.view"})
    _assert_no_escalation(admin, ["users.read", "planning.view"])


def test_owner_may_grant_everything():
    owner = actor("super_admin", set())
    _assert_no_escalation(owner, sorted(OWNER_ONLY))


def test_owner_only_set_covers_security_and_billing():
    assert {"security.manage", "system.settings", "billing.manage",
            "billing.cancel", "roles.permissions.manage"} <= OWNER_ONLY
