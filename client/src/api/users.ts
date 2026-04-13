import apiClient from './client'

export type UserRole = 'admin' | 'manager' | 'operator'

export interface UserItem {
  id: number
  username: string
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
}

export interface UserListResponse {
  items: UserItem[]
  total: number
}

export interface UserCreateRequest {
  username: string
  email: string
  password: string
  role: UserRole
}

export interface UserUpdateRequest {
  role?: UserRole
  email?: string
  is_active?: boolean
}

export const usersApi = {
  list: (): Promise<UserListResponse> =>
    apiClient.get('/users').then((r) => r.data),

  create: (body: UserCreateRequest): Promise<UserItem> =>
    apiClient.post('/users', body).then((r) => r.data),

  update: (id: number, body: UserUpdateRequest): Promise<UserItem> =>
    apiClient.put(`/users/${id}`, body).then((r) => r.data),

  disable: (id: number): Promise<void> =>
    apiClient.delete(`/users/${id}`).then(() => undefined),

  enable: (id: number): Promise<UserItem> =>
    apiClient.put(`/users/${id}`, { is_active: true }).then((r) => r.data),
}
