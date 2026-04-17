import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, RefreshCw, RotateCcw } from 'lucide-react'
import {
  type AgentRunDetail,
  type AgentRunItem,
  type AgentStatus,
  getAgentRun,
  getAgentsStatus,
  listAgentRuns,
  retryAgentRun,
} from '../../api/admin/agents_monitor'

const ALL_AGENTS = ['scraper', 'sender', 'monitor', 'classifier', 'responder', 'holiday']

const STATE_COLORS: Record<string, string> = {
  running: 'text-blue-700 bg-blue-50',
  success: 'text-green-700 bg-green-50',
  failed: 'text-red-700 bg-red-50',
  pending: 'text-yellow-700 bg-yellow-50',
  cancelled: 'text-gray-500 bg-gray-100',
}

const AGENT_ICONS: Record<string, string> = {
  scraper: '🕷️',
  sender: '✉️',
  monitor: '📡',
  classifier: '🧠',
  responder: '💬',
  holiday: '🎉',
}

function formatTs(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

function formatDuration(ms: number | null): string {
  if (ms === null) return '—'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${(ms / 60000).toFixed(1)}m`
}

function StatusDot({ state }: { state: string }) {
  const color =
    state === 'running' ? 'bg-blue-500 animate-pulse' :
    state === 'success' ? 'bg-green-500' :
    state === 'failed' ? 'bg-red-500' : 'bg-gray-300'
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${color}`} />
}

// ── Agent Status Cards ────────────────────────────────────────────────────────

function AgentCard({ name, status }: { name: string; status: AgentStatus | undefined }) {
  const rate = status?.success_rate
  const rateStr = rate !== null && rate !== undefined ? `${(rate * 100).toFixed(0)}%` : '—'
  const running = status?.running_count ?? 0

  return (
    <div className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm hover:shadow-md transition-shadow">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-lg">{AGENT_ICONS[name] ?? '⚙️'}</span>
        <span className="text-sm font-semibold text-gray-800 capitalize">{name}</span>
        <StatusDot state={running > 0 ? 'running' : (status?.recent_total ? 'success' : 'pending')} />
      </div>
      <div className="grid grid-cols-2 gap-y-1.5 text-xs text-gray-500">
        <span>Success rate</span>
        <span className="text-right font-medium text-gray-800">{rateStr}</span>
        <span>Avg duration</span>
        <span className="text-right font-medium text-gray-800">{formatDuration(status?.avg_duration_ms ?? null)}</span>
        <span>Running</span>
        <span className={`text-right font-medium ${running > 0 ? 'text-blue-600' : 'text-gray-800'}`}>{running}</span>
        <span>Last run</span>
        <span className="text-right font-medium text-gray-800">{formatTs(status?.last_run_at ?? null)}</span>
      </div>
    </div>
  )
}

// ── Run Detail Drawer ─────────────────────────────────────────────────────────

function RunDetailRow({
  run,
  onRetry,
}: {
  run: AgentRunItem
  onRetry: (id: number) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [detail, setDetail] = useState<AgentRunDetail | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  const toggle = async () => {
    if (!expanded && detail === null) {
      setLoadingDetail(true)
      try {
        const d = await getAgentRun(run.id)
        setDetail(d)
      } finally {
        setLoadingDetail(false)
      }
    }
    setExpanded(v => !v)
  }

  return (
    <>
      <tr className="hover:bg-gray-50 cursor-pointer" onClick={toggle}>
        <td className="px-4 py-3 text-xs text-gray-400">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </td>
        <td className="px-4 py-3 text-xs font-mono text-gray-500">#{run.id}</td>
        <td className="px-4 py-3 text-sm font-medium text-gray-800 capitalize">{run.agent_name}</td>
        <td className="px-4 py-3 text-xs text-gray-500">{run.task_id ?? '—'}</td>
        <td className="px-4 py-3">
          <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATE_COLORS[run.state] ?? 'text-gray-600 bg-gray-100'}`}>
            {run.state}
          </span>
        </td>
        <td className="px-4 py-3 text-xs text-gray-500">{formatTs(run.started_at)}</td>
        <td className="px-4 py-3 text-xs text-gray-500">{formatDuration(run.duration_ms)}</td>
        <td className="px-4 py-3 text-xs text-red-500 max-w-[200px] truncate">{run.error_message ?? '—'}</td>
        <td className="px-4 py-3">
          {run.state === 'failed' && (
            <button
              onClick={e => { e.stopPropagation(); onRetry(run.id) }}
              className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-lg bg-amber-50 text-amber-700 hover:bg-amber-100 border border-amber-200 font-medium"
            >
              <RotateCcw size={11} /> Retry
            </button>
          )}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={9} className="px-4 pb-4 pt-0 bg-gray-50">
            {loadingDetail ? (
              <p className="text-xs text-gray-400 py-2">Loading…</p>
            ) : detail ? (
              <div className="grid grid-cols-1 gap-3 mt-2">
                {detail.input_snapshot && (
                  <div>
                    <p className="text-xs font-semibold text-gray-600 mb-1">Input</p>
                    <pre className="text-xs bg-white border border-gray-200 rounded-lg p-3 overflow-x-auto max-h-40 text-gray-700">
                      {tryPrettyJson(detail.input_snapshot)}
                    </pre>
                  </div>
                )}
                {detail.error_stack && (
                  <div>
                    <p className="text-xs font-semibold text-red-600 mb-1">Error Stack</p>
                    <pre className="text-xs bg-red-50 border border-red-100 rounded-lg p-3 overflow-x-auto max-h-48 text-red-700 whitespace-pre-wrap">
                      {detail.error_stack}
                    </pre>
                  </div>
                )}
              </div>
            ) : null}
          </td>
        </tr>
      )}
    </>
  )
}

function tryPrettyJson(s: string): string {
  try { return JSON.stringify(JSON.parse(s), null, 2) } catch { return s }
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function AgentsMonitorPage() {
  const [statusMap, setStatusMap] = useState<Record<string, AgentStatus>>({})
  const [runs, setRuns] = useState<AgentRunItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [filterAgent, setFilterAgent] = useState('')
  const [filterState, setFilterState] = useState('')
  const [retrying, setRetrying] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)

  const loadStatus = useCallback(async () => {
    try {
      const r = await getAgentsStatus()
      setStatusMap(r.agents)
    } catch { /* ignore */ }
  }, [])

  const loadRuns = useCallback(async (p: number, agent: string, state: string) => {
    setLoading(true)
    try {
      const r = await listAgentRuns({ page: p, page_size: 20, agent: agent || undefined, state: state || undefined })
      setRuns(r.items)
      setTotal(r.total)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadStatus()
    const id = setInterval(loadStatus, 15000)
    return () => clearInterval(id)
  }, [loadStatus])

  useEffect(() => {
    loadRuns(page, filterAgent, filterState)
  }, [page, filterAgent, filterState, loadRuns])

  const handleRetry = async (runId: number) => {
    setRetrying(runId)
    try {
      await retryAgentRun(runId)
      await loadRuns(page, filterAgent, filterState)
      await loadStatus()
    } catch {
      alert('Retry failed')
    } finally {
      setRetrying(null)
    }
  }

  const totalPages = Math.ceil(total / 20)

  return (
    <div className="p-6 max-w-[1200px] mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-gray-900">Agent Monitor</h1>
        <button
          onClick={() => { loadStatus(); loadRuns(page, filterAgent, filterState) }}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
        >
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      {/* Agent Status Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6 gap-4">
        {ALL_AGENTS.map(name => (
          <AgentCard key={name} name={name} status={statusMap[name]} />
        ))}
      </div>

      {/* Filters */}
      <div className="bg-white border border-gray-100 rounded-2xl p-4 shadow-sm">
        <div className="flex flex-wrap gap-3 mb-4">
          <select
            value={filterAgent}
            onChange={e => { setFilterAgent(e.target.value); setPage(1) }}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-slate-200"
          >
            <option value="">All Agents</option>
            {ALL_AGENTS.map(a => <option key={a} value={a} className="capitalize">{a}</option>)}
          </select>
          <select
            value={filterState}
            onChange={e => { setFilterState(e.target.value); setPage(1) }}
            className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-slate-200"
          >
            <option value="">All States</option>
            {['running', 'success', 'failed', 'pending', 'cancelled'].map(s => (
              <option key={s} value={s} className="capitalize">{s}</option>
            ))}
          </select>
          <span className="ml-auto text-xs text-gray-400 self-center">{total} runs total</span>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-gray-100">
                {['', 'ID', 'Agent', 'Task', 'State', 'Started', 'Duration', 'Error', ''].map((h, i) => (
                  <th key={i} className="px-4 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wider whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading ? (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-sm text-gray-400">Loading…</td>
                </tr>
              ) : runs.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-4 py-8 text-center text-sm text-gray-400">No runs found</td>
                </tr>
              ) : (
                runs.map(run => (
                  <RunDetailRow
                    key={run.id}
                    run={run}
                    onRetry={retrying === null ? handleRetry : () => {}}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 mt-4">
            <button
              disabled={page <= 1}
              onClick={() => setPage(p => p - 1)}
              className="px-3 py-1 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40"
            >
              Prev
            </button>
            <span className="text-sm text-gray-600">{page} / {totalPages}</span>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage(p => p + 1)}
              className="px-3 py-1 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
