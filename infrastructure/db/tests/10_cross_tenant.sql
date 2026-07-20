-- Межарендаторная целостность: ребёнок компании A не может ссылаться на сущность компании B
\set ON_ERROR_STOP on
SELECT tst.suite('cross_tenant');

-- objects → clients
SELECT tst.throws('objects: клиент чужой компании отклонён',
$$INSERT INTO objects (company_id,client_id,name,norm_minutes)
  VALUES ('11111111-1111-1111-1111-111111111111','c2222222-0000-0000-0000-000000000002','Хак',60)$$,
'23503');

-- jobs → objects
SELECT tst.throws('jobs: объект чужой компании отклонён',
$$INSERT INTO jobs (company_id,object_id,date,start_time,duration_min,service_type)
  VALUES ('11111111-1111-1111-1111-111111111111','02222222-0000-0000-0000-000000000002',
          CURRENT_DATE,'09:00',60,'X')$$,
'23503');

-- job_assignments → employees
SELECT tst.throws('job_assignments: сотрудник чужой компании отклонён',
$$INSERT INTO job_assignments (company_id,job_id,employee_id)
  VALUES ('11111111-1111-1111-1111-111111111111','11110000-0000-0000-0000-000000000001',
          'e2222222-0000-0000-0000-000000000002')$$,
'23503');

-- timesheets → jobs
SELECT tst.throws('timesheets: задание чужой компании отклонено',
$$INSERT INTO timesheets (company_id,job_id,employee_id,work_date,planned_min,actual_min)
  VALUES ('11111111-1111-1111-1111-111111111111','22220000-0000-0000-0000-000000000002',
          'e1111111-0000-0000-0000-000000000001',CURRENT_DATE,60,60)$$,
'23503');

-- inventory → materials
SELECT tst.throws('inventory: материал чужой компании отклонён',
$$INSERT INTO inventory (company_id,object_id,material_id,qty)
  VALUES ('11111111-1111-1111-1111-111111111111','01111111-0000-0000-0000-000000000001',
          'a2222222-0000-0000-0000-000000000002',5)$$,
'23503');

-- incidents → objects
SELECT tst.throws('incidents: объект чужой компании отклонён',
$$INSERT INTO incidents (company_id,object_id,category,description)
  VALUES ('11111111-1111-1111-1111-111111111111','02222222-0000-0000-0000-000000000002','Жалоба','текст')$$,
'23503');

-- photos → jobs
SELECT tst.throws('photos: задание чужой компании отклонено',
$$INSERT INTO photos (company_id,job_id,kind,storage_key)
  VALUES ('11111111-1111-1111-1111-111111111111','22220000-0000-0000-0000-000000000002','before','k1')$$,
'23503');

-- client_contacts → clients
SELECT tst.throws('client_contacts: клиент чужой компании отклонён',
$$INSERT INTO client_contacts (company_id,client_id,name)
  VALUES ('11111111-1111-1111-1111-111111111111','c2222222-0000-0000-0000-000000000002','Контакт')$$,
'23503');

-- departments → branches
SELECT tst.throws('departments: филиал чужой компании отклонён',
$$INSERT INTO departments (company_id,branch_id,name)
  VALUES ('11111111-1111-1111-1111-111111111111','b2222222-0000-0000-0000-000000000002','Отдел')$$,
'23503');

-- users → employees
SELECT tst.throws('users: сотрудник чужой компании отклонён',
$$INSERT INTO users (company_id,role_id,email,status,employee_id)
  SELECT '11111111-1111-1111-1111-111111111111',r.id,'hack@test.local','active',
         'e2222233-0000-0000-0000-000000000003' FROM roles r WHERE r.key='worker'$$,
'23503');

-- objects → employees (основной исполнитель)
SELECT tst.throws('objects: основной исполнитель чужой компании отклонён',
$$UPDATE objects SET main_employee_id='e2222222-0000-0000-0000-000000000002'
  WHERE id='01111111-0000-0000-0000-000000000001'$$,
'23503');

-- UPDATE тоже проверяется, не только INSERT
SELECT tst.throws('jobs UPDATE: перенос на чужой объект отклонён',
$$UPDATE jobs SET object_id='02222222-0000-0000-0000-000000000002'
  WHERE id='11110000-0000-0000-0000-000000000001'$$,
'23503');

-- Позитив: своя связь работает
SELECT tst.lives('objects: свой клиент принимается',
$$INSERT INTO objects (id,company_id,client_id,name,norm_minutes)
  VALUES ('01111111-0000-0000-0000-00000000000f','11111111-1111-1111-1111-111111111111',
          'c1111111-0000-0000-0000-000000000001','Object A2',60)
  ON CONFLICT (id) DO NOTHING$$);

-- Составные ключи существуют физически
SELECT tst.ok('составных FK не менее 40',
  (SELECT count(*) FROM pg_constraint WHERE contype='f' AND conname LIKE '%same_company_fk') >= 40,
  (SELECT count(*)::text FROM pg_constraint WHERE contype='f' AND conname LIKE '%same_company_fk'));

SELECT tst.ok('UNIQUE (company_id,id) у ключевых родителей',
  (SELECT count(*) FROM pg_constraint WHERE contype='u' AND conname LIKE '%_company_id_uq') >= 15);
