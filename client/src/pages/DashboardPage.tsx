import { useEffect, useState } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
} from 'recharts'
import {
  fetchDashboardStats,
  fetchDashboardTrends,
  fetchPlatformDistribution,
  fetchMailboxHealth,
  type DashboardStats,
  type TrendPoint,
  type PlatformItem,
  type MailboxHealthItem,
} from '../api/dashboard'

// ── palette for pie chart ──────────────────────────────────────────────────
const PIE_COLORS = ['#1a1a2e', '#16213e', '#0f3460', '#533483', '#e94560', '#2d6a4f']

// ── helpers ────────────────────────────────────────────────────────────────
function pct(value: number) {
  return `${(value * 100).toFixed(1)}%`
}

function shortDate(iso: string) {
  return iso.slice(5) // MM-DD
}

// ── Stat card ──────────────────────────────────────────────────────────────
interface StatCardProps {
  label: string
  value: string | number
  sub?: string
}
function StatCard({ label, value, sub }: StatCardProps) {
  return (
    <div className="bg-white rounded-xl border border-gray-100 p-5 hover:border-t-2 hover:border-t-gray-900 transition-all duration-150">
      <p className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900 tabular-nums">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

// ── main page ──────────────────────────────────────────────────────────────
export default function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [trends, setTrends] = useState<TrendPoint[]>([])
  const [platforms, setPlatforms] = useState<PlatformItem[]>([])
  const [mailboxes, setMailboxes] = useState<MailboxHealthItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    Promise.all([
      fetchDashboardStats(),
      fetchDashboardTrends(),
      fetchPlatformDistribution(),
      fetchMailboxHealth(),
    ])
      .then(([s, t, p, m]) => {
        if (cancelled) return
        setStats(s)
        setTrends(t)
        setPlatforms(p)
        setMailboxes(m)
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? 'Failed to load dashboard')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  if (loading) {
    return (
      <div className="p-6 flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-gray-900 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-6">
        <div className="rounded-lg border border-red-100 bg-red-50 p-4 text-sm text-red-600">{error}</div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      {/* ── header ── */}
      <div>
        <h1 className="text-lg font-semibold text-gray-900">Dashboard</h1>
        <p className="text-sm text-gray-400 mt-0.5">Overview of influencer outreach operations</p>
      </div>

      {/* ── 5 stat cards ── */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-4">
          <StatCard
            label="Total Influencers"
            value={stats.total_influencers.toLocaleString()}
            sub={`+${stats.new_this_week} this week`}
          />
          <StatCard
            label="Total Sent"
            value={stats.total_sent.toLocaleString()}
            sub={`${stats.sent_this_week} this week`}
          />
          <StatCard
            label="Reply Rate"
            value={pct(stats.reply_rate)}
            sub="replied / sent"
          />
          <StatCard
            label="Effective Reply Rate"
            value={pct(stats.effective_reply_rate)}
            sub="interested + pricing / sent"
          />
          <StatCard
            label="Conversion Rate"
            value={pct(stats.conversion_rate)}
            sub="collaborations / influencers"
          />
        </div>
      )}

      {/* ── trend chart ── */}
      <div className="bg-white rounded-xl border border-gray-100 p-5">
        <p className="text-sm font-medium text-gray-700 mb-4">30-Day Send & Reply Trend</p>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={trends} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" />
            <XAxis
              dataKey="date"
              tickFormatter={shortDate}
              tick={{ fontSize: 11, fill: '#9ca3af' }}
              interval={4}
            />
            <YAxis tick={{ fontSize: 11, fill: '#9ca3af' }} width={36} />
            <Tooltip
              contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 12 }}
              labelFormatter={(l) => String(l)}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line
              type="monotone"
              dataKey="sent"
              name="Sent"
              stroke="#1a1a2e"
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="replied"
              name="Replied"
              stroke="#e94560"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* ── bottom row: pie + mailbox table ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Platform distribution */}
        <div className="bg-white rounded-xl border border-gray-100 p-5">
          <p className="text-sm font-medium text-gray-700 mb-4">Platform Distribution</p>
          {platforms.length === 0 ? (
            <p className="text-xs text-gray-400 text-center py-12">No data yet</p>
          ) : (
            <div className="flex items-center gap-6">
              <ResponsiveContainer width="60%" height={200}>
                <PieChart>
                  <Pie
                    data={platforms}
                    dataKey="count"
                    nameKey="platform"
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    labelLine={false}
                  >
                    {platforms.map((_, i) => (
                      <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 12 }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <ul className="flex-1 space-y-2">
                {platforms.map((p, i) => (
                  <li key={p.platform} className="flex items-center gap-2 text-xs">
                    <span
                      className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                      style={{ backgroundColor: PIE_COLORS[i % PIE_COLORS.length] }}
                    />
                    <span className="capitalize text-gray-700 flex-1">{p.platform}</span>
                    <span className="text-gray-500 tabular-nums font-medium">{p.count.toLocaleString()}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Mailbox health */}
        <div className="bg-white rounded-xl border border-gray-100 p-5">
          <p className="text-sm font-medium text-gray-700 mb-4">Mailbox Health</p>
          {mailboxes.length === 0 ? (
            <p className="text-xs text-gray-400 text-center py-12">No mailboxes configured</p>
          ) : (
            <div className="overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-gray-400 uppercase tracking-wider border-b border-gray-100">
                    <th className="text-left pb-2 font-medium">Email</th>
                    <th className="text-left pb-2 font-medium w-32">Usage</th>
                    <th className="text-left pb-2 font-medium">Bounce</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {mailboxes.map((m) => {
                    const usagePct = m.daily_limit > 0 ? (m.today_sent / m.daily_limit) * 100 : 0
                    const isBounceAlert = m.bounce_rate > 0.1
                    return (
                      <tr key={m.id} className="text-gray-700">
                        <td className="py-2 pr-3">
                          <span className="truncate block max-w-[180px]" title={m.email}>{m.email}</span>
                        </td>
                        <td className="py-2 pr-3">
                          <div className="flex items-center gap-2">
                            <div className="flex-1 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                              <div
                                className="h-full rounded-full bg-gray-900 transition-all"
                                style={{ width: `${Math.min(usagePct, 100)}%` }}
                              />
                            </div>
                            <span className="tabular-nums text-gray-500 w-16 shrink-0">
                              {m.today_sent}/{m.daily_limit}
                            </span>
                          </div>
                        </td>
                        <td className="py-2">
                          <span className={`font-medium tabular-nums ${isBounceAlert ? 'text-red-500' : 'text-gray-700'}`}>
                            {isBounceAlert && '⚠ '}
                            {pct(m.bounce_rate)}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
