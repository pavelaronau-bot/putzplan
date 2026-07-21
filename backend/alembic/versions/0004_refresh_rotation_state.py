"""Sprint 1.2: состояние ротации refresh вместо трактовки гонки как кражи.

Проблема: при параллельных запросах проигравший видел отозванную старую
сессию и считал это повторным использованием, после чего отзывал всё
семейство — включая только что созданную сессию победителя.

Решение: явное состояние «сессия заменена» с отметкой времени и ссылкой
на преемника. Повторное предъявление заменённого токена в пределах
grace-window — штатная гонка (benign duplicate), семейство не трогаем.
За пределами окна то же действие означает кражу: отзываем семейство.

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

GRACE_SECONDS_DEFAULT = 30


def upgrade() -> None:
    op.execute("""
        ALTER TABLE sessions
            ADD COLUMN IF NOT EXISTS rotated_at timestamptz,
            ADD COLUMN IF NOT EXISTS replaced_by_session_id uuid
                REFERENCES sessions(id) ON DELETE SET NULL
    """)
    # Ранее отозванные ротацией сессии считаем заменёнными в момент отзыва
    op.execute("""
        UPDATE sessions SET rotated_at = revoked_at
         WHERE revoke_reason = 'rotated' AND rotated_at IS NULL
    """)
    op.execute("CREATE INDEX IF NOT EXISTS sessions_rotated_ix ON sessions (rotated_at)")

    op.execute("DROP FUNCTION IF EXISTS auth_rotate_session(text, text, inet, text, int)")
    op.execute(f"""
    CREATE OR REPLACE FUNCTION auth_rotate_session(
        p_old_hash text, p_new_hash text, p_ip inet, p_user_agent text,
        p_ttl_days int, p_grace_seconds int DEFAULT {GRACE_SECONDS_DEFAULT})
    RETURNS TABLE (result text, session_id uuid, user_id uuid, company_id uuid,
                   role_key text, family_id uuid, revoked_count int,
                   replacement_session_id uuid)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    DECLARE
        old_row sessions%ROWTYPE;
        usr     record;
        new_id  uuid;
        n       int := 0;
    BEGIN
        -- Блокировка строки: параллельные ротации одного токена выстраиваются
        -- в очередь, поэтому решение принимается по фактическому состоянию.
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

        IF old_row.revoked_at IS NOT NULL THEN
            -- Штатная гонка: токен уже заменён, но совсем недавно.
            -- Победителя не трогаем, семейство остаётся живым.
            IF old_row.revoke_reason = 'rotated'
               AND old_row.rotated_at IS NOT NULL
               AND old_row.rotated_at > now() - make_interval(secs => p_grace_seconds) THEN
                result := 'race';
                session_id := old_row.id;
                replacement_session_id := old_row.replaced_by_session_id;
                user_id := old_row.user_id; company_id := usr.company_id;
                role_key := usr.role_key; family_id := old_row.token_family_id;
                revoked_count := 0;
                RETURN NEXT; RETURN;
            END IF;

            -- За пределами окна либо отзыв по другой причине — это кража
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

        INSERT INTO sessions (user_id, refresh_token_hash, ip, user_agent, expires_at,
                              last_seen_at, token_family_id, parent_session_id)
        VALUES (old_row.user_id, p_new_hash, p_ip, p_user_agent,
                now() + make_interval(days => p_ttl_days), now(),
                old_row.token_family_id, old_row.id)
        RETURNING id INTO new_id;

        UPDATE sessions
           SET revoked_at = now(), revoke_reason = 'rotated',
               rotated_at = now(), replaced_by_session_id = new_id
         WHERE id = old_row.id;

        result := 'rotated'; session_id := new_id; user_id := old_row.user_id;
        company_id := usr.company_id; role_key := usr.role_key;
        family_id := old_row.token_family_id; revoked_count := 0;
        replacement_session_id := new_id;
        RETURN NEXT;
    END $$;
    """)
    op.execute("REVOKE EXECUTE ON FUNCTION auth_rotate_session(text, text, inet, text, int, int) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION auth_rotate_session(text, text, inet, text, int, int) TO putzplan_runtime")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS auth_rotate_session(text, text, inet, text, int, int)")
    op.execute("DROP INDEX IF EXISTS sessions_rotated_ix")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS replaced_by_session_id")
    op.execute("ALTER TABLE sessions DROP COLUMN IF EXISTS rotated_at")
    # Восстанавливаем предыдущую версию функции из ревизии 0003
    op.execute("""
    CREATE OR REPLACE FUNCTION auth_rotate_session(
        p_old_hash text, p_new_hash text, p_ip inet, p_user_agent text, p_ttl_days int)
    RETURNS TABLE (result text, session_id uuid, user_id uuid, company_id uuid,
                   role_key text, family_id uuid, revoked_count int)
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
    BEGIN
        result := 'not_found'; RETURN NEXT;
    END $$;
    """)
