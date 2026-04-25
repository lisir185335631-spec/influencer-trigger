import apiClient from './client'

export interface SystemSettings {
  follow_up_enabled: boolean
  interval_days: number
  max_count: number
  hour_utc: number
  scrape_concurrency: number
  webhook_feishu: string
  webhook_slack: string
}

export interface SystemSettingsUpdate {
  follow_up_enabled?: boolean
  interval_days?: number
  max_count?: number
  hour_utc?: number
  scrape_concurrency?: number
  webhook_feishu?: string
  webhook_slack?: string
}

export const getSettings = () =>
  apiClient.get<SystemSettings>('/settings').then((r) => r.data)

export const updateSettings = (body: SystemSettingsUpdate) =>
  apiClient.put<SystemSettings>('/settings', body).then((r) => r.data)

export const testWebhook = (platform: 'feishu' | 'slack', url: string) =>
  apiClient
    .post<{ success: boolean; platform: string }>('/settings/test-webhook', {
      platform,
      url,
    })
    .then((r) => r.data)

export interface YouTubeCookiesStatus {
  configured: boolean
  count: number
  auth_complete: boolean
  updated_at: string | null
  file_size: number
}

export const getYouTubeCookiesStatus = () =>
  apiClient
    .get<YouTubeCookiesStatus>('/settings/youtube-cookies/status')
    .then((r) => r.data)

export const saveYouTubeCookies = (raw: string) =>
  apiClient
    .post<YouTubeCookiesStatus>('/settings/youtube-cookies', { raw })
    .then((r) => r.data)

export const deleteYouTubeCookies = () =>
  apiClient
    .delete<YouTubeCookiesStatus>('/settings/youtube-cookies')
    .then((r) => r.data)
