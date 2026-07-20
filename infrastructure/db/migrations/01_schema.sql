-- ═══════════════════════════════════════════════════════════════════════════
-- 01_schema.sql · PUTZPLAN · структура базы
-- Выполняется ролью putzplan_migration после 00_platform_bootstrap.sql:
--   psql -v ON_ERROR_STOP=1 -U putzplan_migration -d putzplan -f 01_schema.sql
-- Содержит: типы, таблицы, межарендаторные ограничения, партиции,
-- триггеры, RLS. Прав и справочных данных здесь нет.
-- ═══════════════════════════════════════════════════════════════════════════
\set ON_ERROR_STOP on

-- ── 3. Перечисления ────────────────────────────────────────────────────────
CREATE TYPE user_status AS ENUM
  ('invited','active','temporarily_blocked','on_leave','sick','password_reset','terminated','archived');
CREATE TYPE subscription_status AS ENUM
  ('trialing','active','past_due','suspended','cancelled','archived');
CREATE TYPE job_status AS ENUM
  ('planned','arrived','running','paused','done','cancelled');
CREATE TYPE timesheet_status AS ENUM
  ('draft','pending_review','approved','exported','rejected');
CREATE TYPE sync_status AS ENUM
  ('saved_local','queued','uploading','synced','conflict','failed');
CREATE TYPE secret_kind AS ENUM ('key','door_code','alarm_code','contact');
CREATE TYPE photo_kind  AS ENUM ('before','after','damage','material','closed','signature');
CREATE TYPE channel_kind AS ENUM ('app','push','email','sms','whatsapp');
CREATE TYPE actor_kind  AS ENUM ('user','api_key','service','system');

-- ── 4. Арендатор ───────────────────────────────────────────────────────────
CREATE TABLE companies (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name          text NOT NULL,
  legal_name    text,
  bundesland    text NOT NULL DEFAULT 'Bayern',
  data_region   text NOT NULL DEFAULT 'eu-central-1',
  settings      jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz,
  deleted_at    timestamptz,
  created_by    uuid,                       -- FK на users добавляется ниже
  updated_by    uuid,
  CONSTRAINT companies_name_not_blank CHECK (length(btrim(name)) > 0)
);

CREATE TABLE branches (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  name          text NOT NULL,
  city          text,
  address       text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz,
  deleted_at    timestamptz,
  created_by    uuid,
  updated_by    uuid
);

CREATE TABLE departments (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  branch_id     uuid REFERENCES branches(id) ON DELETE SET NULL,
  name          text NOT NULL,
  zone          text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz,
  deleted_at    timestamptz,
  created_by    uuid,
  updated_by    uuid
);

-- ── 5. Роли и права ────────────────────────────────────────────────────────
CREATE TABLE roles (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid REFERENCES companies(id) ON DELETE CASCADE,  -- NULL = системная роль
  key           text NOT NULL,
  name          text NOT NULL,
  description   text,
  is_system     boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now(),
  created_by    uuid,
  CONSTRAINT roles_system_has_no_company CHECK (NOT is_system OR company_id IS NULL)
);
CREATE UNIQUE INDEX roles_company_key_uq  ON roles (company_id, key) WHERE company_id IS NOT NULL;
CREATE UNIQUE INDEX roles_system_key_uq   ON roles (key)             WHERE company_id IS NULL;

CREATE TABLE permissions (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  key           text NOT NULL UNIQUE,          -- домен.действие, напр. planning.edit
  module        text NOT NULL,
  action        text NOT NULL,
  default_scope text NOT NULL DEFAULT 'company'
                CHECK (default_scope IN ('own','assigned','department','company','all')),
  description   text
);

CREATE TABLE role_permissions (
  role_id       uuid NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
  permission_id uuid NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  scope         text NOT NULL DEFAULT 'company'
                CHECK (scope IN ('own','assigned','department','company','all')),
  PRIMARY KEY (role_id, permission_id)
);

-- ── 6. Кадры ───────────────────────────────────────────────────────────────
CREATE TABLE employees (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id        uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  department_id     uuid REFERENCES departments(id) ON DELETE SET NULL,
  first_name        text NOT NULL,
  last_name         text NOT NULL,
  phone             text,
  email             citext,
  address           text,
  language          text,
  hourly_rate       numeric(6,2) CHECK (hourly_rate IS NULL OR hourly_rate >= 0),
  pay_type          text CHECK (pay_type IS NULL OR pay_type IN ('Festanstellung','Teilzeit','Minijob','Werkvertrag')),
  max_hours_day     integer CHECK (max_hours_day IS NULL OR max_hours_day BETWEEN 1 AND 16),
  skills            text[] NOT NULL DEFAULT '{}',
  zones             text[] NOT NULL DEFAULT '{}',
  has_car           boolean NOT NULL DEFAULT false,
  employment_status text NOT NULL DEFAULT 'active',
  hired_at          date,
  terminated_at     date,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz,
  deleted_at        timestamptz,
  created_by        uuid,
  updated_by        uuid,
  CONSTRAINT employees_term_after_hire CHECK (terminated_at IS NULL OR hired_at IS NULL OR terminated_at >= hired_at)
);

-- ── 7. Пользователи и доступ ───────────────────────────────────────────────
CREATE TABLE users (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id            uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  branch_id             uuid REFERENCES branches(id) ON DELETE SET NULL,
  department_id         uuid REFERENCES departments(id) ON DELETE SET NULL,
  employee_id           uuid,                        -- FK ниже (цикл с employees)
  role_id               uuid NOT NULL,               -- FK ниже (roles создан выше, но FK единым блоком)
  email                 citext,
  phone                 text,
  position              text,
  password_hash         text,                        -- argon2id, NULL до активации
  password_changed_at   timestamptz,
  must_change_password  boolean NOT NULL DEFAULT false,
  pin_hash              text,
  pin_set_at            timestamptz,
  status                user_status NOT NULL DEFAULT 'invited',
  status_reason         text,
  failed_attempts       integer NOT NULL DEFAULT 0 CHECK (failed_attempts >= 0),
  locked_until          timestamptz,
  last_login_at         timestamptz,
  last_seen_at          timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz,
  deleted_at            timestamptz,
  created_by            uuid,
  updated_by            uuid,
  CONSTRAINT users_login_present CHECK (email IS NOT NULL OR phone IS NOT NULL),
  CONSTRAINT users_status_reason_required
    CHECK (status NOT IN ('temporarily_blocked','terminated') OR status_reason IS NOT NULL)
);
CREATE UNIQUE INDEX users_email_uq ON users (company_id, lower(email::text))
  WHERE email IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX users_phone_uq ON users (company_id, phone)
  WHERE phone IS NOT NULL AND deleted_at IS NULL;
CREATE UNIQUE INDEX users_employee_uq ON users (employee_id)
  WHERE employee_id IS NOT NULL AND deleted_at IS NULL;
CREATE INDEX users_role_status_ix ON users (company_id, role_id, status);

CREATE TABLE user_permissions (
  user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  permission_id uuid NOT NULL REFERENCES permissions(id) ON DELETE CASCADE,
  effect        text NOT NULL CHECK (effect IN ('grant','deny')),
  scope         text CHECK (scope IS NULL OR scope IN ('own','assigned','department','company','all')),
  valid_until   timestamptz,
  reason        text,
  grantor_id    uuid,                                -- FK ниже
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, permission_id)
);

CREATE TABLE trusted_devices (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id      uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  user_id         uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  label           text,
  platform        text CHECK (platform IS NULL OR platform IN ('ios','android','web','desktop')),
  fingerprint_hash text NOT NULL,
  trusted_until   timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  revoked_at      timestamptz
);
CREATE UNIQUE INDEX trusted_devices_uq ON trusted_devices (user_id, fingerprint_hash) WHERE revoked_at IS NULL;

CREATE TABLE sessions (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id           uuid REFERENCES trusted_devices(id) ON DELETE SET NULL,
  refresh_token_hash  text NOT NULL UNIQUE,
  ip                  inet,
  user_agent          text,
  created_at          timestamptz NOT NULL DEFAULT now(),
  last_seen_at        timestamptz,
  expires_at          timestamptz NOT NULL,
  revoked_at          timestamptz,
  revoked_by          uuid,                          -- FK ниже
  revoke_reason       text,
  CONSTRAINT sessions_expiry_ok CHECK (expires_at > created_at)
);
CREATE INDEX sessions_user_active_ix ON sessions (user_id) WHERE revoked_at IS NULL;

CREATE TABLE invitations (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  channel       text NOT NULL CHECK (channel IN ('email','sms')),
  token_hash    text NOT NULL UNIQUE,
  expires_at    timestamptz NOT NULL,
  accepted_at   timestamptz,
  revoked_at    timestamptz,
  revoke_reason text,
  resend_count  integer NOT NULL DEFAULT 0 CHECK (resend_count >= 0),
  sent_by       uuid,                                -- FK ниже
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX invitations_open_ix ON invitations (company_id) WHERE accepted_at IS NULL AND revoked_at IS NULL;

CREATE TABLE password_history (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  password_hash text NOT NULL,
  changed_by    uuid,                                -- FK ниже
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX password_history_user_ix ON password_history (user_id, created_at DESC);

CREATE TABLE two_factor_methods (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind          text NOT NULL CHECK (kind IN ('totp','sms','email')),
  secret_enc    bytea,
  confirmed_at  timestamptz,
  is_primary    boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX two_factor_primary_uq ON two_factor_methods (user_id) WHERE is_primary;

CREATE TABLE login_attempts (
  id              bigint GENERATED ALWAYS AS IDENTITY,
  company_id      uuid,
  user_id         uuid,
  login           text,
  ip              inet,
  user_agent      text,
  success         boolean NOT NULL,
  failure_reason  text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- ── 8. Клиенты и объекты ───────────────────────────────────────────────────
CREATE TABLE clients (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id      uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  name            text NOT NULL,
  legal_name      text,
  client_type     text,
  contact_name    text,
  phone           text,
  email           citext,
  billing_address text,
  payment_terms   text,
  ust_id          text,
  status          text NOT NULL DEFAULT 'active',
  note            text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz,
  deleted_at      timestamptz,
  created_by      uuid,
  updated_by      uuid
);
CREATE INDEX clients_company_ix ON clients (company_id) WHERE deleted_at IS NULL;

CREATE TABLE objects (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id      uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  client_id       uuid NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
  branch_id       uuid REFERENCES branches(id) ON DELETE SET NULL,
  department_id   uuid REFERENCES departments(id) ON DELETE SET NULL,
  name            text NOT NULL,
  street          text,
  zip             text,
  city            text,
  district        text,
  location        geography(Point,4326),
  object_type     text,
  area_sqm        integer CHECK (area_sqm IS NULL OR area_sqm >= 0),
  floors          integer CHECK (floors IS NULL OR floors >= 0),
  rooms           integer CHECK (rooms IS NULL OR rooms >= 0),
  clean_type      text,
  frequency       text,
  crew_size       integer NOT NULL DEFAULT 1 CHECK (crew_size BETWEEN 1 AND 20),
  norm_minutes    integer NOT NULL DEFAULT 60 CHECK (norm_minutes BETWEEN 15 AND 1440),
  price_month     numeric(10,2) CHECK (price_month IS NULL OR price_month >= 0),
  price_visit     numeric(10,2) CHECK (price_visit IS NULL OR price_visit >= 0),
  access_hours    text,
  parking         text,
  storage_place   text,
  instructions    text,
  risks           text,
  main_employee_id   uuid REFERENCES employees(id) ON DELETE SET NULL,
  backup_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
  leader_employee_id uuid REFERENCES employees(id) ON DELETE SET NULL,
  contract_start  date,
  contract_end    date,
  notice_period   text,
  active          boolean NOT NULL DEFAULT true,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz,
  deleted_at      timestamptz,
  created_by      uuid,
  updated_by      uuid,
  CONSTRAINT objects_contract_period CHECK (contract_end IS NULL OR contract_start IS NULL OR contract_end >= contract_start)
);
CREATE INDEX objects_geo_ix     ON objects USING gist (location);
CREATE INDEX objects_client_ix  ON objects (company_id, client_id) WHERE deleted_at IS NULL;

CREATE TABLE object_access_secrets (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id        uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  object_id         uuid NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
  kind              secret_kind NOT NULL,
  value_enc         bytea NOT NULL,
  reveal_window_min integer NOT NULL DEFAULT 120 CHECK (reveal_window_min BETWEEN 15 AND 1440),
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz,
  updated_by        uuid
);
CREATE UNIQUE INDEX object_secret_kind_uq ON object_access_secrets (object_id, kind);

-- ── 9. Планирование и работа ───────────────────────────────────────────────
CREATE TABLE job_series (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id     uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  object_id      uuid NOT NULL REFERENCES objects(id) ON DELETE RESTRICT,
  employee_id    uuid REFERENCES employees(id) ON DELETE SET NULL,
  start_time     time NOT NULL,
  duration_min   integer NOT NULL CHECK (duration_min BETWEEN 15 AND 720),
  service_type   text NOT NULL,
  rule           jsonb NOT NULL,
  holiday_policy text NOT NULL DEFAULT 'skip' CHECK (holiday_policy IN ('skip','shift','ignore')),
  valid_from     date NOT NULL,
  valid_until    date,
  note           text,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz,
  deleted_at     timestamptz,
  created_by     uuid,
  updated_by     uuid,
  CONSTRAINT series_period_ok CHECK (valid_until IS NULL OR valid_until >= valid_from)
);

CREATE TABLE jobs (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id          uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  series_id           uuid REFERENCES job_series(id) ON DELETE SET NULL,
  object_id           uuid NOT NULL REFERENCES objects(id) ON DELETE RESTRICT,
  date                date NOT NULL,
  start_time          time NOT NULL,
  duration_min        integer NOT NULL CHECK (duration_min BETWEEN 15 AND 720),
  service_type        text NOT NULL,
  note                text,
  status              job_status NOT NULL DEFAULT 'planned',
  cancel_reason       text,
  actual_min          integer CHECK (actual_min IS NULL OR actual_min BETWEEN 1 AND 1440),
  pause_min           integer NOT NULL DEFAULT 0 CHECK (pause_min >= 0),
  arrived_at          timestamptz,
  started_at          timestamptz,
  finished_at         timestamptz,
  gps_point           geography(Point,4326),
  gps_accuracy_m      integer CHECK (gps_accuracy_m IS NULL OR gps_accuracy_m >= 0),
  gps_deviation_reason text,
  photo_waiver_reason text,
  signature_skip_reason text,
  server_rev          integer NOT NULL DEFAULT 1 CHECK (server_rev > 0),
  synced_at           timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz,
  deleted_at          timestamptz,
  created_by          uuid,
  updated_by          uuid,
  CONSTRAINT jobs_date_sane   CHECK (date >= DATE '2020-01-01'),
  CONSTRAINT jobs_cancel_reason CHECK (status <> 'cancelled' OR cancel_reason IS NOT NULL),
  CONSTRAINT jobs_finish_order CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at)
);
CREATE INDEX jobs_company_date_ix ON jobs (company_id, date) WHERE deleted_at IS NULL;
CREATE INDEX jobs_object_date_ix  ON jobs (object_id, date);
CREATE INDEX jobs_series_ix       ON jobs (series_id) WHERE series_id IS NOT NULL;

CREATE TABLE job_assignments (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  job_id        uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  employee_id   uuid NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
  role_on_site  text,
  assigned_at   timestamptz NOT NULL DEFAULT now(),
  assigned_by   uuid,                               -- FK ниже
  unassigned_at timestamptz,
  reason        text
);
CREATE UNIQUE INDEX job_assign_active_uq ON job_assignments (job_id, employee_id) WHERE unassigned_at IS NULL;
CREATE INDEX job_assign_emp_ix ON job_assignments (employee_id) WHERE unassigned_at IS NULL;

CREATE TABLE checklists (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  service_type  text NOT NULL,
  name          text NOT NULL,
  version       integer NOT NULL DEFAULT 1 CHECK (version > 0),
  active        boolean NOT NULL DEFAULT true,
  created_at    timestamptz NOT NULL DEFAULT now(),
  created_by    uuid
);
CREATE UNIQUE INDEX checklists_active_uq ON checklists (company_id, service_type, version);

CREATE TABLE checklist_items (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  checklist_id    uuid NOT NULL REFERENCES checklists(id) ON DELETE CASCADE,
  position        integer NOT NULL CHECK (position >= 0),
  text            text NOT NULL,
  required        boolean NOT NULL DEFAULT false,
  photo_required  boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX checklist_items_pos_uq ON checklist_items (checklist_id, position);

CREATE TABLE checklist_results (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id  uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  job_id      uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  item_id     uuid NOT NULL REFERENCES checklist_items(id) ON DELETE RESTRICT,
  checked     boolean NOT NULL DEFAULT false,
  checked_at  timestamptz,
  note        text,
  CONSTRAINT checklist_result_uq UNIQUE (job_id, item_id)
);

CREATE TABLE timesheets (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id        uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  job_id            uuid NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
  employee_id       uuid NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
  work_date         date NOT NULL,
  planned_min       integer NOT NULL CHECK (planned_min >= 0),
  actual_min        integer NOT NULL CHECK (actual_min >= 0),
  pause_min         integer NOT NULL DEFAULT 0 CHECK (pause_min >= 0),
  travel_min        integer NOT NULL DEFAULT 0 CHECK (travel_min >= 0),
  night_min         integer NOT NULL DEFAULT 0 CHECK (night_min >= 0),
  is_sunday         boolean NOT NULL DEFAULT false,
  is_holiday        boolean NOT NULL DEFAULT false,
  correction_min    integer,
  correction_reason text,
  status            timesheet_status NOT NULL DEFAULT 'draft',
  approved_by       uuid,                            -- FK ниже
  approved_at       timestamptz,
  exported_at       timestamptz,
  created_at        timestamptz NOT NULL DEFAULT now(),
  updated_at        timestamptz,
  CONSTRAINT timesheet_job_uq UNIQUE (job_id),
  CONSTRAINT timesheet_correction_reason CHECK (correction_min IS NULL OR correction_reason IS NOT NULL),
  CONSTRAINT timesheet_approved_fields CHECK (status <> 'approved' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL))
);
CREATE INDEX timesheets_emp_date_ix ON timesheets (company_id, employee_id, work_date);

CREATE TABLE photos (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id      uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  job_id          uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  kind            photo_kind NOT NULL,
  storage_key     text NOT NULL,
  sha256          text,
  size_bytes      bigint CHECK (size_bytes IS NULL OR size_bytes BETWEEN 1 AND 20971520),
  taken_at        timestamptz,
  uploaded_at     timestamptz NOT NULL DEFAULT now(),
  uploaded_by     uuid,                              -- FK ниже
  review_status   text NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending','accepted','rejected')),
  review_note     text,
  reviewed_by     uuid,                              -- FK ниже
  reviewed_at     timestamptz,
  retention_until date
);
CREATE UNIQUE INDEX photos_storage_uq ON photos (storage_key);
CREATE INDEX photos_job_ix ON photos (job_id);

CREATE TABLE signatures (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  job_id        uuid NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  signed_by     text,
  storage_key   text,
  signed_at     timestamptz NOT NULL DEFAULT now(),
  skip_reason   text,
  CONSTRAINT signature_job_uq UNIQUE (job_id),
  CONSTRAINT signature_present CHECK (storage_key IS NOT NULL OR skip_reason IS NOT NULL)
);

CREATE TABLE incidents (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  object_id     uuid REFERENCES objects(id) ON DELETE SET NULL,
  job_id        uuid REFERENCES jobs(id) ON DELETE SET NULL,
  employee_id   uuid REFERENCES employees(id) ON DELETE SET NULL,
  client_id     uuid REFERENCES clients(id) ON DELETE SET NULL,
  category      text NOT NULL,
  priority      text NOT NULL DEFAULT 'mittel' CHECK (priority IN ('niedrig','mittel','hoch')),
  status        text NOT NULL DEFAULT 'new' CHECK (status IN ('new','in_progress','waiting_client','resolved','closed')),
  description   text NOT NULL,
  solution      text,
  due_date      date,
  responsible_id uuid,                               -- FK ниже
  created_at    timestamptz NOT NULL DEFAULT now(),
  created_by    uuid,
  closed_at     timestamptz,
  CONSTRAINT incident_resolution CHECK (status NOT IN ('resolved','closed') OR solution IS NOT NULL)
);
CREATE INDEX incidents_open_ix ON incidents (company_id, status) WHERE status NOT IN ('resolved','closed');

CREATE TABLE absences (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  employee_id   uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
  kind          text NOT NULL CHECK (kind IN ('krank','urlaub','frei','schulung','sperre','kein_auto','teil')),
  date_from     date NOT NULL,
  date_to       date NOT NULL,
  note          text,
  requested_by  uuid,                                -- FK ниже
  approved_by   uuid,                                -- FK ниже
  approved_at   timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT absence_period_ok CHECK (date_to >= date_from)
);
CREATE INDEX absences_emp_period_ix ON absences (employee_id, date_from, date_to);

-- ── 10. Материалы и склад ──────────────────────────────────────────────────
CREATE TABLE materials (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id  uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name        text NOT NULL,
  category    text,
  unit        text NOT NULL DEFAULT 'Stk',
  price       numeric(8,2) CHECK (price IS NULL OR price >= 0),
  active      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz,
  deleted_at  timestamptz,
  created_by  uuid,
  updated_by  uuid
);
CREATE UNIQUE INDEX materials_name_uq ON materials (company_id, lower(name)) WHERE deleted_at IS NULL;

CREATE TABLE inventory (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  object_id     uuid NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
  material_id   uuid NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
  qty           numeric(10,2) NOT NULL DEFAULT 0 CHECK (qty >= 0),
  min_qty       numeric(10,2) NOT NULL DEFAULT 0 CHECK (min_qty >= 0),
  per_month     numeric(10,2) NOT NULL DEFAULT 0 CHECK (per_month >= 0),
  storage_place text,
  responsible_id uuid,                               -- FK ниже
  last_delivery date,
  next_delivery date,
  updated_at    timestamptz,
  CONSTRAINT inventory_uq UNIQUE (object_id, material_id)
);

CREATE TABLE stock_movements (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  company_id   uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  object_id    uuid NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
  material_id  uuid NOT NULL REFERENCES materials(id) ON DELETE RESTRICT,
  delta        numeric(10,2) NOT NULL CHECK (delta <> 0),
  reason       text NOT NULL,
  job_id       uuid REFERENCES jobs(id) ON DELETE SET NULL,
  created_by   uuid,                                 -- FK ниже
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX stock_mov_obj_ix ON stock_movements (object_id, created_at DESC);

-- ── 11. Связь ──────────────────────────────────────────────────────────────
CREATE TABLE messages (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  sender_id     uuid,                                -- FK ниже (NULL = система)
  recipient     jsonb NOT NULL,                      -- {"kind":"all"|"user"|"object","id":"…"}
  subject       text NOT NULL,
  body          text NOT NULL,
  urgent        boolean NOT NULL DEFAULT false,
  created_at    timestamptz NOT NULL DEFAULT now(),
  deleted_at    timestamptz
);
CREATE INDEX messages_company_ix ON messages (company_id, created_at DESC);

CREATE TABLE message_reads (
  message_id  uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  read_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (message_id, user_id)
);

-- ── 12. Подписка и биллинг ─────────────────────────────────────────────────
CREATE TABLE plans (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  key            text NOT NULL UNIQUE,
  name           text NOT NULL,
  price_month    numeric(8,2) NOT NULL CHECK (price_month >= 0),
  max_users      integer NOT NULL CHECK (max_users > 0),
  max_objects    integer NOT NULL CHECK (max_objects > 0),
  max_storage_gb integer NOT NULL CHECK (max_storage_gb > 0),
  max_api_calls  integer NOT NULL CHECK (max_api_calls > 0),
  active         boolean NOT NULL DEFAULT true
);

CREATE TABLE plan_features (
  plan_id     uuid NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  feature_key text NOT NULL,
  enabled     boolean NOT NULL DEFAULT true,
  PRIMARY KEY (plan_id, feature_key)
);

CREATE TABLE company_feature_overrides (
  company_id  uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  feature_key text NOT NULL,
  enabled     boolean NOT NULL,
  reason      text,
  valid_until timestamptz,
  granted_by  uuid,                                  -- FK ниже
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (company_id, feature_key)
);

CREATE TABLE subscriptions (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id              uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  plan_id                 uuid NOT NULL REFERENCES plans(id) ON DELETE RESTRICT,
  status                  subscription_status NOT NULL DEFAULT 'trialing',
  trial_ends_at           timestamptz,
  current_period_start    date NOT NULL,
  current_period_end      date NOT NULL,
  cancel_at               timestamptz,
  cancel_reason           text,
  external_customer_id    text,
  external_subscription_id text,
  created_at              timestamptz NOT NULL DEFAULT now(),
  updated_at              timestamptz,
  updated_by              uuid,                      -- FK ниже
  CONSTRAINT sub_period_ok CHECK (current_period_end > current_period_start)
);
CREATE UNIQUE INDEX subscriptions_company_uq ON subscriptions (company_id) WHERE status <> 'archived';

CREATE TABLE invoices (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id    uuid NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  client_id     uuid REFERENCES clients(id) ON DELETE SET NULL,   -- NULL = счёт платформы арендатору
  subscription_id uuid REFERENCES subscriptions(id) ON DELETE SET NULL,
  number        text NOT NULL,
  period_start  date NOT NULL,
  period_end    date NOT NULL,
  amount_net    numeric(12,2) NOT NULL CHECK (amount_net >= 0),
  vat_rate      numeric(5,2) NOT NULL DEFAULT 19.00 CHECK (vat_rate >= 0),
  vat_amount    numeric(12,2) NOT NULL DEFAULT 0 CHECK (vat_amount >= 0),
  status        text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','paid','overdue','void')),
  sent_at       timestamptz,
  paid_at       timestamptz,
  external_ref  text,
  created_at    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT invoice_number_uq UNIQUE (company_id, number),
  CONSTRAINT invoice_period_ok CHECK (period_end >= period_start)
);

CREATE TABLE usage_counters (
  company_id  uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  period      date NOT NULL,
  metric      text NOT NULL,
  value       bigint NOT NULL DEFAULT 0 CHECK (value >= 0),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (company_id, period, metric)
);

-- ── 13. Интеграции ─────────────────────────────────────────────────────────
CREATE TABLE api_credentials (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id         uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  name               text NOT NULL,
  key_prefix         text NOT NULL UNIQUE,
  key_hash           text NOT NULL,
  scopes             text[] NOT NULL DEFAULT '{}',
  rate_limit_per_min integer NOT NULL DEFAULT 60 CHECK (rate_limit_per_min > 0),
  created_by         uuid,                           -- FK ниже
  created_at         timestamptz NOT NULL DEFAULT now(),
  expires_at         timestamptz,
  revoked_at         timestamptz,
  last_used_at       timestamptz
);

CREATE TABLE webhooks (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id      uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  url             text NOT NULL CHECK (url LIKE 'https://%'),
  secret_hash     text NOT NULL,
  event_types     text[] NOT NULL DEFAULT '{}',
  active          boolean NOT NULL DEFAULT true,
  created_by      uuid,                              -- FK ниже
  created_at      timestamptz NOT NULL DEFAULT now(),
  last_success_at timestamptz,
  last_failure_at timestamptz,
  failure_count   integer NOT NULL DEFAULT 0 CHECK (failure_count >= 0),
  CONSTRAINT webhook_url_uq UNIQUE (company_id, url)
);

CREATE TABLE service_accounts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name        text NOT NULL UNIQUE,
  scopes      text[] NOT NULL DEFAULT '{}',
  active      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE client_contacts (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id     uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  client_id      uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  name           text NOT NULL,
  email          citext,
  phone          text,
  portal_enabled boolean NOT NULL DEFAULT false,
  password_hash  text,
  last_login_at  timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  deleted_at     timestamptz
);
CREATE UNIQUE INDEX client_contacts_email_uq ON client_contacts (company_id, lower(email::text))
  WHERE email IS NOT NULL AND deleted_at IS NULL;

-- ── 14. Синхронизация ──────────────────────────────────────────────────────
CREATE TABLE sync_queue (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id        uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  user_id           uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id         uuid REFERENCES trusted_devices(id) ON DELETE SET NULL,
  local_id          text NOT NULL,
  kind              text NOT NULL,
  job_id            uuid REFERENCES jobs(id) ON DELETE SET NULL,
  payload           jsonb NOT NULL,
  created_at_device timestamptz NOT NULL,
  timezone          text NOT NULL DEFAULT 'Europe/Berlin',
  base_rev          integer,
  status            sync_status NOT NULL DEFAULT 'queued',
  retry_count       integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
  last_error        text,
  server_id         uuid,
  synced_at         timestamptz,
  CONSTRAINT sync_local_uq UNIQUE (user_id, local_id)
);
CREATE INDEX sync_pending_ix ON sync_queue (company_id, status) WHERE status <> 'synced';

-- ── 15. События, уведомления, журнал (партиционированные) ──────────────────
CREATE TABLE domain_events (
  id             uuid NOT NULL DEFAULT gen_random_uuid(),
  company_id     uuid NOT NULL,
  type           text NOT NULL,
  version        integer NOT NULL DEFAULT 1,
  aggregate_type text,
  aggregate_id   uuid,
  actor_id       uuid,
  actor_kind     actor_kind NOT NULL DEFAULT 'user',
  payload        jsonb NOT NULL DEFAULT '{}'::jsonb,
  targets        text[] NOT NULL DEFAULT '{}',
  correlation_id text,
  causation_id   uuid,
  occurred_at    timestamptz NOT NULL,
  recorded_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, recorded_at)
) PARTITION BY RANGE (recorded_at);

CREATE TABLE outbox (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  event_id        uuid NOT NULL,
  event_recorded_at timestamptz NOT NULL,
  channel         text NOT NULL,
  status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','dead')),
  attempts        integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  next_attempt_at timestamptz,
  last_error      text,
  created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX outbox_pending_ix ON outbox (next_attempt_at) WHERE status = 'pending';

CREATE TABLE notifications (
  id          uuid NOT NULL DEFAULT gen_random_uuid(),
  company_id  uuid NOT NULL,
  event_id    uuid,
  user_id     uuid NOT NULL,
  type        text NOT NULL,
  urgent      boolean NOT NULL DEFAULT false,
  title       text NOT NULL,
  body        text,
  deep_link   text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  read_at     timestamptz,
  archived_at timestamptz,
  PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

CREATE TABLE notification_deliveries (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  notification_id     uuid NOT NULL,
  notification_created_at timestamptz NOT NULL,
  channel             channel_kind NOT NULL,
  status              text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','delivered','failed','skipped')),
  provider_message_id text,
  attempts            integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
  sent_at             timestamptz,
  delivered_at        timestamptz,
  failed_at           timestamptz,
  error               text
);

CREATE TABLE notification_preferences (
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  event_type text NOT NULL,
  channel    channel_kind NOT NULL,
  enabled    boolean NOT NULL DEFAULT true,
  PRIMARY KEY (user_id, event_type, channel)
);

CREATE TABLE push_tokens (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  device_id  uuid REFERENCES trusted_devices(id) ON DELETE SET NULL,
  platform   text NOT NULL CHECK (platform IN ('ios','android','web')),
  token      text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  revoked_at timestamptz
);
CREATE UNIQUE INDEX push_tokens_uq ON push_tokens (token) WHERE revoked_at IS NULL;

-- Журнал: только вставка. Хеш-цепочка обеспечивает обнаружение подмены.
CREATE TABLE audit_logs (
  id            bigint GENERATED ALWAYS AS IDENTITY,
  company_id    uuid NOT NULL,
  request_id    text,
  user_id       uuid,
  actor_kind    actor_kind NOT NULL DEFAULT 'user',
  actor_role    text,
  action        text NOT NULL,
  entity        text,
  entity_id     uuid,
  before        jsonb,
  after         jsonb,
  reason        text,
  ip            inet,
  user_agent    text,
  device        text,
  http_status   integer,
  chain_seq     bigint NOT NULL,          -- монотонный номер записи внутри компании
  prev_id       bigint,                   -- идентификатор предыдущей записи цепочки
  prev_hash     text NOT NULL,
  row_hash      text NOT NULL,
  server_time   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (id, server_time),
  CONSTRAINT audit_chain_seq_positive CHECK (chain_seq > 0)
) PARTITION BY RANGE (server_time);

CREATE TABLE secret_reveals (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  company_id  uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
  object_id   uuid NOT NULL REFERENCES objects(id) ON DELETE CASCADE,
  secret_id   uuid REFERENCES object_access_secrets(id) ON DELETE SET NULL,
  user_id     uuid REFERENCES users(id) ON DELETE SET NULL,
  job_id      uuid REFERENCES jobs(id) ON DELETE SET NULL,
  action      text NOT NULL CHECK (action IN ('view','copy')),
  reason      text,
  ip          inet,
  device      text,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX secret_reveals_obj_ix ON secret_reveals (object_id, created_at DESC);

-- ── 16. Отложенные внешние ключи (разрыв циклов) ───────────────────────────
ALTER TABLE users ADD CONSTRAINT users_employee_fk
  FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE SET NULL;
ALTER TABLE users ADD CONSTRAINT users_role_fk
  FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE RESTRICT;

-- created_by / updated_by и прочие ссылки на users во всех таблицах
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT c.table_name, c.column_name
    FROM information_schema.columns c
    JOIN information_schema.tables t
      ON t.table_name = c.table_name AND t.table_schema = c.table_schema
    WHERE c.table_schema = 'public'
      AND t.table_type = 'BASE TABLE'
      AND c.column_name IN ('created_by','updated_by','assigned_by','approved_by','sent_by',
                            'changed_by','revoked_by','granted_by','grantor_id','responsible_id',
                            'requested_by','uploaded_by','reviewed_by','sender_id')
      AND c.table_name NOT IN ('audit_logs','domain_events','notifications','login_attempts')
  LOOP
    EXECUTE format(
      'ALTER TABLE %I ADD CONSTRAINT %I FOREIGN KEY (%I) REFERENCES users(id) ON DELETE SET NULL',
      r.table_name, r.table_name || '_' || r.column_name || '_fk', r.column_name);
  END LOOP;
END $$;


-- ── 16а. МЕЖАРЕНДАТОРНАЯ ЦЕЛОСТНОСТЬ ───────────────────────────────────────
-- Простой внешний ключ по id гарантирует существование записи, но не то,
-- что она принадлежит той же компании. RLS защищает чтение и запись сессии,
-- но не спасает от ошибки в коде, выполняющей вставку под правильным
-- company_id со ссылкой на чужую сущность. Поэтому каждая tenant-owned связь
-- дополнительно закрывается СОСТАВНЫМ внешним ключом (company_id, entity_id).
-- Простые ключи сохранены: они дают ON DELETE-семантику и понятные ошибки.

-- Уникальность пары (company_id, id) у всех tenant-owned родителей
ALTER TABLE branches ADD CONSTRAINT branches_company_id_uq UNIQUE (company_id, id);
ALTER TABLE departments ADD CONSTRAINT departments_company_id_uq UNIQUE (company_id, id);
ALTER TABLE employees ADD CONSTRAINT employees_company_id_uq UNIQUE (company_id, id);
ALTER TABLE users ADD CONSTRAINT users_company_id_uq UNIQUE (company_id, id);
ALTER TABLE clients ADD CONSTRAINT clients_company_id_uq UNIQUE (company_id, id);
ALTER TABLE objects ADD CONSTRAINT objects_company_id_uq UNIQUE (company_id, id);
ALTER TABLE job_series ADD CONSTRAINT job_series_company_id_uq UNIQUE (company_id, id);
ALTER TABLE jobs ADD CONSTRAINT jobs_company_id_uq UNIQUE (company_id, id);
ALTER TABLE materials ADD CONSTRAINT materials_company_id_uq UNIQUE (company_id, id);
ALTER TABLE checklists ADD CONSTRAINT checklists_company_id_uq UNIQUE (company_id, id);
ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_company_id_uq UNIQUE (company_id, id);
ALTER TABLE messages ADD CONSTRAINT messages_company_id_uq UNIQUE (company_id, id);
ALTER TABLE trusted_devices ADD CONSTRAINT trusted_devices_company_id_uq UNIQUE (company_id, id);
ALTER TABLE object_access_secrets ADD CONSTRAINT object_access_secrets_company_id_uq UNIQUE (company_id, id);
ALTER TABLE invoices ADD CONSTRAINT invoices_company_id_uq UNIQUE (company_id, id);

-- Составные внешние ключи: ребёнок компании A не может ссылаться на сущность компании B
ALTER TABLE departments ADD CONSTRAINT departments_branch_same_company_fk
  FOREIGN KEY (company_id, branch_id) REFERENCES branches (company_id, id) ON DELETE SET NULL;
ALTER TABLE employees ADD CONSTRAINT employees_department_same_company_fk
  FOREIGN KEY (company_id, department_id) REFERENCES departments (company_id, id) ON DELETE SET NULL;
ALTER TABLE users ADD CONSTRAINT users_branch_same_company_fk
  FOREIGN KEY (company_id, branch_id) REFERENCES branches (company_id, id) ON DELETE SET NULL;
ALTER TABLE users ADD CONSTRAINT users_department_same_company_fk
  FOREIGN KEY (company_id, department_id) REFERENCES departments (company_id, id) ON DELETE SET NULL;
ALTER TABLE users ADD CONSTRAINT users_employee_same_company_fk
  FOREIGN KEY (company_id, employee_id) REFERENCES employees (company_id, id) ON DELETE SET NULL;
ALTER TABLE trusted_devices ADD CONSTRAINT trusted_devices_user_same_company_fk
  FOREIGN KEY (company_id, user_id) REFERENCES users (company_id, id) ON DELETE CASCADE;
ALTER TABLE invitations ADD CONSTRAINT invitations_user_same_company_fk
  FOREIGN KEY (company_id, user_id) REFERENCES users (company_id, id) ON DELETE CASCADE;
ALTER TABLE client_contacts ADD CONSTRAINT client_contacts_client_same_company_fk
  FOREIGN KEY (company_id, client_id) REFERENCES clients (company_id, id) ON DELETE CASCADE;
ALTER TABLE objects ADD CONSTRAINT objects_client_same_company_fk
  FOREIGN KEY (company_id, client_id) REFERENCES clients (company_id, id) ON DELETE RESTRICT;
ALTER TABLE objects ADD CONSTRAINT objects_branch_same_company_fk
  FOREIGN KEY (company_id, branch_id) REFERENCES branches (company_id, id) ON DELETE SET NULL;
ALTER TABLE objects ADD CONSTRAINT objects_department_same_company_fk
  FOREIGN KEY (company_id, department_id) REFERENCES departments (company_id, id) ON DELETE SET NULL;
ALTER TABLE objects ADD CONSTRAINT objects_main_employee_same_company_fk
  FOREIGN KEY (company_id, main_employee_id) REFERENCES employees (company_id, id) ON DELETE SET NULL;
ALTER TABLE objects ADD CONSTRAINT objects_backup_employee_same_company_fk
  FOREIGN KEY (company_id, backup_employee_id) REFERENCES employees (company_id, id) ON DELETE SET NULL;
ALTER TABLE objects ADD CONSTRAINT objects_leader_employee_same_company_fk
  FOREIGN KEY (company_id, leader_employee_id) REFERENCES employees (company_id, id) ON DELETE SET NULL;
ALTER TABLE object_access_secrets ADD CONSTRAINT object_access_secrets_object_same_company_fk
  FOREIGN KEY (company_id, object_id) REFERENCES objects (company_id, id) ON DELETE CASCADE;
ALTER TABLE secret_reveals ADD CONSTRAINT secret_reveals_object_same_company_fk
  FOREIGN KEY (company_id, object_id) REFERENCES objects (company_id, id) ON DELETE CASCADE;
ALTER TABLE secret_reveals ADD CONSTRAINT secret_reveals_job_same_company_fk
  FOREIGN KEY (company_id, job_id) REFERENCES jobs (company_id, id) ON DELETE SET NULL;
ALTER TABLE secret_reveals ADD CONSTRAINT secret_reveals_user_same_company_fk
  FOREIGN KEY (company_id, user_id) REFERENCES users (company_id, id) ON DELETE SET NULL;
ALTER TABLE job_series ADD CONSTRAINT job_series_object_same_company_fk
  FOREIGN KEY (company_id, object_id) REFERENCES objects (company_id, id) ON DELETE RESTRICT;
ALTER TABLE job_series ADD CONSTRAINT job_series_employee_same_company_fk
  FOREIGN KEY (company_id, employee_id) REFERENCES employees (company_id, id) ON DELETE SET NULL;
ALTER TABLE jobs ADD CONSTRAINT jobs_object_same_company_fk
  FOREIGN KEY (company_id, object_id) REFERENCES objects (company_id, id) ON DELETE RESTRICT;
ALTER TABLE jobs ADD CONSTRAINT jobs_series_same_company_fk
  FOREIGN KEY (company_id, series_id) REFERENCES job_series (company_id, id) ON DELETE SET NULL;
ALTER TABLE job_assignments ADD CONSTRAINT job_assignments_job_same_company_fk
  FOREIGN KEY (company_id, job_id) REFERENCES jobs (company_id, id) ON DELETE CASCADE;
ALTER TABLE job_assignments ADD CONSTRAINT job_assignments_employee_same_company_fk
  FOREIGN KEY (company_id, employee_id) REFERENCES employees (company_id, id) ON DELETE RESTRICT;
ALTER TABLE checklist_results ADD CONSTRAINT checklist_results_job_same_company_fk
  FOREIGN KEY (company_id, job_id) REFERENCES jobs (company_id, id) ON DELETE CASCADE;
ALTER TABLE timesheets ADD CONSTRAINT timesheets_job_same_company_fk
  FOREIGN KEY (company_id, job_id) REFERENCES jobs (company_id, id) ON DELETE RESTRICT;
ALTER TABLE timesheets ADD CONSTRAINT timesheets_employee_same_company_fk
  FOREIGN KEY (company_id, employee_id) REFERENCES employees (company_id, id) ON DELETE RESTRICT;
ALTER TABLE photos ADD CONSTRAINT photos_job_same_company_fk
  FOREIGN KEY (company_id, job_id) REFERENCES jobs (company_id, id) ON DELETE CASCADE;
ALTER TABLE signatures ADD CONSTRAINT signatures_job_same_company_fk
  FOREIGN KEY (company_id, job_id) REFERENCES jobs (company_id, id) ON DELETE CASCADE;
ALTER TABLE incidents ADD CONSTRAINT incidents_object_same_company_fk
  FOREIGN KEY (company_id, object_id) REFERENCES objects (company_id, id) ON DELETE SET NULL;
ALTER TABLE incidents ADD CONSTRAINT incidents_job_same_company_fk
  FOREIGN KEY (company_id, job_id) REFERENCES jobs (company_id, id) ON DELETE SET NULL;
ALTER TABLE incidents ADD CONSTRAINT incidents_employee_same_company_fk
  FOREIGN KEY (company_id, employee_id) REFERENCES employees (company_id, id) ON DELETE SET NULL;
ALTER TABLE incidents ADD CONSTRAINT incidents_client_same_company_fk
  FOREIGN KEY (company_id, client_id) REFERENCES clients (company_id, id) ON DELETE SET NULL;
ALTER TABLE absences ADD CONSTRAINT absences_employee_same_company_fk
  FOREIGN KEY (company_id, employee_id) REFERENCES employees (company_id, id) ON DELETE CASCADE;
ALTER TABLE inventory ADD CONSTRAINT inventory_object_same_company_fk
  FOREIGN KEY (company_id, object_id) REFERENCES objects (company_id, id) ON DELETE CASCADE;
ALTER TABLE inventory ADD CONSTRAINT inventory_material_same_company_fk
  FOREIGN KEY (company_id, material_id) REFERENCES materials (company_id, id) ON DELETE RESTRICT;
ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_object_same_company_fk
  FOREIGN KEY (company_id, object_id) REFERENCES objects (company_id, id) ON DELETE CASCADE;
ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_material_same_company_fk
  FOREIGN KEY (company_id, material_id) REFERENCES materials (company_id, id) ON DELETE RESTRICT;
ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_job_same_company_fk
  FOREIGN KEY (company_id, job_id) REFERENCES jobs (company_id, id) ON DELETE SET NULL;
ALTER TABLE invoices ADD CONSTRAINT invoices_client_same_company_fk
  FOREIGN KEY (company_id, client_id) REFERENCES clients (company_id, id) ON DELETE SET NULL;
ALTER TABLE invoices ADD CONSTRAINT invoices_subscription_same_company_fk
  FOREIGN KEY (company_id, subscription_id) REFERENCES subscriptions (company_id, id) ON DELETE SET NULL;
ALTER TABLE sync_queue ADD CONSTRAINT sync_queue_user_same_company_fk
  FOREIGN KEY (company_id, user_id) REFERENCES users (company_id, id) ON DELETE CASCADE;
ALTER TABLE sync_queue ADD CONSTRAINT sync_queue_job_same_company_fk
  FOREIGN KEY (company_id, job_id) REFERENCES jobs (company_id, id) ON DELETE SET NULL;
ALTER TABLE sync_queue ADD CONSTRAINT sync_queue_device_same_company_fk
  FOREIGN KEY (company_id, device_id) REFERENCES trusted_devices (company_id, id) ON DELETE SET NULL;
ALTER TABLE notifications ADD CONSTRAINT notifications_user_same_company_fk
  FOREIGN KEY (company_id, user_id) REFERENCES users (company_id, id) ON DELETE CASCADE;
ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_user_same_company_fk
  FOREIGN KEY (company_id, user_id) REFERENCES users (company_id, id) ON DELETE RESTRICT;
ALTER TABLE domain_events ADD CONSTRAINT domain_events_actor_same_company_fk
  FOREIGN KEY (company_id, actor_id) REFERENCES users (company_id, id) ON DELETE RESTRICT;

-- ── 17. Партиционирование ──────────────────────────────────────────────────
-- Партиционируются четыре растущие таблицы, ключ — время события:
--   audit_logs.server_time · domain_events.recorded_at
--   notifications.created_at · login_attempts.created_at
-- Горизонт: 18 месяцев вперёд. Поддерживается функцией ensure_partitions(),
-- которую вызывает ежемесячное задание. Дополнительно у каждой таблицы есть
-- DEFAULT-партиция: она никогда не должна наполняться, но гарантирует, что
-- вставка не упадёт, если задание не отработало. Непустая DEFAULT-партиция —
-- это авария уровня P2, для неё есть процедура перераспределения.

CREATE TABLE partitioned_tables (
  table_name  text PRIMARY KEY,
  part_column text NOT NULL,
  retention_months int NOT NULL,
  horizon_months   int NOT NULL DEFAULT 18
);
INSERT INTO partitioned_tables (table_name, part_column, retention_months) VALUES
  ('audit_logs',     'server_time', 36),
  ('domain_events',  'recorded_at', 12),
  ('notifications',  'created_at',   6),
  ('login_attempts', 'created_at',  12)
ON CONFLICT DO NOTHING;

-- Создание партиций на N месяцев вперёд. Идемпотентна.
CREATE OR REPLACE FUNCTION ensure_partitions(p_months int DEFAULT NULL)
RETURNS TABLE (created_table text)
LANGUAGE plpgsql AS $$
DECLARE
  t     record;
  i     int;
  start_d date;
  part  text;
  months int;
BEGIN
  FOR t IN SELECT * FROM partitioned_tables LOOP
    months := COALESCE(p_months, t.horizon_months);
    FOR i IN 0..months LOOP
      start_d := (date_trunc('month', now()) + make_interval(months => i))::date;
      part := format('%s_%s', t.table_name, to_char(start_d, 'YYYY_MM'));
      IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = part) THEN
        EXECUTE format('CREATE TABLE %I PARTITION OF %I FOR VALUES FROM (%L) TO (%L)',
                       part, t.table_name, start_d, (start_d + interval '1 month')::date);
        created_table := part; RETURN NEXT;
      END IF;
    END LOOP;
    -- DEFAULT-партиция как страховка
    part := t.table_name || '_default';
    IF NOT EXISTS (SELECT 1 FROM pg_class WHERE relname = part) THEN
      EXECUTE format('CREATE TABLE %I PARTITION OF %I DEFAULT', part, t.table_name);
      created_table := part; RETURN NEXT;
    END IF;
  END LOOP;
END $$;

-- Сколько дней осталось до конца последней созданной партиции.
-- Мониторинг поднимает тревогу, если меньше 60 дней.
CREATE OR REPLACE FUNCTION partition_headroom()
RETURNS TABLE (table_name text, last_partition text, covered_until date, days_left int, alert boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE t record; upper_txt text; upper_d date; last_part text;
BEGIN
  FOR t IN SELECT * FROM partitioned_tables LOOP
    SELECT c.relname, pg_get_expr(c.relpartbound, c.oid)
      INTO last_part, upper_txt
      FROM pg_class c JOIN pg_inherits i ON i.inhrelid = c.oid
      JOIN pg_class p ON p.oid = i.inhparent
     WHERE p.relname = t.table_name AND c.relname <> t.table_name || '_default'
     ORDER BY c.relname DESC LIMIT 1;
    IF upper_txt IS NULL THEN
      table_name := t.table_name; last_partition := NULL; covered_until := NULL;
      days_left := -1; alert := true; RETURN NEXT; CONTINUE;
    END IF;
    upper_d := (regexp_match(upper_txt, 'TO \(''(\d{4}-\d{2}-\d{2})'))[1]::date;
    table_name := t.table_name; last_partition := last_part; covered_until := upper_d;
    days_left := COALESCE(upper_d - CURRENT_DATE, -1);
    alert := COALESCE(upper_d - CURRENT_DATE, -1) < 60;
    RETURN NEXT;
  END LOOP;
END $$;

-- Строки, попавшие в DEFAULT-партицию: должно быть 0.
CREATE OR REPLACE FUNCTION partition_default_rows()
RETURNS TABLE (table_name text, rows_in_default bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE t record; n bigint;
BEGIN
  FOR t IN SELECT * FROM partitioned_tables LOOP
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = t.table_name || '_default') THEN
      EXECUTE format('SELECT count(*) FROM %I', t.table_name || '_default') INTO n;
      table_name := t.table_name; rows_in_default := n; RETURN NEXT;
    END IF;
  END LOOP;
END $$;

-- Перераспределение строк из DEFAULT-партиции после создания недостающих.
-- Порядок: отсоединить DEFAULT → создать партиции → вернуть строки → присоединить.
CREATE OR REPLACE PROCEDURE redistribute_default_partition(p_table text)
LANGUAGE plpgsql AS $$
DECLARE def text := p_table || '_default'; moved bigint;
BEGIN
  EXECUTE format('ALTER TABLE %I DETACH PARTITION %I', p_table, def);
  PERFORM ensure_partitions(24);
  EXECUTE format('WITH moved AS (DELETE FROM %I RETURNING *) INSERT INTO %I SELECT * FROM moved', def, p_table);
  GET DIAGNOSTICS moved = ROW_COUNT;
  EXECUTE format('ALTER TABLE %I ATTACH PARTITION %I DEFAULT', p_table, def);
  RAISE NOTICE 'Перераспределено строк: %', moved;
END $$;

-- Отсоединение старых партиций по сроку хранения (архивирование выполняется отдельно)
CREATE OR REPLACE FUNCTION detach_expired_partitions(p_dry_run boolean DEFAULT true)
RETURNS TABLE (detached text, older_than date)
LANGUAGE plpgsql AS $$
DECLARE t record; c record; cutoff date; part_date date;
BEGIN
  FOR t IN SELECT * FROM partitioned_tables LOOP
    cutoff := (date_trunc('month', now()) - make_interval(months => t.retention_months))::date;
    FOR c IN
      SELECT cl.relname FROM pg_class cl
      JOIN pg_inherits i ON i.inhrelid = cl.oid JOIN pg_class p ON p.oid = i.inhparent
      WHERE p.relname = t.table_name AND cl.relname ~ '_[0-9]{4}_[0-9]{2}$'
    LOOP
      part_date := to_date(right(c.relname, 7), 'YYYY_MM');
      IF part_date < cutoff THEN
        IF NOT p_dry_run THEN
          EXECUTE format('ALTER TABLE %I DETACH PARTITION %I', t.table_name, c.relname);
        END IF;
        detached := c.relname; older_than := cutoff; RETURN NEXT;
      END IF;
    END LOOP;
  END LOOP;
END $$;

-- Первичное создание партиций на 18 месяцев + DEFAULT
SELECT count(*) AS created_partitions FROM ensure_partitions();

ALTER TABLE login_attempts ADD CONSTRAINT login_attempts_company_fk
  FOREIGN KEY (company_id) REFERENCES companies(id) ON DELETE SET NULL;
ALTER TABLE login_attempts ADD CONSTRAINT login_attempts_user_fk
  FOREIGN KEY (user_id)    REFERENCES users(id)     ON DELETE SET NULL;

-- Индексы на партиционированных таблицах (наследуются партициями)
CREATE INDEX audit_company_time_ix   ON audit_logs (company_id, server_time DESC);
CREATE INDEX audit_user_ix           ON audit_logs (user_id, server_time DESC);
CREATE INDEX events_company_time_ix  ON domain_events (company_id, recorded_at DESC);
CREATE INDEX events_type_ix          ON domain_events (type, recorded_at DESC);
CREATE INDEX notif_user_unread_ix    ON notifications (user_id, created_at DESC);
CREATE INDEX login_attempts_ip_ix    ON login_attempts (ip, created_at DESC);
CREATE INDEX login_attempts_user_ix  ON login_attempts (user_id, created_at DESC);

-- ── 18. Триггеры ───────────────────────────────────────────────────────────
-- 18.1 updated_at проставляется автоматически
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.table_name FROM information_schema.columns c
    JOIN information_schema.tables t ON t.table_name = c.table_name AND t.table_schema = c.table_schema
    WHERE c.table_schema='public' AND t.table_type='BASE TABLE' AND c.column_name='updated_at'
      AND c.table_name NOT LIKE '%\_20%'
  LOOP
    EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
                   r.table_name || '_set_updated_at', r.table_name);
  END LOOP;
END $$;

-- 18.2 Журнал неизменяем: UPDATE и DELETE запрещены на уровне БД
CREATE OR REPLACE FUNCTION audit_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_logs is append-only: % denied', TG_OP
    USING ERRCODE = 'insufficient_privilege';
END $$;

CREATE TRIGGER audit_logs_no_update BEFORE UPDATE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_immutable();
CREATE TRIGGER audit_logs_no_delete BEFORE DELETE ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_immutable();

-- 18.3 Хеш-цепочка журнала: каждая запись подписывает предыдущую.
-- Состояние цепочки хранится отдельно: триггер не читает audit_logs,
-- поэтому не зависит от политик RLS и не сканирует партиции.
CREATE TABLE audit_chain_state (
  company_id uuid PRIMARY KEY REFERENCES companies(id) ON DELETE RESTRICT,
  last_seq   bigint NOT NULL DEFAULT 0 CHECK (last_seq >= 0),
  last_id    bigint,
  last_hash  text   NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION audit_hash_chain() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  st audit_chain_state%ROWTYPE;
BEGIN
  -- Блокировка по компании: параллельные вставки выстраиваются в очередь,
  -- ветвление цепочки невозможно. Строка состояния блокируется FOR UPDATE.
  PERFORM pg_advisory_xact_lock(hashtext('audit_chain'), hashtext(NEW.company_id::text));

  SELECT * INTO st FROM audit_chain_state WHERE company_id = NEW.company_id FOR UPDATE;

  IF NOT FOUND THEN
    NEW.chain_seq := 1;
    NEW.prev_id   := NULL;
    NEW.prev_hash := repeat('0', 64);
  ELSE
    NEW.chain_seq := st.last_seq + 1;
    NEW.prev_id   := st.last_id;
    NEW.prev_hash := st.last_hash;
  END IF;

  -- Хеш считается по данным записи и её позиции в цепочке, но НЕ по времени:
  -- порядок определяется chain_seq, а не server_time.
  NEW.row_hash := encode(digest(
      NEW.prev_hash || '|' || NEW.chain_seq::text || '|' ||
      COALESCE(NEW.company_id::text,'') || '|' || COALESCE(NEW.user_id::text,'') || '|' ||
      COALESCE(NEW.action,'')  || '|' || COALESCE(NEW.entity,'') || '|' ||
      COALESCE(NEW.entity_id::text,'') || '|' ||
      COALESCE(NEW.before::text,'') || '|' || COALESCE(NEW.after::text,'') || '|' ||
      COALESCE(NEW.reason,''),
      'sha256'), 'hex');

  -- Состояние обновляется здесь же, в BEFORE-триггере: значение identity-колонки
  -- уже вычислено, а AFTER-триггер при многострочном INSERT выполнился бы только
  -- после всего оператора и все строки получили бы одинаковый chain_seq.
  INSERT INTO audit_chain_state (company_id, last_seq, last_id, last_hash, updated_at)
       VALUES (NEW.company_id, NEW.chain_seq, NEW.id, NEW.row_hash, now())
  ON CONFLICT (company_id) DO UPDATE
     SET last_seq = EXCLUDED.last_seq, last_id = EXCLUDED.last_id,
         last_hash = EXCLUDED.last_hash, updated_at = now();
  RETURN NEW;
END $$;

CREATE TRIGGER audit_logs_hash BEFORE INSERT ON audit_logs
  FOR EACH ROW EXECUTE FUNCTION audit_hash_chain();

-- 18.4 Проверка целостности цепочки (вызывается регламентом и мониторингом)
CREATE OR REPLACE FUNCTION audit_verify_chain(p_company uuid)
RETURNS TABLE (chain_seq bigint, audit_id bigint, problem text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
  r          record;
  expect_seq bigint := 1;
  expect_hash text  := repeat('0', 64);
  expect_prev bigint := NULL;
  calc       text;
BEGIN
  FOR r IN
    SELECT * FROM audit_logs
     WHERE company_id = p_company
     ORDER BY chain_seq            -- порядок определяет только chain_seq
  LOOP
    IF r.chain_seq <> expect_seq THEN
      chain_seq := r.chain_seq; audit_id := r.id;
      problem := format('разрыв последовательности: ожидался %s', expect_seq);
      RETURN NEXT;
    END IF;
    IF r.prev_hash IS DISTINCT FROM expect_hash THEN
      chain_seq := r.chain_seq; audit_id := r.id; problem := 'prev_hash не совпадает';
      RETURN NEXT;
    END IF;
    IF r.prev_id IS DISTINCT FROM expect_prev THEN
      chain_seq := r.chain_seq; audit_id := r.id; problem := 'prev_id не совпадает';
      RETURN NEXT;
    END IF;
    calc := encode(digest(
      r.prev_hash || '|' || r.chain_seq::text || '|' ||
      COALESCE(r.company_id::text,'') || '|' || COALESCE(r.user_id::text,'') || '|' ||
      COALESCE(r.action,'')  || '|' || COALESCE(r.entity,'') || '|' ||
      COALESCE(r.entity_id::text,'') || '|' ||
      COALESCE(r.before::text,'') || '|' || COALESCE(r.after::text,'') || '|' ||
      COALESCE(r.reason,''),
      'sha256'), 'hex');
    IF r.row_hash IS DISTINCT FROM calc THEN
      chain_seq := r.chain_seq; audit_id := r.id; problem := 'row_hash не совпадает: запись изменена';
      RETURN NEXT;
    END IF;
    expect_seq  := r.chain_seq + 1;
    expect_hash := r.row_hash;
    expect_prev := r.id;
  END LOOP;
END $$;

-- Сверка состояния цепочки с фактическими данными (для мониторинга)
CREATE OR REPLACE FUNCTION audit_chain_status(p_company uuid)
RETURNS TABLE (rows_total bigint, state_seq bigint, max_seq bigint, consistent boolean)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT count(*)::bigint,
         COALESCE((SELECT last_seq FROM audit_chain_state WHERE company_id = p_company), 0),
         COALESCE(max(chain_seq), 0),
         COALESCE(max(chain_seq), 0) = COALESCE((SELECT last_seq FROM audit_chain_state WHERE company_id = p_company), 0)
           AND count(*) = COALESCE(max(chain_seq), 0)
  FROM audit_logs WHERE company_id = p_company;
$$;

-- 18.5 Доменные события неизменяемы
CREATE OR REPLACE FUNCTION events_immutable() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'domain_events is append-only: % denied', TG_OP
    USING ERRCODE = 'insufficient_privilege';
END $$;
CREATE TRIGGER domain_events_no_update BEFORE UPDATE ON domain_events
  FOR EACH ROW EXECUTE FUNCTION events_immutable();
CREATE TRIGGER domain_events_no_delete BEFORE DELETE ON domain_events
  FOR EACH ROW EXECUTE FUNCTION events_immutable();

-- 18.6 Оптимистичная блокировка заданий: server_rev растёт при каждом изменении
CREATE OR REPLACE FUNCTION bump_server_rev() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.server_rev = OLD.server_rev THEN
    NEW.server_rev := OLD.server_rev + 1;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER jobs_bump_rev BEFORE UPDATE ON jobs
  FOR EACH ROW EXECUTE FUNCTION bump_server_rev();

-- ── 18.7 Функции аутентификации ────────────────────────────────────────────
-- Вход выполняется ДО того, как известен арендатор, поэтому RLS ещё не может
-- отфильтровать строки. Вместо выдачи рабочей роли права BYPASSRLS открыт
-- узкий набор SECURITY DEFINER-функций: они возвращают ровно те поля, которые
-- нужны для аутентификации, и ничего больше.

CREATE OR REPLACE FUNCTION auth_find_user(p_login text)
RETURNS TABLE (id uuid, company_id uuid, password_hash text, status user_status,
               failed_attempts int, locked_until timestamptz, role_key text,
               must_change_password boolean)
LANGUAGE sql SECURITY DEFINER SET search_path = public STABLE AS $$
  SELECT u.id, u.company_id, u.password_hash, u.status, u.failed_attempts, u.locked_until,
         r.key, u.must_change_password
  FROM users u JOIN roles r ON r.id = u.role_id
  WHERE (lower(u.email::text) = lower(p_login) OR u.phone = p_login)
    AND u.deleted_at IS NULL
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION auth_record_attempt(
  p_company uuid, p_user uuid, p_login text, p_ip inet, p_ua text,
  p_success boolean, p_reason text)
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  INSERT INTO login_attempts (company_id,user_id,login,ip,user_agent,success,failure_reason)
  VALUES (p_company,p_user,p_login,p_ip,p_ua,p_success,p_reason);
$$;

-- Возвращает новое число неудачных попыток и признак блокировки
CREATE OR REPLACE FUNCTION auth_register_failure(p_user uuid, p_max int, p_lock_min int)
RETURNS TABLE (failed int, locked boolean)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE n int;
BEGIN
  UPDATE users SET failed_attempts = failed_attempts + 1 WHERE id = p_user
  RETURNING failed_attempts INTO n;
  IF n >= p_max THEN
    UPDATE users SET locked_until = now() + make_interval(mins => p_lock_min) WHERE id = p_user;
    failed := n; locked := true;
  ELSE
    failed := n; locked := false;
  END IF;
  RETURN NEXT;
END $$;

CREATE OR REPLACE FUNCTION auth_register_success(p_user uuid)
RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  UPDATE users SET failed_attempts = 0, locked_until = NULL,
                   last_login_at = now(), last_seen_at = now()
  WHERE id = p_user;
$$;

CREATE OR REPLACE FUNCTION auth_session_lookup(p_token_hash text)
RETURNS TABLE (session_id uuid, user_id uuid, company_id uuid, revoked_at timestamptz,
               expires_at timestamptz, status user_status, role_key text)
LANGUAGE sql SECURITY DEFINER SET search_path = public STABLE AS $$
  SELECT s.id, s.user_id, u.company_id, s.revoked_at, s.expires_at, u.status, r.key
  FROM sessions s JOIN users u ON u.id = s.user_id JOIN roles r ON r.id = u.role_id
  WHERE s.refresh_token_hash = p_token_hash;
$$;

CREATE OR REPLACE FUNCTION auth_revoke_user_sessions(p_user uuid, p_reason text)
RETURNS int LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE n int;
BEGIN
  UPDATE sessions SET revoked_at = now(), revoke_reason = p_reason
   WHERE user_id = p_user AND revoked_at IS NULL;
  GET DIAGNOSTICS n = ROW_COUNT; RETURN n;
END $$;

-- Права пользователя (роль + индивидуальные), тоже до контекста арендатора
CREATE OR REPLACE FUNCTION auth_user_permissions(p_user uuid)
RETURNS TABLE (key text, scope text, source text)
LANGUAGE sql SECURITY DEFINER SET search_path = public STABLE AS $$
  SELECT p.key, rp.scope, 'role'
  FROM users u JOIN role_permissions rp ON rp.role_id = u.role_id
  JOIN permissions p ON p.id = rp.permission_id
  WHERE u.id = p_user
  UNION ALL
  SELECT p.key, COALESCE(up.scope,'company'), up.effect
  FROM user_permissions up JOIN permissions p ON p.id = up.permission_id
  WHERE up.user_id = p_user AND (up.valid_until IS NULL OR up.valid_until > now());
$$;

-- ── 19. Row Level Security ─────────────────────────────────────────────────
-- Политика включается на всех таблицах с company_id.
-- Приложение выставляет SET LOCAL app.company_id в начале транзакции.
CREATE OR REPLACE FUNCTION current_company() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.company_id', true), '')::uuid
$$;

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT c.relname AS table_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'company_id' AND a.attnum > 0
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r','p')
      AND c.relname NOT LIKE '%\_20%'
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', r.table_name);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', r.table_name);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I USING (company_id = current_company()) '
      'WITH CHECK (company_id = current_company())', r.table_name);
  END LOOP;
END $$;

-- Системные роли принадлежат платформе (company_id IS NULL) и должны быть
-- видны всем арендаторам, но изменять их может только роль миграций.
DROP POLICY IF EXISTS tenant_isolation ON roles;
CREATE POLICY roles_read ON roles FOR SELECT
  USING (company_id IS NULL OR company_id = current_company());
CREATE POLICY roles_write ON roles FOR ALL
  USING (company_id = current_company()) WITH CHECK (company_id = current_company());

-- Таблица companies: арендатор определяется собственным идентификатором
ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE companies FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation_self ON companies
  USING (id = current_company()) WITH CHECK (id = current_company());

-- Журнал читается по своей компании, но пишется только ролью putzplan_audit
DROP POLICY IF EXISTS tenant_isolation ON audit_logs;
CREATE POLICY audit_read ON audit_logs FOR SELECT USING (company_id = current_company());
CREATE POLICY audit_write ON audit_logs FOR INSERT TO putzplan_audit WITH CHECK (true);
CREATE POLICY audit_state_all ON audit_chain_state USING (true) WITH CHECK (true);

