import apiClient from './client'

// ── Types ────────────────────────────────────────────────────────────────────

export interface AngleOption {
  key: string
  description: string
}

export interface GenerateDraftsRequest {
  influencer_ids: number[]
  template_id: number
  campaign_name?: string
  angle: string
  extra_notes?: string
  use_premium_model?: boolean
}

export interface GenerateDraftsResponse {
  campaign_id: number
  campaign_name: string
  total_count: number
  message: string
}

export type DraftStatus =
  | 'pending'
  | 'generating'
  | 'ready'
  | 'edited'
  | 'failed'
  | 'sending'
  | 'sent'
  | 'cancelled'

export interface DraftOut {
  id: number
  campaign_id: number
  influencer_id: number
  template_id: number | null
  subject: string
  body_html: string
  angle_used: string | null
  generation_model: string | null
  status: DraftStatus
  edited_by_user: boolean
  error_message: string | null
  email_id: number | null
  created_at: string
  updated_at: string
  generated_at: string | null
  sent_at: string | null
}

export interface DraftListItem {
  id: number
  campaign_id: number
  influencer_id: number
  influencer_name: string | null
  influencer_email: string
  influencer_platform: string | null
  influencer_followers: number | null
  subject: string
  body_html_preview: string
  angle_used: string | null
  status: DraftStatus
  edited_by_user: boolean
  error_message: string | null
  updated_at: string
}

export interface DraftListResponse {
  items: DraftListItem[]
  total: number
  counts_by_status: Record<string, number>
}

export interface UpdateDraftRequest {
  subject: string
  body_html: string
}

export interface RegenerateDraftRequest {
  angle?: string
  use_premium_model?: boolean
  extra_notes?: string
}

export interface SendCampaignFromDraftsResponse {
  campaign_id: number
  total_drafts: number
  sendable_drafts: number
  message: string
}

// WebSocket events broadcast during draft generation.
// Note: events are broadcast globally to all WS subscribers, so no
// influencer email / PII is included in the payload — the campaign
// owner reconciles per-row details via the authenticated REST list
// endpoint. Frontend listens on campaign_id match.
export interface DraftProgressEvent {
  campaign_id: number
  completed: number
  total: number
  succeeded: number
  failed: number
}

export interface DraftCompletedEvent {
  campaign_id: number
  total: number
  succeeded: number
  failed: number
}

// ── API client ───────────────────────────────────────────────────────────────

export const draftsApi = {
  listAngles: () =>
    apiClient.get<AngleOption[]>('/personalizer/angles').then(r => r.data),

  generate: (data: GenerateDraftsRequest) =>
    apiClient.post<GenerateDraftsResponse>('/campaigns/drafts/generate', data).then(r => r.data),

  listForCampaign: (campaignId: number) =>
    apiClient.get<DraftListResponse>(`/campaigns/${campaignId}/drafts`).then(r => r.data),

  get: (draftId: number) =>
    apiClient.get<DraftOut>(`/drafts/${draftId}`).then(r => r.data),

  update: (draftId: number, data: UpdateDraftRequest) =>
    apiClient.put<DraftOut>(`/drafts/${draftId}`, data).then(r => r.data),

  regenerate: (draftId: number, data: RegenerateDraftRequest) =>
    apiClient.post<DraftOut>(`/drafts/${draftId}/regenerate`, data).then(r => r.data),

  remove: (draftId: number) =>
    apiClient.delete<DraftOut>(`/drafts/${draftId}`).then(r => r.data),

  send: (campaignId: number) =>
    apiClient.post<SendCampaignFromDraftsResponse>(
      `/campaigns/${campaignId}/drafts/send`,
    ).then(r => r.data),
}
