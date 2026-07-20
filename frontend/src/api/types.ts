// Типы соответствуют контракту OpenAPI 3.1 бэкенда.
export type UserStatus =
  | 'invited' | 'active' | 'temporarily_blocked' | 'on_leave'
  | 'sick' | 'password_reset' | 'terminated' | 'archived'

export interface ApiError {
  code: string
  message: string
  request_id: string
  details: { field?: string | null; message: string }[]
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
  refresh_token: string | null
}

export interface Permission { key: string; scope: string }

export interface Me {
  id: string
  company_id: string
  email: string | null
  full_name: string | null
  position: string | null
  status: UserStatus
  role: string
  last_login_at: string | null
  permissions: Permission[]
}

export interface User {
  id: string
  email: string | null
  phone: string | null
  full_name: string | null
  position: string | null
  status: UserStatus
  role: string
  last_login_at: string | null
  created_at: string
}

export interface Page<T> {
  data: T[]
  total: number
  limit: number
  offset: number
  next_offset: number | null
}

export interface Role {
  id: string
  key: string
  name: string
  description: string | null
  is_system: boolean
  permissions_count: number
  permissions?: string[]
}

export interface PermissionCatalogItem {
  key: string; module: string; action: string; default_scope: string; description: string | null
}
