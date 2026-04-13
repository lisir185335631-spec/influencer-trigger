import { useState, useEffect, useCallback } from 'react'
import {
  Plus,
  X,
  Loader2,
  CheckCircle,
  XCircle,
  Clock,
  Zap,
  Globe,
} from 'lucide-react'
import { useWebSocket, WsMessage } from '../hooks/useWebSocket'
import {
  scrapeApi,
  ScrapeTask,
  ScrapeTaskCreate,
  parsePlatforms,
} from '../api/scrape'

// ── Constants ─────────────────────────────────────────────────────────────────

const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`

const PLATFORMS = [
  { id: 'instagram', label: 'Instagram' },
  { id: 'youtube', label: 'YouTube' },
  { id: 'tiktok', label: 'TikTok', stub: true },
  { id: 'twitter', label: 'Twitter / X', stub: true },
  { id: 'facebook', label: 'Facebook', stub: true },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

type ProgressEvent = {
  task_id: number
  status: string
  progress: number
  found_count: number
  valid_count: number
  latest_email?: string
  error?: string
}

function isRunning(t: ScrapeTask) {
  return t.status === 'running' || t.status === 'pending'
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string; icon: React.ReactNode }> = {
    pending:   { label: 'Pending',   cls: 'bg-amber-50 text-amber-700 ring-amber-200',   icon: <Clock size={11} /> },
    running:   { label: 'Running',   cls: 'bg-blue-50 text-blue-700 ring-blue-200',      icon: <Loader2 size={11} className="animate-spin" /> },
    completed: { label: 'Done',      cls: 'bg-emerald-50 text-emerald-700 ring-emerald-200', icon: <CheckCircle size={11} /> },
    failed:    { label: 'Failed',    cls: 'bg-red-50 text-red-600 ring-red-200',          icon: <XCircle size={11} /> },
    cancelled: { label: 'Cancelled', cls: 'bg-gray-50 text-gray-500 ring-gray-200',       icon: <XCircle size={11} /> },
  }
  const cfg = map[status] ?? map['pending']
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ring-1 ${cfg.cls}`}>
      {cfg.icon}
      {cfg.label}
    </span>
  )
}

function ProgressBar({ value }: { value: number }) {
  return (
    <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
      <div
        className="h-full bg-blue-500 rounded-full transition-all duration-500"
        style={{ width: `${value}%` }}
      />
    </div>
  )
}

function PlatformTags({ raw }: { raw: string }) {
  const platforms = parsePlatforms(raw)
  return (
    <div className="flex flex-wrap gap-1">
      {platforms.map((p) => (
        <span key={p} className="px-1.5 py-0.5 text-xs bg-gray-100 text-gray-600 rounded capitalize">
          {p}
        </span>
      ))}
    </div>
  )
}

// ── Create Task Modal ─────────────────────────────────────────────────────────

type CreateModalProps = {
  onClose: () => void
  onCreated: (task: ScrapeTask) => void
}

function CreateModal({ onClose, onCreated }: CreateModalProps) {
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>(['instagram', 'youtube'])
  const [industry, setIndustry] = useState('')
  const [targetCount, setTargetCount] = useState(50)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  function togglePlatform(id: string) {
    setSelectedPlatforms((prev) =>
      prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]
    )
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (selectedPlatforms.length === 0) {
      setError('Select at least one platform')
      return
    }
    if (!industry.trim()) {
      setError('Industry keyword is required')
      return
    }
    setCreating(true)
    setError('')
    try {
      const payload: ScrapeTaskCreate = {
        platforms: selectedPlatforms,
        industry: industry.trim(),
        target_count: targetCount,
      }
      const task = await scrapeApi.createTask(payload)
      onCreated(task)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to create task')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">New Scrape Task</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-5">
          {/* Platform selection */}
          <div>
            <label className="block text-xs text-gray-500 mb-2">Platforms</label>
            <div className="grid grid-cols-2 gap-2">
              {PLATFORMS.map((p) => {
                const checked = selectedPlatforms.includes(p.id)
                return (
                  <label
                    key={p.id}
                    className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg border cursor-pointer transition-all ${
                      checked
                        ? 'border-gray-900 bg-gray-50'
                        : 'border-gray-200 hover:border-gray-300'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => togglePlatform(p.id)}
                      className="w-3.5 h-3.5 accent-gray-900"
                    />
                    <span className="text-xs text-gray-700">{p.label}</span>
                    {p.stub && (
                      <span className="ml-auto text-[10px] text-gray-400 bg-gray-100 px-1.5 py-0.5 rounded">
                        CSV only
                      </span>
                    )}
                  </label>
                )
              })}
            </div>
            <p className="text-[11px] text-gray-400 mt-1.5">
              Instagram &amp; YouTube support automatic Playwright scraping.
              TikTok / Twitter / Facebook will prompt for CSV import.
            </p>
          </div>

          {/* Industry */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">Industry keyword *</label>
            <input
              type="text"
              required
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              placeholder="e.g. fitness, beauty, gaming"
              className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
            />
          </div>

          {/* Target count */}
          <div>
            <label className="block text-xs text-gray-500 mb-1">
              Target email count — <span className="font-medium text-gray-700">{targetCount}</span>
            </label>
            <input
              type="range"
              min={5}
              max={500}
              step={5}
              value={targetCount}
              onChange={(e) => setTargetCount(Number(e.target.value))}
              className="w-full accent-gray-900"
            />
            <div className="flex justify-between text-[11px] text-gray-400 mt-0.5">
              <span>5</span>
              <span>500</span>
            </div>
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}

          {/* Footer */}
          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={creating}
              className="flex items-center gap-1.5 px-4 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors"
            >
              {creating && <Loader2 size={13} className="animate-spin" />}
              Start Scraping
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ScrapePage() {
  const [tasks, setTasks] = useState<ScrapeTask[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  // Map task_id → live progress from WS
  const [liveProgress, setLiveProgress] = useState<Record<number, ProgressEvent>>({})

  const fetchTasks = useCallback(async () => {
    try {
      const data = await scrapeApi.listTasks()
      setTasks(data)
    } catch {
      /* silent */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchTasks() }, [fetchTasks])

  // Listen to WebSocket scrape:progress events
  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.event !== 'scrape:progress') return
    const evt = msg.data as ProgressEvent

    setLiveProgress((prev) => ({ ...prev, [evt.task_id]: evt }))

    // When completed / failed → refresh task list to get latest DB state
    if (evt.status === 'completed' || evt.status === 'failed') {
      setTimeout(() => fetchTasks(), 500)
    }
  }, [fetchTasks])

  useWebSocket(WS_URL, handleWsMessage)

  function handleCreated(task: ScrapeTask) {
    setTasks((prev) => [task, ...prev])
    setShowCreate(false)
  }

  // Merge live WS data into task display
  function resolveTask(t: ScrapeTask): ScrapeTask & { _live?: ProgressEvent } {
    const live = liveProgress[t.id]
    if (!live) return t
    return {
      ...t,
      status: live.status as ScrapeTask['status'],
      progress: live.progress,
      found_count: live.found_count,
      valid_count: live.valid_count,
      _live: live,
    }
  }

  const anyRunning = tasks.some(isRunning)

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Scrape Tasks</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            Extract influencer emails from social platforms via Playwright
          </p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1.5 px-3 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition-colors"
        >
          <Plus size={14} />
          New Task
        </button>
      </div>

      {/* Running hint */}
      {anyRunning && (
        <div className="flex items-center gap-2 px-4 py-2.5 bg-blue-50 border border-blue-100 rounded-lg text-xs text-blue-700">
          <Zap size={12} className="text-blue-500 shrink-0" />
          A scrape task is running — progress updates in real time via WebSocket.
        </div>
      )}

      {/* Task list */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <Loader2 size={18} className="animate-spin mr-2" />
            <span className="text-sm">Loading…</span>
          </div>
        ) : tasks.length === 0 ? (
          <div className="py-16 text-center space-y-3">
            <Globe size={32} className="mx-auto text-gray-200" />
            <div>
              <p className="text-sm text-gray-500">No scrape tasks yet</p>
              <p className="text-xs text-gray-400 mt-0.5">
                Create a task to start extracting influencer emails
              </p>
            </div>
            <button
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition-colors"
            >
              <Plus size={12} />
              New Task
            </button>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Platforms</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Industry</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 w-40">Progress</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500">Valid Emails</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500">Target</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {tasks.map((rawTask) => {
                const t = resolveTask(rawTask)
                const live = (t as ScrapeTask & { _live?: ProgressEvent })._live
                return (
                  <tr key={t.id} className="hover:bg-gray-50/60 transition-colors">
                    <td className="px-4 py-3">
                      <PlatformTags raw={t.platforms} />
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-700 capitalize">
                      {t.industry}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={t.status} />
                      {t.error_message && (
                        <p className="text-[10px] text-red-400 mt-0.5 max-w-[160px] truncate" title={t.error_message}>
                          {t.error_message}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="space-y-1">
                        <ProgressBar value={t.progress} />
                        <div className="flex justify-between text-[10px] text-gray-400">
                          <span>{t.progress}%</span>
                          {live?.latest_email && (
                            <span className="truncate max-w-[100px]" title={live.latest_email}>
                              {live.latest_email}
                            </span>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className="text-xs font-medium text-gray-900">{t.valid_count}</span>
                      {t.found_count > t.valid_count && (
                        <span className="text-[10px] text-gray-400 ml-1">
                          / {t.found_count} found
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-gray-500">
                      {t.target_count}
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-gray-400">
                      {new Date(t.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Create modal */}
      {showCreate && (
        <CreateModal
          onClose={() => setShowCreate(false)}
          onCreated={handleCreated}
        />
      )}
    </div>
  )
}
