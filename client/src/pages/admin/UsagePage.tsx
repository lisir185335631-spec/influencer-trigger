import { useCallback, useEffect, useState } from 'react'
import {
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  type BreakdownItem,
  type TrendPoint,
  type UsageAlerts,
  type UsageSummary,
  getUsageAlerts,
  getUsageBreakdown,
  getUsageSummary,
  getUsageTrend,
  setBudget,
} from '../../api/admin/usage'

const PIE_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4']

const PERIODS = [
  { label: 'Today', value: 'day' },
  { label: 'This Week', value: 'week' },
  { label: 'This Month', value: 'month' },
] as const

function MetricCard({
  label,
  value,
  sub,
}: {
  label: string
  value: string
  sub?: string
}) {
  return (
    <div className="bg-white border border-gray-100 rounded-lg p-5 hover:shadow-sm transition-shadow">
      <p className="text-xs text-gray-400 uppercase tracking-wide mb-1">{label}</p>
      <p className="text-2xl font-semibold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

export default function UsagePage() {
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('month')
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [trend, setTrend] = useState<TrendPoint[]>([])
  const [breakdown, setBreakdown] = useState<BreakdownItem[]>([])
  const [alerts, setAlerts] = useState<UsageAlerts | null>(null)
  const [loading, setLoading] = useState(true)

  const [budgetModal, setBudgetModal] = useState(false)
  const [budgetUsd, setBudgetUsd] = useState('')
  const [budgetThreshold, setBudgetThreshold] = useState('80')
  const [budgetSaving, setBudgetSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, t, b, a] = await Promise.all([
        getUsageSummary(period),
        getUsageTrend('llm_token', '30d'),
        getUsageBreakdown('llm_token', 'model'),
        getUsageAlerts(),
      ])
      setSummary(s)
      setTrend(t.data)
      setBreakdown(b.data)
      setAlerts(a)
    } finally {
      setLoading(false)
    }
  }, [period])

  useEffect(() => {
    load()
  }, [load])

  const handleSaveBudget = async () => {
    if (!budgetUsd) return
    setBudgetSaving(true)
    try {
      const month = new Date().toISOString().slice(0, 7)
      await setBudget({
        month,
        budget_usd: parseFloat(budgetUsd),
        alert_threshold_pct: parseFloat(budgetThreshold) || 80,
      })
      setBudgetModal(false)
      await load()
    } finally {
      setBudgetSaving(false)
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Cost & Usage</h1>
        <div className="flex items-center gap-2">
          {PERIODS.map((p) => (
            <button
              key={p.value}
              onClick={() => setPeriod(p.value)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                period === p.value
                  ? 'bg-gray-900 text-white'
                  : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <MetricCard
          label="Total Cost (period)"
          value={loading ? '—' : `$${summary?.total_cost_usd.toFixed(4) ?? '0'}`}
          sub="USD"
        />
        <MetricCard
          label="LLM Tokens"
          value={loading ? '—' : (summary?.llm_tokens ?? 0).toLocaleString()}
          sub="tokens consumed"
        />
        <MetricCard
          label="Emails Sent"
          value={loading ? '—' : (summary?.emails_sent ?? 0).toLocaleString()}
          sub="outreach emails"
        />
        <MetricCard
          label="Storage"
          value={loading ? '—' : `${summary?.storage_mb.toFixed(1) ?? '0'} MB`}
          sub="database size"
        />
      </div>

      {/* Budget Alert Panel */}
      {alerts && (
        <div className="bg-white border border-gray-100 rounded-lg p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-700">Budget & Alerts</h2>
            <button
              onClick={() => {
                setBudgetUsd(alerts.budget?.budget_usd.toString() ?? '')
                setBudgetThreshold(alerts.budget?.alert_threshold_pct.toString() ?? '80')
                setBudgetModal(true)
              }}
              className="text-xs px-3 py-1.5 bg-gray-900 text-white rounded-md hover:bg-gray-700 transition-colors"
            >
              Set Budget
            </button>
          </div>
          <div className="flex gap-6 text-sm text-gray-600 mb-3">
            <span>
              Month cost: <strong>${alerts.month_cost_usd.toFixed(4)}</strong>
            </span>
            <span>
              Today: <strong>${alerts.today_cost_usd.toFixed(4)}</strong>
            </span>
            {alerts.budget && (
              <span>
                Budget: <strong>${alerts.budget.budget_usd.toFixed(2)}</strong> (alert at{' '}
                {alerts.budget.alert_threshold_pct}%)
              </span>
            )}
          </div>
          {alerts.alerts.length > 0 ? (
            <div className="space-y-2">
              {alerts.alerts.map((a, i) => (
                <div
                  key={i}
                  className={`text-xs px-3 py-2 rounded-md ${
                    a.severity === 'critical'
                      ? 'bg-red-50 text-red-700 border border-red-100'
                      : 'bg-yellow-50 text-yellow-700 border border-yellow-100'
                  }`}
                >
                  {a.message}
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-gray-400">No active alerts</p>
          )}
        </div>
      )}

      {/* Charts Row */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* 30-day cost trend */}
        <div className="bg-white border border-gray-100 rounded-lg p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">30-Day LLM Cost Trend</h2>
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 4 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11 }}
                tickFormatter={(v) => v.slice(5)}
              />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => `$${v}`} width={48} />
              <Tooltip
                formatter={(v: number) => [`$${v.toFixed(4)}`, 'Cost']}
                labelFormatter={(l) => `Date: ${l}`}
              />
              <Line
                type="monotone"
                dataKey="cost_usd"
                stroke="#3b82f6"
                dot={false}
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Model breakdown donut */}
        <div className="bg-white border border-gray-100 rounded-lg p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">
            Model Cost Distribution (This Month)
          </h2>
          {breakdown.length === 0 ? (
            <div className="flex items-center justify-center h-[220px] text-gray-400 text-sm">
              No data yet
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={breakdown}
                  dataKey="cost_usd"
                  nameKey="key"
                  cx="50%"
                  cy="50%"
                  innerRadius={55}
                  outerRadius={90}
                  paddingAngle={2}
                >
                  {breakdown.map((_, idx) => (
                    <Cell key={idx} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(v: number) => [`$${v.toFixed(4)}`, 'Cost']} />
                <Legend
                  iconType="circle"
                  iconSize={8}
                  formatter={(value) => (
                    <span style={{ fontSize: 11, color: '#6b7280' }}>{value}</span>
                  )}
                />
              </PieChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* Top users table */}
      <div className="bg-white border border-gray-100 rounded-lg p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-4">
          Top Cost by Model (This Month)
        </h2>
        {breakdown.length === 0 ? (
          <p className="text-sm text-gray-400">No usage data recorded yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left py-2 text-xs text-gray-400 font-medium">Model</th>
                <th className="text-right py-2 text-xs text-gray-400 font-medium">Tokens</th>
                <th className="text-right py-2 text-xs text-gray-400 font-medium">Cost (USD)</th>
              </tr>
            </thead>
            <tbody>
              {breakdown.map((row, i) => (
                <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="py-2.5 text-gray-700">{row.key}</td>
                  <td className="py-2.5 text-right text-gray-600">
                    {row.value.toLocaleString()}
                  </td>
                  <td className="py-2.5 text-right font-mono text-gray-700">
                    ${row.cost_usd.toFixed(4)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Budget Modal */}
      {budgetModal && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl shadow-lg w-full max-w-sm p-6 space-y-4">
            <h3 className="font-semibold text-gray-900">Set Monthly Budget</h3>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-500 block mb-1">
                  Budget (USD) for {new Date().toISOString().slice(0, 7)}
                </label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={budgetUsd}
                  onChange={(e) => setBudgetUsd(e.target.value)}
                  className="w-full border border-gray-200 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="e.g. 50.00"
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">
                  Alert threshold (%)
                </label>
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={budgetThreshold}
                  onChange={(e) => setBudgetThreshold(e.target.value)}
                  className="w-full border border-gray-200 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="80"
                />
              </div>
            </div>
            <div className="flex gap-3 pt-1">
              <button
                onClick={() => setBudgetModal(false)}
                className="flex-1 px-4 py-2 text-sm border border-gray-200 rounded-md text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveBudget}
                disabled={budgetSaving || !budgetUsd}
                className="flex-1 px-4 py-2 text-sm bg-gray-900 text-white rounded-md hover:bg-gray-700 disabled:opacity-50"
              >
                {budgetSaving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
