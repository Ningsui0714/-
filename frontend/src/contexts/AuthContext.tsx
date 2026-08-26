import { createContext, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import {
  competitionDemoLogin, devLogin, getCurrentUser, loginUser, logoutUser, registerUser,
} from '../services/api'
import type { AuthUser, RegisterPayload } from '../services/api'

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  login: (username: string, password: string) => Promise<AuthUser>
  register: (data: RegisterPayload) => Promise<AuthUser>
  enterDevAccount: (accountId: number) => Promise<AuthUser>
  enterCompetitionDemo: () => Promise<AuthUser>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = async () => {
    try {
      setUser(await getCurrentUser())
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
    const handleUnauthorized = () => setUser(null)
    window.addEventListener('learnflow:unauthorized', handleUnauthorized)
    return () => window.removeEventListener('learnflow:unauthorized', handleUnauthorized)
  }, [])

  const value = useMemo<AuthContextValue>(() => ({
    user,
    loading,
    login: async (username, password) => {
      const next = await loginUser(username, password)
      setUser(next)
      return next
    },
    register: async data => {
      const next = await registerUser(data)
      setUser(next)
      return next
    },
    enterDevAccount: async accountId => {
      const next = await devLogin(accountId)
      setUser(next)
      return next
    },
    enterCompetitionDemo: async () => {
      const next = await competitionDemoLogin()
      setUser(next)
      return next
    },
    logout: async () => {
      await logoutUser()
      setUser(null)
    },
    refresh,
  }), [user, loading])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
