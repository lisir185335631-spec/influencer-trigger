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

export const emailsApi = {
  sendBatch: (data: SendBatchRequest) =>
    apiClient.post<SendBatchResponse>('/emails/send-batch', data).then(r => r.data),

  listCampaigns: () =>
    apiClient.get<Campaign[]>('/emails/campaigns').then(r => r.data),

  getCampaign: (id: number) =>
    apiClient.get<Campaign>(`/emails/campaigns/${id}`).then(r => r.data),
}
