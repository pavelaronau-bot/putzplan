-- Проверка результата параллельных вставок в журнал (запускается после нагрузки)
\set ON_ERROR_STOP on
SELECT tst.suite('concurrency');
SET app.company_id = '33333333-3333-3333-3333-333333333333';

SELECT tst.ok('параллельные вставки: цепочка без разрывов и ветвления',
  NOT EXISTS (SELECT 1 FROM audit_verify_chain('33333333-3333-3333-3333-333333333333')),
  (SELECT string_agg(problem, '; ') FROM audit_verify_chain('33333333-3333-3333-3333-333333333333')));

SELECT tst.ok('chain_seq уникален внутри компании',
  (SELECT count(*) = count(DISTINCT chain_seq) FROM audit_logs
   WHERE company_id='33333333-3333-3333-3333-333333333333'));

SELECT tst.ok('chain_seq непрерывен: max = количество записей',
  (SELECT max(chain_seq) = count(*) FROM audit_logs
   WHERE company_id='33333333-3333-3333-3333-333333333333'),
  (SELECT format('max=%s count=%s', max(chain_seq), count(*)) FROM audit_logs
   WHERE company_id='33333333-3333-3333-3333-333333333333'));

SELECT tst.ok('каждая запись ссылается на предыдущую по prev_id',
  NOT EXISTS (
    SELECT 1 FROM audit_logs a
    JOIN audit_logs b ON b.company_id=a.company_id AND b.chain_seq=a.chain_seq-1
    WHERE a.company_id='33333333-3333-3333-3333-333333333333' AND a.prev_id IS DISTINCT FROM b.id));

SELECT tst.ok('состояние цепочки совпадает с фактическим максимумом',
  (SELECT consistent FROM audit_chain_status('33333333-3333-3333-3333-333333333333')));
