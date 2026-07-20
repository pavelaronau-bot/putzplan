"""Sprint 1.1: атомарная ротация refresh и связывание сессии с запросом.

Добавляет:
  * token_family_id и parent_session_id для цепочек ротации;
  * функцию auth_rotate_session — атомарная ротация под row lock;
  * функцию auth_revoke_family — отзыв всей цепочки при обнаружении повтора;
  * функцию auth_verify_request — единая проверка сессии, пользователя,
    компании и статуса за один запрос.

Revision ID: 0003
Revises: 0002
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sessions
            ADD COLUMN IF NOT EXISTS token_family_id uuid,
            ADD COLUMN IF NOT EXISTS parent_session_id uuid REFERENCES sessions(id) ON DELETE SET NULL
    """)
    # Существующие сессии образуют семейство из самих себя
    op.execute("UPDATE sessions SET token_family_id = id WHERE token_family_id IS NULL")
    op.execute("ALTER TABLE sessions ALTER COLUMN token_family_id SET NOT NULL")
    op.execute("""
        ALTER TABLE sessions ALTER COLUMN token_family_id SET DEFAULT gen_random_uuid()
    """)
    op.execute("CREATE INDEX IF NOT EXISTS sessions_family_ix ON sessions (token_family_id)")

    # ── Атомарная ротация ────────────────────────────────────────────────
    # Один UPDATE ... WHERE revoked_at IS NULL RETURNING под блокировкой строки:
    # при параллельных запросах ровно один получает строку, остальные видят
    # уже отозванный токен и обязаны сообщить о повторном использовании.
    op.execute("""
    CREATE OR REPLACE FUNCTION auth_rotate_session(
        p_old_hash text, p_new_hash text, p_ip inet, p_user_agent text, p_ttl_days int)
    RETURNS TABLE (result text, session_id uuid, user_id uuid, company_id uuid,
                   role_key text, family_id uuid, revoked_count int)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE
        old_row     sessions%ROWTYPE;
        usr         record;
        new_id      uuid;
        n           int := 0;
    BEGIN
        -- Блокируем строку сессии: параллельные ротации выстраиваются в очередь
        SELECT * INTO old_row FROM sessions
         WHERE refresh_token_hash = p_old_hash
         FOR UPDATE;

        IF NOT FOUND THEN
            result := 'not_found'; RETURN NEXT; RETURN;
        END IF;

        SELECT u.id, u.company_id, u.status::text AS status, r.key AS role_key
          INTO usr
          FROM users u JOIN roles r ON r.id = u.role_id
         WHERE u.id = old_row.user_id;

        -- Повторное использование: токен уже отозван — рвём всё семейство
        IF old_row.revoked_at IS NOT NULL THEN
            UPDATE sessions SET revoked_at = now(), revoke_reason = 'reuse_detected'
             WHERE token_family_id = old_row.token_family_id AND revoked_at IS NULL;
            GET DIAGNOSTICS n = ROW_COUNT;
            result := 'reuse'; session_id := old_row.id; user_id := old_row.user_id;
            company_id := usr.company_id; role_key := usr.role_key;
            family_id := old_row.token_family_id; revoked_count := n;
            RETURN NEXT; RETURN;
        END IF;

        IF old_row.expires_at <= now() THEN
            result := 'expired'; RETURN NEXT; RETURN;
        END IF;

        IF usr.status <> 'active' THEN
            result := 'inactive_user'; RETURN NEXT; RETURN;
        END IF;

        -- Отзыв старой строки условным UPDATE: если её успел забрать
        -- параллельный запрос, ROW_COUNT будет нулевым.
        UPDATE sessions SET revoked_at = now(), revoke_reason = 'rotated'
         WHERE id = old_row.id AND revoked_at IS NULL;
        GET DIAGNOSTICS n = ROW_COUNT;
        IF n = 0 THEN
            result := 'race_lost'; RETURN NEXT; RETURN;
        END IF;

        INSERT INTO sessions (user_id, refresh_token_hash, ip, user_agent, expires_at,
                              last_seen_at, token_family_id, parent_session_id)
        VALUES (old_row.user_id, p_new_hash, p_ip, p_user_agent,
                now() + make_interval(days => p_ttl_days), now(),
                old_row.token_family_id, old_row.id)
        RETURNING id INTO new_id;

        result := 'rotated'; session_id := new_id; user_id := old_row.user_id;
        company_id := usr.company_id; role_key := usr.role_key;
        family_id := old_row.token_family_id; revoked_count := 0;
        RETURN NEXT;
    END $$;
    """)

    op.execute("""
    CREATE OR REPLACE FUNCTION auth_revoke_family(p_family uuid, p_reason text)
    RETURNS int LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE n int;
    BEGIN
        UPDATE sessions SET revoked_at = now(), revoke_reason = p_reason
         WHERE token_family_id = p_family AND revoked_at IS NULL;
        GET DIAGNOSTICS n = ROW_COUNT; RETURN n;
    END $$;
    """)

    # ── Единая проверка запроса ──────────────────────────────────────────
    # Сессия, пользователь, компания и статус проверяются одним запросом;
    # роль возвращается из БД, а не берётся из JWT.
    op.execute("""
    CREATE OR REPLACE FUNCTION auth_verify_request(p_session uuid, p_user uuid, p_company uuid)
    RETURNS TABLE (valid boolean, reason text, role_key text, status text,
                   must_change_password boolean)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE s sessions%ROWTYPE; u record;
    BEGIN
        SELECT * INTO s FROM sessions WHERE id = p_session;
        IF NOT FOUND THEN
            valid := false; reason := 'session_not_found'; RETURN NEXT; RETURN;
        END IF;
        IF s.revoked_at IS NOT NULL THEN
            valid := false; reason := 'session_revoked'; RETURN NEXT; RETURN;
        END IF;
        IF s.expires_at <= now() THEN
            valid := false; reason := 'session_expired'; RETURN NEXT; RETURN;
        END IF;
        IF s.user_id <> p_user THEN
            valid := false; reason := 'user_mismatch'; RETURN NEXT; RETURN;
        END IF;

        SELECT u2.company_id, u2.status::text AS status, u2.must_change_password,
               r.key AS role_key
          INTO u
          FROM users u2 JOIN roles r ON r.id = u2.role_id
         WHERE u2.id = p_user AND u2.deleted_at IS NULL;

        IF NOT FOUND THEN
            valid := false; reason := 'user_not_found'; RETURN NEXT; RETURN;
        END IF;
        IF u.company_id <> p_company THEN
            valid := false; reason := 'company_mismatch'; RETURN NEXT; RETURN;
        END IF;
        IF u.status <> 'active' THEN
            valid := false; reason := 'user_' || u.status; RETURN NEXT; RETURN;
        END IF;

        valid := true; reason := NULL; role_key := u.role_key;
        status := u.status; must_change_password := u.must_change_password;
        RETURN NEXT;
    END $$;
    """)

    for fn, args in [("auth_rotate_session", "text, text, inet, text, int"),
                     ("auth_revoke_family", "uuid, text"),
                     ("auth_verify_request", "uuid, uuid, uuid")]:
        op.execute(f"REVOKE EXECUTE ON FUNCTION {fn}({args}) FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {fn}({args}) TO putzplan_runtime")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_verify_request(uuid, uuid, uuid)")
    op.execute("DROP FUNCTION IF EXISTS auth_revoke_family(uuid, text)")
    op.execute("DROP FUNCTION IF EXISTS auth_rotate_session(text, text, inet, text, int)")
    op.execute("DROP INDEX IF EXISTS sessions_family_ix")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS parent_session_id")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS token_family_id")
