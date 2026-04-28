import apiClient from './client'

export interface WebhookLogItem {
  id: number
  channel: string
  email_id: number | null
  influencer_id: number | null
  title: string
  content_preview: string
  status: 'success' | 'failed' | string
  http_code: number | null
  error_message: string | null
  duration_ms: number
  created_at: string
}

export interface WebhookLogList {
  items: WebhookLogItem[]
  total: number
}

export interface WebhookLogStats {
  total: number
  success: number
  failed: number
}

export interface WebhookLogListParams {
  channel?: string
  limit?: number
  offset?: number
}

export const webhookLogsApi = {
  getStats: (channel: string = 'serverchan'): Promise<WebhookLogStats> =>
    apiClient
      .get<WebhookLogStats>('/webhook-logs/stats', { params: { channel } })
      .then((r) => r.data),

  list: (params: WebhookLogListParams = {}): Promise<WebhookLogList> =>
    apiClient
      .get<WebhookLogList>('/webhook-logs', { params })
      .then((r) => r.data),
}
