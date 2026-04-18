import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Send,
  Loader2,
  Users,
  CheckSquare,
  Square,
  ExternalLink,
} from 'lucide-react'
import { scrapeApi, ScrapeTask, ScrapeInfluencerResult, parsePlatforms } from '../api/scrape'
import { useWebSocket, WsMessage } from '../hooks/useWebSocket'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatFollowers(n: number | null): string {
  if (n === null || n === undefined) return '—'
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

type SortDir = 'desc' | 'asc'

// ── Live Progress Types & Helpers ─────────────────────────────────────────────

type LiveProgress = {
  task_id: number
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  found_count: number
  valid_count: number
  latest_email?: string
  error?: string
}

function StatusPill({ status }: { status: string }) {
  const { t } = useTranslation()
  const styles: Record<string, string> = {
    pending: 'bg-gray-100 text-gray-600',
    running: 'bg-blue-50 text-blue-700 animate-pulse',
    completed: 'bg-emerald-50 text-emerald-700',
    failed: 'bg-red-50 text-red-700',
    cancelled: 'bg-gray-100 text-gray-500',
  }
  return (
    <span className={`inline-flex items-center px-3 py-1 text-xs font-medium rounded-full ${styles[status] ?? styles.pending}`}>
      {t(`scrape.status.${status === 'completed' ? 'done' : status}`)}
    </span>
  )
}

function StatCard({ label, value, highlight }: { label: string; value: number; highlight?: boolean }) {
  return (
    <div className={`px-4 py-3 rounded-xl ${highlight ? 'bg-blue-50' : 'bg-white border border-gray-100'}`}>
      <div className={`text-2xl font-bold tabular-nums ${highlight ? 'text-blue-700' : 'text-gray-900'}`}>
        {value}
      </div>
      <div className="text-[11px] text-gray-500 mt-0.5">{label}</div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ScrapeTaskDetailPage() {
  const { t } = useTranslation()
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const id = Number(taskId)

  const [task, setTask] = useState<ScrapeTask | null>(null)
  const [results, setResults] = useState<ScrapeInfluencerResult[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [live, setLive] = useState<LiveProgress | null>(null)
  const [emailStream, setEmailStream] = useState<{ email: string; at: number }[]>([])

  const fetchData = useCallback(async () => {
    if (!id) return
    setLoading(true)
    try {
      const [taskData, resultsData] = await Promise.all([
        scrapeApi.getTask(id),
        scrapeApi.getTaskResults(id, 'followers'),
      ])
      setTask(taskData)
      setResults(resultsData)
      // Select all by default
      setSelected(new Set(resultsData.map((r) => r.id)))
    } catch {
      /* silent */
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetchData() }, [fetchData])

  // ── WebSocket: subscribe to scrape:progress for this task ──────────────────
  const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`
  useWebSocket(wsUrl, useCallback((msg: WsMessage) => {
    if (msg.event !== 'scrape:progress') return
    const evt = msg.data as LiveProgress
    if (evt.task_id !== id) return
    setLive(evt)
    if (evt.latest_email) {
      setEmailStream((prev) => {
        if (prev.some((e) => e.email === evt.latest_email)) return prev
        const next = [{ email: evt.latest_email!, at: Date.now() }, ...prev]
        return next.slice(0, 20)
      })
    }
  }, [id]))

  // ── Poll results every 3s while running ────────────────────────────────────
  useEffect(() => {
    const currentStatus = live?.status ?? task?.status
    if (currentStatus !== 'running' && currentStatus !== 'pending') return
    const timer = setInterval(() => { fetchData() }, 3000)
    return () => clearInterval(timer)
  }, [live?.status, task?.status, fetchData])

  // ── Final refresh when task completes or fails ─────────────────────────────
  useEffect(() => {
    if (live?.status === 'completed' || live?.status === 'failed') {
      const timer = setTimeout(() => { fetchData() }, 1500)
      return () => clearTimeout(timer)
    }
  }, [live?.status, fetchData])

  // ── Sort client-side for asc/desc toggle ───────────────────────────────────
  const sorted = [...results].sort((a, b) => {
    const fa = a.followers ?? -1
    const fb = b.followers ?? -1
    return sortDir === 'desc' ? fb - fa : fa - fb
  })

  // ── Selection helpers ──────────────────────────────────────────────────────
  const allSelected = results.length > 0 && selected.size === results.length
  const someSelected = selected.size > 0 && selected.size < results.length

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set())
    } else {
      setSelected(new Set(results.map((r) => r.id)))
    }
  }

  function toggleOne(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // ── Send all selected ──────────────────────────────────────────────────────
  function handleSendAll() {
    const ids = [...selected].join(',')
    navigate(`/emails?influencer_ids=${ids}`)
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <Loader2 size={20} className="animate-spin mr-2" />
        <span className="text-sm">{t('scrapeDetail.loading')}</span>
      </div>
    )
  }

  if (!task) {
    return (
      <div className="p-6">
        <p className="text-sm text-red-500">{t('scrapeDetail.notFound')}</p>
      </div>
    )
  }

  const platforms = parsePlatforms(task.platforms)

  return (
    <div className="p-6 space-y-5">
      {/* Back + header */}
      <div className="flex items-start gap-4">
        <button
          onClick={() => navigate('/scrape')}
          className="mt-0.5 text-gray-400 hover:text-gray-700 transition-colors"
        >
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-base font-semibold text-gray-900">
            {t('scrapeDetail.title', { id: task.id })}
          </h1>
          <p className="text-xs text-gray-400 mt-0.5">
            {t('scrapeDetail.subtitle', { platforms: platforms.join(', '), industry: task.industry, count: task.valid_count })}
          </p>
        </div>
      </div>

      {/* Live progress dashboard */}
      {task && (task.status === 'running' || task.status === 'pending' || live) && (
        <div className="bg-gradient-to-br from-white to-gray-50 border border-gray-200 rounded-2xl p-6 space-y-5">
          {/* Status pill + big percentage */}
          <div className="flex items-center justify-between">
            <StatusPill status={(live?.status ?? task.status) as string} />
            <div className="text-right">
              <div className="text-3xl font-bold text-gray-900 tabular-nums">
                {live?.progress ?? task.progress}%
              </div>
              <div className="text-xs text-gray-400 mt-0.5">{t('scrapeDetail.live.progress')}</div>
            </div>
          </div>

          {/* Large progress bar */}
          <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ease-out ${
                (live?.status ?? task.status) === 'completed' ? 'bg-emerald-500' :
                (live?.status ?? task.status) === 'failed' ? 'bg-red-500' :
                'bg-blue-500'
              }`}
              style={{ width: `${live?.progress ?? task.progress}%` }}
            />
          </div>

          {/* 4 stat cards */}
          <div className="grid grid-cols-4 gap-3">
            <StatCard label={t('scrapeDetail.live.stats.target')} value={task.target_count} />
            <StatCard label={t('scrapeDetail.live.stats.found')} value={live?.found_count ?? task.found_count} />
            <StatCard label={t('scrapeDetail.live.stats.valid')} value={live?.valid_count ?? task.valid_count} highlight />
            <StatCard label={t('scrapeDetail.live.stats.platforms')} value={platforms.length} />
          </div>

          {/* Live email stream */}
          {emailStream.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-100 p-4 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-gray-500 uppercase tracking-wider">
                  {t('scrapeDetail.live.recentEmails')}
                </span>
                <span className="text-[10px] text-gray-400">
                  {t('scrapeDetail.live.showingCount', { count: emailStream.length })}
                </span>
              </div>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {emailStream.map((item, i) => (
                  <div
                    key={i}
                    className={`flex items-center gap-2 text-xs font-mono ${i === 0 ? 'text-gray-900' : 'text-gray-500'}`}
                  >
                    <span className="text-green-500">●</span>
                    <span className="truncate">{item.email}</span>
                    <span className="text-gray-300 ml-auto shrink-0">
                      {new Date(item.at).toLocaleTimeString()}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Error message when failed */}
          {(live?.status === 'failed' || task.status === 'failed') && (task.error_message || live?.error) && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-xs text-red-700">
              <strong>{t('scrapeDetail.live.errorLabel')}:</strong>{' '}
              {live?.error ?? task.error_message}
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {results.length === 0 && (
        <div className="py-16 text-center space-y-2">
          <Users size={32} className="mx-auto text-gray-200" />
          <p className="text-sm text-gray-500">{t('scrapeDetail.emptyTitle')}</p>
          <p className="text-xs text-gray-400">
            {task.status === 'running' || task.status === 'pending'
              ? t('scrapeDetail.emptyInProgress')
              : t('scrapeDetail.emptyNoResults')}
          </p>
        </div>
      )}

      {/* Results table */}
      {results.length > 0 && (
        <>
          {/* Table controls */}
          <div className="flex items-center justify-between">
            <p className="text-xs text-gray-500">
              {t('scrapeDetail.selected', { selected: selected.size, total: results.length })}
            </p>
            <button
              onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 transition-colors px-2 py-1 rounded hover:bg-gray-100"
            >
              {sortDir === 'desc' ? <ArrowDown size={12} /> : <ArrowUp size={12} />}
              {sortDir === 'desc' ? t('scrapeDetail.sortMost') : t('scrapeDetail.sortLeast')}
              <ArrowUpDown size={10} className="opacity-40" />
            </button>
          </div>

          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/60">
                  <th className="px-4 py-3 text-left w-10">
                    <button onClick={toggleAll} className="text-gray-400 hover:text-gray-700 transition-colors">
                      {allSelected ? (
                        <CheckSquare size={14} className="text-gray-900" />
                      ) : someSelected ? (
                        <CheckSquare size={14} className="text-gray-400" />
                      ) : (
                        <Square size={14} />
                      )}
                    </button>
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('scrapeDetail.table.name')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('scrapeDetail.table.platform')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('scrapeDetail.table.email')}</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 cursor-pointer select-none"
                      onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}>
                    <span className="flex items-center justify-end gap-1">
                      {t('scrapeDetail.table.followers')}
                      {sortDir === 'desc' ? <ArrowDown size={11} /> : <ArrowUp size={11} />}
                    </span>
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('scrapeDetail.table.bio')}</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('scrapeDetail.table.relevance')}</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('scrapeDetail.table.matchReason')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {sorted.map((inf) => {
                  const isChecked = selected.has(inf.id)
                  return (
                    <tr
                      key={inf.id}
                      className={`transition-colors ${isChecked ? 'bg-white hover:bg-gray-50/60' : 'bg-gray-50/40 opacity-60 hover:opacity-80'}`}
                    >
                      <td className="px-4 py-3">
                        <button
                          onClick={() => toggleOne(inf.id)}
                          className="text-gray-400 hover:text-gray-700 transition-colors"
                        >
                          {isChecked ? (
                            <CheckSquare size={14} className="text-gray-900" />
                          ) : (
                            <Square size={14} />
                          )}
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
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
                      <td className="px-4 py-3">
                        <PlatformBadge platform={inf.platform} />
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-700 font-mono truncate max-w-[180px]">
                        {inf.email}
                      </td>
                      <td className="px-4 py-3 text-right text-xs font-medium text-gray-800">
                        {formatFollowers(inf.followers)}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400 truncate max-w-[200px]">
                        {inf.bio ? inf.bio.slice(0, 80) + (inf.bio.length > 80 ? '…' : '') : '—'}
                      </td>
                      <td className="px-3 py-2 text-sm">
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
                      <td className="px-3 py-2 text-sm text-gray-600 max-w-[200px] truncate" title={inf.match_reason || ''}>
                        {inf.match_reason ? inf.match_reason : <span className="text-gray-300">—</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Bottom action bar */}
          <div className="flex items-center justify-between pt-1">
            <p className="text-xs text-gray-400">
              {t('scrapeDetail.hint')}
            </p>
            <button
              onClick={handleSendAll}
              disabled={selected.size === 0}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Send size={13} />
              {t('scrapeDetail.sendAll', { count: selected.size })}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
