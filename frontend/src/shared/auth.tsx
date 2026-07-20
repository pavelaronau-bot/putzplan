import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api, setAccessToken, setUnauthorizedHandler } from '../api/client'
import type { Me } from '../api/types'

interface AuthState {
  me: Me | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => Promise<void>
  can: (permission: string) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)

  const refreshMe = useCallback(async () => {
    try {
      setMe(await api.me())
    } catch {
      setMe(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setAccessToken(null)
      setMe(null)
    })
    // При загрузке пробуем восстановить сессию по refresh-cookie
    void refreshMe()
  }, [refreshMe])

  const login = useCallback(async (email: string, password: string) => {
    const tokens = await api.login(email, password)
    setAccessToken(tokens.access_token)
    setMe(await api.me())
  }, [])

  const logout = useCallback(async () => {
    try { await api.logout() } finally {
      setAccessToken(null)
      setMe(null)
    }
  }, [])

  const value = useMemo<AuthState>(() => ({
    me, loading, login, logout,
    can: (permission: string) => me?.permissions.some((p) => p.key === permission) ?? false,
  }), [me, loading, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth используется вне AuthProvider')
  return ctx
}
