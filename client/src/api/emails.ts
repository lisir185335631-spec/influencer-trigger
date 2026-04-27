import apiClient from './client'

export interface SendBatchRequest {
  influencer_ids: number[]
  template_id: number
  campaign_name?: string
}

export interface SendBatchResponse {
  campaign_id: number
  campaign_name: string
  total_count: number
  message: string
}

export interface Campaign {
  id: number
  name: string
  status: 'pending' | 'running' | 'completed' | 'paused' | 'failed'
  total_count: number
  sent_count: number
  success_count: number
  failed_count: number
  replied_count: number
  bounced_count: number
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface EmailProgressEvent {
  campaign_id: number
  sent: number
  success: number
  failed: number
  total: number
  current_email?: string
}

export interface EmailListItem {
  id: number
  influencer_id: number
  influencer_name: string | null
  influencer_email: string
  influencer_platform: string | null
  // 'initial' | 'follow_up' | 'holiday' — exposed as plain string so we
  // don't have to keep the union in sync with backend EmailType enum.
  email_type: string
  // Snapshot of the influencer's follow_up_count at list-time.
  follow_up_count: number
  campaign_id: number | null
  campaign_name: string | null
  status: string
  subject: string
  sent_at: string | null
  updated_at: string
}

export interface EmailStats {
  total_sent: number
  delivered: number
  opened: number
  replied: number
  no_reply: number
  bounced: number
}

export interface EmailListResponse {
  items: EmailListItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface EmailListParams {
  campaign_id?: number
  platform?: string
  status?: string
  email_type?: string
  page?: number
  page_size?: number
}

export const emailsApi = {
  sendBatch: (data: SendBatchRequest) =>
    apiClient.post<SendBatchResponse>('/emails/send-batch', data).then(r => r.data),

  listCampaigns: () =>
    apiClient.get<Campaign[]>('/emails/campaigns').then(r => r.data),

  getCampaign: (id: number) =>
    apiClient.get<Campaign>(`/emails/campaigns/${id}`).then(r => r.data),

  getStats: () =>
    apiClient.get<EmailStats>('/emails/stats').then(r => r.data),

  listEmails: (params: EmailListParams = {}) =>
    apiClient.get<EmailListResponse>('/emails', { params }).then(r => r.data),
}
