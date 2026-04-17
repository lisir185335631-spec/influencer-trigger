import adminClient from './client'

export interface ScrapeTaskAdminItem {
  id: number
  platforms: string[]
  industry: string
  target_count: number
  status: string
  progress: number
  found_count: number
  valid_count: number
  error_message: string | null
  target_market: string | null
  created_by: number | null
  creator_username: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface ScrapeTasksAdminResponse {
  total: number
  running: number
  items: ScrapeTaskAdminItem[]
}

export interface PlatformQuotaItem {
  platform: string
  daily_limit: number
  today_used: number
  last_reset_at: string | null
}

export interface PlatformQuotaResponse {
  items: PlatformQuotaItem[]
}

export async function listAdminScrapeTasks(): Promise<ScrapeTasksAdminResponse> {
  const res = await adminClient.get('/scrape/tasks')
  return res.data
}

export async function forceTerminateTask(taskId: number): Promise<{ ok: boolean }> {
  const res = await adminClient.post(`/scrape/tasks/${taskId}/force-terminate`)
  return res.data
}

export async function retryTask(taskId: number): Promise<{ ok: boolean }> {
  const res = await adminClient.post(`/scrape/tasks/${taskId}/retry`)
  return res.data
}

export async function getPlatformQuota(): Promise<PlatformQuotaResponse> {
  const res = await adminClient.get('/scrape/platform-quota')
  return res.data
}

export async function updatePlatformQuota(
  platform: string,
  dailyLimit: number,
): Promise<PlatformQuotaItem> {
  const res = await adminClient.patch('/scrape/platform-quota', {
    platform,
    daily_limit: dailyLimit,
  })
  return res.data
}
