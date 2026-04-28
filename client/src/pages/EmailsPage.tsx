import { useState, useEffect, useCallback, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import {
  emailsApi,
  Campaign,
  EmailListItem,
  EmailStats,
} from '../api/emails'
import { useWebSocket, WsMessage } from '../hooks/useWebSocket'
import { WS_URL } from '../api/websocket'

// ── Status badge ─────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  pending:   'bg-gray-100 text-gray-500',
  sent:      'bg-blue-50 text-blue-600',
  delivered: 'bg-cyan-50 text-cyan-600',
  opened:    'bg-yellow-50 text-yellow-600',
  clicked:   'bg-amber-50 text-amber-600',
  replied:   'bg-green-50 text-green-700',
  bounced:   'bg-red-50 text-red-600',
  failed:    'bg-orange-50 text-orange-600',
}

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-500'
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {status}
    </span>
  )
}

// ── Status Dashboard tab ──────────────────────────────────────────────────────

const PLATFORMS = ['tiktok', 'instagram', 'youtube', 'twitter', 'facebook', 'other']
const STATUSES  = ['pending', 'sent', 'delivered', 'opened', 'clicked', 'replied', 'bounced', 'failed']
// Mirrors backend EmailType enum (initial / follow_up / holiday). Adding a
// new type later requires backend + this list — keep in sync intentionally.
const EMAIL_TYPES = ['initial', 'follow_up', 'holiday']
const PAGE_SIZE = 20

function StatusDashboard() {
  const { t } = useTranslation()
  const [stats, setStats]       = useState<EmailStats | null>(null)
  const [items, setItems]       = useState<EmailListItem[]>([])
  const [total, setTotal]       = useState(0)
  const [page, setPage]         = useState(1)
  const [loading, setLoading]   = useState(true)
  const [campaigns, setCampaigns] = useState<Campaign[]>([])

  const [campaignFilter, setCampaignFilter]   = useState<number | ''>('')
  const [platformFilter, setPlatformFilter]   = useState('')
  const [statusFilter,   setStatusFilter]     = useState('')
  const [typeFilter,     setTypeFilter]       = useState('')

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [statsRes, listRes] = await Promise.all([
        emailsApi.getStats(),
        emailsApi.listEmails({
          campaign_id: campaignFilter || undefined,
          platform:    platformFilter || undefined,
          status:      statusFilter   || undefined,
          email_type:  typeFilter     || undefined,
          page,
          page_size:   PAGE_SIZE,
        }),
      ])
      setStats(statsRes)
      setItems(listRes.items)
      setTotal(listRes.total)
    } catch {
      // ignore — stale data is acceptable
    } finally {
      setLoading(false)
    }
  }, [campaignFilter, platformFilter, statusFilter, typeFilter, page])

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => {
    emailsApi.listCampaigns().then(setCampaigns).catch(() => {})
  }, [])

  // Debounced reload: a burst of WS events (e.g. scheduler dispatching 50
  // follow-ups in one scan → 50 follow_up:sent broadcasts) collapses into
  // a single trailing-edge loadData call ~700ms later. Without this the
  // monitor page can hammer /emails and /stats per row, which is wasteful
  // and (in extreme cases) can stutter the UI.
  const reloadTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Cancel any pending reload on unmount so we don't setState on an
  // unmounted component when the user navigates away mid-debounce.
  useEffect(() => () => {
    if (reloadTimerRef.current) clearTimeout(reloadTimerRef.current)
  }, [])

  // Real-time updates via WebSocket
  const handleWs = useCallback((msg: WsMessage) => {
    // Reload on any event that mutates email rows visible in this list.
    // follow_up:sent fires when the auto-follow-up scheduler dispatches
    // a new email — without this branch, follow-ups would only show after
    // a manual reload or the next status_change event.
    if (msg.event === 'email:status_change' || msg.event === 'follow_up:sent') {
      if (reloadTimerRef.current) clearTimeout(reloadTimerRef.current)
      reloadTimerRef.current = setTimeout(() => {
        loadData()
        reloadTimerRef.current = null
      }, 700)
    }
  }, [loadData])
  useWebSocket(WS_URL, handleWs)

  const resetFilters = () => {
    setCampaignFilter('')
    setPlatformFilter('')
    setStatusFilter('')
    setTypeFilter('')
    setPage(1)
  }

  // When any filter changes, reset to page 1
  const handleCampaignFilter = (v: number | '') => { setCampaignFilter(v); setPage(1) }
  const handlePlatformFilter = (v: string)       => { setPlatformFilter(v); setPage(1) }
  const handleStatusFilter   = (v: string)       => { setStatusFilter(v);   setPage(1) }
  const handleTypeFilter     = (v: string)       => { setTypeFilter(v);     setPage(1) }

  // Optional `hint` becomes a native-tooltip ⓘ next to the label.
  // Used for "opened" because most non-Gmail clients hide remote images,
  // so the displayed open count is a lower bound — flagging that
  // in-place avoids a "why is opens always 0?" support-ticket loop.
  const statCards = stats ? [
    { label: t('emails.stats.totalSent'),  value: stats.total_sent, color: 'text-gray-900' },
    { label: t('emails.stats.delivered'),  value: stats.delivered,  color: 'text-cyan-600' },
    { label: t('emails.stats.opened'),     value: stats.opened,     color: 'text-yellow-600', hint: t('emails.stats.openedHint') },
    { label: t('emails.stats.replied'),    value: stats.replied,    color: 'text-green-600' },
    { label: t('emails.stats.noReply'),    value: stats.no_reply,   color: 'text-gray-400' },
    { label: t('emails.stats.bounced'),    value: stats.bounced,    color: 'text-red-500' },
  ] : []

  return (
    <div>
      {/* Stats cards */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-6">
        {statCards.map(({ label, value, color, hint }) => (
          <div key={label} className="border border-gray-100 rounded-xl p-4 text-center">
            <div className={`text-2xl font-semibold ${color}`}>{value}</div>
            <div className="text-xs text-gray-400 mt-0.5">
              {label}
              {hint && (
                <span
                  className="ml-1 cursor-help text-gray-300 hover:text-gray-500 transition-colors"
                  title={hint}
                >
                  ⓘ
                </span>
              )}
            </div>
          </div>
        ))}
        {!stats && Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="border border-gray-100 rounded-xl p-4 text-center animate-pulse">
            <div className="h-8 bg-gray-100 rounded mb-1" />
            <div className="h-3 bg-gray-100 rounded w-2/3 mx-auto" />
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={campaignFilter}
          onChange={e => handleCampaignFilter(e.target.value ? Number(e.target.value) : '')}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">{t('emails.filter.allCampaigns')}</option>
          {campaigns.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        <select
          value={platformFilter}
          onChange={e => handlePlatformFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">{t('emails.filter.allPlatforms')}</option>
          {PLATFORMS.map(p => (
            <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
          ))}
        </select>

        <select
          value={statusFilter}
          onChange={e => handleStatusFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">{t('emails.filter.allStatuses')}</option>
          {STATUSES.map(s => (
            <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
          ))}
        </select>

        <select
          value={typeFilter}
          onChange={e => handleTypeFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">{t('emails.filter.allTypes')}</option>
          {EMAIL_TYPES.map(typ => (
            <option key={typ} value={typ}>{t(`emails.filter.types.${typ}`)}</option>
          ))}
        </select>

        {(campaignFilter !== '' || platformFilter || statusFilter || typeFilter) && (
          <button
            onClick={resetFilters}
            className="text-xs text-gray-400 hover:text-gray-600 px-2"
          >
            {t('emails.filter.clearFilters')}
          </button>
        )}

        <span className="ml-auto text-xs text-gray-400 self-center">
          {t('emails.emailCount', { count: total })}
        </span>
      </div>

      {/* Email list table */}
      <div className="border border-gray-100 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.influencer')}</th>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.email')}</th>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.emailType')}</th>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.campaign')}</th>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.sentAt')}</th>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.status')}</th>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.lastUpdated')}</th>
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 && (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b border-gray-50">
                  {Array.from({ length: 7 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-gray-100 rounded animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={7} className="text-center py-12 text-sm text-gray-400">
                  {t('emails.noEmails')}
                </td>
              </tr>
            )}
            {items.map(item => (
              <tr key={item.id} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3 font-medium text-gray-800">
                  {item.influencer_name || '—'}
                  {item.influencer_platform && (
                    <span className="ml-1.5 text-xs text-gray-400">{item.influencer_platform}</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-500 font-mono text-xs">{item.influencer_email}</td>
                <td className="px-4 py-3 text-xs">
                  {/* Show "follow-up #N" inline so operators don't have to
                      cross-reference the influencer detail page. Initial
                      and holiday don't have a counter. */}
                  {/* Reuses the same emails.filter.types.* keys as the
                      filter dropdown — single source of truth, no risk of
                      filter and table drifting apart. */}
                  {item.email_type === 'follow_up' ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-amber-50 text-amber-700">
                      {t('emails.filter.types.follow_up')}
                      <span className="font-mono text-[10px] text-amber-600">
                        #{item.follow_up_count}
                      </span>
                    </span>
                  ) : item.email_type === 'holiday' ? (
                    <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-pink-50 text-pink-700">
                      {t('emails.filter.types.holiday')}
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">
                      {t('emails.filter.types.initial')}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-500">{item.campaign_name || '—'}</td>
                <td className="px-4 py-3 text-gray-400 text-xs">
                  {item.sent_at ? new Date(item.sent_at).toLocaleString() : '—'}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={item.status} />
                </td>
                <td className="px-4 py-3 text-gray-400 text-xs">
                  {new Date(item.updated_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50 transition-colors"
          >
            {t('emails.prev')}
          </button>
          <span className="text-xs text-gray-400">
            {t('emails.pageOf', { current: page, total: totalPages })}
          </span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50 transition-colors"
          >
            {t('emails.next')}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────
// Single-purpose monitor page. The previous "批量发送" tab was a duplicate of
// the standalone "邮件发送" menu (/mailboxes); folding it into here muddied
// the page's job, so it was removed. The legacy `?influencer_ids=...`
// jump-in entry pointed at that tab and had no remaining callers, so it
// went with it.

export default function EmailsPage() {
  return (
    <div className="p-6">
      <StatusDashboard />
    </div>
  )
}
