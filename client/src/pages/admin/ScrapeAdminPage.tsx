import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, RefreshCw, Square, RotateCcw, X } from 'lucide-react'
import {
  type PlatformQuotaItem,
  type ScrapeTaskAdminItem,
  type ScrapeTasksAdminResponse,
  forceTerminateTask,
  getPlatformQuota,
  listAdminScrapeTasks,
  retryTask,
  updatePlatformQuota,
} from '../../api/admin/scrape_admin'

type Tab = 'tasks' | 'quota'

const STATUS_COLORS: Record<string, string> = {
  pending: 'text-yellow-700 bg-yellow-50',
  running: 'text-blue-700 bg-blue-50',
  completed: 'text-green-700 bg-green-50',
  failed: 'text-red-700 bg-red-50',
  cancelled: 'text-gray-500 bg-gray-100',
}

const PLATFORM_COLORS: Record<string, string> = {
  tiktok: 'bg-pink-500',
  instagram: 'bg-purple-500',
  youtube: 'bg-red-500',
  twitter: 'bg-sky-500',
  facebook: 'bg-blue-600',
}

function formatTs(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

// ─── Confirm Modal ─────────────────────────────────────────────────────────────

function ConfirmModal({
  taskId,
  onConfirm,
  onCancel,
}: {
  taskId: number
  onConfirm: () => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-xl p-7 w-[380px] max-w-[90vw]">
        <div className="flex items-center gap-3 mb-4">
          <AlertTriangle className="text-red-500 shrink-0" size={22} />
          <h2 className="text-base font-semibold text-gray-900">{t('admin.scrape.confirmTerminate.title', { id: taskId })}</h2>
          <button onClick={onCancel} className="ml-auto text-gray-400 hover:text-gray-600">
            <X size={16} />
          </button>
        </div>
        <p className="text-sm text-gray-600 mb-6">
          {t('admin.scrape.confirmTerminate.message')}
        </p>
        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
          >
            {t('admin.common.cancel')}
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm rounded-lg bg-red-600 text-white hover:bg-red-700 font-medium"
          >
            {t('admin.scrape.confirmTerminate.terminate')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Quota Edit Modal ──────────────────────────────────────────────────────────

function QuotaEditModal({
  quota,
  onSave,
  onCancel,
}: {
  quota: PlatformQuotaItem
  onSave: (limit: number) => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const [value, setValue] = useState(String(quota.daily_limit))

  function handleSave() {
    const num = parseInt(value, 10)
    if (isNaN(num) || num < 0) return
    onSave(num)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-xl p-7 w-[360px] max-w-[90vw]">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold text-gray-900 capitalize">
            {t('admin.scrape.quotaModal.title', { platform: quota.platform })}
          </h2>
          <button onClick={onCancel} className="text-gray-400 hover:text-gray-600">
            <X size={16} />
          </button>
        </div>
        <div className="mb-5">
          <label className="text-xs text-gray-500 font-medium uppercase tracking-wider block mb-2">
            {t('admin.scrape.quotaModal.newLimit')}
          </label>
          <input
            type="number"
            min={0}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-300"
            autoFocus
          />
        </div>
        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
          >
            {t('admin.common.cancel')}
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 text-sm rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 font-medium"
          >
            {t('admin.common.save')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function ScrapeAdminPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('tasks')

  // Tasks tab state
  const [taskData, setTaskData] = useState<ScrapeTasksAdminResponse | null>(null)
  const [tasksLoading, setTasksLoading] = useState(false)
  const [confirmTaskId, setConfirmTaskId] = useState<number | null>(null)
  const [actionLoading, setActionLoading] = useState<number | null>(null)

  // Quota tab state
  const [quotas, setQuotas] = useState<PlatformQuotaItem[]>([])
  const [quotaLoading, setQuotaLoading] = useState(false)
  const [editingQuota, setEditingQuota] = useState<PlatformQuotaItem | null>(null)

  const loadTasks = useCallback(async () => {
    setTasksLoading(true)
    try {
      const data = await listAdminScrapeTasks()
      setTaskData(data)
    } finally {
      setTasksLoading(false)
    }
  }, [])

  const loadQuotas = useCallback(async () => {
    setQuotaLoading(true)
    try {
      const data = await getPlatformQuota()
      setQuotas(data.items)
    } finally {
      setQuotaLoading(false)
    }
  }, [])

  useEffect(() => {
    loadTasks()
  }, [loadTasks])

  useEffect(() => {
    if (tab === 'quota') loadQuotas()
  }, [tab, loadQuotas])

  async function handleForceTerminate(taskId: number) {
    setActionLoading(taskId)
    setConfirmTaskId(null)
    try {
      await forceTerminateTask(taskId)
      await loadTasks()
    } finally {
      setActionLoading(null)
    }
  }

  async function handleRetry(taskId: number) {
    setActionLoading(taskId)
    try {
      await retryTask(taskId)
      await loadTasks()
    } finally {
      setActionLoading(null)
    }
  }

  async function handleQuotaSave(platform: string, limit: number) {
    setEditingQuota(null)
    try {
      await updatePlatformQuota(platform, limit)
      await loadQuotas()
    } catch {
      // ignore
    }
  }

  const tabCls = (t: Tab) =>
    `px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
      tab === t
        ? 'bg-indigo-600 text-white'
        : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100'
    }`

  return (
    <div className="p-8 max-w-7xl mx-auto">
      {confirmTaskId !== null && (
        <ConfirmModal
          taskId={confirmTaskId}
          onConfirm={() => handleForceTerminate(confirmTaskId)}
          onCancel={() => setConfirmTaskId(null)}
        />
      )}
      {editingQuota && (
        <QuotaEditModal
          quota={editingQuota}
          onSave={(limit) => handleQuotaSave(editingQuota.platform, limit)}
          onCancel={() => setEditingQuota(null)}
        />
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">{t('admin.scrape.title')}</h1>
          <p className="text-sm text-gray-500 mt-0.5">{t('admin.scrape.subtitle')}</p>
        </div>
        <div className="flex gap-2">
          <div className={tabCls('tasks')}>
            <button onClick={() => setTab('tasks')}>{t('admin.scrape.tabs.tasks')}</button>
          </div>
          <div className={tabCls('quota')}>
            <button onClick={() => setTab('quota')}>{t('admin.scrape.tabs.quota')}</button>
          </div>
        </div>
      </div>

      {/* Tasks Tab */}
      {tab === 'tasks' && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <div className="flex gap-4 text-sm text-gray-500">
              {taskData && (
                <>
                  <span>
                    {t('admin.scrape.tasks.total')}: <span className="font-semibold text-gray-900">{taskData.total}</span>
                  </span>
                  <span>
                    {t('admin.scrape.tasks.running')}:{' '}
                    <span className="font-semibold text-blue-600">{taskData.running}</span>
                  </span>
                </>
              )}
            </div>
            <button
              onClick={loadTasks}
              disabled={tasksLoading}
              className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 px-3 py-1.5 rounded-lg hover:bg-gray-100"
            >
              <RefreshCw size={14} className={tasksLoading ? 'animate-spin' : ''} />
              {t('admin.common.refresh')}
            </button>
          </div>

          <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 text-xs text-gray-400 font-medium uppercase tracking-wider">
                  <th className="px-4 py-3 text-left">ID</th>
                  <th className="px-4 py-3 text-left">{t('admin.scrape.table.industry')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.scrape.table.platforms')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.scrape.table.creator')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.common.status')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.scrape.table.progress')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.scrape.table.found')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.common.createdAt')}</th>
                  <th className="px-4 py-3 text-left">{t('admin.common.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {tasksLoading && (
                  <tr>
                    <td colSpan={9} className="px-4 py-10 text-center text-gray-400">
                      {t('admin.common.loading')}
                    </td>
                  </tr>
                )}
                {!tasksLoading && taskData?.items.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-4 py-10 text-center text-gray-400">
                      {t('admin.scrape.tasks.noTasks')}
                    </td>
                  </tr>
                )}
                {!tasksLoading &&
                  taskData?.items.map((task: ScrapeTaskAdminItem) => (
                    <tr
                      key={task.id}
                      className={`border-b border-gray-50 last:border-0 hover:bg-gray-50 ${
                        task.status === 'running' ? 'bg-blue-50/40' : ''
                      }`}
                    >
                      <td className="px-4 py-3 font-mono text-gray-500">#{task.id}</td>
                      <td className="px-4 py-3 font-medium text-gray-900 max-w-[120px] truncate">
                        {task.industry}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {task.platforms.map((p) => (
                            <span
                              key={p}
                              className="text-xs px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 capitalize"
                            >
                              {p}
                            </span>
                          ))}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {task.creator_username ?? '—'}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                            STATUS_COLORS[task.status] ?? 'text-gray-600 bg-gray-100'
                          }`}
                        >
                          {task.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-indigo-500 rounded-full"
                              style={{ width: `${task.progress}%` }}
                            />
                          </div>
                          <span className="text-xs text-gray-500">{task.progress}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-gray-600">{task.found_count}</td>
                      <td className="px-4 py-3 text-gray-400 text-xs">{formatTs(task.created_at)}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          {(task.status === 'running' || task.status === 'pending') && (
                            <button
                              onClick={() => setConfirmTaskId(task.id)}
                              disabled={actionLoading === task.id}
                              title={t('admin.scrape.actions.forceTerminate')}
                              className="p-1.5 rounded hover:bg-red-50 text-red-500 hover:text-red-700 disabled:opacity-40"
                            >
                              <Square size={14} />
                            </button>
                          )}
                          {(task.status === 'failed' || task.status === 'cancelled') && (
                            <button
                              onClick={() => handleRetry(task.id)}
                              disabled={actionLoading === task.id}
                              title={t('admin.scrape.actions.retry')}
                              className="p-1.5 rounded hover:bg-indigo-50 text-indigo-500 hover:text-indigo-700 disabled:opacity-40"
                            >
                              <RotateCcw size={14} />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Platform Quota Tab */}
      {tab === 'quota' && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <p className="text-sm text-gray-500">
              {t('admin.scrape.quota.editHint')}
            </p>
            <button
              onClick={loadQuotas}
              disabled={quotaLoading}
              className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 px-3 py-1.5 rounded-lg hover:bg-gray-100"
            >
              <RefreshCw size={14} className={quotaLoading ? 'animate-spin' : ''} />
              {t('admin.common.refresh')}
            </button>
          </div>

          {quotaLoading && (
            <div className="text-center text-gray-400 py-12 text-sm">{t('admin.common.loading')}</div>
          )}

          {!quotaLoading && (
            <div className="grid grid-cols-1 gap-4">
              {quotas.map((q) => {
                const pct = q.daily_limit > 0 ? Math.min((q.today_used / q.daily_limit) * 100, 100) : 0
                const barColor = PLATFORM_COLORS[q.platform] ?? 'bg-gray-400'
                return (
                  <div
                    key={q.platform}
                    className="bg-white border border-gray-100 rounded-xl p-5 hover:border-indigo-200 cursor-pointer transition-colors"
                    onClick={() => setEditingQuota(q)}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <span className="text-sm font-semibold text-gray-900 capitalize">
                        {q.platform}
                      </span>
                      <div className="text-sm text-gray-500">
                        <span className="font-semibold text-gray-900">{q.today_used}</span>
                        {' / '}
                        <span>{q.daily_limit}</span>
                        <span className="ml-1 text-xs text-gray-400">{t('admin.scrape.quota.today')}</span>
                      </div>
                    </div>
                    <div className="w-full h-2.5 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${barColor} ${
                          pct >= 90 ? 'opacity-100' : 'opacity-80'
                        }`}
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="flex items-center justify-between mt-2">
                      <span className="text-xs text-gray-400">{pct.toFixed(1)}% {t('admin.scrape.quota.used')}</span>
                      <span className="text-xs text-indigo-500 hover:underline">{t('admin.scrape.quota.editLimit')} →</span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
