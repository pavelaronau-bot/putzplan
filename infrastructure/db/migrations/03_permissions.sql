-- ═══════════════════════════════════════════════════════════════════════════
-- 03_permissions.sql · права ролей базы данных
-- Принцип наименьших привилегий:
--   runtime  — SELECT/INSERT/UPDATE; DELETE только там, где нет мягкого удаления
--   audit    — INSERT/SELECT только в журнал и состояние цепочки
--   readonly — SELECT
--   migration— владелец объектов, DDL
-- ═══════════════════════════════════════════════════════════════════════════
\set ON_ERROR_STOP on

-- Таблицы с мягким удалением: физический DELETE рабочей роли запрещён
CREATE OR REPLACE VIEW soft_delete_tables AS
SELECT c.relname AS table_name
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'deleted_at' AND a.attnum > 0
WHERE n.nspname = 'public' AND c.relkind = 'r';

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p')
      AND c.relname NOT LIKE '%\_20%' AND c.relname <> 'spatial_ref_sys'
  LOOP
    -- журнал и неизменяемые таблицы: рабочая роль только читает
    IF r.relname IN ('audit_logs','audit_chain_state','domain_events') THEN
      EXECUTE format('GRANT SELECT ON %I TO putzplan_runtime', r.relname);
    -- append-only таблицы: чтение и вставка
    ELSIF r.relname IN ('secret_reveals','login_attempts','password_history','stock_movements','outbox') THEN
      EXECUTE format('GRANT SELECT, INSERT ON %I TO putzplan_runtime', r.relname);
    -- таблицы с мягким удалением: физический DELETE запрещён
    ELSIF EXISTS (SELECT 1 FROM soft_delete_tables s WHERE s.table_name = r.relname) THEN
      EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %I TO putzplan_runtime', r.relname);
    ELSE
      EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO putzplan_runtime', r.relname);
    END IF;
    EXECUTE format('GRANT SELECT ON %I TO putzplan_readonly', r.relname);
  END LOOP;
END $$;

-- Журнал: писать может только putzplan_audit
REVOKE INSERT, UPDATE, DELETE ON audit_logs        FROM putzplan_runtime, putzplan_readonly, PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON audit_chain_state FROM putzplan_runtime, putzplan_readonly, PUBLIC;
GRANT  SELECT ON audit_logs, audit_chain_state TO putzplan_runtime, putzplan_readonly;
GRANT  INSERT, SELECT ON audit_logs TO putzplan_audit;
GRANT  SELECT, INSERT, UPDATE ON audit_chain_state TO putzplan_audit;
REVOKE UPDATE, DELETE ON audit_logs FROM putzplan_audit;

-- Доменные события: вставка рабочей ролью, изменение запрещено всем
GRANT  INSERT, SELECT ON domain_events TO putzplan_runtime;
REVOKE UPDATE, DELETE ON domain_events FROM putzplan_runtime, putzplan_audit, putzplan_readonly, PUBLIC;

-- Партиции (включая DEFAULT) наследуют права родителя только если созданы
-- после выдачи грантов, поэтому права проставляются явно по всем потомкам.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.relname, p.relname AS parent
    FROM pg_class c
    JOIN pg_inherits i ON i.inhrelid = c.oid
    JOIN pg_class p ON p.oid = i.inhparent
    WHERE c.relkind = 'r' AND p.relkind = 'p'
  LOOP
    IF r.parent = 'audit_logs' THEN
      EXECUTE format('GRANT SELECT ON %I TO putzplan_runtime, putzplan_readonly', r.relname);
      EXECUTE format('GRANT SELECT, INSERT ON %I TO putzplan_audit', r.relname);
    ELSIF r.parent = 'domain_events' THEN
      EXECUTE format('GRANT SELECT, INSERT ON %I TO putzplan_runtime', r.relname);
      EXECUTE format('GRANT SELECT ON %I TO putzplan_readonly', r.relname);
    ELSE
      EXECUTE format('GRANT SELECT, INSERT, UPDATE ON %I TO putzplan_runtime', r.relname);
      EXECUTE format('GRANT SELECT ON %I TO putzplan_readonly', r.relname);
    END IF;
  END LOOP;
END $$;

-- Реестр партиционированных таблиц читают все роли (нужен функциям мониторинга)
GRANT SELECT ON partitioned_tables TO putzplan_runtime, putzplan_audit, putzplan_readonly;

-- Последовательности
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO putzplan_runtime, putzplan_audit;

-- Функции обслуживания доступны только роли миграций и планировщику
REVOKE EXECUTE ON FUNCTION ensure_partitions(int)            FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION detach_expired_partitions(boolean) FROM PUBLIC;
REVOKE EXECUTE ON PROCEDURE redistribute_default_partition(text) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION ensure_partitions(int)            TO putzplan_migration;
GRANT  EXECUTE ON FUNCTION detach_expired_partitions(boolean) TO putzplan_migration;
GRANT  EXECUTE ON PROCEDURE redistribute_default_partition(text) TO putzplan_migration;
GRANT  EXECUTE ON FUNCTION partition_headroom()     TO putzplan_runtime, putzplan_readonly, putzplan_migration;
GRANT  EXECUTE ON FUNCTION partition_default_rows() TO putzplan_runtime, putzplan_readonly, putzplan_migration;
GRANT  EXECUTE ON FUNCTION audit_verify_chain(uuid) TO putzplan_readonly, putzplan_migration;
GRANT  EXECUTE ON FUNCTION audit_chain_status(uuid) TO putzplan_runtime, putzplan_readonly, putzplan_migration;
GRANT  EXECUTE ON FUNCTION current_company()        TO putzplan_runtime, putzplan_audit, putzplan_readonly;

-- Функции аутентификации: доступны рабочей роли, но выдают только нужные поля
REVOKE EXECUTE ON FUNCTION auth_find_user(text)            FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION auth_session_lookup(text)       FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION auth_user_permissions(uuid)     FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION auth_register_failure(uuid,int,int) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION auth_register_success(uuid)     FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION auth_revoke_user_sessions(uuid,text) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION auth_record_attempt(uuid,uuid,text,inet,text,boolean,text) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION auth_find_user(text)            TO putzplan_runtime;
GRANT  EXECUTE ON FUNCTION auth_session_lookup(text)       TO putzplan_runtime;
GRANT  EXECUTE ON FUNCTION auth_user_permissions(uuid)     TO putzplan_runtime;
GRANT  EXECUTE ON FUNCTION auth_register_failure(uuid,int,int) TO putzplan_runtime;
GRANT  EXECUTE ON FUNCTION auth_register_success(uuid)     TO putzplan_runtime;
GRANT  EXECUTE ON FUNCTION auth_revoke_user_sessions(uuid,text) TO putzplan_runtime;
GRANT  EXECUTE ON FUNCTION auth_record_attempt(uuid,uuid,text,inet,text,boolean,text) TO putzplan_runtime;

-- Права по умолчанию для будущих объектов
ALTER DEFAULT PRIVILEGES FOR ROLE putzplan_migration IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO putzplan_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE putzplan_migration IN SCHEMA public
  GRANT SELECT ON TABLES TO putzplan_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE putzplan_migration IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO putzplan_runtime, putzplan_audit;
