import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
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

const PERIOD_VALUES = ['day', 'week', 'month'] as const

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
  const { t } = useTranslation()
  const [period, setPeriod] = useState<'day' | 'week' | 'month'>('month')
  const [summary, setSummary] = useState<UsageSummary | null>(null)
  const [trend, setTrend] = useState<TrendPoint[]>([])
  const [breakdown, setBreakdown] = useState<BreakdownItem[]>([])
  const [userBreakdown, setUserBreakdown] = useState<BreakdownItem[]>([])
  const [alerts, setAlerts] = useState<UsageAlerts | null>(null)
  const [loading, setLoading] = useState(true)

  const [budgetModal, setBudgetModal] = useState(false)
  const [budgetUsd, setBudgetUsd] = useState('')
  const [budgetThreshold, setBudgetThreshold] = useState('80')
  const [budgetSaving, setBudgetSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, t, b, ub, a] = await Promise.all([
        getUsageSummary(period),
        getUsageTrend('llm_token', '30d'),
        getUsageBreakdown('llm_token', 'model'),
        getUsageBreakdown('email_sent', 'user'),
        getUsageAlerts(),
      ])
      setSummary(s)
      setTrend(t.data)
      setBreakdown(b.data)
      setUserBreakdown(ub.data)
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
        <h1 className="text-xl font-semibold text-gray-900">{t('admin.usage.title')}</h1>
        <div className="flex items-center gap-2">
          {PERIOD_VALUES.map((v) => (
            <button
              key={v}
              onClick={() => setPeriod(v)}
              className={`px-3 py-1.5 text-sm rounded-md transition-colors ${
                period === v
                  ? 'bg-gray-900 text-white'
                  : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
              }`}
            >
              {t(`admin.usage.periods.${v}`)}
            </button>
          ))}
        </div>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <MetricCard
          label={t('admin.usage.metrics.totalCost')}
          value={loading ? '—' : `$${summary?.total_cost_usd.toFixed(4) ?? '0'}`}
          sub={t('admin.usage.metrics.usd')}
        />
        <MetricCard
          label={t('admin.usage.metrics.llmTokens')}
          value={loading ? '—' : (summary?.llm_tokens ?? 0).toLocaleString()}
          sub={t('admin.usage.metrics.tokensConsumed')}
        />
        <MetricCard
          label={t('admin.usage.metrics.emailsSent')}
          value={loading ? '—' : (summary?.emails_sent ?? 0).toLocaleString()}
          sub={t('admin.usage.metrics.outreachEmails')}
        />
        <MetricCard
          label={t('admin.usage.metrics.storage')}
          value={loading ? '—' : `${summary?.storage_mb.toFixed(1) ?? '0'} MB`}
          sub={t('admin.usage.metrics.dbSize')}
        />
      </div>

      {/* Budget Alert Panel */}
      {alerts && (
        <div className="bg-white border border-gray-100 rounded-lg p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-700">{t('admin.usage.budget.title')}</h2>
            <button
              onClick={() => {
                setBudgetUsd(alerts.budget?.budget_usd.toString() ?? '')
                setBudgetThreshold(alerts.budget?.alert_threshold_pct.toString() ?? '80')
                setBudgetModal(true)
              }}
              className="text-xs px-3 py-1.5 bg-gray-900 text-white rounded-md hover:bg-gray-700 transition-colors"
            >
              {t('admin.usage.budget.setBudget')}
            </button>
          </div>
          <div className="flex gap-6 text-sm text-gray-600 mb-3">
            <span>
              {t('admin.usage.budget.monthCost')} <strong>${alerts.month_cost_usd.toFixed(4)}</strong>
            </span>
            <span>
              {t('admin.usage.budget.today')} <strong>${alerts.today_cost_usd.toFixed(4)}</strong>
            </span>
            {alerts.budget && (
              <span>
                {t('admin.usage.budget.budgetLabel')} <strong>${alerts.budget.budget_usd.toFixed(2)}</strong> ({t('admin.usage.budget.alertAt', { pct: alerts.budget.alert_threshold_pct })})
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
            <p className="text-xs text-gray-400">{t('admin.usage.budget.noActiveAlerts')}</p>
          )}
        </div>
      )}

      {/* Charts Row */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* 30-day cost trend */}
        <div className="bg-white border border-gray-100 rounded-lg p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">{t('admin.usage.charts.llmCostTrend')}</h2>
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
                formatter={(v) => [`$${Number(v).toFixed(4)}`, t('admin.usage.charts.cost')]}
                labelFormatter={(l) => t('admin.usage.charts.date', { date: l })}
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
            {t('admin.usage.charts.modelCostDist')}
          </h2>
          {breakdown.length === 0 ? (
            <div className="flex items-center justify-center h-[220px] text-gray-400 text-sm">
              {t('admin.usage.charts.noDataYet')}
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
                <Tooltip formatter={(v) => [`$${Number(v).toFixed(4)}`, 'Cost']} />
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
          {t('admin.usage.topUsers.title')}
        </h2>
        {userBreakdown.length === 0 ? (
          <p className="text-sm text-gray-400">{t('admin.usage.topUsers.noData')}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left py-2 text-xs text-gray-400 font-medium">{t('admin.usage.topUsers.rank')}</th>
                <th className="text-left py-2 text-xs text-gray-400 font-medium">{t('admin.usage.topUsers.user')}</th>
                <th className="text-right py-2 text-xs text-gray-400 font-medium">{t('admin.usage.topUsers.emailsSent')}</th>
              </tr>
            </thead>
            <tbody>
              {userBreakdown.slice(0, 10).map((row, i) => (
                <tr key={i} className="border-b border-gray-50 hover:bg-gray-50">
                  <td className="py-2.5 text-gray-400 w-8">{i + 1}</td>
                  <td className="py-2.5 text-gray-700">{row.key}</td>
                  <td className="py-2.5 text-right text-gray-600">
                    {row.value.toLocaleString()}
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
            <h3 className="font-semibold text-gray-900">{t('admin.usage.budget.modalTitle')}</h3>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-gray-500 block mb-1">
                  {t('admin.usage.budget.budgetUsdLabel', { month: new Date().toISOString().slice(0, 7) })}
                </label>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={budgetUsd}
                  onChange={(e) => setBudgetUsd(e.target.value)}
                  className="w-full border border-gray-200 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder={t('admin.usage.budget.budgetUsdPlaceholder')}
                />
              </div>
              <div>
                <label className="text-xs text-gray-500 block mb-1">
                  {t('admin.usage.budget.alertThresholdLabel')}
                </label>
                <input
                  type="number"
                  min="1"
                  max="100"
                  value={budgetThreshold}
                  onChange={(e) => setBudgetThreshold(e.target.value)}
                  className="w-full border border-gray-200 rounded-md px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder={t('admin.usage.budget.alertThresholdPlaceholder')}
                />
              </div>
            </div>
            <div className="flex gap-3 pt-1">
              <button
                onClick={() => setBudgetModal(false)}
                className="flex-1 px-4 py-2 text-sm border border-gray-200 rounded-md text-gray-600 hover:bg-gray-50"
              >
                {t('admin.common.cancel')}
              </button>
              <button
                onClick={handleSaveBudget}
                disabled={budgetSaving || !budgetUsd}
                className="flex-1 px-4 py-2 text-sm bg-gray-900 text-white rounded-md hover:bg-gray-700 disabled:opacity-50"
              >
                {budgetSaving ? t('admin.usage.budget.saving') : t('admin.common.save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
