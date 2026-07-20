import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, setAccessToken } from '../src/api/client'

describe('CSRF-токен в клиенте', () => {
  beforeEach(() => {
    document.cookie = 'putzplan_csrf=token-aus-cookie; path=/'
    setAccessToken('access-token')
    vi.restoreAllMocks()
  })

  it('добавляет заголовок x-csrf-token к изменяющим запросам', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'logged_out' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await api.logout()

    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['x-csrf-token']).toBe('token-aus-cookie')
    expect(init.credentials).toBe('include')
  })

  it('не добавляет заголовок к безопасным запросам', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: [], total: 0, limit: 50, offset: 0 }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await api.users({ limit: 50, offset: 0 })

    const [, init] = fetchMock.mock.calls[0]
    expect(init.headers['x-csrf-token']).toBeUndefined()
  })
})
