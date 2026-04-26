import { useState, useEffect, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  emailsApi,
  Campaign,
  EmailListItem,
  EmailStats,
} from '../api/emails'
import { useWebSocket, WsMessage } from '../hooks/useWebSocket'
import SendPanel from '../components/SendPanel'

// See WebSocketContext.tsx for why we hardcode :6002 instead of using window.location.host.
const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.hostname}:6002/ws`

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
const PAGE_SIZE = 20

function StatusDashboard() {
  const { t } = useTranslation()
  const [stats, setStats]       = useState<EmailStats | null>(null)
  const [items, setItems]       = useState<EmailListItem[]>([])
  const [total, setTotal]       = useState(0)
  const [page, setPage]         = useState(1)
  const [loading, setLoading]   = useState(true)
  const [campaigns, setCampaigns] = useState<Campaign[]>([])

  const [campaignFilter, setCampaignFilter] = useState<number | ''>('')
  const [platformFilter, setPlatformFilter] = useState('')
  const [statusFilter,   setStatusFilter]   = useState('')

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
  }, [campaignFilter, platformFilter, statusFilter, page])

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => {
    emailsApi.listCampaigns().then(setCampaigns).catch(() => {})
  }, [])

  // Real-time updates via WebSocket
  const handleWs = useCallback((msg: WsMessage) => {
    if (msg.event === 'email:status_change') {
      loadData()
    }
  }, [loadData])
  useWebSocket(WS_URL, handleWs)

  const resetFilters = () => {
    setCampaignFilter('')
    setPlatformFilter('')
    setStatusFilter('')
    setPage(1)
  }

  // When any filter changes, reset to page 1
  const handleCampaignFilter = (v: number | '') => { setCampaignFilter(v); setPage(1) }
  const handlePlatformFilter = (v: string)       => { setPlatformFilter(v); setPage(1) }
  const handleStatusFilter   = (v: string)       => { setStatusFilter(v);   setPage(1) }

  const statCards = stats ? [
    { label: t('emails.stats.totalSent'),  value: stats.total_sent, color: 'text-gray-900' },
    { label: t('emails.stats.delivered'),  value: stats.delivered,  color: 'text-cyan-600' },
    { label: t('emails.stats.opened'),     value: stats.opened,     color: 'text-yellow-600' },
    { label: t('emails.stats.replied'),    value: stats.replied,    color: 'text-green-600' },
    { label: t('emails.stats.noReply'),    value: stats.no_reply,   color: 'text-gray-400' },
    { label: t('emails.stats.bounced'),    value: stats.bounced,    color: 'text-red-500' },
  ] : []

  return (
    <div>
      {/* Stats cards */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-6">
        {statCards.map(({ label, value, color }) => (
          <div key={label} className="border border-gray-100 rounded-xl p-4 text-center">
            <div className={`text-2xl font-semibold ${color}`}>{value}</div>
            <div className="text-xs text-gray-400 mt-0.5">{label}</div>
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

        {(campaignFilter !== '' || platformFilter || statusFilter) && (
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
                  {Array.from({ length: 6 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-gray-100 rounded animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6} className="text-center py-12 text-sm text-gray-400">
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

type Tab = 'status' | 'send'

export default function EmailsPage() {
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const hasInfluencerIds = !!searchParams.get('influencer_ids')

  const [activeTab, setActiveTab] = useState<Tab>(hasInfluencerIds ? 'send' : 'status')

  useEffect(() => {
    if (hasInfluencerIds) setActiveTab('send')
  }, [hasInfluencerIds])

  return (
    <div className="p-6">
      {/* Tab bar */}
      <div className="flex border-b border-gray-200 mb-6">
        {([
          { key: 'status', label: t('emails.tabStatus') },
          { key: 'send',   label: t('emails.tabBatchSend') },
        ] as { key: Tab; label: string }[]).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === key
                ? 'border-gray-900 text-gray-900'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'status' ? <StatusDashboard /> : <SendPanel />}
    </div>
  )
}
