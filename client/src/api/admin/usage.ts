import adminClient from './client'

export interface UsageSummary {
  total_cost_usd: number
  llm_tokens: number
  emails_sent: number
  scrape_runs: number
  storage_mb: number
}

export interface TrendPoint {
  date: string
  value: number
  cost_usd: number
}

export interface UsageTrend {
  metric: string
  data: TrendPoint[]
}

export interface BreakdownItem {
  key: string
  value: number
  cost_usd: number
}

export interface UsageBreakdown {
  metric: string
  dimension: string
  data: BreakdownItem[]
}

export interface UsageAlert {
  type: string
  message: string
  severity: 'warning' | 'critical'
}

export interface UsageAlerts {
  month: string
  month_cost_usd: number
  today_cost_usd: number
  budget: { budget_usd: number; alert_threshold_pct: number } | null
  alerts: UsageAlert[]
}

export interface BudgetIn {
  month: string
  budget_usd: number
  alert_threshold_pct: number
}

export const getUsageSummary = (period: 'day' | 'week' | 'month' = 'month') =>
  adminClient.get<UsageSummary>('/usage/summary', { params: { period } }).then((r) => r.data)

export const getUsageTrend = (metric = 'llm_token', period = '30d') =>
  adminClient.get<UsageTrend>('/usage/trend', { params: { metric, period } }).then((r) => r.data)

export const getUsageBreakdown = (metric = 'llm_token', dimension = 'model') =>
  adminClient
    .get<UsageBreakdown>('/usage/breakdown', { params: { metric, dimension } })
    .then((r) => r.data)

export const getUsageAlerts = () =>
  adminClient.get<UsageAlerts>('/usage/alerts').then((r) => r.data)

export const setBudget = (body: BudgetIn) =>
  adminClient.post('/usage/budget', body).then((r) => r.data)
