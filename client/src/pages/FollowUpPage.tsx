import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { Settings, Clock, Mail, RefreshCw, Save, AlertCircle, CheckCircle } from 'lucide-react'
import { followUpApi, FollowUpSettings, FollowUpLogItem } from '../api/follow_up'

const PAGE_SIZE = 20

const STATUS_STYLES: Record<string, string> = {
  sent:      'bg-blue-50 text-blue-600',
  delivered: 'bg-cyan-50 text-cyan-600',
  opened:    'bg-yellow-50 text-yellow-600',
  replied:   'bg-green-50 text-green-700',
  failed:    'bg-red-50 text-red-600',
}

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-500'
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {status}
    </span>
  )
}

function PlatformBadge({ platform }: { platform: string | null }) {
  if (!platform) return <span className="text-gray-300">—</span>
  const colors: Record<string, string> = {
    tiktok: 'bg-black text-white',
    instagram: 'bg-pink-100 text-pink-700',
    youtube: 'bg-red-50 text-red-600',
    twitter: 'bg-sky-50 text-sky-600',
    facebook: 'bg-blue-50 text-blue-600',
  }
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${colors[platform] ?? 'bg-gray-100 text-gray-600'}`}>
      {platform}
    </span>
  )
}

// ── Settings Panel ────────────────────────────────────────────────────────────

function SettingsPanel() {
  const { t } = useTranslation()
  const [settings, setSettings] = useState<FollowUpSettings | null>(null)
  const [loading, setLoading]   = useState(true)
  const [saving, setSaving]     = useState(false)
  const [saved, setSaved]       = useState(false)
  const [error, setError]       = useState('')

  // Cadence state — locked to spec defaults (3 phase-1 + 6 phase-2 = 9
  // follow-ups over ~7 months). UI no longer exposes inputs for these;
  // values stay at their useState initial values for the lifetime of the
  // component. Setters are deliberately omitted — see handleSave below for
  // why we still keep the state instead of using bare consts.
  const [enabled, setEnabled] = useState(true)
  const [phase1Count]         = useState(3)
  const [phase1IntervalDays]  = useState(2)
  const [intervalDays]        = useState(30)
  const [maxCount]            = useState(6)
  const [hourUtc, setHourUtc] = useState(10)

  // Cadence preview — recomputed from the live form state so the user sees
  // the impact of every input change in real time.
  // totalDays = days from initial send → final follow-up (= when the
  // influencer is auto-archived). Use Math.ceil so "186 days" rounds up to
  // 7 months instead of 6 — the archive date is past the 6-month mark, so
  // "约 7 个月" is closer to user expectation than "约 6 个月".
  const totalCount  = phase1Count + maxCount
  const totalDays   = phase1Count * phase1IntervalDays + maxCount * intervalDays
  const totalMonths = Math.max(1, Math.ceil(totalDays / 30))

  // Build a list of dated events for the timeline preview. The timeline
  // is the ONLY surface that shows the cadence — the numeric inputs that
  // used to live in a collapsible were removed; cadence is now read-only
  // and locked to spec. Each event carries a `kind` so the renderer can
  // highlight phase boundaries and the archive row.
  //
  // Day numbering uses 1-based indexing to match the original spec wording
  // ("第 1 天首发, 第 3/5/7 天密集追发"). With phase1_interval_days=2 and
  // initial on Day 1, the first follow-up lands on Day 3 — matching spec.
  type TimelineEvent = { day: number; label: string; kind: 'initial' | 'p1' | 'p1end' | 'p2' | 'p2end' | 'archive' }
  const events: TimelineEvent[] = []
  let cursor = 1
  events.push({ day: cursor, label: t('followUp.strategy.timelineEventInitial'), kind: 'initial' })
  for (let i = 1; i <= phase1Count; i++) {
    cursor += phase1IntervalDays
    events.push({
      day: cursor,
      label: t(
        i === phase1Count
          ? 'followUp.strategy.timelineEventPhase1End'
          : 'followUp.strategy.timelineEventPhase1',
        { n: i },
      ),
      kind: i === phase1Count ? 'p1end' : 'p1',
    })
  }
  for (let i = 1; i <= maxCount; i++) {
    cursor += intervalDays
    events.push({
      day: cursor,
      label: t(
        i === maxCount
          ? 'followUp.strategy.timelineEventPhase2End'
          : 'followUp.strategy.timelineEventPhase2',
        { n: i },
      ),
      kind: i === maxCount ? 'p2end' : 'p2',
    })
  }
  events.push({ day: cursor + 1, label: t('followUp.strategy.timelineEventArchive'), kind: 'archive' })

  useEffect(() => {
    followUpApi.getSettings()
      .then((s) => {
        setSettings(s)
        setEnabled(s.enabled ?? true)
        // Cadence (phase1_count / phase1_interval_days / max_count /
        // interval_days) is INTENTIONALLY not read from the response —
        // the UI no longer exposes it as configurable, so the React state
        // stays at its useState initial values (3 / 2 / 6 / 30 = spec).
        // handleSave below sends these state values back, so any drift in
        // DB (e.g. left over from prior tweaks) gets overwritten back to
        // spec on the next save.
        setHourUtc(s.hour_utc ?? 10)
      })
      .catch(() => setError(t('followUp.strategy.loadFailed')))
      .finally(() => setLoading(false))
    // Run-once on mount. `t` is referentially stable (i18next pattern),
    // so omitting it from deps doesn't risk a stale closure here.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setError('')
    setSaved(false)
    try {
      // ⚠ Side effect: phase1_count / phase1_interval_days / interval_days /
      // max_count are sent every save with their locked spec values. Any
      // out-of-band write to those columns (admin script, future tooling)
      // gets silently overwritten the next time anyone clicks Save here.
      // Intentional — keeps the cadence anchored to the spec — but if you
      // ever add another writer for these fields, decide carefully who wins.
      const updated = await followUpApi.updateSettings({
        enabled,
        phase1_count: phase1Count,
        phase1_interval_days: phase1IntervalDays,
        interval_days: intervalDays,
        max_count: maxCount,
        hour_utc: hourUtc,
      })
      setSettings(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch {
      setError(t('followUp.strategy.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="bg-white rounded-lg border border-gray-100 p-6">
        <div className="animate-pulse space-y-3">
          <div className="h-4 bg-gray-100 rounded w-1/3" />
          <div className="h-10 bg-gray-100 rounded" />
          <div className="h-10 bg-gray-100 rounded" />
        </div>
      </div>
    )
  }

  return (
    <div className="bg-white rounded-lg border border-gray-100">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-50">
        <div className="flex items-center gap-2">
          <Settings size={16} className="text-gray-400" />
          <h2 className="text-sm font-semibold text-gray-800">{t('followUp.strategy.title')}</h2>
        </div>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <span className="text-xs text-gray-500">{t('followUp.strategy.autoFollowUp')}</span>
          <div
            onClick={() => setEnabled(!enabled)}
            className={`relative w-9 h-5 rounded-full transition-colors ${enabled ? 'bg-gray-900' : 'bg-gray-200'}`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${enabled ? 'translate-x-4' : 'translate-x-0'}`}
            />
          </div>
        </label>
      </div>

      {/* Form */}
      <div className="px-6 py-5 space-y-5">
        {/* Timeline preview — primary view. Replaces the old "preview banner
            of numbers"; users now see the actual fire dates instead of
            having to mentally compute them from interval × count. */}
        <div className="bg-emerald-50 border border-emerald-100 rounded-md px-4 py-3">
          <ol className="space-y-1.5">
            {events.map((ev, i) => (
              <li key={`${ev.kind}-${i}`} className="flex items-baseline gap-3 text-sm">
                <span className="font-mono text-xs text-emerald-700 min-w-[64px] tabular-nums">
                  {t('followUp.strategy.timelineDayLabel', { day: ev.day })}
                </span>
                <span className={
                  ev.kind === 'archive' ? 'text-emerald-900 font-medium' :
                  ev.kind === 'initial' ? 'text-emerald-900 font-medium' :
                  'text-emerald-800'
                }>
                  {ev.label}
                </span>
              </li>
            ))}
          </ol>
          <div className="mt-3 pt-2 border-t border-emerald-100 text-xs text-emerald-700">
            {t('followUp.strategy.timelineSummary', {
              count: totalCount,
              total: totalCount + 1,
              months: totalMonths,
            })}
          </div>
        </div>

        {/* Daily check time — when the scheduler runs each day */}
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1.5">
            {t('followUp.strategy.sendTimeLabel')}
          </label>
          <select
            value={hourUtc}
            onChange={(e) => setHourUtc(Number(e.target.value))}
            className="w-full sm:w-1/3 border border-gray-200 rounded-md px-3 py-2 text-sm focus:outline-none focus:border-gray-400 transition-colors bg-white"
          >
            {Array.from({ length: 24 }, (_, h) => (
              <option key={h} value={h}>
                {String(h).padStart(2, '0')}:00 UTC
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-gray-400">{t('followUp.strategy.sendTimeHint')}</p>
        </div>

      </div>

      {/* Footer */}
      <div className="px-6 py-4 border-t border-gray-50 flex items-center justify-between">
        <div>
          {error && (
            <div className="flex items-center gap-1.5 text-xs text-red-500">
              <AlertCircle size={12} />
              {error}
            </div>
          )}
          {saved && (
            <div className="flex items-center gap-1.5 text-xs text-green-600">
              <CheckCircle size={12} />
              {t('followUp.strategy.saved')}
            </div>
          )}
          {settings && !error && !saved && (
            <p className="text-xs text-gray-400">
              {t('followUp.strategy.lastUpdated', { date: new Date(settings.updated_at).toLocaleString() })}
            </p>
          )}
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 bg-gray-900 text-white text-xs font-medium px-4 py-2 rounded-md hover:bg-gray-700 transition-colors disabled:opacity-50"
        >
          {saving ? <RefreshCw size={12} className="animate-spin" /> : <Save size={12} />}
          {saving ? t('followUp.strategy.saving') : t('followUp.strategy.saveButton')}
        </button>
      </div>
    </div>
  )
}

// ── Logs Table ────────────────────────────────────────────────────────────────

function LogsTable() {
  const { t } = useTranslation()
  const [items, setItems]     = useState<FollowUpLogItem[]>([])
  const [total, setTotal]     = useState(0)
  const [page, setPage]       = useState(1)
  const [loading, setLoading] = useState(true)

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await followUpApi.getLogs(page, PAGE_SIZE)
      setItems(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [page])

  useEffect(() => { load() }, [load])

  return (
    <div className="bg-white rounded-lg border border-gray-100">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-50">
        <div className="flex items-center gap-2">
          <Mail size={16} className="text-gray-400" />
          <h2 className="text-sm font-semibold text-gray-800">{t('followUp.log.title')}</h2>
          <span className="bg-gray-100 text-gray-500 text-xs px-2 py-0.5 rounded-full">{total}</span>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="p-1.5 rounded hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-colors"
        >
          <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {/* Table */}
      {loading && items.length === 0 ? (
        <div className="p-8 text-center text-gray-400 text-sm">{t('followUp.log.loading')}</div>
      ) : items.length === 0 ? (
        <div className="p-8 text-center">
          <Clock size={32} className="mx-auto text-gray-200 mb-2" />
          <p className="text-gray-400 text-sm">{t('followUp.log.noLogs')}</p>
          <p className="text-gray-300 text-xs mt-1">{t('followUp.log.noLogsHint')}</p>
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-50">
                {[t('followUp.log.table.influencer'), t('followUp.log.table.platform'), t('followUp.log.table.subject'), t('followUp.log.table.followUpNum'), t('followUp.log.table.status'), t('followUp.log.table.sentAt')].map((h) => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-medium text-gray-400 whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {items.map((item) => (
                <tr key={item.id} className="hover:bg-gray-50/50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="font-medium text-gray-800 text-xs truncate max-w-[160px]">
                      {item.influencer_name || '—'}
                    </div>
                    <div className="text-gray-400 text-xs truncate max-w-[160px]">
                      {item.influencer_email}
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <PlatformBadge platform={item.influencer_platform} />
                  </td>
                  <td className="px-4 py-3 text-gray-600 text-xs max-w-[240px] truncate" title={item.subject}>
                    {item.subject}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className="inline-block w-7 h-7 rounded-full bg-gray-100 text-gray-600 text-xs font-semibold leading-7 text-center">
                      {item.follow_up_count}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={item.status} />
                  </td>
                  <td className="px-4 py-3 text-gray-400 text-xs whitespace-nowrap">
                    {item.sent_at ? new Date(item.sent_at).toLocaleString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-6 py-3 border-t border-gray-50">
          <span className="text-xs text-gray-400">
            {t('followUp.log.total', { count: total, current: page, pages: totalPages })}
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="px-3 py-1.5 text-xs border border-gray-200 rounded hover:bg-gray-50 disabled:opacity-40 transition-colors"
            >
              {t('common.prev')}
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="px-3 py-1.5 text-xs border border-gray-200 rounded hover:bg-gray-50 disabled:opacity-40 transition-colors"
            >
              {t('common.next')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function FollowUpPage() {
  const { t } = useTranslation()
  return (
    <div className="p-6 space-y-5 max-w-5xl mx-auto">
      {/* Page title */}
      <div>
        <h1 className="text-lg font-semibold text-gray-900">{t('followUp.title')}</h1>
        <p className="text-xs text-gray-400 mt-0.5">
          {t('followUp.subtitle')}
        </p>
      </div>

      <SettingsPanel />
      <LogsTable />
    </div>
  )
}
