-- RLS, изоляция контекста арендатора и утечка контекста в пуле соединений.
-- Выполняется ролью putzplan_runtime.
\set ON_ERROR_STOP on
SELECT tst.suite('rls');

-- Без контекста арендатора данные не видны вообще
SELECT tst.is_count('без app.company_id ничего не видно','SELECT count(*) FROM jobs',0::bigint);
SELECT tst.is_count('без контекста компании не видны','SELECT count(*) FROM companies',0::bigint);

BEGIN;
  SET LOCAL app.company_id = '11111111-1111-1111-1111-111111111111';
  SELECT tst.is_count('арендатор A видит своё задание','SELECT count(*) FROM jobs',1::bigint);
  SELECT tst.is_count('арендатор A видит свою компанию','SELECT count(*) FROM companies',1::bigint);
  SELECT tst.is_count('арендатор A не видит чужие объекты',
    $$SELECT count(*) FROM objects WHERE company_id<>'11111111-1111-1111-1111-111111111111'$$,0::bigint);
  -- запись с чужим company_id отклоняется политикой
  SELECT tst.throws('вставка с чужим company_id отклонена политикой',
    $$INSERT INTO clients (company_id,name) VALUES ('22222222-2222-2222-2222-222222222222','Взлом')$$,
    '42501');
COMMIT;

BEGIN;
  SET LOCAL app.company_id = '22222222-2222-2222-2222-222222222222';
  SELECT tst.is_count('арендатор B видит только своё задание','SELECT count(*) FROM jobs',1::bigint);
  SELECT tst.is_count('арендатор B не видит объекты A',
    $$SELECT count(*) FROM objects WHERE company_id='11111111-1111-1111-1111-111111111111'$$,0::bigint);
COMMIT;

-- Утечка контекста при повторном использовании соединения из пула:
-- SET LOCAL действует только внутри транзакции, после COMMIT контекст пуст.
SELECT tst.suite('tenant_context');
BEGIN;
  SET LOCAL app.company_id = '11111111-1111-1111-1111-111111111111';
COMMIT;
SELECT tst.ok('после COMMIT контекст арендатора очищен',
  COALESCE(current_setting('app.company_id', true),'') = '',
  'осталось: ' || COALESCE(current_setting('app.company_id', true),'(пусто)'));
SELECT tst.is_count('после COMMIT данные снова не видны','SELECT count(*) FROM jobs',0::bigint);

-- Мягкое удаление: рабочая роль не может физически удалять
SELECT tst.suite('soft_delete');
BEGIN;
  SET LOCAL app.company_id = '11111111-1111-1111-1111-111111111111';
  SELECT tst.throws('физическое удаление клиента запрещено рабочей роли',
    $$DELETE FROM clients WHERE id='c1111111-0000-0000-0000-000000000001'$$, '42501');
  SELECT tst.throws('физическое удаление объекта запрещено рабочей роли',
    $$DELETE FROM objects WHERE id='01111111-0000-0000-0000-000000000001'$$, '42501');
  SELECT tst.throws('физическое удаление задания запрещено рабочей роли',
    $$DELETE FROM jobs WHERE id='11110000-0000-0000-0000-000000000001'$$, '42501');
  SELECT tst.lives('мягкое удаление клиента разрешено',
    $$UPDATE clients SET deleted_at=now() WHERE id='c1111111-0000-0000-0000-000000000001'$$);
  SELECT tst.lives('возврат клиента из мягкого удаления',
    $$UPDATE clients SET deleted_at=NULL WHERE id='c1111111-0000-0000-0000-000000000001'$$);
ROLLBACK;

-- Права: рабочая роль не пишет в журнал
SELECT tst.suite('permissions');
SELECT tst.throws('рабочая роль не может писать в журнал',
  $$INSERT INTO audit_logs (company_id,action) VALUES ('11111111-1111-1111-1111-111111111111','ПОПЫТКА')$$,
  '42501');
SELECT tst.throws('рабочая роль не может изменять журнал',
  $$UPDATE audit_logs SET action='ПОДМЕНА' WHERE true$$, '42501');
SELECT tst.throws('рабочая роль не может менять состояние цепочки',
  $$UPDATE audit_chain_state SET last_hash='0' WHERE true$$, '42501');
SELECT tst.throws('рабочая роль не может создавать таблицы',
  $$CREATE TABLE hack_table (id int)$$, '42501');
SELECT tst.throws('рабочая роль не может изменять доменные события',
  $$UPDATE domain_events SET type='hack' WHERE true$$, '42501');
SELECT tst.ok('рабочая роль не суперпользователь',
  NOT (SELECT rolsuper FROM pg_roles WHERE rolname=current_user));
SELECT tst.ok('рабочая роль не обходит RLS',
  NOT (SELECT rolbypassrls FROM pg_roles WHERE rolname=current_user));

-- Ограничения CHECK / UNIQUE / FK
SELECT tst.suite('constraints');
BEGIN;
  SET LOCAL app.company_id = '11111111-1111-1111-1111-111111111111';
  SELECT tst.throws('CHECK: длительность 5 минут отклонена',
    $$INSERT INTO jobs (company_id,object_id,date,start_time,duration_min,service_type)
      VALUES ('11111111-1111-1111-1111-111111111111','01111111-0000-0000-0000-000000000001',
              CURRENT_DATE,'10:00',5,'X')$$, '23514');
  SELECT tst.throws('CHECK: отмена задания без причины отклонена',
    $$UPDATE jobs SET status='cancelled' WHERE id='11110000-0000-0000-0000-000000000001'$$, '23514');
  SELECT tst.throws('CHECK: блокировка пользователя без причины отклонена',
    $$UPDATE users SET status='terminated' WHERE id='d1111111-0000-0000-0000-000000000001'$$, '23514');
  SELECT tst.lives('CHECK: блокировка с причиной проходит',
    $$UPDATE users SET status='terminated', status_reason='тест'
      WHERE id='d1111111-0000-0000-0000-000000000001'$$);
  SELECT tst.throws('FK: несуществующий объект отклонён',
    $$INSERT INTO jobs (company_id,object_id,date,start_time,duration_min,service_type)
      VALUES ('11111111-1111-1111-1111-111111111111','00000000-0000-0000-0000-0000000000ff',
              CURRENT_DATE,'11:00',60,'X')$$, '23503');
  SELECT tst.throws('UNIQUE: дубль local_id в очереди отклонён',
    $$INSERT INTO sync_queue (company_id,user_id,local_id,kind,payload,created_at_device)
      VALUES ('11111111-1111-1111-1111-111111111111','d1111111-0000-0000-0000-000000000001','loc_x','finish','{}',now()),
             ('11111111-1111-1111-1111-111111111111','d1111111-0000-0000-0000-000000000001','loc_x','finish','{}',now())$$,
    '23505');
ROLLBACK;
