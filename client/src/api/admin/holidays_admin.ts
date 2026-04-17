import adminClient from './client'

export interface HolidayAdminItem {
  id: number
  name: string
  date: string
  is_recurring: boolean
  is_active: boolean
  greeting_template: string | null
  sensitive_regions: string
  created_at: string
  send_count: number
  open_rate: number
  reply_rate: number
}

export interface HolidayCreatePayload {
  name: string
  date: string
  is_recurring?: boolean
  is_active?: boolean
  greeting_template?: string | null
  sensitive_regions?: string
}

export interface HolidayPatchPayload {
  name?: string
  date?: string
  is_recurring?: boolean
  is_active?: boolean
  greeting_template?: string | null
  sensitive_regions?: string
}

export interface YearlyReport {
  year: string
  total: number
  open_rate: number
  reply_rate: number
}

export interface InvestmentReport {
  holiday_id: number
  name: string
  yearly: YearlyReport[]
}

export async function listAdminHolidays(): Promise<HolidayAdminItem[]> {
  const res = await adminClient.get<HolidayAdminItem[]>('/holidays')
  return res.data
}

export async function createAdminHoliday(data: HolidayCreatePayload): Promise<HolidayAdminItem> {
  const res = await adminClient.post<HolidayAdminItem>('/holidays', data)
  return res.data
}

export async function patchAdminHoliday(id: number, data: HolidayPatchPayload): Promise<HolidayAdminItem> {
  const res = await adminClient.patch<HolidayAdminItem>(`/holidays/${id}`, data)
  return res.data
}

export async function deleteAdminHoliday(id: number): Promise<void> {
  await adminClient.delete(`/holidays/${id}`)
}

export async function getInvestmentReport(id: number): Promise<InvestmentReport> {
  const res = await adminClient.get<InvestmentReport>(`/holidays/${id}/investment-report`)
  return res.data
}

export async function setSensitiveRegions(holidayId: number, regions: string): Promise<void> {
  await adminClient.post('/holidays/sensitive-regions', { holiday_id: holidayId, regions })
}
