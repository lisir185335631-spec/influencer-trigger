import adminClient from './client'

export interface InfluencerAdminItem {
  id: number
  nickname: string | null
  email: string
  platform: string | null
  profile_url: string | null
  followers: number | null
  industry: string | null
  status: string
  priority: string
  follow_up_count: number
  created_at: string
  email_count: number
  tags: string[]
  task_ids: number[]
}

export interface InfluencersAdminResponse {
  total: number
  page: number
  page_size: number
  items: InfluencerAdminItem[]
}

export interface DuplicateGroup {
  type: string
  influencers: InfluencerAdminItem[]
}

export interface QualityMetric {
  count: number
  pct: number
}

export interface QualityReport {
  total: number
  empty_email: QualityMetric
  invalid_email: QualityMetric
  missing_followers: QualityMetric
  missing_bio: QualityMetric
}

export interface BatchVerifyStartResult {
  task_id: string
  total: number
}

export interface BatchVerifyStatus {
  status: 'pending' | 'running' | 'done'
  total: number
  done: number
  passed: number
  failed: number
  results: Record<string, boolean>
}

export async function listAdminInfluencers(params: {
  page?: number
  page_size?: number
  platform?: string
  status?: string
  search?: string
}): Promise<InfluencersAdminResponse> {
  const { data } = await adminClient.get('/influencers', { params })
  return data
}

export async function getDuplicates(): Promise<DuplicateGroup[]> {
  const { data } = await adminClient.get('/influencers/duplicates')
  return data
}

export async function getQualityReport(): Promise<QualityReport> {
  const { data } = await adminClient.get('/influencers/quality-report')
  return data
}

export async function mergeInfluencers(req: {
  primary_id: number
  secondary_ids: number[]
}): Promise<{ merged: number; primary_id: number }> {
  const { data } = await adminClient.post('/influencers/merge', req)
  return data
}

export async function startBatchVerify(
  influencer_ids: number[] = [],
): Promise<BatchVerifyStartResult> {
  const { data } = await adminClient.post('/influencers/batch-verify-email', {
    influencer_ids,
  })
  return data
}

export async function getBatchVerifyStatus(
  task_id: string,
): Promise<BatchVerifyStatus> {
  const { data } = await adminClient.get(
    `/influencers/batch-verify-email/${task_id}`,
  )
  return data
}
