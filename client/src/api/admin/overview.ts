import adminClient from './client'

export interface OverviewMetrics {
  users: { total: number; active: number }
  emails_sent: { today: number; this_week: number; this_month: number }
  emails_replied: { today: number; this_week: number; this_month: number }
  influencers: { total: number; today: number; this_week: number; this_month: number }
  scrape_tasks: { today: number; this_week: number; this_month: number }
  agent_tasks: { today: number }
  errors: { today: number }
  charts: {
    email_trend: Array<{ date: string; sent: number; replied: number }>
    scrape_trend: Array<{ date: string; tasks: number }>
    platform_dist: Array<{ platform: string; count: number }>
  }
}

export interface HealthStatus {
  db: { ok: boolean; label: string }
  scheduler: { ok: boolean; label: string }
  monitor: { ok: boolean; label: string }
  websocket: { count: number; label: string; ok: boolean }
  mailbox_pool: { status: 'green' | 'yellow' | 'red'; label: string }
}

export interface RecentEvent {
  id: number
  title: string
  content: string
  level: 'info' | 'warning' | 'error' | 'success'
  is_read: boolean
  created_at: string
}

export async function getOverviewMetrics(): Promise<OverviewMetrics> {
  const { data } = await adminClient.get<OverviewMetrics>('/overview/metrics')
  return data
}

export async function getHealthStatus(): Promise<HealthStatus> {
  const { data } = await adminClient.get<HealthStatus>('/overview/health')
  return data
}

export async function getRecentEvents(): Promise<RecentEvent[]> {
  const { data } = await adminClient.get<RecentEvent[]>('/overview/recent-events')
  return data
}
