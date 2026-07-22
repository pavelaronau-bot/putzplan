import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import type { ReactNode } from 'react'
import {
  api,
  setAccessToken,
  setUnauthorizedHandler,
} from '../api/client'
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

  /*
   * Храним запуск первоначального восстановления сессии.
   * Login обязан дождаться его окончания, чтобы старый ответ /me
   * не мог стереть новый access token.
   */
  const bootstrapPromiseRef = useRef<Promise<void> | null>(null)

  const refreshMe = useCallback(async (): Promise<void> => {
    try {
      const currentUser = await api.me()
      setMe(currentUser)
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
      setLoading(false)
    })

    const bootstrapPromise = refreshMe()
    bootstrapPromiseRef.current = bootstrapPromise

    void bootstrapPromise
  }, [refreshMe])

  const login = useCallback(
    async (email: string, password: string): Promise<void> => {
      /*
       * Сначала обязательно завершаем первоначальную проверку refresh-cookie.
       * Это устраняет гонку между начальным /me и новым входом.
       */
      if (bootstrapPromiseRef.current) {
        await bootstrapPromiseRef.current
      }

      setLoading(true)

      try {
        const tokens = await api.login(email, password)

        setAccessToken(tokens.access_token)

        const currentUser = await api.me()
        setMe(currentUser)
      } catch (error) {
        setAccessToken(null)
        setMe(null)
        throw error
      } finally {
        setLoading(false)
      }
    },
    [],
  )

  const logout = useCallback(async (): Promise<void> => {
    setLoading(true)

    try {
      await api.logout()
    } finally {
      setAccessToken(null)
      setMe(null)
      setLoading(false)
    }
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      me,
      loading,
      login,
      logout,
      can: (permission: string) =>
        me?.permissions.some(item => item.key === permission) ?? false,
    }),
    [me, loading, login, logout],
  )

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const context = useContext(AuthContext)

  if (!context) {
    throw new Error('useAuth используется вне AuthProvider')
  }

  return context
}
