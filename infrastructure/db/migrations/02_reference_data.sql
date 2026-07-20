-- ═══════════════════════════════════════════════════════════════════════════
-- 02_reference_data.sql · справочные данные платформы
-- Идемпотентна: повторный запуск не создаёт дублей.
-- Выполняется ролью putzplan_migration.
-- ═══════════════════════════════════════════════════════════════════════════
\set ON_ERROR_STOP on

-- Системные роли (общие для всех арендаторов)
INSERT INTO roles (company_id, key, name, description, is_system) VALUES
  (NULL,'super_admin',      'Owner / Super Admin','Владелец компании: полный доступ',true),
  (NULL,'admin',            'Administrator',      'Büroleitung: операционное управление',true),
  (NULL,'senior_dispatcher','Senior Dispatcher',  'Старший диспетчер: планирование и приёмка',true),
  (NULL,'dispatcher',       'Dispatcher',         'Einsatzleiter: планирование смен',true),
  (NULL,'worker',           'Mitarbeiter',        'Сотрудник: только свои задания',true)
ON CONFLICT DO NOTHING;

-- Реестр прав: домен.действие
INSERT INTO permissions (key, module, action, default_scope, description) VALUES
  ('planning.view','planning','view','company','Просмотр графика'),
  ('planning.create','planning','create','company','Создание заданий'),
  ('planning.edit','planning','edit','company','Изменение заданий'),
  ('planning.delete','planning','delete','company','Удаление заданий'),
  ('planning.assign','planning','assign','company','Назначение исполнителей'),
  ('planning.optimize','planning','optimize','company','Оптимизация графика'),
  ('planning.export','planning','export','company','Экспорт графика'),
  ('employees.view','employees','view','company','Просмотр сотрудников'),
  ('employees.edit','employees','edit','company','Изменение сотрудников'),
  ('employees.block','employees','block','company','Блокировка сотрудника'),
  ('employees.view_rate','employees','view_rate','company','Просмотр ставок'),
  ('employees.view_documents','employees','view_documents','company','Личные документы'),
  ('timesheets.view_own','timesheets','view_own','own','Свой табель'),
  ('timesheets.view_all','timesheets','view_all','company','Табель всех сотрудников'),
  ('timesheets.edit','timesheets','edit','company','Корректировка времени'),
  ('timesheets.approve','timesheets','approve','company','Подтверждение времени'),
  ('timesheets.export','timesheets','export','company','Экспорт табеля'),
  ('objects.view','objects','view','company','Просмотр объектов'),
  ('objects.edit','objects','edit','company','Изменение объектов'),
  ('objects.delete','objects','delete','company','Удаление объектов'),
  ('objects.view_access_secret','objects','view_access_secret','assigned','Коды, ключи, сигнализация'),
  ('objects.export','objects','export','company','Экспорт объектов'),
  ('clients.view','clients','view','company','Просмотр клиентов'),
  ('clients.edit','clients','edit','company','Изменение клиентов'),
  ('finance.view','finance','view','company','Финансы, прибыль, маржа'),
  ('finance.edit','finance','edit','company','Изменение цен'),
  ('finance.export','finance','export','company','Экспорт финансов'),
  ('materials.view','materials','view','company','Просмотр склада'),
  ('materials.edit','materials','edit','company','Изменение остатков'),
  ('materials.report_own','materials','report_own','own','Отчёт об остатках'),
  ('messages.view','messages','view','company','Сообщения и проблемы'),
  ('messages.send','messages','send','company','Отправка сообщений'),
  ('messages.own','messages','own','own','Переписка с диспетчером'),
  ('incidents.edit','incidents','edit','company','Обработка инцидентов'),
  ('issues.create_own','issues','create_own','own','Сообщение о проблеме'),
  ('photos.review','photos','review','company','Проверка фотоотчётов'),
  ('photos.upload_own','photos','upload_own','own','Загрузка своих фото'),
  ('jobs.view_own','jobs','view_own','own','Свои задания'),
  ('jobs.start_own','jobs','start_own','own','Начало и пауза смены'),
  ('jobs.finish_own','jobs','finish_own','own','Завершение и подпись'),
  ('absence.request_own','absence','request_own','own','Заявка на отсутствие'),
  ('users.view','users','view','company','Просмотр учётных записей'),
  ('users.invite','users','invite','company','Приглашение'),
  ('users.edit','users','edit','company','Изменение профиля'),
  ('users.disable','users','disable','company','Блокировка и увольнение'),
  ('users.delete','users','delete','company','Удаление учётной записи'),
  ('users.reset_password','users','reset_password','company','Сброс пароля и PIN'),
  ('sessions.revoke','sessions','revoke','company','Отзыв сессий и устройств'),
  ('roles.manage','roles','manage','company','Роли и права'),
  ('security.manage','security','manage','company','Настройки безопасности'),
  ('system.settings','system','settings','company','Системные параметры'),
  ('audit.view','audit','view','company','Журнал действий'),
  ('audit.view_all','audit','view_all','company','Журнал всех пользователей'),
  ('api_keys.manage','api_keys','manage','company','Интеграции и ключи API'),
  ('company.export','company','export','company','Экспорт всей базы'),
  ('company.delete','company','delete','company','Удаление компании'),
  ('settings.view','settings','view','company','Настройки компании'),
  ('billing.view','billing','view','company','Тариф и потребление'),
  ('billing.manage','billing','manage','company','Смена тарифа'),
  ('billing.cancel','billing','cancel','company','Отмена подписки'),
  ('billing.invoice.view','billing','invoice_view','company','Счета — просмотр'),
  ('billing.invoice.export','billing','invoice_export','company','Счета — выгрузка')
ON CONFLICT (key) DO NOTHING;

-- Привязка прав к системным ролям
WITH r AS (SELECT id, key FROM roles WHERE is_system),
     p AS (SELECT id, key FROM permissions)
INSERT INTO role_permissions (role_id, permission_id, scope)
SELECT r.id, p.id,
       CASE WHEN p.key LIKE '%_own' OR p.key = 'messages.own' THEN 'own'
            WHEN p.key = 'objects.view_access_secret' THEN 'assigned'
            ELSE 'company' END
FROM r JOIN p ON
  (r.key = 'super_admin')
  OR (r.key = 'admin' AND p.key NOT IN ('company.delete','company.export','security.manage','system.settings',
       'roles.manage','api_keys.manage','users.delete','users.reset_password','billing.manage','billing.cancel',
       'finance.view','finance.edit','finance.export','employees.view_rate'))
  OR (r.key = 'senior_dispatcher' AND p.key IN ('planning.view','planning.create','planning.edit','planning.delete',
       'planning.assign','planning.optimize','planning.export','employees.view','timesheets.view_all','timesheets.edit',
       'timesheets.approve','objects.view','objects.view_access_secret','clients.view','materials.view','materials.edit',
       'messages.view','messages.send','incidents.edit','photos.review','timesheets.view_own'))
  OR (r.key = 'dispatcher' AND p.key IN ('planning.view','planning.create','planning.edit','planning.assign',
       'planning.optimize','employees.view','timesheets.view_all','timesheets.approve','objects.view',
       'objects.view_access_secret','clients.view','materials.view','materials.edit','messages.view','messages.send',
       'incidents.edit','photos.review','timesheets.view_own'))
  OR (r.key = 'worker' AND p.key IN ('jobs.view_own','jobs.start_own','jobs.finish_own','photos.upload_own',
       'issues.create_own','materials.report_own','absence.request_own','messages.own','timesheets.view_own'))
ON CONFLICT DO NOTHING;

-- Тарифы платформы. Коммерческие условия — PRODUCT_AND_BILLING_POLICY.md
INSERT INTO plans (key, name, price_month, max_users, max_objects, max_storage_gb, max_api_calls) VALUES
  ('starter','Starter',49.00,10,25,5,50000),
  ('professional','Professional',149.00,60,150,50,250000),
  ('enterprise','Enterprise',399.00,5000,2000,500,2000000)
ON CONFLICT (key) DO NOTHING;

INSERT INTO plan_features (plan_id, feature_key)
SELECT p.id, f.key FROM plans p
CROSS JOIN LATERAL (VALUES
  ('planning'),('mobile'),('timesheets'),('materials'),('messages'),('csv_export')) AS f(key)
ON CONFLICT DO NOTHING;
INSERT INTO plan_features (plan_id, feature_key)
SELECT p.id, f.key FROM plans p
CROSS JOIN LATERAL (VALUES
  ('finance'),('routes'),('optimizer'),('photo_review'),('audit'),('api'),('datev_export'),('offline_sync')) AS f(key)
WHERE p.key IN ('professional','enterprise')
ON CONFLICT DO NOTHING;
INSERT INTO plan_features (plan_id, feature_key)
SELECT p.id, f.key FROM plans p
CROSS JOIN LATERAL (VALUES
  ('sso'),('multi_branch'),('custom_roles'),('webhooks'),('sla'),('data_residency'),('white_label')) AS f(key)
WHERE p.key = 'enterprise'
ON CONFLICT DO NOTHING;
