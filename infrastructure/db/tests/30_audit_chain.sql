-- Журнал: неизменяемость и детерминированная хеш-цепочка.
-- Выполняется ролью putzplan_audit (единственная, кому разрешена запись).
\set ON_ERROR_STOP on
SELECT tst.suite('audit_chain');
-- Контекст арендатора нужен для чтения журнала: политика audit_read
-- разрешает SELECT только по своей компании.
SET app.company_id = '11111111-1111-1111-1111-111111111111';

INSERT INTO audit_logs (company_id,user_id,action,entity,reason) VALUES
 ('11111111-1111-1111-1111-111111111111','d1111111-0000-0000-0000-000000000001','ВХОД','сессия','первый'),
 ('11111111-1111-1111-1111-111111111111','d1111111-0000-0000-0000-000000000001','ИЗМЕНЕНИЕ','job','второй'),
 ('11111111-1111-1111-1111-111111111111',NULL,'ЭКСПОРТ','timesheets','третий');

SELECT tst.is_count('три записи журнала созданы',
  $$SELECT count(*) FROM audit_logs WHERE company_id='11111111-1111-1111-1111-111111111111'$$, 3::bigint);

SELECT tst.is_count('chain_seq последователен 1..3',
  $$SELECT count(*) FROM audit_logs
    WHERE company_id='11111111-1111-1111-1111-111111111111' AND chain_seq IN (1,2,3)$$, 3::bigint);

SELECT tst.ok('prev_hash второй записи равен row_hash первой',
  (SELECT a2.prev_hash = a1.row_hash
   FROM audit_logs a1, audit_logs a2
   WHERE a1.company_id=a2.company_id AND a1.company_id='11111111-1111-1111-1111-111111111111'
     AND a1.chain_seq=1 AND a2.chain_seq=2));

SELECT tst.ok('prev_id второй записи указывает на первую',
  (SELECT a2.prev_id = a1.id
   FROM audit_logs a1, audit_logs a2
   WHERE a1.company_id=a2.company_id AND a1.company_id='11111111-1111-1111-1111-111111111111'
     AND a1.chain_seq=1 AND a2.chain_seq=2));

SELECT tst.is_count('цепочка цела: нарушений нет',
  $$SELECT count(*) FROM audit_verify_chain('11111111-1111-1111-1111-111111111111')$$, 0::bigint);

SELECT tst.ok('состояние цепочки согласовано с данными',
  (SELECT consistent FROM audit_chain_status('11111111-1111-1111-1111-111111111111')));

SELECT tst.ok('last_id состояния заполнен и указывает на последнюю запись',
  (SELECT s.last_id = (SELECT id FROM audit_logs
                        WHERE company_id=s.company_id ORDER BY chain_seq DESC LIMIT 1)
   FROM audit_chain_state s WHERE s.company_id='11111111-1111-1111-1111-111111111111'));

SELECT tst.throws('UPDATE журнала запрещён',
  $$UPDATE audit_logs SET action='ПОДМЕНА'
    WHERE company_id='11111111-1111-1111-1111-111111111111' AND chain_seq=1$$, '42501');
SELECT tst.throws('DELETE журнала запрещён',
  $$DELETE FROM audit_logs WHERE company_id='11111111-1111-1111-1111-111111111111' AND chain_seq=1$$, '42501');

-- Цепочки разных арендаторов независимы
INSERT INTO audit_logs (company_id,action,entity) VALUES
 ('22222222-2222-2222-2222-222222222222','ВХОД','сессия');
SET app.company_id = '22222222-2222-2222-2222-222222222222';
SELECT tst.is_count('цепочка второго арендатора начинается с 1',
  $$SELECT count(*) FROM audit_logs
    WHERE company_id='22222222-2222-2222-2222-222222222222' AND chain_seq=1$$, 1::bigint);
SELECT tst.is_count('цепочка второго арендатора цела',
  $$SELECT count(*) FROM audit_verify_chain('22222222-2222-2222-2222-222222222222')$$, 0::bigint);

-- Партиционирование: запись попала в партицию текущего месяца
SELECT tst.suite('partitions');
SELECT tst.ok('запись журнала попала в партицию текущего месяца',
  (SELECT tableoid::regclass::text = 'audit_logs_' || to_char(now(),'YYYY_MM')
   FROM audit_logs WHERE company_id='22222222-2222-2222-2222-222222222222' LIMIT 1));

SELECT tst.lives('вставка в будущую партицию (через 12 месяцев) проходит',
  $$INSERT INTO audit_logs (company_id,action,entity,server_time)
    VALUES ('22222222-2222-2222-2222-222222222222','БУДУЩЕЕ','test', now() + interval '12 months')$$);

SELECT tst.ok('DEFAULT-партиция пуста',
  (SELECT COALESCE(sum(rows_in_default),0) FROM partition_default_rows()) = 0,
  (SELECT string_agg(table_name||'='||rows_in_default, ', ') FROM partition_default_rows()));

SELECT tst.ok('горизонт партиций известен для всех таблиц',
  NOT EXISTS (SELECT 1 FROM partition_headroom() WHERE days_left IS NULL OR covered_until IS NULL),
  (SELECT string_agg(table_name||'='||COALESCE(days_left::text,'NULL'), ', ') FROM partition_headroom()));

SELECT tst.ok('горизонт партиций не менее 60 дней у всех таблиц',
  NOT EXISTS (SELECT 1 FROM partition_headroom() WHERE alert IS NOT FALSE),
  (SELECT string_agg(table_name||': '||days_left||' дн.', ', ') FROM partition_headroom()));

SELECT tst.ok('горизонт партиций не менее 500 дней (18 месяцев)',
  (SELECT min(days_left) FROM partition_headroom()) >= 500,
  (SELECT min(days_left)::text FROM partition_headroom()));
