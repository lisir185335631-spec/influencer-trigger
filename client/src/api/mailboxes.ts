import client from './client'

export interface Mailbox {
  id: number
  email: string
  display_name: string | null
  smtp_host: string
  smtp_port: number
  smtp_use_tls: boolean
  imap_host: string | null
  imap_port: number
  daily_limit: number
  hourly_limit: number
  today_sent: number
  total_sent: number
  bounce_rate: number
  status: 'active' | 'inactive' | 'error'
  created_at: string
  updated_at: string
}

export interface MailboxCreate {
  email: string
  display_name?: string
  smtp_host: string
  smtp_port: number
  smtp_password: string
  smtp_use_tls: boolean
  imap_host?: string
  imap_port: number
  daily_limit: number
  hourly_limit: number
}

export interface MailboxUpdate {
  display_name?: string
  smtp_host?: string
  smtp_port?: number
  smtp_password?: string
  smtp_use_tls?: boolean
  imap_host?: string
  imap_port?: number
  daily_limit?: number
  hourly_limit?: number
}

export interface TestResult {
  success: boolean
  message?: string
  error?: string
}

export const mailboxesApi = {
  list: (): Promise<Mailbox[]> =>
    client.get<Mailbox[]>('/mailboxes/').then((r) => r.data),

  create: (data: MailboxCreate): Promise<Mailbox> =>
    client.post<Mailbox>('/mailboxes/', data).then((r) => r.data),

  update: (id: number, data: MailboxUpdate): Promise<Mailbox> =>
    client.put<Mailbox>(`/mailboxes/${id}`, data).then((r) => r.data),

  delete: (id: number): Promise<void> =>
    client.delete(`/mailboxes/${id}`).then(() => undefined),

  test: (id: number, testTo?: string): Promise<TestResult> =>
    client
      .post<TestResult>(`/mailboxes/${id}/test`, { test_to: testTo || null })
      .then((r) => r.data),
}
