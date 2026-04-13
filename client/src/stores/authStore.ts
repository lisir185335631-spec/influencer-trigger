import { useState, useCallback } from 'react'
import { login as loginApi } from '../api/auth'

export interface AuthState {
  isAuthenticated: boolean
  username: string | null
  role: string | null
}

function parseJwtPayload(token: string): { username?: string; role?: string } | null {
  try {
    const base64 = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')
    return JSON.parse(atob(base64))
  } catch {
    return null
  }
}

function getInitialState(): AuthState {
  const token = localStorage.getItem('access_token')
  if (!token) return { isAuthenticated: false, username: null, role: null }
  const payload = parseJwtPayload(token)
  if (!payload) return { isAuthenticated: false, username: null, role: null }
  return {
    isAuthenticated: true,
    username: payload.username ?? null,
    role: payload.role ?? null,
  }
}

export function useAuth() {
  const [auth, setAuth] = useState<AuthState>(getInitialState)

  const login = useCallback(async (username: string, password: string) => {
    const data = await loginApi(username, password)
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    const payload = parseJwtPayload(data.access_token)
    setAuth({
      isAuthenticated: true,
      username: payload?.username ?? username,
      role: payload?.role ?? null,
    })
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    setAuth({ isAuthenticated: false, username: null, role: null })
  }, [])

  return { auth, login, logout }
}
