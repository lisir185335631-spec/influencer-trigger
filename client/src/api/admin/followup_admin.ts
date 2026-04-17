import adminClient from './client'

export interface FollowUpSettings {
  id: number
  enabled: boolean
  interval_days: number
  max_count: number
  hour_utc: number
  created_at: string
  updated_at: string
}

export interface FollowUpSettingsPatch {
  enabled?: boolean
  interval_days?: number
  max_count?: number
  hour_utc?: number
}

export interface ResponderLogItem {
  email_id: number
  influencer_id: number
  influencer_name: string | null
  influencer_email: string
  influencer_platform: string | null
  original_reply: string | null
  reply_from: string | null
  follow_up_subject: string
  follow_up_status: string
  sent_at: string | null
  replied_at: string | null
  created_at: string
}

export interface ResponderLogsResponse {
  items: ResponderLogItem[]
  total: number
  page: number
  page_size: number
}

export async function getFollowUpSettings(): Promise<FollowUpSettings> {
  const res = await adminClient.get<FollowUpSettings>('/followup/settings')
  return res.data
}

export async function patchFollowUpSettings(data: FollowUpSettingsPatch): Promise<FollowUpSettings> {
  const res = await adminClient.patch<FollowUpSettings>('/followup/settings', data)
  return res.data
}

export async function pauseAllFollowUps(): Promise<void> {
  await adminClient.post('/followup/pause-all')
}

export async function resumeAllFollowUps(): Promise<void> {
  await adminClient.post('/followup/resume-all')
}

export async function getResponderLogs(page = 1, pageSize = 20): Promise<ResponderLogsResponse> {
  const res = await adminClient.get<ResponderLogsResponse>('/followup/responder-logs', {
    params: { page, page_size: pageSize },
  })
  return res.data
}
