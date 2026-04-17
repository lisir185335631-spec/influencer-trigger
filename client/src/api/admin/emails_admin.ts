import adminClient from './client'

export interface AdminEmailItem {
  id: number
  status: string
  subject: string
  sent_at: string | null
  opened: boolean
  replied: boolean
  created_at: string
  recipient_email: string
  recipient_name: string | null
  sender_email: string | null
  template_name: string | null
  template_id: number | null
}

export interface AdminEmailsResponse {
  total: number
  page: number
  page_size: number
  items: AdminEmailItem[]
}

export interface EmailStatsResponse {
  total_sent: number
  today_sent: number
  bounce_rate: number
  open_rate: number
  reply_rate: number
  per_mailbox: {
    mailbox_email: string
    total: number
    bounce_rate: number
    open_rate: number
    reply_rate: number
  }[]
}

export interface BlacklistEntry {
  id: number
  email: string
  reason: string | null
  added_by_user_id: number | null
  created_at: string
}

export interface EmailFilters {
  status?: string
  sender_email?: string
  recipient?: string
  template_id?: number
  sent_at_start?: string
  sent_at_end?: string
}

export async function listAdminEmails(
  filters: EmailFilters,
  page: number,
  pageSize = 50
): Promise<AdminEmailsResponse> {
  const params: Record<string, string | number> = { page, page_size: pageSize }
  if (filters.status) params.status = filters.status
  if (filters.sender_email) params.sender_email = filters.sender_email
  if (filters.recipient) params.recipient = filters.recipient
  if (filters.template_id) params.template_id = filters.template_id
  if (filters.sent_at_start) params.sent_at_start = `${filters.sent_at_start}T00:00:00`
  if (filters.sent_at_end) params.sent_at_end = `${filters.sent_at_end}T23:59:59`

  const { data } = await adminClient.get<AdminEmailsResponse>('/emails', { params })
  return data
}

export async function batchCancelEmails(emailIds: number[]): Promise<{ cancelled: number; skipped: number }> {
  const { data } = await adminClient.post<{ cancelled: number; skipped: number }>('/emails/batch-cancel', {
    email_ids: emailIds,
  })
  return data
}

export async function getEmailStats(): Promise<EmailStatsResponse> {
  const { data } = await adminClient.get<EmailStatsResponse>('/emails/stats')
  return data
}

export async function listBlacklist(): Promise<BlacklistEntry[]> {
  const { data } = await adminClient.get<BlacklistEntry[]>('/emails/blacklist')
  return data
}

export async function addToBlacklist(email: string, reason: string): Promise<BlacklistEntry> {
  const { data } = await adminClient.post<BlacklistEntry>('/emails/blacklist', { email, reason })
  return data
}

export async function removeFromBlacklist(entryId: number): Promise<void> {
  await adminClient.delete(`/emails/blacklist/${entryId}`)
}
