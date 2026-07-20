-- ═══════════════════════════════════════════════════════════════════════════
-- Тестовый каркас на PL/pgSQL. Никакого визуального просмотра:
-- каждый тест записывает результат, в конце считается passed/failed,
-- при любом failed раннер завершается ненулевым кодом.
-- ═══════════════════════════════════════════════════════════════════════════
\set ON_ERROR_STOP on

DROP SCHEMA IF EXISTS tst CASCADE;
CREATE SCHEMA tst;

CREATE TABLE tst.results (
  id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  suite     text NOT NULL,
  name      text NOT NULL,
  passed    boolean NOT NULL,
  detail    text,
  run_as    text NOT NULL DEFAULT current_user,
  at        timestamptz NOT NULL DEFAULT clock_timestamp()
);
GRANT USAGE ON SCHEMA tst TO putzplan_runtime, putzplan_audit, putzplan_readonly;
GRANT SELECT, INSERT ON tst.results TO putzplan_runtime, putzplan_audit, putzplan_readonly;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA tst TO putzplan_runtime, putzplan_audit, putzplan_readonly;

-- Текущий набор тестов (устанавливается в начале файла теста)
CREATE OR REPLACE FUNCTION tst.suite(p text) RETURNS void
LANGUAGE plpgsql AS $$ BEGIN PERFORM set_config('tst.suite', p, false); END $$;

CREATE OR REPLACE FUNCTION tst.record(p_name text, p_passed boolean, p_detail text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO tst.results (suite, name, passed, detail)
  VALUES (COALESCE(current_setting('tst.suite', true), 'default'), p_name, p_passed, p_detail);
  IF p_passed THEN RAISE NOTICE '  PASS  %', p_name;
  ELSE            RAISE WARNING '  FAIL  % — %', p_name, COALESCE(p_detail,'');
  END IF;
END $$;

-- Утверждение: условие истинно
CREATE OR REPLACE FUNCTION tst.ok(p_name text, p_cond boolean, p_detail text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN PERFORM tst.record(p_name, COALESCE(p_cond,false), p_detail); END $$;

-- Утверждение: значения равны
CREATE OR REPLACE FUNCTION tst.is(p_name text, p_actual anyelement, p_expected anyelement)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  PERFORM tst.record(p_name, p_actual IS NOT DISTINCT FROM p_expected,
    format('получено %s, ожидалось %s', p_actual, p_expected));
END $$;

-- Утверждение: запрос возвращает ожидаемое число
CREATE OR REPLACE FUNCTION tst.is_count(p_name text, p_sql text, p_expected bigint)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE n bigint;
BEGIN
  EXECUTE p_sql INTO n;
  PERFORM tst.record(p_name, n = p_expected, format('получено %s, ожидалось %s', n, p_expected));
END $$;

-- Негативный тест: операция ОБЯЗАНА упасть с указанным SQLSTATE.
-- Если операция прошла — тест провален (а не «пропущен»).
CREATE OR REPLACE FUNCTION tst.throws(p_name text, p_sql text, p_sqlstate text DEFAULT NULL)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE got text;
BEGIN
  BEGIN
    EXECUTE p_sql;
    PERFORM tst.record(p_name, false, 'операция выполнилась, хотя должна была быть отклонена');
    RETURN;
  EXCEPTION WHEN OTHERS THEN
    got := SQLSTATE;
  END;
  IF p_sqlstate IS NULL OR got = p_sqlstate THEN
    PERFORM tst.record(p_name, true, 'SQLSTATE ' || got);
  ELSE
    PERFORM tst.record(p_name, false, format('SQLSTATE %s, ожидался %s', got, p_sqlstate));
  END IF;
END $$;

-- Позитивный тест: операция обязана выполниться без ошибки
CREATE OR REPLACE FUNCTION tst.lives(p_name text, p_sql text)
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
  EXECUTE p_sql;
  PERFORM tst.record(p_name, true, NULL);
EXCEPTION WHEN OTHERS THEN
  PERFORM tst.record(p_name, false, format('%s: %s', SQLSTATE, SQLERRM));
END $$;

CREATE OR REPLACE FUNCTION tst.summary()
RETURNS TABLE (suite text, passed bigint, failed bigint)
LANGUAGE sql AS $$
  SELECT r.suite, count(*) FILTER (WHERE r.passed), count(*) FILTER (WHERE NOT r.passed)
  FROM tst.results r GROUP BY r.suite ORDER BY r.suite;
$$;

-- Завершение прогона: при любом провале выбрасывает исключение,
-- psql с ON_ERROR_STOP возвращает ненулевой код и CI падает.
CREATE OR REPLACE FUNCTION tst.finish() RETURNS void
LANGUAGE plpgsql AS $$
DECLARE p bigint; f bigint;
BEGIN
  SELECT count(*) FILTER (WHERE passed), count(*) FILTER (WHERE NOT passed)
    INTO p, f FROM tst.results;
  RAISE NOTICE '───────────────────────────────────────────';
  RAISE NOTICE 'ИТОГО: passed=% failed=%', p, f;
  IF f > 0 THEN
    RAISE EXCEPTION 'ТЕСТЫ ПРОВАЛЕНЫ: % из %', f, p + f USING ERRCODE = 'raise_exception';
  END IF;
END $$;

GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA tst TO putzplan_runtime, putzplan_audit, putzplan_readonly;
