"""Sprint 1: имя пользователя и права первого вертикального среза.

Добавляет users.full_name и права из раздела 8 ТЗ №7:
users.read/create/update/deactivate, roles.read/create/update,
roles.permissions.manage, security.sessions.read/revoke, profile.security,
audit.read. Существующие ключи сохраняются — обратная совместимость.

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

NEW_PERMISSIONS = [
    ("users.read", "users", "read", "company", "Просмотр пользователей"),
    ("users.create", "users", "create", "company", "Создание пользователя"),
    ("users.update", "users", "update", "company", "Изменение пользователя"),
    ("users.deactivate", "users", "deactivate", "company", "Деактивация пользователя"),
    ("roles.read", "roles", "read", "company", "Просмотр ролей"),
    ("roles.create", "roles", "create", "company", "Создание роли"),
    ("roles.update", "roles", "update", "company", "Изменение роли"),
    ("roles.permissions.manage", "roles", "permissions_manage", "company", "Назначение прав роли"),
    ("security.sessions.read", "security", "sessions_read", "company", "Просмотр сессий"),
    ("security.sessions.revoke", "security", "sessions_revoke", "company", "Отзыв сессий"),
    ("profile.security", "profile", "security", "own", "Управление своими сессиями"),
    ("audit.read", "audit", "read", "company", "Просмотр журнала действий"),
]

# Кому какие права выдаются по умолчанию
ROLE_GRANTS = {
    "super_admin": [p[0] for p in NEW_PERMISSIONS],
    "admin": ["users.read", "users.create", "users.update", "roles.read",
              "security.sessions.read", "profile.security", "audit.read"],
    "senior_dispatcher": ["users.read", "roles.read", "profile.security"],
    "dispatcher": ["profile.security"],
    "worker": ["profile.security"],
}


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS full_name text")
    op.execute("""
        UPDATE users u SET full_name = COALESCE(
            (SELECT trim(e.first_name || ' ' || e.last_name) FROM employees e WHERE e.id = u.employee_id),
            split_part(u.email::text, '@', 1))
        WHERE u.full_name IS NULL""")
    op.execute("CREATE INDEX IF NOT EXISTS users_full_name_ix ON users (company_id, full_name)")

    values = ",".join(
        f"('{k}','{m}','{a}','{s}','{d}')" for k, m, a, s, d in NEW_PERMISSIONS)
    op.execute(f"""
        INSERT INTO permissions (key, module, action, default_scope, description)
        VALUES {values}
        ON CONFLICT (key) DO NOTHING""")

    for role_key, keys in ROLE_GRANTS.items():
        keys_sql = ",".join(f"'{k}'" for k in keys)
        op.execute(f"""
            INSERT INTO role_permissions (role_id, permission_id, scope)
            SELECT r.id, p.id, p.default_scope
              FROM roles r JOIN permissions p ON p.key IN ({keys_sql})
             WHERE r.key = '{role_key}' AND r.is_system
            ON CONFLICT DO NOTHING""")


def downgrade() -> None:
    keys_sql = ",".join(f"'{p[0]}'" for p in NEW_PERMISSIONS)
    op.execute(f"DELETE FROM role_permissions WHERE permission_id IN "
               f"(SELECT id FROM permissions WHERE key IN ({keys_sql}))")
    op.execute(f"DELETE FROM permissions WHERE key IN ({keys_sql})")
    op.execute("DROP INDEX IF EXISTS users_full_name_ix")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS full_name")
