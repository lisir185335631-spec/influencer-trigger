import client from './client'

export interface Holiday {
  id: number
  name: string
  date: string // ISO date string YYYY-MM-DD
  is_recurring: boolean
  is_active: boolean
  greeting_template: string | null
  created_at: string
}

export interface HolidayCreate {
  name: string
  date: string
  is_recurring?: boolean
  is_active?: boolean
  greeting_template?: string | null
}

export interface HolidayUpdate {
  name?: string
  date?: string
  is_recurring?: boolean
  is_active?: boolean
  greeting_template?: string | null
}

export interface HolidayGreetingLogItem {
  id: number
  influencer_id: number
  influencer_name: string | null
  influencer_email: string
  influencer_platform: string | null
  subject: string
  status: string
  sent_at: string | null
  created_at: string
}

export interface HolidayGreetingLogsResponse {
  items: HolidayGreetingLogItem[]
  total: number
  page: number
  page_size: number
}

export const holidaysApi = {
  list: (): Promise<Holiday[]> =>
    client.get<Holiday[]>('/holidays').then((r) => r.data),

  create: (data: HolidayCreate): Promise<Holiday> =>
    client.post<Holiday>('/holidays', data).then((r) => r.data),

  update: (id: number, data: HolidayUpdate): Promise<Holiday> =>
    client.put<Holiday>(`/holidays/${id}`, data).then((r) => r.data),

  delete: (id: number): Promise<void> =>
    client.delete(`/holidays/${id}`).then(() => undefined),

  listLogs: (page = 1, pageSize = 20): Promise<HolidayGreetingLogsResponse> =>
    client
      .get<HolidayGreetingLogsResponse>('/holidays/logs', {
        params: { page, page_size: pageSize },
      })
      .then((r) => r.data),

  trigger: (): Promise<{ message: string }> =>
    client.post<{ message: string }>('/holidays/trigger').then((r) => r.data),
}
