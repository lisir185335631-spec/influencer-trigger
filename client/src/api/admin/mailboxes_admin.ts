import adminClient from './client'

export interface MailboxAdminItem {
  id: number
  email: string
  display_name: string | null
  status: string
  smtp_host: string
  smtp_port: number
  imap_host: string | null
  imap_port: number
  today_sent: number
  daily_limit: number
  quota_pct: number
  total_sent: number
  failure_rate: number
  last_success_at: string | null
  last_failure_at: string | null
  health_score: 'healthy' | 'warning' | 'critical' | 'disabled'
  health_color: 'green' | 'yellow' | 'red' | 'gray'
  created_at: string
  last_reset_at: string | null
}

export interface MailboxesAdminResponse {
  total: number
  healthy: number
  warning: number
  critical: number
  disabled: number
  items: MailboxAdminItem[]
}

export interface TestConnectionResult {
  success: boolean
  error: string | null
}

export interface SendHistoryItem {
  id: number
  subject: string
  status: string | null
  sent_at: string | null
  created_at: string
  recipient_email: string
  recipient_name: string | null
}

export async function listAdminMailboxes(): Promise<MailboxesAdminResponse> {
  const { data } = await adminClient.get<MailboxesAdminResponse>('/mailboxes')
  return data
}

export async function testSmtp(mailboxId: number): Promise<TestConnectionResult> {
  const { data } = await adminClient.post<TestConnectionResult>(`/mailboxes/${mailboxId}/test-smtp`)
  return data
}

export async function testImap(mailboxId: number): Promise<TestConnectionResult> {
  const { data } = await adminClient.post<TestConnectionResult>(`/mailboxes/${mailboxId}/test-imap`)
  return data
}

export async function disableMailbox(mailboxId: number): Promise<{ id: number; status: string }> {
  const { data } = await adminClient.post<{ id: number; status: string }>(`/mailboxes/${mailboxId}/disable`)
  return data
}

export async function resetMailboxQuota(mailboxId: number): Promise<{ id: number; today_sent: number }> {
  const { data } = await adminClient.post<{ id: number; today_sent: number }>(`/mailboxes/${mailboxId}/reset-quota`)
  return data
}

export async function getMailboxSendHistory(mailboxId: number): Promise<SendHistoryItem[]> {
  const { data } = await adminClient.get<SendHistoryItem[]>(`/mailboxes/${mailboxId}/send-history`)
  return data
}
