import apiClient from './client'

export interface DashboardStats {
  total_influencers: number
  new_this_week: number
  total_sent: number
  sent_this_week: number
  reply_rate: number
  effective_reply_rate: number
  conversion_rate: number
}

export interface TrendPoint {
  date: string
  sent: number
  replied: number
}

export interface PlatformItem {
  platform: string
  count: number
}

export interface MailboxHealthItem {
  id: number
  email: string
  today_sent: number
  daily_limit: number
  total_sent: number
  bounce_rate: number
  status: string
}

export async function fetchDashboardStats(): Promise<DashboardStats> {
  const res = await apiClient.get<DashboardStats>('/dashboard/stats')
  return res.data
}

export async function fetchDashboardTrends(): Promise<TrendPoint[]> {
  const res = await apiClient.get<{ data: TrendPoint[] }>('/dashboard/trends')
  return res.data.data
}

export async function fetchPlatformDistribution(): Promise<PlatformItem[]> {
  const res = await apiClient.get<{ data: PlatformItem[] }>('/dashboard/platform-distribution')
  return res.data.data
}

export async function fetchMailboxHealth(): Promise<MailboxHealthItem[]> {
  const res = await apiClient.get<{ data: MailboxHealthItem[] }>('/dashboard/mailbox-health')
  return res.data.data
}
