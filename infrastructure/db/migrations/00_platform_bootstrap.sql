-- ═══════════════════════════════════════════════════════════════════════════
-- 00_platform_bootstrap.sql · PUTZPLAN
-- Выполняется ОДИН раз суперпользователем при развёртывании кластера.
-- Создаёт расширения и роли. Не содержит объектов приложения.
--   putzplan_migration — владелец схемы, выполняет миграции (DDL)
--   putzplan_runtime   — рабочая роль приложения (DML, без DELETE там, где soft delete)
--   putzplan_audit     — единственная роль, пишущая в журнал
--   putzplan_readonly  — отчёты и аналитика
-- Пароли задаются переменными psql: -v mig_pw=... -v run_pw=... и т. д.
-- ═══════════════════════════════════════════════════════════════════════════
\set ON_ERROR_STOP on

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS postgis;

\if :{?mig_pw} \else \set mig_pw 'change_me_migration' \endif
\if :{?run_pw} \else \set run_pw 'change_me_runtime'   \endif
\if :{?aud_pw} \else \set aud_pw 'change_me_audit'     \endif
\if :{?ro_pw}  \else \set ro_pw  'change_me_readonly'  \endif

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='putzplan_migration') THEN
    CREATE ROLE putzplan_migration LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='putzplan_runtime') THEN
    CREATE ROLE putzplan_runtime LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='putzplan_audit') THEN
    CREATE ROLE putzplan_audit LOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='putzplan_readonly') THEN
    CREATE ROLE putzplan_readonly LOGIN;
  END IF;
END $$;

ALTER ROLE putzplan_migration PASSWORD :'mig_pw';
ALTER ROLE putzplan_runtime   PASSWORD :'run_pw';
ALTER ROLE putzplan_audit     PASSWORD :'aud_pw';
ALTER ROLE putzplan_readonly  PASSWORD :'ro_pw';

-- Ни одна из ролей приложения не является суперпользователем и не создаёт объекты
ALTER ROLE putzplan_runtime  NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER ROLE putzplan_audit    NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
ALTER ROLE putzplan_readonly NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
-- Роль миграций обходит RLS: она наполняет системные справочники и обслуживает
-- партиции, где контекст арендатора не определён. Рабочие роли — никогда.
ALTER ROLE putzplan_migration NOSUPERUSER NOCREATEDB NOCREATEROLE BYPASSRLS;

-- Схема принадлежит роли миграций; runtime не может создавать объекты
ALTER SCHEMA public OWNER TO putzplan_migration;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT  USAGE  ON SCHEMA public TO putzplan_runtime, putzplan_audit, putzplan_readonly;
GRANT  CREATE, USAGE ON SCHEMA public TO putzplan_migration;

-- Безопасные значения по умолчанию для сессий приложения
ALTER ROLE putzplan_runtime  SET statement_timeout = '30s';
ALTER ROLE putzplan_runtime  SET idle_in_transaction_session_timeout = '15s';
ALTER ROLE putzplan_readonly SET statement_timeout = '120s';
ALTER ROLE putzplan_audit    SET statement_timeout = '10s';
