import adminClient from './client'

export interface AdminUser {
  id: number
  username: string
  email: string
  role: 'admin' | 'manager' | 'operator'
  is_active: boolean
  created_at: string
  last_login: string | null
}

export interface LoginHistoryEntry {
  id: number
  ip: string | null
  user_agent: string | null
  success: boolean
  failed_reason: string | null
  created_at: string
}

export interface UsersListResponse {
  total: number
  page: number
  page_size: number
  items: AdminUser[]
}

export function listUsers(params: {
  page?: number
  page_size?: number
  search?: string
  role?: string
}): Promise<{ data: UsersListResponse }> {
  return adminClient.get('/users', { params })
}

export function createUser(body: {
  username: string
  email: string
  password: string
  role: string
}): Promise<{ data: AdminUser }> {
  return adminClient.post('/users', body)
}

export function patchUser(
  userId: number,
  body: { role?: string; is_active?: boolean }
): Promise<{ data: AdminUser }> {
  return adminClient.patch(`/users/${userId}`, body)
}

export function resetPassword(
  userId: number,
  body: { new_password: string; admin_password: string }
): Promise<{ data: { ok: boolean } }> {
  return adminClient.post(`/users/${userId}/reset-password`, body)
}

export function forceLogout(
  userId: number,
  body: { admin_password: string }
): Promise<{ data: { ok: boolean } }> {
  return adminClient.post(`/users/${userId}/force-logout`, body)
}

export function getLoginHistory(userId: number): Promise<{ data: LoginHistoryEntry[] }> {
  return adminClient.get(`/users/${userId}/login-history`)
}
