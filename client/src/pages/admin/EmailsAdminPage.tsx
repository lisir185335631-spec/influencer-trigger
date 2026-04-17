import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Ban, Mail, RefreshCw, Trash2, X } from 'lucide-react'
import {
  type AdminEmailItem,
  type BlacklistEntry,
  type EmailFilters,
  type EmailStatsResponse,
  addToBlacklist,
  batchCancelEmails,
  getEmailStats,
  listAdminEmails,
  listBlacklist,
  removeFromBlacklist,
} from '../../api/admin/emails_admin'

const STATUS_OPTIONS = [
  '', 'pending', 'queued', 'sent', 'delivered', 'opened', 'clicked',
  'replied', 'bounced', 'failed', 'blocked', 'cancelled',
]

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-yellow-600 bg-yellow-50',
  queued: 'text-blue-600 bg-blue-50',
  sent: 'text-indigo-600 bg-indigo-50',
  delivered: 'text-teal-600 bg-teal-50',
  opened: 'text-green-600 bg-green-50',
  clicked: 'text-emerald-600 bg-emerald-50',
  replied: 'text-purple-600 bg-purple-50',
  bounced: 'text-red-600 bg-red-50',
  failed: 'text-red-700 bg-red-50',
  blocked: 'text-gray-600 bg-gray-100',
  cancelled: 'text-gray-500 bg-gray-50',
}

function formatTs(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
    hour12: false,
  })
}

function StatCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white border border-gray-100 rounded-xl p-5">
      <div className="text-xs text-gray-400 font-medium uppercase tracking-wider mb-1">{label}</div>
      <div className="text-2xl font-bold text-gray-900">{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  )
}

const PAGE_SIZE = 50
const inputCls =
  'w-full text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-300 bg-white'

export default function EmailsAdminPage() {
  const [tab, setTab] = useState<'flow' | 'blacklist'>('flow')

  // Stats
  const [stats, setStats] = useState<EmailStatsResponse | null>(null)

  // Email flow
  const [filters, setFilters] = useState<EmailFilters>({})
  const [draftFilters, setDraftFilters] = useState<EmailFilters>({})
  const [page, setPage] = useState(1)
  const [emails, setEmails] = useState<AdminEmailItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<Set<number>>(new Set())

  // Confirm modal
  const [showConfirm, setShowConfirm] = useState(false)
  const [cancelling, setCancelling] = useState(false)

  // Blacklist
  const [blacklist, setBlacklist] = useState<BlacklistEntry[]>([])
  const [blEmail, setBlEmail] = useState('')
  const [blReason, setBlReason] = useState('')
  const [blAdding, setBlAdding] = useState(false)

  const loadStats = useCallback(async () => {
    try {
      setStats(await getEmailStats())
    } catch { /* silent */ }
  }, [])

  const loadEmails = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listAdminEmails(filters, page, PAGE_SIZE)
      setEmails(res.items)
      setTotal(res.total)
    } catch {
      setEmails([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [filters, page])

  const loadBlacklist = useCallback(async () => {
    try {
      setBlacklist(await listBlacklist())
    } catch { /* silent */ }
  }, [])

  useEffect(() => { loadStats() }, [loadStats])
  useEffect(() => { loadEmails() }, [loadEmails])
  useEffect(() => {
    if (tab === 'blacklist') loadBlacklist()
  }, [tab, loadBlacklist])

  function toggleSelect(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function toggleAll() {
    if (selected.size === emails.length) {
      setSelected(new Set())
    } else {
      setSelected(new Set(emails.map((e) => e.id)))
    }
  }

  async function handleBatchCancel() {
    setCancelling(true)
    try {
      await batchCancelEmails(Array.from(selected))
      setSelected(new Set())
      setShowConfirm(false)
      await Promise.all([loadEmails(), loadStats()])
    } finally {
      setCancelling(false)
    }
  }

  async function handleAddBlacklist() {
    if (!blEmail.trim()) return
    setBlAdding(true)
    try {
      await addToBlacklist(blEmail.trim(), blReason.trim())
      setBlEmail('')
      setBlReason('')
      await loadBlacklist()
    } catch { /* toast in production */ }
    finally { setBlAdding(false) }
  }

  async function handleRemoveBlacklist(id: number) {
    try {
      await removeFromBlacklist(id)
      setBlacklist((prev) => prev.filter((e) => e.id !== id))
    } catch { /* silent */ }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const selectedEmails = emails.filter((e) => selected.has(e.id))

  return (
    <div className="p-6 space-y-5 max-w-screen-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Email Admin</h1>
          <p className="text-xs text-gray-400 mt-0.5">Global email flow & blacklist management</p>
        </div>
        <button
          onClick={() => { loadEmails(); loadStats() }}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Today Sent" value={stats?.today_sent ?? '—'} />
        <StatCard
          label="Bounce Rate"
          value={stats ? `${stats.bounce_rate}%` : '—'}
          sub={`of ${stats?.total_sent ?? 0} total sent`}
        />
        <StatCard
          label="Open Rate"
          value={stats ? `${stats.open_rate}%` : '—'}
        />
        <StatCard
          label="Reply Rate"
          value={stats ? `${stats.reply_rate}%` : '—'}
        />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-100">
        {(['flow', 'blacklist'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
              tab === t
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t === 'flow' ? 'Email Flow' : 'Blacklist'}
          </button>
        ))}
      </div>

      {tab === 'flow' && (
        <>
          {/* Filters */}
          <div className="bg-white border border-gray-100 rounded-xl p-4">
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Status</label>
                <select
                  value={draftFilters.status ?? ''}
                  onChange={(e) => setDraftFilters({ ...draftFilters, status: e.target.value || undefined })}
                  className={inputCls}
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>{s || 'All statuses'}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Sender Email</label>
                <input
                  type="text"
                  placeholder="@domain.com"
                  value={draftFilters.sender_email ?? ''}
                  onChange={(e) => setDraftFilters({ ...draftFilters, sender_email: e.target.value || undefined })}
                  className={inputCls}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Recipient</label>
                <input
                  type="text"
                  placeholder="recipient@…"
                  value={draftFilters.recipient ?? ''}
                  onChange={(e) => setDraftFilters({ ...draftFilters, recipient: e.target.value || undefined })}
                  className={inputCls}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Sent From</label>
                <input
                  type="date"
                  value={draftFilters.sent_at_start ?? ''}
                  onChange={(e) => setDraftFilters({ ...draftFilters, sent_at_start: e.target.value || undefined })}
                  className={inputCls}
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Sent To</label>
                <input
                  type="date"
                  value={draftFilters.sent_at_end ?? ''}
                  onChange={(e) => setDraftFilters({ ...draftFilters, sent_at_end: e.target.value || undefined })}
                  className={inputCls}
                />
              </div>
              <div className="flex items-end gap-2">
                <button
                  onClick={() => { setFilters(draftFilters); setPage(1); setSelected(new Set()) }}
                  className="flex-1 px-3 py-1.5 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
                >
                  Apply
                </button>
                <button
                  onClick={() => { setDraftFilters({}); setFilters({}); setPage(1); setSelected(new Set()) }}
                  className="flex-1 px-3 py-1.5 text-sm font-medium text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  Reset
                </button>
              </div>
            </div>
          </div>

          {/* Batch action bar */}
          {selected.size > 0 && (
            <div className="flex items-center gap-3 bg-indigo-50 border border-indigo-100 rounded-xl px-4 py-2.5">
              <span className="text-sm text-indigo-700 font-medium">{selected.size} selected</span>
              <button
                onClick={() => setShowConfirm(true)}
                className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-red-600 text-white hover:bg-red-700 transition-colors"
              >
                <X className="w-4 h-4" />
                Batch Cancel
              </button>
              <button
                onClick={() => setSelected(new Set())}
                className="text-sm text-gray-500 hover:text-gray-700"
              >
                Clear selection
              </button>
            </div>
          )}

          {/* Table */}
          <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
            {loading ? (
              <div className="flex items-center justify-center h-40">
                <RefreshCw className="w-5 h-5 text-gray-300 animate-spin" />
              </div>
            ) : emails.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 text-sm text-gray-400">
                <Mail className="w-8 h-8 mb-2 text-gray-200" />
                No emails found.
              </div>
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="bg-gray-50 border-b border-gray-100 text-xs text-gray-500 uppercase tracking-wider">
                        <th className="px-3 py-3 w-8">
                          <input
                            type="checkbox"
                            checked={selected.size === emails.length}
                            onChange={toggleAll}
                            className="rounded"
                          />
                        </th>
                        <th className="px-4 py-3 text-left">Time</th>
                        <th className="px-4 py-3 text-left">Recipient</th>
                        <th className="px-4 py-3 text-left">Sender</th>
                        <th className="px-4 py-3 text-left">Status</th>
                        <th className="px-4 py-3 text-left">Template</th>
                        <th className="px-4 py-3 text-left">Opened</th>
                        <th className="px-4 py-3 text-left">Replied</th>
                      </tr>
                    </thead>
                    <tbody>
                      {emails.map((email) => (
                        <tr
                          key={email.id}
                          className={`border-b border-gray-50 hover:bg-gray-50/60 transition-colors ${
                            selected.has(email.id) ? 'bg-indigo-50/40' : ''
                          }`}
                        >
                          <td className="px-3 py-3">
                            <input
                              type="checkbox"
                              checked={selected.has(email.id)}
                              onChange={() => toggleSelect(email.id)}
                              className="rounded"
                            />
                          </td>
                          <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap tabular-nums">
                            {formatTs(email.sent_at || email.created_at)}
                          </td>
                          <td className="px-4 py-3">
                            <div className="font-medium text-gray-800 text-xs">{email.recipient_email}</div>
                            {email.recipient_name && (
                              <div className="text-xs text-gray-400">{email.recipient_name}</div>
                            )}
                          </td>
                          <td className="px-4 py-3 text-xs text-gray-500 truncate max-w-[140px]">
                            {email.sender_email ?? '—'}
                          </td>
                          <td className="px-4 py-3">
                            <span
                              className={`inline-block text-xs font-medium px-1.5 py-0.5 rounded ${
                                STATUS_COLORS[email.status] ?? 'text-gray-600 bg-gray-50'
                              }`}
                            >
                              {email.status}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-xs text-gray-500 truncate max-w-[120px]">
                            {email.template_name ?? '—'}
                          </td>
                          <td className="px-4 py-3 text-xs">
                            {email.opened ? (
                              <span className="text-green-600 font-medium">Yes</span>
                            ) : (
                              <span className="text-gray-300">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-xs">
                            {email.replied ? (
                              <span className="text-purple-600 font-medium">Yes</span>
                            ) : (
                              <span className="text-gray-300">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Pagination */}
                <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
                  <span className="text-xs text-gray-400">
                    Page {page} of {totalPages} · {total.toLocaleString()} total
                  </span>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => { setPage(1); setSelected(new Set()) }}
                      disabled={page === 1}
                      className="px-2 py-1 text-xs text-gray-500 border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50"
                    >«</button>
                    <button
                      onClick={() => { setPage((p) => Math.max(1, p - 1)); setSelected(new Set()) }}
                      disabled={page === 1}
                      className="px-2 py-1 text-xs text-gray-500 border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50"
                    >‹</button>
                    {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                      const start = Math.max(1, Math.min(page - 2, totalPages - 4))
                      return start + i
                    }).map((p) => (
                      <button
                        key={p}
                        onClick={() => { setPage(p); setSelected(new Set()) }}
                        className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                          p === page
                            ? 'bg-indigo-600 text-white border-indigo-600'
                            : 'text-gray-500 border-gray-200 hover:bg-gray-50'
                        }`}
                      >{p}</button>
                    ))}
                    <button
                      onClick={() => { setPage((p) => Math.min(totalPages, p + 1)); setSelected(new Set()) }}
                      disabled={page === totalPages}
                      className="px-2 py-1 text-xs text-gray-500 border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50"
                    >›</button>
                    <button
                      onClick={() => { setPage(totalPages); setSelected(new Set()) }}
                      disabled={page === totalPages}
                      className="px-2 py-1 text-xs text-gray-500 border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50"
                    >»</button>
                  </div>
                </div>
              </>
            )}
          </div>
        </>
      )}

      {tab === 'blacklist' && (
        <div className="space-y-5">
          {/* Add form */}
          <div className="bg-white border border-gray-100 rounded-xl p-5">
            <h2 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
              <Ban className="w-4 h-4 text-red-500" />
              Add to Blacklist
            </h2>
            <div className="flex gap-3">
              <input
                type="email"
                placeholder="recipient@example.com"
                value={blEmail}
                onChange={(e) => setBlEmail(e.target.value)}
                className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-red-300"
              />
              <input
                type="text"
                placeholder="Reason (optional)"
                value={blReason}
                onChange={(e) => setBlReason(e.target.value)}
                className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-red-300"
              />
              <button
                onClick={handleAddBlacklist}
                disabled={blAdding || !blEmail.trim()}
                className="px-4 py-2 text-sm font-medium bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                {blAdding ? 'Adding…' : 'Add'}
              </button>
            </div>
          </div>

          {/* Blacklist table */}
          <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
            {blacklist.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-32 text-sm text-gray-400">
                <Ban className="w-7 h-7 mb-2 text-gray-200" />
                Blacklist is empty.
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-100 text-xs text-gray-500 uppercase tracking-wider">
                    <th className="px-4 py-3 text-left">Email</th>
                    <th className="px-4 py-3 text-left">Reason</th>
                    <th className="px-4 py-3 text-left">Added At</th>
                    <th className="px-4 py-3 w-12"></th>
                  </tr>
                </thead>
                <tbody>
                  {blacklist.map((entry) => (
                    <tr key={entry.id} className="border-b border-gray-50 hover:bg-gray-50/60 transition-colors">
                      <td className="px-4 py-3 font-mono text-xs text-gray-800">{entry.email}</td>
                      <td className="px-4 py-3 text-xs text-gray-500">{entry.reason ?? '—'}</td>
                      <td className="px-4 py-3 text-xs text-gray-400 tabular-nums whitespace-nowrap">
                        {formatTs(entry.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          onClick={() => handleRemoveBlacklist(entry.id)}
                          className="p-1 text-gray-400 hover:text-red-600 transition-colors"
                          title="Remove"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}

      {/* Confirm cancel modal */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl shadow-xl p-6 w-full max-w-md mx-4">
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-full bg-red-50 flex items-center justify-center flex-shrink-0">
                <AlertTriangle className="w-5 h-5 text-red-600" />
              </div>
              <div>
                <h3 className="text-base font-semibold text-gray-900">Batch Cancel Emails</h3>
                <p className="text-xs text-gray-400">This action cannot be undone.</p>
              </div>
            </div>

            <p className="text-sm text-gray-600 mb-2">
              You are about to cancel <span className="font-semibold text-gray-900">{selected.size}</span> email(s).
              Only pending/queued emails will be affected.
            </p>

            <div className="max-h-40 overflow-y-auto mb-4 bg-gray-50 rounded-lg p-3 space-y-1">
              {selectedEmails.slice(0, 20).map((e) => (
                <div key={e.id} className="text-xs font-mono text-gray-600">{e.recipient_email}</div>
              ))}
              {selectedEmails.length > 20 && (
                <div className="text-xs text-gray-400 italic">…and {selectedEmails.length - 20} more</div>
              )}
            </div>

            <div className="flex justify-end gap-3">
              <button
                onClick={() => setShowConfirm(false)}
                className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleBatchCancel}
                disabled={cancelling}
                className="px-4 py-2 text-sm font-medium bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 transition-colors"
              >
                {cancelling ? 'Cancelling…' : 'Confirm Cancel'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
