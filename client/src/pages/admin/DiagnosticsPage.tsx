import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Activity,
  AlertCircle,
  CheckCircle,
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  HelpCircle,
  Loader2,
  RefreshCw,
  Server,
  Wifi,
} from 'lucide-react'
import {
  type DbHealth,
  type HealthcheckResult,
  type RedisHealth,
  type SchedulerHealth,
  type SystemHealth,
  type WsHealth,
  runHealthcheck,
} from '../../api/admin/diagnostics'

// ─── Status Badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation()
  if (status === 'ok') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 text-xs font-medium">
        <CheckCircle size={11} /> {t('admin.diagnostics.status.ok')}
      </span>
    )
  }
  if (status === 'not_configured' || status === 'not_available') {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 text-xs font-medium">
        <HelpCircle size={11} /> {status === 'not_configured' ? t('admin.diagnostics.status.notConfigured') : t('admin.diagnostics.status.notAvailable')}
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-red-50 text-red-600 text-xs font-medium">
      <AlertCircle size={11} /> {t('admin.diagnostics.status.error')}
    </span>
  )
}

// ─── Progress Bar ─────────────────────────────────────────────────────────────

function ProgressBar({ percent, label }: { percent: number; label: string }) {
  const color =
    percent > 90 ? 'bg-red-500' : percent > 75 ? 'bg-amber-400' : 'bg-emerald-500'
  return (
    <div>
      <div className="flex justify-between text-xs text-gray-500 mb-1">
        <span>{label}</span>
        <span>{percent}%</span>
      </div>
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

// ─── Card Shell ───────────────────────────────────────────────────────────────

function DiagCard({
  icon,
  title,
  status,
  children,
}: {
  icon: React.ReactNode
  title: string
  status: string | undefined
  children?: React.ReactNode
}) {
  const [expanded, setExpanded] = useState(false)
  const borderColor =
    status === 'ok'
      ? 'border-emerald-200'
      : status === 'not_configured' || status === 'not_available'
      ? 'border-slate-200'
      : status
      ? 'border-red-200'
      : 'border-gray-200'

  return (
    <div className={`border rounded-xl bg-white overflow-hidden ${borderColor}`}>
      <button
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors"
        onClick={() => children && setExpanded((e) => !e)}
      >
        <div className="flex items-center gap-3">
          <span className="text-slate-500">{icon}</span>
          <span className="font-medium text-sm text-gray-900">{title}</span>
          {status && <StatusBadge status={status} />}
        </div>
        {children && (
          <span className="text-gray-400">
            {expanded ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
          </span>
        )}
      </button>
      {expanded && children && (
        <div className="border-t border-gray-100 px-5 py-4 bg-gray-50 text-sm">{children}</div>
      )}
    </div>
  )
}

// ─── DB Card ─────────────────────────────────────────────────────────────────

function DbCard({ data }: { data: DbHealth | undefined }) {
  const { t } = useTranslation()
  return (
    <DiagCard icon={<Database size={16} />} title={t('admin.diagnostics.cards.database')} status={data?.status}>
      {data && data.status === 'ok' && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="bg-white rounded-lg p-3 border border-gray-100">
              <p className="text-gray-400 mb-0.5">{t('admin.diagnostics.db.latency')}</p>
              <p className="font-semibold text-gray-800">{data.latency_ms} ms</p>
            </div>
            <div className="bg-white rounded-lg p-3 border border-gray-100">
              <p className="text-gray-400 mb-0.5">{t('admin.diagnostics.db.poolSize')}</p>
              <p className="font-semibold text-gray-800">{data.pool?.size ?? '—'}</p>
            </div>
            <div className="bg-white rounded-lg p-3 border border-gray-100">
              <p className="text-gray-400 mb-0.5">{t('admin.diagnostics.db.checkedOut')}</p>
              <p className="font-semibold text-gray-800">{data.pool?.checked_out ?? '—'}</p>
            </div>
            <div className="bg-white rounded-lg p-3 border border-gray-100">
              <p className="text-gray-400 mb-0.5">{t('admin.diagnostics.db.overflow')}</p>
              <p className="font-semibold text-gray-800">{data.pool?.overflow ?? '—'}</p>
            </div>
          </div>
          {data.slow_queries_top10 && data.slow_queries_top10.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-600 mb-2">{t('admin.diagnostics.db.slowQueries')}</p>
              <pre className="text-xs bg-white border border-gray-100 rounded p-2 overflow-auto max-h-32">
                {JSON.stringify(data.slow_queries_top10, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
      {data?.status === 'error' && (
        <p className="text-xs text-red-600">{data.reason}</p>
      )}
    </DiagCard>
  )
}

// ─── Redis Card ───────────────────────────────────────────────────────────────

function RedisCard({ data }: { data: RedisHealth | undefined }) {
  const { t } = useTranslation()
  return (
    <DiagCard icon={<Server size={16} />} title="Redis" status={data?.status}>
      {data && data.status === 'ok' && (
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div className="bg-white rounded-lg p-3 border border-gray-100">
            <p className="text-gray-400 mb-0.5">{t('admin.diagnostics.db.latency')}</p>
            <p className="font-semibold text-gray-800">{data.latency_ms} ms</p>
          </div>
          <div className="bg-white rounded-lg p-3 border border-gray-100">
            <p className="text-gray-400 mb-0.5">{t('admin.diagnostics.redis.connectedClients')}</p>
            <p className="font-semibold text-gray-800">{data.connected_clients}</p>
          </div>
          <div className="bg-white rounded-lg p-3 border border-gray-100">
            <p className="text-gray-400 mb-0.5">{t('admin.diagnostics.redis.keys')}</p>
            <p className="font-semibold text-gray-800">{data.key_count}</p>
          </div>
          <div className="bg-white rounded-lg p-3 border border-gray-100">
            <p className="text-gray-400 mb-0.5">{t('admin.diagnostics.redis.queueDepth')}</p>
            <p className="font-semibold text-gray-800">{data.queue_depth}</p>
          </div>
        </div>
      )}
      {data && (data.status === 'not_configured' || data.status === 'error') && (
        <p className="text-xs text-slate-500">
          {data.status === 'not_configured'
            ? t('admin.diagnostics.redis.notConfigured')
            : data.reason}
        </p>
      )}
    </DiagCard>
  )
}

// ─── WebSocket Card ───────────────────────────────────────────────────────────

function WsCard({ data }: { data: WsHealth | undefined }) {
  const { t } = useTranslation()
  return (
    <DiagCard icon={<Wifi size={16} />} title="WebSocket" status={data?.status}>
      {data && data.status === 'ok' && (
        <div className="space-y-2 text-xs">
          <div className="bg-white rounded-lg p-3 border border-gray-100 inline-block">
            <p className="text-gray-400 mb-0.5">{t('admin.diagnostics.ws.activeConnections')}</p>
            <p className="font-semibold text-gray-800">{data.active_connections}</p>
          </div>
          {data.channels && (
            <div>
              <p className="text-xs font-medium text-gray-600 mb-1">{t('admin.diagnostics.ws.channels')}</p>
              {Object.entries(data.channels).map(([ch, count]) => (
                <div key={ch} className="flex justify-between text-xs text-gray-600 py-0.5">
                  <span>{ch}</span>
                  <span className="font-medium">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </DiagCard>
  )
}

// ─── Scheduler Card ───────────────────────────────────────────────────────────

function SchedulerCard({ data }: { data: SchedulerHealth | undefined }) {
  const { t } = useTranslation()
  return (
    <DiagCard icon={<Clock size={16} />} title={t('admin.diagnostics.cards.scheduler')} status={data?.status}>
      {data && data.status === 'ok' && (
        <div className="space-y-3">
          <div className="flex items-center gap-3 text-xs">
            <span
              className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                data.running ? 'bg-emerald-50 text-emerald-700' : 'bg-red-50 text-red-600'
              }`}
            >
              {data.running ? t('admin.diagnostics.scheduler.running') : t('admin.diagnostics.scheduler.stopped')}
            </span>
            <span className="text-gray-500">{data.job_count} {t('admin.diagnostics.scheduler.jobs')}</span>
          </div>
          {data.jobs && data.jobs.length > 0 && (
            <div className="space-y-1">
              {data.jobs.map((job) => (
                <div
                  key={job.id}
                  className="bg-white border border-gray-100 rounded-lg px-3 py-2 text-xs"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-gray-800">{job.name}</span>
                    <span className="text-gray-400 font-mono text-[10px]">{job.id}</span>
                  </div>
                  <div className="text-gray-500 mt-0.5">
                    {t('admin.diagnostics.scheduler.next')}: {job.next_run_time ?? t('admin.diagnostics.scheduler.paused')}
                  </div>
                  <div className="text-gray-400 text-[10px] mt-0.5">{job.trigger}</div>
                </div>
              ))}
            </div>
          )}
          {data.jobs?.length === 0 && (
            <p className="text-xs text-gray-400">{t('admin.diagnostics.scheduler.noJobs')}</p>
          )}
        </div>
      )}
    </DiagCard>
  )
}

// ─── System Card ──────────────────────────────────────────────────────────────

function SystemCard({ data }: { data: SystemHealth | undefined }) {
  const { t } = useTranslation()
  if (data?.status === 'not_available') {
    return (
      <DiagCard icon={<Activity size={16} />} title={t('admin.diagnostics.cards.system')} status={data.status}>
        <p className="text-xs text-slate-500">
          {t('admin.diagnostics.system.notAvailable')}
        </p>
      </DiagCard>
    )
  }

  return (
    <DiagCard icon={<Activity size={16} />} title={t('admin.diagnostics.cards.system')} status={data?.status}>
      {data && data.status === 'ok' && (
        <div className="space-y-4">
          {data.disk && (
            <div>
              <p className="text-xs font-medium text-gray-600 mb-2">{t('admin.diagnostics.system.disk')}</p>
              <ProgressBar percent={data.disk.percent} label={`${data.disk.used_gb} GB / ${data.disk.total_gb} GB`} />
            </div>
          )}
          {data.memory && (
            <div>
              <p className="text-xs font-medium text-gray-600 mb-2">{t('admin.diagnostics.system.memory')}</p>
              <ProgressBar
                percent={data.memory.percent}
                label={`${data.memory.used_gb} GB / ${data.memory.total_gb} GB`}
              />
            </div>
          )}
          {data.process && (
            <div>
              <p className="text-xs font-medium text-gray-600 mb-2">{t('admin.diagnostics.system.pythonProcess')}</p>
              <div className="grid grid-cols-2 gap-2 text-xs">
                {[
                  ['PID', data.process.pid],
                  [t('admin.diagnostics.system.threads'), data.process.num_threads],
                  ['RSS', data.process.memory_rss_mb != null ? `${data.process.memory_rss_mb} MB` : '—'],
                  [t('admin.diagnostics.system.uptime'), data.process.uptime_s != null ? `${Math.round(data.process.uptime_s / 60)} min` : '—'],
                ].map(([k, v]) => (
                  <div key={k as string} className="bg-white border border-gray-100 rounded p-2">
                    <p className="text-gray-400">{k}</p>
                    <p className="font-semibold text-gray-800">{v ?? '—'}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {data?.status === 'error' && (
        <p className="text-xs text-red-600">{data.reason}</p>
      )}
    </DiagCard>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function DiagnosticsPage() {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<HealthcheckResult | null>(null)
  const [err, setErr] = useState('')
  const [checkedAt, setCheckedAt] = useState<string | null>(null)

  const runCheck = async () => {
    setLoading(true)
    setErr('')
    try {
      const data = await runHealthcheck()
      setResult(data)
      setCheckedAt(new Date(data.checked_at).toLocaleTimeString())
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErr(msg ?? t('admin.diagnostics.healthcheckFailed'))
    } finally {
      setLoading(false)
    }
  }

  const overallColor =
    result?.overall === 'ok'
      ? 'text-emerald-600'
      : result?.overall === 'degraded'
      ? 'text-amber-600'
      : result?.overall === 'error'
      ? 'text-red-600'
      : 'text-gray-400'

  return (
    <div className="px-8 py-8 max-w-3xl">
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">{t('admin.diagnostics.title')}</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {t('admin.diagnostics.subtitle')}
          </p>
        </div>
        {result && (
          <div className="text-right">
            <p className={`text-sm font-semibold ${overallColor} capitalize`}>
              {t('admin.diagnostics.overall')}: {result.overall}
            </p>
            <p className="text-xs text-gray-400 mt-0.5">{t('admin.diagnostics.checkedAt', { time: checkedAt })}</p>
          </div>
        )}
      </div>

      <button
        onClick={runCheck}
        disabled={loading}
        className="w-full flex items-center justify-center gap-2 bg-slate-900 hover:bg-slate-800 disabled:bg-slate-400 text-white text-sm font-medium rounded-xl px-6 py-3.5 transition-colors mb-8"
      >
        {loading ? (
          <>
            <Loader2 size={16} className="animate-spin" /> {t('admin.diagnostics.running')}
          </>
        ) : (
          <>
            <RefreshCw size={15} /> {t('admin.diagnostics.runButton')}
          </>
        )}
      </button>

      {err && (
        <div className="mb-6 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700">
          {err}
        </div>
      )}

      <div className="space-y-3">
        <DbCard data={result?.components?.db} />
        <RedisCard data={result?.components?.redis} />
        <WsCard data={result?.components?.websocket} />
        <SchedulerCard data={result?.components?.scheduler} />
        <SystemCard data={result?.components?.system} />
      </div>

      {!result && !loading && (
        <p className="text-center text-xs text-gray-400 mt-8">
          {t('admin.diagnostics.hint')}
        </p>
      )}
    </div>
  )
}
