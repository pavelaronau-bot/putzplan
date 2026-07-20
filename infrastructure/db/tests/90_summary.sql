\set ON_ERROR_STOP on
\echo ''
\echo '════════════ РЕЗУЛЬТАТЫ ПО НАБОРАМ ════════════'
SELECT suite AS "Набор", passed AS "Пройдено", failed AS "Провалено" FROM tst.summary();
\echo ''
SELECT suite, name, detail FROM tst.results WHERE NOT passed ORDER BY id;
SELECT tst.finish();
