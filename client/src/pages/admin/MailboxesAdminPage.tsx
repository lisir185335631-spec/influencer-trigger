import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { History, Mail, RefreshCw, RotateCcw, ServerOff, Wifi, WifiOff, X } from 'lucide-react'
import {
  type MailboxAdminItem,
  type SendHistoryItem,
  type TestConnectionResult,
  disableMailbox,
  getMailboxSendHistory,
  listAdminMailboxes,
  resetMailboxQuota,
  testImap,
  testSmtp,
} from '../../api/admin/mailboxes_admin'

function formatTs(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
    hour12: false,
  })
}

const HEALTH_DOT: Record<string, string> = {
  healthy: 'bg-green-500',
  warning: 'bg-yellow-400',
  critical: 'bg-red-500',
  disabled: 'bg-gray-300',
}
const HEALTH_TEXT: Record<string, string> = {
  healthy: 'text-green-700',
  warning: 'text-yellow-700',
  critical: 'text-red-700',
  disabled: 'text-gray-400',
}
const STATUS_BADGE: Record<string, string> = {
  sent: 'text-indigo-600 bg-indigo-50',
  delivered: 'text-teal-600 bg-teal-50',
  opened: 'text-green-600 bg-green-50',
  replied: 'text-purple-600 bg-purple-50',
  bounced: 'text-red-600 bg-red-50',
  failed: 'text-red-700 bg-red-50',
  pending: 'text-yellow-600 bg-yellow-50',
  queued: 'text-blue-600 bg-blue-50',
  cancelled: 'text-gray-500 bg-gray-50',
}

function StatCard({ label, value, color }: { label: string; value: number; color?: string }) {
  return (
    <div className="bg-white border border-gray-100 rounded-xl p-5">
      <div className="text-xs text-gray-400 font-medium uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-2xl font-bold ${color ?? 'text-gray-900'}`}>{value}</div>
    </div>
  )
}

interface ToastState {
  id: number
  msg: string
  ok: boolean
}

let toastSeq = 0

export default function MailboxesAdminPage() {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [total, setTotal] = useState(0)
  const [healthy, setHealthy] = useState(0)
  const [warning, setWarning] = useState(0)
  const [critical, setCritical] = useState(0)
  const [disabled, setDisabled] = useState(0)
  const [mailboxes, setMailboxes] = useState<MailboxAdminItem[]>([])

  // per-row action loading
  const [actionLoading, setActionLoading] = useState<Record<number, string>>({})

  // toast
  const [toasts, setToasts] = useState<ToastState[]>([])

  // history drawer
  const [historyMailbox, setHistoryMailbox] = useState<MailboxAdminItem | null>(null)
  const [history, setHistory] = useState<SendHistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)

  const pushToast = (msg: string, ok: boolean) => {
    const id = ++toastSeq
    setToasts((prev) => [...prev, { id, msg, ok }])
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listAdminMailboxes()
      setTotal(res.total)
      setHealthy(res.healthy)
      setWarning(res.warning)
      setCritical(res.critical)
      setDisabled(res.disabled)
      setMailboxes(res.items)
    } catch { /* silent */ } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleTestSmtp(mb: MailboxAdminItem) {
    setActionLoading((p) => ({ ...p, [mb.id]: 'smtp' }))
    try {
      const res: TestConnectionResult = await testSmtp(mb.id)
      pushToast(res.success ? t('admin.mailboxes.smtpOk', { email: mb.email }) : t('admin.mailboxes.smtpFailed', { error: res.error }), res.success)
    } finally {
      setActionLoading((p) => { const n = { ...p }; delete n[mb.id]; return n })
    }
  }

  async function handleTestImap(mb: MailboxAdminItem) {
    setActionLoading((p) => ({ ...p, [mb.id]: 'imap' }))
    try {
      const res: TestConnectionResult = await testImap(mb.id)
      pushToast(res.success ? t('admin.mailboxes.imapOk', { email: mb.email }) : t('admin.mailboxes.imapFailed', { error: res.error }), res.success)
    } finally {
      setActionLoading((p) => { const n = { ...p }; delete n[mb.id]; return n })
    }
  }

  async function handleDisable(mb: MailboxAdminItem) {
    if (!window.confirm(t('admin.mailboxes.disableConfirm', { email: mb.email }))) return
    setActionLoading((p) => ({ ...p, [mb.id]: 'disable' }))
    try {
      await disableMailbox(mb.id)
      pushToast(t('admin.mailboxes.disableSuccess', { email: mb.email }), true)
      await load()
    } catch {
      pushToast(t('admin.mailboxes.disableFailed'), false)
    } finally {
      setActionLoading((p) => { const n = { ...p }; delete n[mb.id]; return n })
    }
  }

  async function handleResetQuota(mb: MailboxAdminItem) {
    setActionLoading((p) => ({ ...p, [mb.id]: 'quota' }))
    try {
      await resetMailboxQuota(mb.id)
      pushToast(t('admin.mailboxes.quotaResetSuccess', { email: mb.email }), true)
      await load()
    } catch {
      pushToast(t('admin.mailboxes.quotaResetFailed'), false)
    } finally {
      setActionLoading((p) => { const n = { ...p }; delete n[mb.id]; return n })
    }
  }

  async function openHistory(mb: MailboxAdminItem) {
    setHistoryMailbox(mb)
    setHistoryLoading(true)
    setHistory([])
    try {
      setHistory(await getMailboxSendHistory(mb.id))
    } finally {
      setHistoryLoading(false)
    }
  }

  return (
    <div className="p-6 space-y-5 max-w-screen-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">{t('admin.mailboxes.title')}</h1>
          <p className="text-xs text-gray-400 mt-0.5">{t('admin.mailboxes.subtitle')}</p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          {t('admin.common.refresh')}
        </button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <StatCard label={t('admin.mailboxes.stats.total')} value={total} />
        <StatCard label={t('admin.mailboxes.stats.healthy')} value={healthy} color="text-green-700" />
        <StatCard label={t('admin.mailboxes.stats.warning')} value={warning} color="text-yellow-700" />
        <StatCard label={t('admin.mailboxes.stats.critical')} value={critical} color="text-red-700" />
        <StatCard label={t('admin.mailboxes.stats.disabled')} value={disabled} color="text-gray-400" />
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
        {loading && mailboxes.length === 0 ? (
          <div className="flex items-center justify-center h-40">
            <RefreshCw className="w-5 h-5 text-gray-300 animate-spin" />
          </div>
        ) : mailboxes.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-sm text-gray-400">
            <Mail className="w-8 h-8 mb-2 text-gray-200" />
            {t('admin.mailboxes.noMailboxes')}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100 text-xs text-gray-500 uppercase tracking-wider">
                  <th className="px-4 py-3 text-left">{t('admin.mailboxes.table.health')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.mailboxes.table.mailbox')}</th>
                  <th className="px-4 py-3 text-left">SMTP</th>
                  <th className="px-4 py-3 text-left">IMAP</th>
                  <th className="px-4 py-3 text-left">{t('admin.mailboxes.table.todayLimit')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.mailboxes.table.failRate')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.mailboxes.table.lastSuccess')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.mailboxes.table.lastFailure')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.common.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {mailboxes.map((mb) => {
                  const busy = actionLoading[mb.id]
                  return (
                    <tr key={mb.id} className="border-b border-gray-50 hover:bg-gray-50/60 transition-colors">
                      {/* Health indicator */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${HEALTH_DOT[mb.health_score] ?? 'bg-gray-300'}`} />
                          <span className={`text-xs font-medium capitalize ${HEALTH_TEXT[mb.health_score] ?? 'text-gray-500'}`}>
                            {mb.health_score}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="font-medium text-gray-800 text-xs">{mb.email}</div>
                        {mb.display_name && <div className="text-xs text-gray-400">{mb.display_name}</div>}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500">{mb.smtp_host}:{mb.smtp_port}</td>
                      <td className="px-4 py-3 text-xs text-gray-500">
                        {mb.imap_host ? `${mb.imap_host}:${mb.imap_port}` : '—'}
                      </td>
                      <td className="px-4 py-3 text-xs tabular-nums">
                        <span className="text-gray-800 font-medium">{mb.today_sent}</span>
                        <span className="text-gray-400"> / {mb.daily_limit}</span>
                        <div className="w-20 h-1 bg-gray-100 rounded-full mt-1">
                          <div
                            className="h-1 rounded-full bg-indigo-400"
                            style={{ width: `${Math.min(100, mb.quota_pct)}%` }}
                          />
                        </div>
                      </td>
                      <td className="px-4 py-3 text-xs tabular-nums">
                        <span className={mb.failure_rate > 5 ? 'text-red-600 font-semibold' : mb.failure_rate >= 1 ? 'text-yellow-700' : 'text-green-700'}>
                          {mb.failure_rate.toFixed(1)}%
                        </span>
                        <div className="text-gray-400 text-xs">{mb.total_sent.toLocaleString()} {t('admin.mailboxes.table.totalSent')}</div>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-500 tabular-nums whitespace-nowrap">
                        {formatTs(mb.last_success_at)}
                      </td>
                      <td className="px-4 py-3 text-xs tabular-nums whitespace-nowrap">
                        <span className={mb.last_failure_at ? 'text-red-500' : 'text-gray-300'}>
                          {formatTs(mb.last_failure_at)}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1 flex-wrap">
                          <ActionBtn
                            title={t('admin.mailboxes.actions.testSmtp')}
                            busy={busy === 'smtp'}
                            onClick={() => handleTestSmtp(mb)}
                            icon={<Wifi className="w-3.5 h-3.5" />}
                          />
                          <ActionBtn
                            title={t('admin.mailboxes.actions.testImap')}
                            busy={busy === 'imap'}
                            onClick={() => handleTestImap(mb)}
                            icon={<WifiOff className="w-3.5 h-3.5" />}
                          />
                          <ActionBtn
                            title={t('admin.mailboxes.actions.disable')}
                            busy={busy === 'disable'}
                            onClick={() => handleDisable(mb)}
                            icon={<ServerOff className="w-3.5 h-3.5" />}
                            danger
                            disabled={mb.status === 'inactive'}
                          />
                          <ActionBtn
                            title={t('admin.mailboxes.actions.resetQuota')}
                            busy={busy === 'quota'}
                            onClick={() => handleResetQuota(mb)}
                            icon={<RotateCcw className="w-3.5 h-3.5" />}
                          />
                          <ActionBtn
                            title={t('admin.mailboxes.actions.sendHistory')}
                            busy={false}
                            onClick={() => openHistory(mb)}
                            icon={<History className="w-3.5 h-3.5" />}
                          />
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* History Drawer */}
      {historyMailbox && (
        <div className="fixed inset-0 z-50 flex">
          <div className="flex-1 bg-black/40" onClick={() => setHistoryMailbox(null)} />
          <div className="w-full max-w-lg bg-white shadow-2xl flex flex-col h-full">
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <div>
                <h2 className="text-sm font-semibold text-gray-900">{t('admin.mailboxes.history.title')}</h2>
                <p className="text-xs text-gray-400 mt-0.5">{historyMailbox.email} · {t('admin.mailboxes.history.last100')}</p>
              </div>
              <button onClick={() => setHistoryMailbox(null)} className="text-gray-400 hover:text-gray-700">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto">
              {historyLoading ? (
                <div className="flex items-center justify-center h-40">
                  <RefreshCw className="w-5 h-5 text-gray-300 animate-spin" />
                </div>
              ) : history.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-40 text-sm text-gray-400">
                  {t('admin.mailboxes.history.noHistory')}
                </div>
              ) : (
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-100 text-gray-500 uppercase tracking-wider">
                      <th className="px-4 py-2 text-left">{t('admin.mailboxes.history.colTime')}</th>
                      <th className="px-4 py-2 text-left">{t('admin.mailboxes.history.colRecipient')}</th>
                      <th className="px-4 py-2 text-left">{t('admin.common.status')}</th>
                      <th className="px-4 py-2 text-left">{t('admin.mailboxes.history.colSubject')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map((h) => (
                      <tr key={h.id} className="border-b border-gray-50 hover:bg-gray-50/60">
                        <td className="px-4 py-2 text-gray-400 tabular-nums whitespace-nowrap">
                          {formatTs(h.sent_at || h.created_at)}
                        </td>
                        <td className="px-4 py-2">
                          <div className="text-gray-800">{h.recipient_email}</div>
                          {h.recipient_name && <div className="text-gray-400">{h.recipient_name}</div>}
                        </td>
                        <td className="px-4 py-2">
                          {h.status && (
                            <span className={`inline-block font-medium px-1.5 py-0.5 rounded ${STATUS_BADGE[h.status] ?? 'text-gray-600 bg-gray-50'}`}>
                              {h.status}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-2 text-gray-500 truncate max-w-[160px]">{h.subject}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Toasts */}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`px-4 py-3 rounded-xl shadow-lg text-sm font-medium text-white ${t.ok ? 'bg-green-600' : 'bg-red-600'}`}
          >
            {t.msg}
          </div>
        ))}
      </div>
    </div>
  )
}

function ActionBtn({
  title, busy, onClick, icon, danger, disabled,
}: {
  title: string
  busy: boolean
  onClick: () => void
  icon: React.ReactNode
  danger?: boolean
  disabled?: boolean
}) {
  return (
    <button
      title={title}
      onClick={onClick}
      disabled={busy || disabled}
      className={`flex items-center gap-1 px-2 py-1 text-xs rounded-lg border transition-colors disabled:opacity-40 ${
        danger
          ? 'border-red-200 text-red-600 hover:bg-red-50'
          : 'border-gray-200 text-gray-600 hover:bg-gray-50'
      }`}
    >
      {busy ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : icon}
      <span className="hidden sm:inline">{title}</span>
    </button>
  )
}
