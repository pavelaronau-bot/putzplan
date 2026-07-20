-- ═══════════════════════════════════════════════════════════════════════════
-- validate.sql · структурная проверка развёрнутой базы.
-- Проверяет НАЛИЧИЕ ожидаемых объектов: таблиц, внешних ключей, индексов,
-- политик RLS, триггеров, партиций и прав. Падает с ошибкой при отклонении.
--   psql -v ON_ERROR_STOP=1 -d putzplan -f validate.sql
-- ═══════════════════════════════════════════════════════════════════════════
\set ON_ERROR_STOP on

DO $$
DECLARE
  missing text[] := '{}';
  expected_tables text[] := ARRAY[
    'companies','branches','departments','roles','permissions','role_permissions','user_permissions',
    'employees','users','invitations','sessions','trusted_devices','login_attempts','password_history',
    'two_factor_methods','clients','client_contacts','objects','object_access_secrets','secret_reveals',
    'job_series','jobs','job_assignments','checklists','checklist_items','checklist_results','timesheets',
    'photos','signatures','incidents','absences','materials','inventory','stock_movements','messages',
    'message_reads','plans','plan_features','company_feature_overrides','subscriptions','invoices',
    'usage_counters','api_credentials','webhooks','service_accounts','sync_queue','domain_events','outbox',
    'notifications','notification_deliveries','notification_preferences','push_tokens','audit_logs',
    'audit_chain_state','partitioned_tables'];
  t text; n int; v record;
BEGIN
  -- 1. Таблицы
  FOREACH t IN ARRAY expected_tables LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace ns ON ns.oid=c.relnamespace
                   WHERE ns.nspname='public' AND c.relname=t AND c.relkind IN ('r','p')) THEN
      missing := missing || ('таблица ' || t);
    END IF;
  END LOOP;

  -- 2. Ни одна колонка-ссылка не осталась без внешнего ключа
  FOR v IN
    SELECT c.table_name, c.column_name
    FROM information_schema.columns c
    JOIN information_schema.tables tb ON tb.table_name=c.table_name AND tb.table_schema=c.table_schema
    WHERE c.table_schema='public' AND tb.table_type='BASE TABLE'
      AND c.column_name IN ('company_id','created_by','updated_by','employee_id','role_id','department_id',
                            'device_id','grantor_id','client_id','object_id','job_id','user_id','material_id',
                            'plan_id','branch_id','subscription_id','permission_id','checklist_id')
      AND c.table_name !~ '_(default|[0-9]{4}_[0-9]{2})$'
      AND c.table_name <> 'partitioned_tables'
      AND NOT EXISTS (
        SELECT 1 FROM pg_constraint pc
        JOIN pg_attribute a ON a.attrelid=pc.conrelid AND a.attnum=ANY(pc.conkey)
        WHERE pc.contype='f' AND pc.conrelid=(quote_ident(c.table_name))::regclass AND a.attname=c.column_name)
  LOOP
    missing := missing || format('внешний ключ %s.%s', v.table_name, v.column_name);
  END LOOP;

  -- 3. Составные межарендаторные ключи
  SELECT count(*) INTO n FROM pg_constraint WHERE contype='f' AND conname LIKE '%same_company_fk';
  IF n < 40 THEN missing := missing || format('составных FK только %s, ожидалось ≥ 40', n); END IF;

  -- 4. RLS включена на всех таблицах с company_id
  FOR v IN
    SELECT c.relname FROM pg_class c JOIN pg_namespace ns ON ns.oid=c.relnamespace
    JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname='company_id' AND a.attnum>0
    WHERE ns.nspname='public' AND c.relkind IN ('r','p')
      AND c.relname !~ '_(default|[0-9]{4}_[0-9]{2})$' AND NOT c.relrowsecurity
  LOOP
    missing := missing || ('RLS выключена: ' || v.relname);
  END LOOP;

  -- 5. Обязательные триггеры
  FOREACH t IN ARRAY ARRAY['audit_logs_no_update','audit_logs_no_delete','audit_logs_hash',
                           'domain_events_no_update','domain_events_no_delete','jobs_bump_rev'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname=t AND NOT tgisinternal) THEN
      missing := missing || ('триггер ' || t);
    END IF;
  END LOOP;

  -- 6. Обязательные функции
  FOREACH t IN ARRAY ARRAY['ensure_partitions','partition_headroom','partition_default_rows',
                           'detach_expired_partitions','audit_verify_chain','audit_chain_status',
                           'current_company','set_updated_at','audit_hash_chain'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace ns ON ns.oid=p.pronamespace
                   WHERE ns.nspname='public' AND p.proname=t) THEN
      missing := missing || ('функция ' || t);
    END IF;
  END LOOP;

  -- 7. Партиции: горизонт и наличие DEFAULT
  FOR v IN SELECT * FROM partition_headroom() LOOP
    IF v.days_left IS NULL OR v.days_left < 500 THEN
      missing := missing || format('горизонт партиций %s: %s дней (нужно ≥ 500)', v.table_name, COALESCE(v.days_left::text,'неизвестно'));
    END IF;
  END LOOP;
  FOREACH t IN ARRAY ARRAY['audit_logs_default','domain_events_default','notifications_default','login_attempts_default'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname=t) THEN
      missing := missing || ('DEFAULT-партиция ' || t);
    END IF;
  END LOOP;

  -- 8. Ключевые индексы
  FOREACH t IN ARRAY ARRAY['jobs_company_date_ix','objects_geo_ix','users_email_uq','sync_local_uq',
                           'audit_company_time_ix','timesheet_job_uq'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname=t AND relkind IN ('i','I'))
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname=t) THEN
      missing := missing || ('индекс ' || t);
    END IF;
  END LOOP;

  -- 9. Права: рабочая роль не пишет в журнал
  IF has_table_privilege('putzplan_runtime','audit_logs','INSERT') THEN
    missing := missing || 'putzplan_runtime имеет INSERT на audit_logs';
  END IF;
  IF has_table_privilege('putzplan_runtime','clients','DELETE') THEN
    missing := missing || 'putzplan_runtime имеет DELETE на clients (мягкое удаление)';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('putzplan_runtime','putzplan_audit','putzplan_readonly')
             AND (rolsuper OR rolbypassrls)) THEN
    missing := missing || 'рабочая роль имеет SUPERUSER или BYPASSRLS';
  END IF;

  -- 10. Справочные данные
  SELECT count(*) INTO n FROM roles WHERE is_system;
  IF n <> 5 THEN missing := missing || format('системных ролей %s, ожидалось 5', n); END IF;
  SELECT count(*) INTO n FROM permissions;
  IF n < 60 THEN missing := missing || format('прав %s, ожидалось ≥ 60', n); END IF;
  SELECT count(*) INTO n FROM plans;
  IF n <> 3 THEN missing := missing || format('тарифов %s, ожидалось 3', n); END IF;

  IF array_length(missing,1) IS NULL THEN
    RAISE NOTICE '✅ Структура базы соответствует ожиданиям';
  ELSE
    RAISE EXCEPTION 'Отклонения структуры (%): %', array_length(missing,1), array_to_string(missing, ' | ');
  END IF;
END $$;

-- Сводка для отчёта
SELECT
  (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relkind IN ('r','p')
      AND c.relname !~ '_(default|[0-9]{4}_[0-9]{2})$' AND c.relname<>'spatial_ref_sys') AS tables,
  (SELECT count(*) FROM pg_class WHERE relname ~ '_[0-9]{4}_[0-9]{2}$') AS partitions,
  (SELECT count(*) FROM pg_constraint WHERE contype='f') AS foreign_keys,
  (SELECT count(*) FROM pg_constraint WHERE contype='f' AND conname LIKE '%same_company_fk') AS cross_tenant_fks,
  (SELECT count(*) FROM pg_constraint WHERE contype='c') AS checks,
  (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname='public' AND c.relrowsecurity) AS rls_tables,
  (SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal) AS triggers;
