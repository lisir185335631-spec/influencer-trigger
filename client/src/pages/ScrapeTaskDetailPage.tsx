import { useState, useEffect, useCallback, Fragment } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Loader2,
  Users,
  ExternalLink,
  ChevronDown,
} from 'lucide-react'
import { scrapeApi, ScrapeTask, ScrapeInfluencerResult, parsePlatforms } from '../api/scrape'
import { useWebSocket, WsMessage } from '../hooks/useWebSocket'
import AvatarBadge from '../components/AvatarBadge'

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
type SortField = 'relevance_score' | 'followers'

// ── Live Progress Types & Helpers ─────────────────────────────────────────────

type QuotaError = {
  service: 'brave' | 'apify' | string
  http_code: number
  message: string
}

type LiveProgress = {
  task_id: number
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  progress: number
  phase?:
    | 'starting'
    | 'querying_history'
    | 'llm_thinking'
    | 'strategy_ready'
    | 'browser_starting'
    | 'searching'
    | 'crawling'
    | 'enriching'
    | 'completed'
  // Free-text status line emitted by inner scrapers during the long
  // crawl phase (e.g. "搜索 query 5/12: ChatGPT", "访问 channel 12/100:
  // @MKBHD"). When non-empty, the UI shows this verbatim instead of
  // the generic phase translation — so the user sees something moving
  // every 5-15s during the multi-minute crawl window.
  phase_detail?: string
  found_count: number
  valid_count: number
  new_count?: number
  reused_count?: number
  latest_email?: string
  error?: string
  warning?: string | null
  quota_exceeded?: boolean
  quota_errors?: QuotaError[] | null
}

function StatusPill({ status }: { status: string }) {
  const { t } = useTranslation()
  const styles: Record<string, string> = {
    pending: 'bg-gray-100 text-gray-600',
    // running: solid blue + white text + ring + pulse so the badge is
    // obvious on white page background. Previous bg-blue-50/text-blue-700
    // had so little contrast the user couldn't tell the task was alive.
    running: 'bg-blue-600 text-white ring-2 ring-blue-300 ring-offset-1 shadow-sm animate-pulse',
    completed: 'bg-emerald-50 text-emerald-700',
    failed: 'bg-red-50 text-red-700',
    cancelled: 'bg-gray-100 text-gray-500',
  }
  return (
    <span className={`inline-flex items-center px-3 py-1 text-xs font-semibold rounded-full ${styles[status] ?? styles.pending}`}>
      {status === 'running' && <Loader2 size={12} className="animate-spin mr-1.5" />}
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
  // Default to relevance_score so the user immediately sees high-quality
  // matches at the top of the list. Followers stays as a one-click toggle.
  const [sortField, setSortField] = useState<SortField>('relevance_score')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [live, setLive] = useState<LiveProgress | null>(null)
  const [emailStream, setEmailStream] = useState<{ email: string; at: number }[]>([])
  const [expandedId, setExpandedId] = useState<number | null>(null)
  // Quota-exceeded modal: when Brave/Apify run out of credit mid-task we
  // pop up a clear "go top up" dialog instead of leaving the user staring
  // at a found=0 result wondering what went wrong. Tracked per task so
  // the modal doesn't re-open on every WebSocket event.
  const [quotaModal, setQuotaModal] = useState<QuotaError[] | null>(null)
  const [quotaModalDismissed, setQuotaModalDismissed] = useState(false)

  const fetchData = useCallback(async (silent = false) => {
    if (!id) return
    if (!silent) setLoading(true)
    try {
      const [taskData, resultsData] = await Promise.all([
        scrapeApi.getTask(id),
        scrapeApi.getTaskResults(id, 'followers'),
      ])
      setTask(taskData)
      setResults((prev) => {
        // Keep the same array reference if content hasn't changed (prevents table flicker)
        if (prev.length === resultsData.length && prev.every((r, i) => r.id === resultsData[i].id && r.relevance_score === resultsData[i].relevance_score)) {
          return prev
        }
        return resultsData
      })
    } catch {
      /* silent */
    } finally {
      if (!silent) setLoading(false)
    }
  }, [id])

  useEffect(() => { fetchData() }, [fetchData])

  // ── Re-derive quota errors from a refreshed task ──────────────────
  // Modal previously only triggered from WebSocket events. If the user
  // navigates away and back, the task is already `completed` and no new
  // WebSocket event will arrive — but task.error_message still contains
  // the quota messages we wrote at completion time. Parse it back into
  // QuotaError[] so the modal pops on refresh too.
  useEffect(() => {
    if (!task?.error_message) return
    if (quotaModal !== null) return  // already populated (e.g. by live event)
    if (quotaModalDismissed) return  // user already saw it this session

    const msg = task.error_message
    const errors: QuotaError[] = []

    // Brave segment — recognise auth/quota messages we wrote in scraper.py.
    if (msg.includes("Brave")) {
      const codeMatch = msg.match(/Brave[^|]*?HTTP\s*(\d{3})/) ||
                        msg.match(/Brave[^|]*?(429|401|403)/)
      const code = codeMatch ? Number(codeMatch[1]) : 429
      const start = msg.indexOf("Brave")
      const end = msg.indexOf(" | ", start)
      errors.push({
        service: "brave",
        http_code: code,
        message: end === -1 ? msg.slice(start) : msg.slice(start, end),
      })
    }

    // Apify segment — same pattern.
    if (msg.includes("Apify")) {
      const codeMatch = msg.match(/Apify[^|]*?HTTP\s*(\d{3})/) ||
                        msg.match(/Apify[^|]*?(429|401|402|403)/)
      const code = codeMatch ? Number(codeMatch[1]) : 402
      const start = msg.indexOf("Apify")
      const end = msg.indexOf(" | ", start)
      errors.push({
        service: "apify",
        http_code: code,
        message: end === -1 ? msg.slice(start) : msg.slice(start, end),
      })
    }

    if (errors.length > 0) {
      setQuotaModal(errors)
    }
  }, [task, quotaModal, quotaModalDismissed])

  // ── WebSocket: subscribe to scrape:progress for this task ──────────────────
  const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`
  useWebSocket(wsUrl, useCallback((msg: WsMessage) => {
    if (msg.event !== 'scrape:progress') return
    const evt = msg.data as LiveProgress
    if (evt.task_id !== id) return
    setLive(evt)
    // Trigger quota modal once per task. We check `quotaModalDismissed`
    // inside the setter via setQuotaModal — actually simplest is to just
    // open the modal whenever quota_exceeded is freshly seen and the user
    // hasn't dismissed it yet for this task.
    if (evt.quota_exceeded && evt.quota_errors && evt.quota_errors.length > 0) {
      setQuotaModal((prev) => prev ?? evt.quota_errors!)
    }
    if (evt.latest_email) {
      setEmailStream((prev) => {
        if (prev.some((e) => e.email === evt.latest_email)) return prev
        const next = [{ email: evt.latest_email!, at: Date.now() }, ...prev]
        return next.slice(0, 20)
      })
    }
  }, [id]))

  // ── Poll results every 3s while running (SILENT refresh, no loading flash) ─
  useEffect(() => {
    const currentStatus = live?.status ?? task?.status
    if (currentStatus !== 'running' && currentStatus !== 'pending') return
    const timer = setInterval(() => { fetchData(true) }, 3000)
    return () => clearInterval(timer)
  }, [live?.status, task?.status, fetchData])

  // ── Final refresh when task completes or fails (also silent) ───────────────
  useEffect(() => {
    if (live?.status === 'completed' || live?.status === 'failed') {
      const timer = setTimeout(() => { fetchData(true) }, 1500)
      return () => clearTimeout(timer)
    }
  }, [live?.status, fetchData])


  // ── Sort client-side: by relevance_score (default) or followers ────────────
  // For relevance_score sorting, ties (e.g. two channels both at 0.85) are
  // broken by followers DESC so the more impactful KOL wins the tiebreak.
  const sorted = [...results].sort((a, b) => {
    if (sortField === 'relevance_score') {
      const sa = a.relevance_score ?? -1
      const sb = b.relevance_score ?? -1
      if (sa !== sb) return sortDir === 'desc' ? sb - sa : sa - sb
      const fa = a.followers ?? -1
      const fb = b.followers ?? -1
      return fb - fa
    }
    const fa = a.followers ?? -1
    const fb = b.followers ?? -1
    return sortDir === 'desc' ? fb - fa : fa - fb
  })

  // Helper: toggle direction if same field clicked again, else switch field
  // (and reset to desc for the new field — desc is what users want by default).
  const handleSortClick = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortField(field)
      setSortDir('desc')
    }
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

  // Quota-exceeded modal: shown when Brave or Apify ran out of credit
  // during this task. We set `quotaModalDismissed` after first close so
  // re-arriving WebSocket events for the same task don't re-pop the modal,
  // but the user can still see the persistent amber warning banner below.
  const quotaModalVisible = quotaModal !== null && !quotaModalDismissed

  return (
    <div className="p-6 space-y-5">
      {/* Quota-exceeded modal — pops once per task when Brave/Apify auth
          or quota fails mid-run. Dismissable, after which the persistent
          amber banner below the progress dashboard keeps the warning
          visible without nagging. */}
      {quotaModalVisible && quotaModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full mx-4 p-6 space-y-4">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-full bg-red-50 flex items-center justify-center shrink-0">
                <span className="text-xl">⚠</span>
              </div>
              <div className="flex-1 min-w-0">
                <h2 className="text-base font-semibold text-gray-900">
                  {t('scrapeDetail.live.quotaModal.title')}
                </h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  {t('scrapeDetail.live.quotaModal.subtitle')}
                </p>
              </div>
            </div>
            <div className="space-y-2">
              {quotaModal.map((qe, i) => (
                <div key={i} className="bg-red-50 border border-red-200 rounded-lg p-3">
                  <div className="text-xs font-mono text-red-700 mb-1">
                    {qe.service.toUpperCase()} · HTTP {qe.http_code}
                  </div>
                  <div className="text-sm text-gray-800 leading-relaxed">
                    {qe.message}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setQuotaModalDismissed(true)}
                className="px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-700 transition-colors"
              >
                {t('scrapeDetail.live.quotaModal.dismiss')}
              </button>
            </div>
          </div>
        </div>
      )}

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

      {/* Progress dashboard — always shown once task data loads so completed
           tasks still display the final % / status pill / stat cards. */}
      {task && (
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

          {/* Phase text (under progress bar). When the inner scraper sends
              a phase_detail (e.g. "搜索 query 5/12: ChatGPT"), prefer it
              over the generic phase translation so the user sees the actual
              work happening during the long crawl phase. Without this, the
              UI sat on "正在抓取频道并提取邮箱…" for several minutes with
              no signal anything was alive (the task #50 "stuck at 15%"
              complaint). */}
          {live?.phase && (live?.status === 'running' || live?.status === 'pending') && (
            <p className="text-xs text-gray-500 -mt-2 transition-opacity truncate" title={live.phase_detail || undefined}>
              {live.phase_detail || t(`scrapeDetail.live.phases.${live.phase}`)}
            </p>
          )}

          {/* 5 stat cards: target / found / NEW (highlight) / reused / platforms.
              "新增" is the one number that actually matters for ROI — pre-fix
              the card said "已入库" mixing fresh discoveries with re-linked
              old channels, which is how task #23's 0-new-finds pretended to
              be a 100% successful 6-find run. Splitting the two numbers
              makes that case immediately legible. */}
          <div className="grid grid-cols-5 gap-3">
            <StatCard label={t('scrapeDetail.live.stats.target')} value={task.target_count} />
            <StatCard label={t('scrapeDetail.live.stats.found')} value={live?.found_count ?? task.found_count} />
            <StatCard label={t('scrapeDetail.live.stats.new')} value={live?.new_count ?? task.new_count ?? task.valid_count} highlight />
            <StatCard label={t('scrapeDetail.live.stats.reused')} value={live?.reused_count ?? task.reused_count ?? 0} />
            <StatCard label={t('scrapeDetail.live.stats.platforms')} value={platforms.length} />
          </div>

          {/* Completed-with-warning banner: the task ran to completion but
              error_message was populated (LLM fallback / 0 new finds). The
              underlying ScrapeTaskStatus is still "completed" — we surface
              the caveat inline rather than inventing a new status. */}
          {(live?.status === 'completed' || task.status === 'completed') && (live?.warning || task.error_message) && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800">
              <strong>{t('scrapeDetail.live.warningLabel')}:</strong>{' '}
              {live?.warning ?? task.error_message}
            </div>
          )}

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
              {t('scrapeDetail.totalInfluencers', { count: results.length })}
            </p>
            <div className="flex items-center gap-1">
              <button
                onClick={() => handleSortClick('relevance_score')}
                className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${
                  sortField === 'relevance_score'
                    ? 'text-gray-900 bg-gray-100'
                    : 'text-gray-400 hover:text-gray-700 hover:bg-gray-50'
                }`}
              >
                {t('scrapeDetail.sortByRelevance') || '相关度'}
                {sortField === 'relevance_score' && (
                  sortDir === 'desc' ? <ArrowDown size={11} /> : <ArrowUp size={11} />
                )}
              </button>
              <button
                onClick={() => handleSortClick('followers')}
                className={`flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors ${
                  sortField === 'followers'
                    ? 'text-gray-900 bg-gray-100'
                    : 'text-gray-400 hover:text-gray-700 hover:bg-gray-50'
                }`}
              >
                {t('scrapeDetail.sortByFollowers') || '粉丝数'}
                {sortField === 'followers' && (
                  sortDir === 'desc' ? <ArrowDown size={11} /> : <ArrowUp size={11} />
                )}
              </button>
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/60">
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('scrapeDetail.table.name')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('scrapeDetail.table.platform')}</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('scrapeDetail.table.email')}</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 cursor-pointer select-none hover:text-gray-800"
                      onClick={() => handleSortClick('followers')}>
                    <span className="flex items-center justify-end gap-1">
                      {t('scrapeDetail.table.followers')}
                      {sortField === 'followers' && (
                        sortDir === 'desc' ? <ArrowDown size={11} /> : <ArrowUp size={11} />
                      )}
                    </span>
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('scrapeDetail.table.bio')}</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase cursor-pointer select-none hover:text-gray-800"
                      onClick={() => handleSortClick('relevance_score')}>
                    <span className="flex items-center gap-1">
                      {t('scrapeDetail.table.relevance')}
                      {sortField === 'relevance_score' && (
                        sortDir === 'desc' ? <ArrowDown size={11} /> : <ArrowUp size={11} />
                      )}
                    </span>
                  </th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">{t('scrapeDetail.table.matchReason')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {sorted.map((inf) => {
                  const isExpanded = expandedId === inf.id
                  // Visual de-emphasis for low-relevance rows: lighter
                  // background tint and dimmed text so the user's eye
                  // naturally lands on the high-relevance rows up top.
                  // Threshold 0.5 matches the prefilter's intent — below
                  // it = low business signal, may not be worth outreach.
                  const isLowRelevance = inf.relevance_score != null && inf.relevance_score < 0.5
                  const rowClass = isLowRelevance
                    ? 'transition-colors bg-gray-50/40 hover:bg-gray-100/60 opacity-70'
                    : 'transition-colors bg-white hover:bg-gray-50/60'
                  return (
                    <Fragment key={inf.id}>
                      <tr className={rowClass}>
                        <td className="px-4 py-3 align-middle">
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
                            <button
                              onClick={(e) => { e.stopPropagation(); setExpandedId(isExpanded ? null : inf.id) }}
                              className="ml-auto p-0.5 text-gray-300 hover:text-gray-700 transition-colors"
                            >
                              <ChevronDown
                                size={12}
                                className={isExpanded ? 'rotate-180 transition-transform' : 'transition-transform'}
                              />
                            </button>
                          </div>
                        </td>
                        <td className="px-4 py-3 align-middle">
                          <PlatformBadge platform={inf.platform} />
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-700 font-mono truncate max-w-[180px] align-middle">
                          {inf.email}
                        </td>
                        <td className="px-4 py-3 text-right text-xs font-medium text-gray-800 align-middle">
                          {formatFollowers(inf.followers)}
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-400 align-middle whitespace-pre-wrap max-w-[320px]">
                          {inf.bio || '—'}
                        </td>
                        <td className="px-3 py-2 text-sm align-middle">
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
                        <td className="px-3 py-2 text-sm text-gray-600 align-middle whitespace-pre-wrap max-w-[240px]" title={inf.match_reason || ''}>
                          {inf.match_reason ? inf.match_reason : <span className="text-gray-300">—</span>}
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr>
                          <td colSpan={7} className="bg-gray-50/60 px-6 py-5">
                            <div className="grid grid-cols-[auto_1fr] gap-5 max-w-4xl">
                              {/* 大头像 */}
                              <AvatarBadge url={inf.avatar_url} name={inf.nickname} size={72} />
                              {/* 详情 */}
                              <div className="space-y-3">
                                <div>
                                  <h3 className="text-base font-semibold text-gray-900">{inf.nickname || '—'}</h3>
                                  {inf.profile_url && (
                                    <a
                                      href={inf.profile_url}
                                      target="_blank"
                                      rel="noreferrer"
                                      className="text-xs text-blue-600 hover:underline break-all"
                                    >
                                      {inf.profile_url}
                                    </a>
                                  )}
                                </div>
                                <div className="grid grid-cols-3 gap-4 text-sm">
                                  <div>
                                    <div className="text-[10px] text-gray-400 uppercase">{t('scrapeDetail.expand.platform')}</div>
                                    <div className="font-medium text-gray-700 mt-1">{inf.platform || '—'}</div>
                                  </div>
                                  <div>
                                    <div className="text-[10px] text-gray-400 uppercase">{t('scrapeDetail.expand.followers')}</div>
                                    <div className="font-medium text-gray-700 mt-1">{formatFollowers(inf.followers)}</div>
                                  </div>
                                  <div>
                                    <div className="text-[10px] text-gray-400 uppercase">{t('scrapeDetail.expand.email')}</div>
                                    <div className="font-mono text-xs text-gray-700 mt-1 break-all">{inf.email}</div>
                                  </div>
                                </div>
                                {inf.bio && (
                                  <div>
                                    <div className="text-[10px] text-gray-400 uppercase mb-1">{t('scrapeDetail.expand.bio')}</div>
                                    <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">{inf.bio}</p>
                                  </div>
                                )}
                                {inf.relevance_score != null && (
                                  <div className="flex items-start gap-6">
                                    <div>
                                      <div className="text-[10px] text-gray-400 uppercase">{t('scrapeDetail.expand.relevance')}</div>
                                      <div className="text-xl font-bold text-gray-900 mt-1">{(inf.relevance_score * 100).toFixed(0)}%</div>
                                    </div>
                                    {inf.match_reason && (
                                      <div className="flex-1">
                                        <div className="text-[10px] text-gray-400 uppercase">{t('scrapeDetail.expand.matchReason')}</div>
                                        <p className="text-sm text-gray-700 mt-1">{inf.match_reason}</p>
                                      </div>
                                    )}
                                  </div>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>

        </>
      )}
    </div>
  )
}
