import { Fragment, useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Download, Filter, RefreshCw } from 'lucide-react'
import {
  Bar,
  BarChart,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  type AuditFilters,
  type AuditLogItem,
  downloadAuditCsv,
  getAuditStats,
  listAuditLogs,
} from '../../api/admin/audit'
import { listUsers, type AdminUser } from '../../api/admin/users'

const ACTION_OPTIONS = ['', 'READ', 'CREATE', 'UPDATE', 'DELETE']
const METHOD_OPTIONS = ['', 'GET', 'POST', 'PUT', 'PATCH', 'DELETE']
const RESOURCE_TYPES = [
  '',
  'auth',
  'users',
  'influencers',
  'emails',
  'mailboxes',
  'templates',
  'scrape',
  'campaigns',
  'tags',
  'overview',
  'audit',
  'agents',
  'settings',
  'followup',
  'holidays',
]

const ACTION_COLORS: Record<string, string> = {
  READ: '#6366f1',
  CREATE: '#10b981',
  UPDATE: '#f59e0b',
  DELETE: '#ef4444',
}

interface TrendChartDatum {
  date: string
  READ: number
  CREATE: number
  UPDATE: number
  DELETE: number
}

function statusColor(code: number | null): string {
  if (!code) return 'text-gray-400'
  if (code < 300) return 'text-green-600'
  if (code < 400) return 'text-yellow-600'
  if (code < 500) return 'text-orange-600'
  return 'text-red-600'
}

function methodColor(method: string | null): string {
  switch (method) {
    case 'GET': return 'text-blue-600'
    case 'POST': return 'text-green-600'
    case 'PUT':
    case 'PATCH': return 'text-yellow-600'
    case 'DELETE': return 'text-red-600'
    default: return 'text-gray-500'
  }
}

function formatTs(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function prettyJson(raw: string | null): string {
  if (!raw) return ''
  try {
    return JSON.stringify(JSON.parse(raw), null, 2)
  } catch {
    return raw
  }
}

function JsonSnippet({ label, raw }: { label: string; raw: string | null }) {
  if (!raw) return null
  return (
    <div className="mb-2">
      <div className="text-xs font-semibold text-gray-500 mb-1">{label}</div>
      <pre className="font-mono text-xs bg-gray-50 rounded p-2 overflow-x-auto whitespace-pre-wrap text-gray-800 border border-gray-100 max-h-48">
        {prettyJson(raw)}
      </pre>
    </div>
  )
}

const PAGE_SIZE = 50

export default function AuditLogPage() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [filters, setFilters] = useState<AuditFilters>({})
  const [draftFilters, setDraftFilters] = useState<AuditFilters>({})
  const [page, setPage] = useState(1)

  const [logs, setLogs] = useState<AuditLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  const [trendData, setTrendData] = useState<TrendChartDatum[]>([])
  const [statsLoading, setStatsLoading] = useState(false)

  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    listUsers({ page: 1, page_size: 100 })
      .then(({ data }) => setUsers(data.items))
      .catch(() => {})
  }, [])

  const loadStats = useCallback(async () => {
    setStatsLoading(true)
    try {
      const { trend } = await getAuditStats()
      setTrendData(
        trend.map((d) => ({
          date: d.date.slice(5),
          READ: d.actions['READ'] ?? 0,
          CREATE: d.actions['CREATE'] ?? 0,
          UPDATE: d.actions['UPDATE'] ?? 0,
          DELETE: d.actions['DELETE'] ?? 0,
        }))
      )
    } catch {
      /* silent */
    } finally {
      setStatsLoading(false)
    }
  }, [])

  const loadLogs = useCallback(async () => {
    setLoading(true)
    try {
      const result = await listAuditLogs(filters, page, PAGE_SIZE)
      setLogs(result.items)
      setTotal(result.total)
    } catch {
      setLogs([])
      setTotal(0)
    } finally {
      setLoading(false)
    }
  }, [filters, page])

  useEffect(() => {
    loadStats()
  }, [loadStats])

  useEffect(() => {
    loadLogs()
  }, [loadLogs])

  function applyFilters() {
    setFilters(draftFilters)
    setPage(1)
    setExpandedId(null)
  }

  function resetFilters() {
    setDraftFilters({})
    setFilters({})
    setPage(1)
    setExpandedId(null)
  }

  async function handleExport() {
    setExporting(true)
    try {
      await downloadAuditCsv(filters)
    } finally {
      setExporting(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const inputCls =
    'w-full text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-indigo-300 bg-white'

  return (
    <div className="p-6 space-y-5 max-w-screen-2xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Audit Log</h1>
          <p className="text-xs text-gray-400 mt-0.5">{total.toLocaleString()} records found</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => { loadLogs(); loadStats() }}
            disabled={loading}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <button
            onClick={handleExport}
            disabled={exporting}
            className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors disabled:opacity-50"
          >
            <Download className="w-4 h-4" />
            {exporting ? 'Exporting…' : 'Export CSV'}
          </button>
        </div>
      </div>

      {/* Trend chart */}
      <div className="bg-white border border-gray-100 rounded-xl p-5">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Operation Trend (7 days)</h2>
        {statsLoading ? (
          <div className="h-28 flex items-center justify-center">
            <RefreshCw className="w-5 h-5 text-gray-300 animate-spin" />
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={112}>
            <BarChart data={trendData} barSize={10}>
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={28} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              <Bar dataKey="READ" stackId="a" fill={ACTION_COLORS['READ']} />
              <Bar dataKey="CREATE" stackId="a" fill={ACTION_COLORS['CREATE']} />
              <Bar dataKey="UPDATE" stackId="a" fill={ACTION_COLORS['UPDATE']} />
              <Bar dataKey="DELETE" stackId="a" fill={ACTION_COLORS['DELETE']} radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Filter panel */}
      <div className="bg-white border border-gray-100 rounded-xl p-4">
        <div className="flex items-center gap-2 mb-3">
          <Filter className="w-4 h-4 text-gray-400" />
          <span className="text-sm font-medium text-gray-700">Filters</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">User</label>
            <select
              value={draftFilters.user_id ?? ''}
              onChange={(e) =>
                setDraftFilters({
                  ...draftFilters,
                  user_id: e.target.value ? Number(e.target.value) : undefined,
                  username: undefined,
                })
              }
              className={inputCls}
            >
              <option value="">All users</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>{u.username}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Action</label>
            <select
              value={draftFilters.action ?? ''}
              onChange={(e) => setDraftFilters({ ...draftFilters, action: e.target.value || undefined })}
              className={inputCls}
            >
              {ACTION_OPTIONS.map((a) => (
                <option key={a} value={a}>{a || 'All actions'}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Resource</label>
            <select
              value={draftFilters.resource_type ?? ''}
              onChange={(e) => setDraftFilters({ ...draftFilters, resource_type: e.target.value || undefined })}
              className={inputCls}
            >
              {RESOURCE_TYPES.map((r) => (
                <option key={r} value={r}>{r || 'All resources'}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">Method</label>
            <select
              value={draftFilters.method ?? ''}
              onChange={(e) => setDraftFilters({ ...draftFilters, method: e.target.value || undefined })}
              className={inputCls}
            >
              {METHOD_OPTIONS.map((m) => (
                <option key={m} value={m}>{m || 'All methods'}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">From</label>
            <input
              type="date"
              value={draftFilters.created_at_start ?? ''}
              onChange={(e) =>
                setDraftFilters({ ...draftFilters, created_at_start: e.target.value || undefined })
              }
              className={inputCls}
            />
          </div>

          <div>
            <label className="block text-xs text-gray-500 mb-1">To</label>
            <input
              type="date"
              value={draftFilters.created_at_end ?? ''}
              onChange={(e) =>
                setDraftFilters({ ...draftFilters, created_at_end: e.target.value || undefined })
              }
              className={inputCls}
            />
          </div>
        </div>

        <div className="mt-3 flex items-center gap-3">
          <input
            type="text"
            placeholder="Search by username…"
            value={draftFilters.username ?? ''}
            onChange={(e) =>
              setDraftFilters({
                ...draftFilters,
                username: e.target.value || undefined,
                user_id: undefined,
              })
            }
            className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 w-60 focus:outline-none focus:ring-1 focus:ring-indigo-300"
          />
          <button
            onClick={applyFilters}
            className="px-4 py-1.5 text-sm font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
          >
            Apply
          </button>
          <button
            onClick={resetFilters}
            className="px-4 py-1.5 text-sm font-medium text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Reset
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-40">
            <RefreshCw className="w-5 h-5 text-gray-300 animate-spin" />
          </div>
        ) : logs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-sm text-gray-400">
            No audit logs found.
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-100 text-xs text-gray-500 uppercase tracking-wider">
                    <th className="px-3 py-3 w-6"></th>
                    <th className="px-4 py-3 text-left">Time</th>
                    <th className="px-4 py-3 text-left">User</th>
                    <th className="px-4 py-3 text-left">Role</th>
                    <th className="px-4 py-3 text-left">Method</th>
                    <th className="px-4 py-3 text-left">Path</th>
                    <th className="px-4 py-3 text-left">Resource</th>
                    <th className="px-4 py-3 text-left">Status</th>
                    <th className="px-4 py-3 text-left">IP</th>
                    <th className="px-4 py-3 text-left">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((log) => (
                    <Fragment key={log.id}>
                      <tr
                        onClick={() => setExpandedId(expandedId === log.id ? null : log.id)}
                        className="border-b border-gray-50 hover:bg-gray-50/60 cursor-pointer transition-colors"
                      >
                        <td className="px-3 py-3 text-gray-400">
                          {expandedId === log.id ? (
                            <ChevronDown className="w-3.5 h-3.5" />
                          ) : (
                            <ChevronRight className="w-3.5 h-3.5" />
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-500 whitespace-nowrap tabular-nums">
                          {formatTs(log.created_at)}
                        </td>
                        <td className="px-4 py-3 font-medium text-gray-800">
                          {log.username ?? '—'}
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-500">{log.role ?? '—'}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`text-xs font-mono font-semibold ${methodColor(log.request_method)}`}
                          >
                            {log.request_method ?? '—'}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-600 max-w-xs truncate font-mono">
                          {log.request_path ?? '—'}
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-500">
                          {log.resource_type ?? '—'}
                        </td>
                        <td
                          className={`px-4 py-3 text-xs font-mono font-semibold tabular-nums ${statusColor(log.status_code)}`}
                        >
                          {log.status_code ?? '—'}
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-400 font-mono">
                          {log.ip ?? '—'}
                        </td>
                        <td className="px-4 py-3 text-xs text-gray-400 tabular-nums">
                          {log.duration_ms != null ? `${log.duration_ms}ms` : '—'}
                        </td>
                      </tr>
                      {expandedId === log.id && (
                        <tr className="bg-slate-50">
                          <td colSpan={10} className="px-6 py-4">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                              <div>
                                <div className="text-xs text-gray-500 mb-2">
                                  <span className="font-semibold">User Agent:</span>{' '}
                                  <span className="font-mono break-all">{log.user_agent ?? '—'}</span>
                                </div>
                                <div className="text-xs text-gray-500 mb-3">
                                  <span className="font-semibold">Resource ID:</span>{' '}
                                  {log.resource_id ?? '—'}
                                </div>
                                <JsonSnippet label="Request Body" raw={log.request_body_snippet} />
                              </div>
                              <div>
                                <JsonSnippet label="Response Snippet" raw={log.response_snippet} />
                                {!log.response_snippet && (
                                  <p className="text-xs text-gray-400 italic">
                                    Response snippet not captured.
                                  </p>
                                )}
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
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
                  onClick={() => { setPage(1); setExpandedId(null) }}
                  disabled={page === 1}
                  className="px-2 py-1 text-xs text-gray-500 border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50 transition-colors"
                >
                  «
                </button>
                <button
                  onClick={() => { setPage((p) => Math.max(1, p - 1)); setExpandedId(null) }}
                  disabled={page === 1}
                  className="px-2 py-1 text-xs text-gray-500 border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50 transition-colors"
                >
                  ‹
                </button>
                {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                  const start = Math.max(1, Math.min(page - 2, totalPages - 4))
                  return start + i
                }).map((p) => (
                  <button
                    key={p}
                    onClick={() => { setPage(p); setExpandedId(null) }}
                    className={`px-2.5 py-1 text-xs rounded border transition-colors ${
                      p === page
                        ? 'bg-indigo-600 text-white border-indigo-600'
                        : 'text-gray-500 border-gray-200 hover:bg-gray-50'
                    }`}
                  >
                    {p}
                  </button>
                ))}
                <button
                  onClick={() => { setPage((p) => Math.min(totalPages, p + 1)); setExpandedId(null) }}
                  disabled={page === totalPages}
                  className="px-2 py-1 text-xs text-gray-500 border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50 transition-colors"
                >
                  ›
                </button>
                <button
                  onClick={() => { setPage(totalPages); setExpandedId(null) }}
                  disabled={page === totalPages}
                  className="px-2 py-1 text-xs text-gray-500 border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50 transition-colors"
                >
                  »
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
