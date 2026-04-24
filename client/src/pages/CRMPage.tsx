import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { ExternalLink, Loader2 } from 'lucide-react'
import { listInfluencers, type InfluencerListItem } from '../api/influencers'
import { useWebSocket, type WsMessage } from '../hooks/useWebSocket'
import AvatarBadge from '../components/AvatarBadge'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatFollowers(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function PlatformBadge({ platform }: { platform: string | null }) {
  if (!platform) return <span className="text-gray-400 text-xs">—</span>
  const colors: Record<string, string> = {
    instagram: 'bg-pink-50 text-pink-700',
    youtube: 'bg-red-50 text-red-700',
    tiktok: 'bg-gray-900 text-white',
    twitter: 'bg-sky-50 text-sky-700',
    facebook: 'bg-blue-50 text-blue-700',
  }
  const cls = colors[platform] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-block px-1.5 py-0.5 text-[11px] font-medium rounded capitalize ${cls}`}>
      {platform}
    </span>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CRMPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [items, setItems] = useState<InfluencerListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await listInfluencers({ page, page_size: pageSize })
      // Backend returns items ordered by created_at DESC (newest first), which
      // matches the "real-time sync" narrative — new scraped influencers
      // surface on page 1 automatically.
      setItems(resp.items)
      setTotal(resp.total)
      setTotalPages(Math.max(1, resp.total_pages))
    } catch {
      setItems([])
      setTotal(0)
      setTotalPages(1)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize])

  useEffect(() => { load() }, [load])

  // If pageSize change puts current page past the new last page, step back.
  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  // ── WebSocket: new influencers from scraper land here in real time ─────────
  const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`
  useWebSocket(wsUrl, useCallback((msg: WsMessage) => {
    if (msg.event !== 'influencer:created') return
    const newItem = msg.data as InfluencerListItem
    if (!newItem || typeof newItem.id !== 'number') return
    // Only prepend live when the user is on page 1 — otherwise pagination
    // would break (the bottom item of page 1 would overlap with the top of
    // page 2). Users on other pages will see the new data when they navigate
    // back to page 1 (which triggers a fresh fetch).
    if (page !== 1) {
      setTotal((t) => t + 1)
      return
    }
    setItems((prev) => {
      if (prev.some((r) => r.id === newItem.id)) return prev
      // Prepend + cap length to keep page size stable; the displaced last
      // item has moved to page 2 logically and will appear there on refetch.
      return [newItem, ...prev].slice(0, pageSize)
    })
    setTotal((t) => t + 1)
  }, [page, pageSize]))

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">{t('crm.title')}</h1>
        <p className="text-xs text-gray-400 mt-1">{t('crm.totalCount', { count: total })}</p>
      </div>

      {loading && items.length === 0 ? (
        <div className="flex items-center justify-center h-64 text-gray-400">
          <Loader2 size={20} className="animate-spin mr-2" />
          <span className="text-sm">{t('crm.loading')}</span>
        </div>
      ) : items.length === 0 ? (
        <div className="flex items-center justify-center h-64 text-gray-400">
          <span className="text-sm">{t('crm.noInfluencers')}</span>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/60">
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">{t('scrapeDetail.table.name')}</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">{t('scrapeDetail.table.platform')}</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">{t('scrapeDetail.table.email')}</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">{t('scrapeDetail.table.followers')}</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">{t('scrapeDetail.table.bio')}</th>
                <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('scrapeDetail.table.relevance')}</th>
                <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('scrapeDetail.table.matchReason')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {items.map((inf) => (
                <tr
                  key={inf.id}
                  className="transition-colors bg-white hover:bg-gray-50/60 cursor-pointer"
                  onClick={() => navigate(`/crm/${inf.id}`)}
                >
                  <td className="px-4 py-3 text-left align-middle" style={{ verticalAlign: 'middle' }}>
                    <div className="flex items-center gap-1.5">
                      <AvatarBadge url={inf.avatar_url} name={inf.nickname} size={24} />
                      <span className="text-xs font-medium text-gray-800 truncate max-w-[120px]">
                        {inf.nickname || '—'}
                      </span>
                      {inf.profile_url && (
                        <a
                          href={inf.profile_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-gray-300 hover:text-gray-600 transition-colors shrink-0"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <ExternalLink size={10} />
                        </a>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center align-middle" style={{ verticalAlign: 'middle' }}>
                    <PlatformBadge platform={inf.platform} />
                  </td>
                  <td className="px-4 py-3 text-center text-xs text-gray-700 font-mono align-middle" style={{ verticalAlign: 'middle' }}>
                    {inf.email}
                  </td>
                  <td className="px-4 py-3 text-center text-xs font-medium text-gray-800 align-middle" style={{ verticalAlign: 'middle' }}>
                    {formatFollowers(inf.followers)}
                  </td>
                  <td className="px-4 py-3 text-center text-xs text-gray-400 align-middle whitespace-pre-wrap max-w-[320px]" style={{ verticalAlign: 'middle' }}>
                    {inf.bio || '—'}
                  </td>
                  <td className="px-3 py-2 text-center text-sm align-middle" style={{ verticalAlign: 'middle' }}>
                    {inf.relevance_score != null ? (
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        inf.relevance_score >= 0.7 ? 'bg-green-50 text-green-700' :
                        inf.relevance_score >= 0.4 ? 'bg-yellow-50 text-yellow-700' :
                        'bg-gray-50 text-gray-500'
                      }`}>
                        {(inf.relevance_score * 100).toFixed(0)}%
                      </span>
                    ) : (
                      <span className="text-gray-300">—</span>
                    )}
                  </td>
                  <td
                    className="px-3 py-2 text-center text-sm text-gray-600 align-middle whitespace-pre-wrap max-w-[240px]"
                    style={{ verticalAlign: 'middle' }}
                    title={inf.match_reason || ''}
                  >
                    {inf.match_reason ? inf.match_reason : <span className="text-gray-300">—</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination footer */}
      {total > 0 && (
        <div className="flex items-center justify-end gap-6 text-xs text-gray-500 pt-2">
          {/* Left: page size selector */}
          <div className="flex items-center gap-2">
            <span>每页</span>
            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1) }}
              className="border border-gray-200 rounded px-2 py-1 text-xs bg-white focus:outline-none focus:border-gray-400 cursor-pointer"
            >
              <option value={10}>10</option>
              <option value={20}>20</option>
            </select>
            <span>条</span>
          </div>

          {/* Middle: page navigator */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              ‹ 上一页
            </button>
            {renderPageButtons(page, totalPages, setPage)}
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              下一页 ›
            </button>
          </div>

          {/* Right: counters */}
          <div className="text-gray-400">
            共 {total} 条 · 第 {page}/{totalPages} 页
          </div>
        </div>
      )}
    </div>
  )
}

// Build a compact page-number list: always show first / last / current ±1
// with '…' collapsing the rest. Keeps the footer scannable even at 100+ pages.
function renderPageButtons(cur: number, total: number, setPage: (n: number) => void) {
  if (total <= 1) return null
  const pages: (number | '...')[] = []
  const add = (n: number) => { if (!pages.includes(n)) pages.push(n) }
  add(1)
  if (cur - 1 > 2) pages.push('...')
  for (let n = Math.max(2, cur - 1); n <= Math.min(total - 1, cur + 1); n++) add(n)
  if (cur + 1 < total - 1) pages.push('...')
  if (total > 1) add(total)
  return pages.map((p, i) =>
    p === '...' ? (
      <span key={`gap-${i}`} className="px-1 text-gray-300">…</span>
    ) : (
      <button
        key={p}
        onClick={() => setPage(p)}
        className={`min-w-[28px] px-2 py-1 rounded transition-colors ${
          p === cur
            ? 'bg-gray-900 text-white'
            : 'hover:bg-gray-100 text-gray-600'
        }`}
      >
        {p}
      </button>
    ),
  )
}
