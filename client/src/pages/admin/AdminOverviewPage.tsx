import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  AlertTriangle,
  CheckCircle,
  Mail,
  RefreshCw,
  Users,
  XCircle,
  Zap,
} from 'lucide-react'
import {
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  Bar,
  BarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Legend,
} from 'recharts'
import {
  getHealthStatus,
  getOverviewMetrics,
  getRecentEvents,
  type HealthStatus,
  type OverviewMetrics,
  type RecentEvent,
} from '../../api/admin/overview'

const PLATFORM_COLORS: Record<string, string> = {
  tiktok: '#010101',
  instagram: '#E1306C',
  youtube: '#FF0000',
  twitter: '#1DA1F2',
  facebook: '#1877F2',
  other: '#94a3b8',
}

const LEVEL_COLORS: Record<string, string> = {
  info: 'text-blue-600',
  warning: 'text-amber-600',
  error: 'text-red-600',
  success: 'text-green-600',
}

const LEVEL_BG: Record<string, string> = {
  info: 'bg-blue-50',
  warning: 'bg-amber-50',
  error: 'bg-red-50',
  success: 'bg-green-50',
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ── Metric Card ────────────────────────────────────────────────────────────────
interface MetricCardProps {
  label: string
  value: number
  icon: React.ReactNode
  sub?: string
}

function MetricCard({ label, value, icon, sub }: MetricCardProps) {
  return (
    <div className="bg-white border border-gray-100 rounded-xl p-5 flex flex-col gap-3 hover:shadow-sm transition-shadow">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">{label}</span>
        <span className="text-gray-300">{icon}</span>
      </div>
      <div className="text-3xl font-bold text-gray-900 tabular-nums">{value.toLocaleString()}</div>
      {sub && <div className="text-xs text-gray-400">{sub}</div>}
    </div>
  )
}

// ── Health Indicator ───────────────────────────────────────────────────────────
interface HealthIndicatorProps {
  label: string
  status: 'green' | 'yellow' | 'red' | boolean
  sub?: string
}

function HealthIndicator({ label, status, sub }: HealthIndicatorProps) {
  const color =
    status === true || status === 'green'
      ? 'bg-green-500'
      : status === 'yellow'
      ? 'bg-amber-400'
      : 'bg-red-500'

  const textColor =
    status === true || status === 'green'
      ? 'text-green-700'
      : status === 'yellow'
      ? 'text-amber-700'
      : 'text-red-700'

  return (
    <div className="flex items-center gap-3 py-2">
      <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${color}`} />
      <div className="min-w-0">
        <div className="text-sm font-medium text-gray-700">{label}</div>
        {sub && <div className={`text-xs ${textColor}`}>{sub}</div>}
      </div>
    </div>
  )
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function AdminOverviewPage() {
  const { t } = useTranslation()
  const [metrics, setMetrics] = useState<OverviewMetrics | null>(null)
  const [health, setHealth] = useState<HealthStatus | null>(null)
  const [events, setEvents] = useState<RecentEvent[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchAll = useCallback(async (isManual = false) => {
    if (isManual) setRefreshing(true)
    try {
      const [m, h, e] = await Promise.all([
        getOverviewMetrics(),
        getHealthStatus(),
        getRecentEvents(),
      ])
      setMetrics(m)
      setHealth(h)
      setEvents(e)
      setLastRefreshed(new Date())
    } catch {
      // silent — keep stale data
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    intervalRef.current = setInterval(() => fetchAll(), 30_000)
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [fetchAll])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <RefreshCw className="w-6 h-6 text-gray-400 animate-spin" />
      </div>
    )
  }

  if (!metrics || !health) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-3">
        <p className="text-sm text-gray-400">{t('admin.overview.failedToLoad')}</p>
        <button
          onClick={() => fetchAll(true)}
          className="text-sm text-indigo-600 hover:text-indigo-800 underline"
        >
          {t('admin.overview.retry')}
        </button>
      </div>
    )
  }

  const m = metrics
  const h = health

  const mailboxStatusLabel =
    h.mailbox_pool.status === 'green'
      ? t('admin.overview.health.mailboxHealthy')
      : h.mailbox_pool.status === 'yellow'
      ? t('admin.overview.health.mailboxDegraded')
      : t('admin.overview.health.mailboxUnavailable')

  return (
    <div className="p-6 space-y-6 max-w-screen-xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">{t('admin.overview.title')}</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            {lastRefreshed
              ? t('admin.overview.lastUpdated', { time: lastRefreshed.toLocaleTimeString() })
              : t('admin.overview.loading')}
          </p>
        </div>
        <button
          onClick={() => fetchAll(true)}
          disabled={refreshing}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 disabled:opacity-50 transition-colors"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          {t('admin.common.refresh')}
        </button>
      </div>

      {/* Top 4 Metric Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label={t('admin.overview.metrics.emailsSentToday')}
          value={m.emails_sent.today}
          icon={<Mail className="w-5 h-5" />}
          sub={t('admin.overview.metrics.thisWeek', { count: m.emails_sent.this_week })}
        />
        <MetricCard
          label={t('admin.overview.metrics.newInfluencersToday')}
          value={m.influencers.today}
          icon={<Users className="w-5 h-5" />}
          sub={t('admin.overview.metrics.total', { count: m.influencers.total })}
        />
        <MetricCard
          label={t('admin.overview.metrics.repliesToday')}
          value={m.emails_replied.today}
          icon={<CheckCircle className="w-5 h-5" />}
          sub={t('admin.overview.metrics.thisWeek', { count: m.emails_replied.this_week })}
        />
        <MetricCard
          label={t('admin.overview.metrics.activeAgents')}
          value={m.agent_tasks.today}
          icon={<Zap className="w-5 h-5" />}
          sub={t('admin.overview.metrics.errorsToday', { count: m.errors.today })}
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* 7-day email trend */}
        <div className="lg:col-span-1 bg-white border border-gray-100 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">{t('admin.overview.charts.emailTrend')}</h2>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={m.charts.email_trend}>
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={28} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="sent" stroke="#6366f1" strokeWidth={2} dot={false} name={t('admin.overview.charts.sent')} />
              <Line type="monotone" dataKey="replied" stroke="#10b981" strokeWidth={2} dot={false} name={t('admin.overview.charts.replied')} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* 7-day scrape task bar chart */}
        <div className="lg:col-span-1 bg-white border border-gray-100 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">{t('admin.overview.charts.scrapeTasks')}</h2>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={m.charts.scrape_trend}>
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={28} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
              <Bar dataKey="tasks" fill="#6366f1" radius={[3, 3, 0, 0]} name={t('admin.overview.charts.tasks')} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Platform distribution donut */}
        <div className="lg:col-span-1 bg-white border border-gray-100 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">{t('admin.overview.charts.influencersByPlatform')}</h2>
          {m.charts.platform_dist.length === 0 ? (
            <div className="flex items-center justify-center h-[180px] text-sm text-gray-400">{t('admin.common.noData')}</div>
          ) : (
            <ResponsiveContainer width="100%" height={180}>
              <PieChart>
                <Pie
                  data={m.charts.platform_dist}
                  dataKey="count"
                  nameKey="platform"
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={75}
                  paddingAngle={2}
                >
                  {m.charts.platform_dist.map((entry) => (
                    <Cell
                      key={entry.platform}
                      fill={PLATFORM_COLORS[entry.platform] ?? '#94a3b8'}
                    />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
                  formatter={(value, name) => [value, name]}
                />
                <Legend
                  wrapperStyle={{ fontSize: 11 }}
                  formatter={(value) => value.charAt(0).toUpperCase() + value.slice(1)}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Bottom row: Health + Events */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* System Health */}
        <div className="bg-white border border-gray-100 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">{t('admin.overview.health.title')}</h2>
          <div className="divide-y divide-gray-50">
            <HealthIndicator
              label={h.db.label}
              status={h.db.ok}
              sub={h.db.ok ? t('admin.overview.health.connected') : t('admin.overview.health.unreachable')}
            />
            <HealthIndicator
              label={h.scheduler.label}
              status={h.scheduler.ok}
              sub={h.scheduler.ok ? t('admin.overview.health.running') : t('admin.overview.health.stopped')}
            />
            <HealthIndicator
              label={h.monitor.label}
              status={h.monitor.ok}
              sub={h.monitor.ok ? t('admin.overview.health.running') : t('admin.overview.health.stopped')}
            />
            <HealthIndicator
              label={h.websocket.label}
              status={h.websocket.ok}
              sub={t('admin.overview.health.activeConnections', { count: h.websocket.count })}
            />
            <HealthIndicator
              label={h.mailbox_pool.label}
              status={h.mailbox_pool.status}
              sub={mailboxStatusLabel}
            />
          </div>
        </div>

        {/* Recent Events */}
        <div className="lg:col-span-2 bg-white border border-gray-100 rounded-xl p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">{t('admin.overview.events.title')}</h2>
          {events.length === 0 ? (
            <div className="flex items-center justify-center h-32 text-sm text-gray-400">
              {t('admin.overview.events.noEvents')}
            </div>
          ) : (
            <div className="space-y-1 max-h-80 overflow-y-auto pr-1">
              {events.map((ev) => (
                <div
                  key={ev.id}
                  className={`flex gap-3 rounded-lg px-3 py-2 ${LEVEL_BG[ev.level] ?? 'bg-gray-50'}`}
                >
                  <div className="flex-shrink-0 mt-0.5">
                    {ev.level === 'error' ? (
                      <XCircle className="w-4 h-4 text-red-500" />
                    ) : ev.level === 'warning' ? (
                      <AlertTriangle className="w-4 h-4 text-amber-500" />
                    ) : ev.level === 'success' ? (
                      <CheckCircle className="w-4 h-4 text-green-500" />
                    ) : (
                      <Zap className="w-4 h-4 text-blue-500" />
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className={`text-xs font-medium ${LEVEL_COLORS[ev.level] ?? 'text-gray-700'}`}>
                      {ev.title}
                    </div>
                    <div className="text-xs text-gray-500 truncate">{ev.content}</div>
                  </div>
                  <div className="flex-shrink-0 text-xs text-gray-400 whitespace-nowrap">
                    {formatTime(ev.created_at)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
