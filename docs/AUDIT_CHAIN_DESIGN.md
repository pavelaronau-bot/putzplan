# AUDIT_CHAIN_DESIGN — устройство хеш-цепочки журнала

Задача: обнаруживать любое изменение или удаление записи журнала, даже
выполненное с правами владельца схемы, и не зависеть от порядка времени.

## 1. Почему не время

Первая версия упорядочивала цепочку по `server_time`. Это неверно:
`now()` возвращает время начала транзакции, поэтому две параллельные
транзакции могут получить одинаковую или обратную по отношению к фактической
вставке отметку. Порядок цепочки должен определяться самой цепочкой.

**Решение:** монотонный `chain_seq` внутри компании плюс явная ссылка
`prev_id` на предыдущую запись.

## 2. Структура

```sql
CREATE TABLE audit_logs (
  id         bigint GENERATED ALWAYS AS IDENTITY,
  company_id uuid NOT NULL,
  chain_seq  bigint NOT NULL CHECK (chain_seq > 0),  -- номер в цепочке компании
  prev_id    bigint,                                  -- предыдущая запись цепочки
  prev_hash  text NOT NULL,                           -- её хеш
  row_hash   text NOT NULL,                           -- хеш этой записи
  ...
  server_time timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, server_time)
) PARTITION BY RANGE (server_time);

CREATE TABLE audit_chain_state (
  company_id uuid PRIMARY KEY,
  last_seq   bigint NOT NULL DEFAULT 0,
  last_id    bigint,
  last_hash  text NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

`audit_chain_state` — не кэш, а рабочее состояние: все три поля
(`last_seq`, `last_id`, `last_hash`) читаются и обновляются атомарно.

## 3. Формула

```
prev_hash = hash предыдущей записи компании, для первой — 64 нуля
row_hash  = sha256(
              prev_hash | chain_seq | company_id | user_id | action |
              entity | entity_id | before | after | reason )
```

Время в хеш **не входит**: положение записи определяет `chain_seq`.
Разделитель `|` исключает склейку соседних полей.

## 4. Параллельные вставки

```sql
PERFORM pg_advisory_xact_lock(hashtext('audit_chain'), hashtext(company_id::text));
SELECT * FROM audit_chain_state WHERE company_id = NEW.company_id FOR UPDATE;
```

Блокировка берётся по паре (пространство имён, компания): цепочки разных
арендаторов не мешают друг другу. `FOR UPDATE` защищает строку состояния.
Блокировка транзакционная — снимается автоматически при COMMIT или ROLLBACK.

**Важная деталь реализации.** Состояние обновляется в том же `BEFORE INSERT`
триггере, а не в `AFTER`. Причина: при многострочном `INSERT` строковые
`AFTER`-триггеры выполняются после завершения всего оператора, поэтому все
строки прочитали бы одно и то же состояние и получили одинаковый `chain_seq`.
Эта ошибка была допущена в первой версии и обнаружена тестом.
Значение `id` доступно уже в `BEFORE`, так как значения по умолчанию
(в том числе `IDENTITY`) вычисляются до срабатывания триггера.

## 5. Неизменяемость

Три независимых барьера:

1. **Права.** `REVOKE UPDATE, DELETE ON audit_logs FROM putzplan_runtime, putzplan_audit, putzplan_readonly, PUBLIC`. Писать может только `putzplan_audit`, и только `INSERT`.
2. **Триггеры.** `audit_logs_no_update` и `audit_logs_no_delete` возбуждают исключение с кодом `insufficient_privilege` — даже если права выданы по ошибке.
3. **Цепочка.** Изменение любой строки в обход первых двух барьеров ломает `row_hash` и обнаруживается проверкой.

## 6. Проверка

```sql
SELECT * FROM audit_verify_chain('<company_id>');
--  chain_seq | audit_id | problem
--  (0 строк) = журнал не изменялся
```

Функция идёт строго по `chain_seq` и проверяет четыре условия: непрерывность
последовательности, совпадение `prev_hash`, совпадение `prev_id` и совпадение
пересчитанного `row_hash`.

Быстрая сверка состояния без полного пересчёта:

```sql
SELECT * FROM audit_chain_status('<company_id>');
--  rows_total | state_seq | max_seq | consistent
```

## 7. Регламент контроля

| Проверка | Частота | Реакция |
|---|---|---|
| `audit_chain_status` по всем компаниям | каждый час | расхождение → P2, разбор в течение рабочего дня |
| `audit_verify_chain` по всем компаниям | ежедневно 03:00 | любое нарушение → **P1**, немедленная эскалация |
| Выгрузка в WORM-хранилище | ежемесячно | отсутствие выгрузки → P2 |
| Сверка архива с последним `row_hash` месяца | ежемесячно | расхождение → P1 |

## 8. Реакция на повреждение

1. Зафиксировать инцидент, снять копию текущего состояния таблицы.
2. Определить первую нарушенную запись по `audit_verify_chain`.
3. Сравнить с последним выгруженным в WORM архивом: если нарушение позже
   архива — восстановить достоверную часть из архива.
4. Проверить `login_attempts`, сессии и права: выяснить, чьи полномочия
   использовались.
5. Уведомить владельца компании; при подозрении на утечку персональных
   данных — надзорный орган в течение 72 часов.
6. Ротировать учётные данные ролей БД и ключи приложения.
7. Разбор без поиска виноватых, отчёт в течение 7 дней.

Цепочка не «чинится»: обнаруженное нарушение фиксируется навсегда,
новая цепочка продолжается от последней достоверной записи с явной
отметкой в журнале платформы.

## 9. Экспорт в WORM

```bash
psql -c "\copy (SELECT * FROM audit_logs WHERE company_id=:cid AND server_time < :cutoff ORDER BY chain_seq) TO 'audit.csv' CSV HEADER"
sha256sum audit.csv > audit.csv.sha256
aws s3 cp audit.csv s3://putzplan-archive/audit/ --object-lock-mode COMPLIANCE --object-lock-retain-until-date 2029-07-20
```

В архив попадают `chain_seq`, `prev_hash` и `row_hash` — этого достаточно,
чтобы проверить целостность отрезка независимо от базы.

## 10. Тесты

| Проверка | Файл |
|---|---|
| Последовательность `chain_seq` 1..N | `db/tests/30_audit_chain.sql` |
| `prev_hash` = `row_hash` предыдущей | там же |
| `prev_id` указывает на предыдущую запись | там же |
| `audit_verify_chain` → 0 нарушений | там же |
| `last_id` состояния указывает на последнюю запись | там же |
| UPDATE и DELETE отклоняются | там же |
| Цепочки арендаторов независимы | там же |
| 8 параллельных потоков × 25 записей: без разрывов и ветвления | `db/tests/40_concurrency.sql` |
| Запись под рабочей ролью запрещена | `db/tests/20_rls_and_context.sql` |
