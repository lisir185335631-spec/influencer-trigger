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
