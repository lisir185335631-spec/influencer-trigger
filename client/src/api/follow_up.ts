import apiClient from './client'

export interface FollowUpSettings {
  id: number
  enabled: boolean
  interval_days: number
  max_count: number
  hour_utc: number
  created_at: string
  updated_at: string
}

export interface FollowUpSettingsUpdate {
  enabled?: boolean
  interval_days?: number
  max_count?: number
  hour_utc?: number
}

export interface FollowUpLogItem {
  id: number
  influencer_id: number
  influencer_name: string | null
  influencer_email: string
  influencer_platform: string | null
  follow_up_count: number
  subject: string
  status: string
  sent_at: string | null
  created_at: string
}

export interface FollowUpLogsResponse {
  items: FollowUpLogItem[]
  total: number
  page: number
  page_size: number
}

export const followUpApi = {
  getSettings: () =>
    apiClient.get<FollowUpSettings>('/follow-up/settings').then((r) => r.data),

  updateSettings: (data: FollowUpSettingsUpdate) =>
    apiClient.put<FollowUpSettings>('/follow-up/settings', data).then((r) => r.data),

  getLogs: (page = 1, pageSize = 20) =>
    apiClient
      .get<FollowUpLogsResponse>('/follow-up/logs', {
        params: { page, page_size: pageSize },
      })
      .then((r) => r.data),
}
