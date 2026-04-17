import adminClient from './client'

export interface AuditLogItem {
  id: number
  user_id: number | null
  username: string | null
  role: string | null
  action: string | null
  resource_type: string | null
  resource_id: string | null
  request_method: string | null
  request_path: string | null
  ip: string | null
  user_agent: string | null
  status_code: number | null
  request_body_snippet: string | null
  response_snippet: string | null
  duration_ms: number | null
  created_at: string
}

export interface AuditLogsResponse {
  total: number
  page: number
  page_size: number
  items: AuditLogItem[]
}

export interface AuditTrendDay {
  date: string
  actions: Record<string, number>
}

export interface AuditFilters {
  user_id?: number
  username?: string
  action?: string
  resource_type?: string
  method?: string
  created_at_start?: string
  created_at_end?: string
}

export async function listAuditLogs(
  filters: AuditFilters,
  page: number,
  pageSize = 50
): Promise<AuditLogsResponse> {
  const params: Record<string, string | number> = { page, page_size: pageSize }
  if (filters.user_id) params.user_id = filters.user_id
  if (filters.username) params.username = filters.username
  if (filters.action) params.action = filters.action
  if (filters.resource_type) params.resource_type = filters.resource_type
  if (filters.method) params.method = filters.method
  if (filters.created_at_start) params.created_at_start = `${filters.created_at_start}T00:00:00`
  if (filters.created_at_end) params.created_at_end = `${filters.created_at_end}T23:59:59`

  const { data } = await adminClient.get<AuditLogsResponse>('/audit/logs', { params })
  return data
}

export async function getAuditStats(): Promise<{ trend: AuditTrendDay[] }> {
  const { data } = await adminClient.get<{ trend: AuditTrendDay[] }>('/audit/stats')
  return data
}

export async function downloadAuditCsv(filters: AuditFilters): Promise<void> {
  const params: Record<string, string | number> = {}
  if (filters.user_id) params.user_id = filters.user_id
  if (filters.username) params.username = filters.username
  if (filters.action) params.action = filters.action
  if (filters.resource_type) params.resource_type = filters.resource_type
  if (filters.method) params.method = filters.method
  if (filters.created_at_start) params.created_at_start = `${filters.created_at_start}T00:00:00`
  if (filters.created_at_end) params.created_at_end = `${filters.created_at_end}T23:59:59`

  const response = await adminClient.get<Blob>('/audit/export', {
    params,
    responseType: 'blob',
  })
  const url = URL.createObjectURL(response.data)
  const a = document.createElement('a')
  a.href = url
  a.download = 'audit_logs.csv'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}
