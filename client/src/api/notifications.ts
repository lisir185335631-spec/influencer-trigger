import apiClient from './client'

export interface NotificationItem {
  id: number
  influencer_id: number | null
  email_id: number | null
  title: string
  content: string
  level: 'info' | 'warning' | 'urgent'
  intent: string | null
  is_read: boolean
  read_at: string | null
  created_at: string
  influencer_name: string | null
}

export interface NotificationListResponse {
  items: NotificationItem[]
  total: number
  unread_count: number
}

export const notificationsApi = {
  list(params?: { is_read?: boolean; limit?: number; offset?: number }) {
    return apiClient
      .get<NotificationListResponse>('/notifications', { params })
      .then((r) => r.data)
  },

  create(data: {
    title: string
    content: string
    influencer_id?: number
    email_id?: number
    level?: string
    intent?: string
  }) {
    return apiClient.post<NotificationItem>('/notifications', data).then((r) => r.data)
  },

  markRead(id: number) {
    return apiClient
      .patch<NotificationItem>(`/notifications/${id}/read`)
      .then((r) => r.data)
  },

  markAllRead() {
    return apiClient.post<{ marked_read: number }>('/notifications/read-all').then((r) => r.data)
  },
}
