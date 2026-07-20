import type { ApiError, Me, Page, Permission, PermissionCatalogItem, Role, TokenResponse, User } from './types'

const BASE = import.meta.env.VITE_API_URL ?? ''

/**
 * Access-токен живёт только в памяти вкладки: в localStorage его не кладём,
 * иначе XSS получает долгоживущий доступ. Refresh хранится в HttpOnly-cookie,
 * недоступной JavaScript.
 */
let accessToken: string | null = null
let onUnauthorized: (() => void) | null = null

/**
 * CSRF-токен двойной отправки. Сервер кладёт его в обычную (не HttpOnly)
 * cookie, клиент обязан вернуть значение заголовком: тогда чужой сайт,
 * даже вызвав запрос с нашими cookie, не сможет подставить заголовок.
 */
function readCsrfToken(): string | null {
  const match = document.cookie.match(/(?:^|;\s*)putzplan_csrf=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

export function setAccessToken(token: string | null): void { accessToken = token }
export function getAccessToken(): string | null { return accessToken }
export function setUnauthorizedHandler(fn: () => void): void { onUnauthorized = fn }

export class RequestFailed extends Error {
  constructor(public status: number, public error: ApiError) {
    super(error.message)
  }
}

async function request<T>(method: string, path: string, body?: unknown, retry = true): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    method,
    credentials: 'include',
    headers: {
      'content-type': 'application/json',
      ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
      ...(method !== 'GET' ? csrfHeader() : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })

  if (response.status === 401 && retry && path !== '/api/v1/auth/refresh') {
    // Молчаливое обновление access-токена по refresh-cookie
    const refreshed = await tryRefresh()
    if (refreshed) return request<T>(method, path, body, false)
    onUnauthorized?.()
  }

  if (!response.ok) {
    let error: ApiError
    try {
      error = (await response.json()) as ApiError
    } catch {
      error = { code: 'network_error', message: 'Сервер недоступен', request_id: '—', details: [] }
    }
    throw new RequestFailed(response.status, error)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function csrfHeader(): Record<string, string> {
  const token = readCsrfToken()
  return token ? { 'x-csrf-token': token } : {}
}

async function tryRefresh(): Promise<boolean> {
  try {
    const response = await fetch(`${BASE}/api/v1/auth/refresh`, {
      method: 'POST', credentials: 'include',
      headers: { 'content-type': 'application/json', ...csrfHeader() }, body: '{}',
    })
    if (!response.ok) return false
    const tokens = (await response.json()) as TokenResponse
    accessToken = tokens.access_token
    return true
  } catch {
    return false
  }
}

export const api = {
  login: (email: string, password: string) =>
    request<TokenResponse>('POST', '/api/v1/auth/login', { email, password }),
  logout: () => request<{ status: string }>('POST', '/api/v1/auth/logout', {}),
  logoutAll: () => request<{ status: string }>('POST', '/api/v1/auth/logout-all', {}),
  me: () => request<Me>('GET', '/api/v1/me'),
  users: (params: { limit: number; offset: number; status?: string; search?: string }) => {
    const query = new URLSearchParams({ limit: String(params.limit), offset: String(params.offset) })
    if (params.status) query.set('status', params.status)
    if (params.search) query.set('search', params.search)
    return request<Page<User>>('GET', `/api/v1/users?${query.toString()}`)
  },
  createUser: (payload: { email: string; full_name: string; role: string; position?: string; password?: string }) =>
    request<User>('POST', '/api/v1/users', payload),
  updateUser: (id: string, payload: { full_name?: string; position?: string; role?: string }) =>
    request<User>('PATCH', `/api/v1/users/${id}`, payload),
  deactivateUser: (id: string, reason: string) =>
    request<{ status: string }>('POST', `/api/v1/users/${id}/deactivate`, { reason }),
  roles: () => request<Role[]>('GET', '/api/v1/roles'),
  role: (id: string) => request<Role>('GET', `/api/v1/roles/${id}`),
  createRole: (payload: { key: string; name: string; description?: string; permissions: string[] }) =>
    request<Role>('POST', '/api/v1/roles', payload),
  setRolePermissions: (id: string, permissions: string[]) =>
    request<Role>('PUT', `/api/v1/roles/${id}/permissions`, { permissions }),
  permissions: () => request<PermissionCatalogItem[]>('GET', '/api/v1/permissions'),
}

export type { Permission }
