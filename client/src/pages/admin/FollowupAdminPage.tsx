import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle, Pause, Play, Save } from 'lucide-react'
import {
  type FollowUpSettings,
  type ResponderLogItem,
  getFollowUpSettings,
  getResponderLogs,
  patchFollowUpSettings,
  pauseAllFollowUps,
  resumeAllFollowUps,
} from '../../api/admin/followup_admin'

// ─── Confirm Modal ─────────────────────────────────────────────────────────────

function ConfirmModal({
  message,
  onConfirm,
  onCancel,
}: {
  message: string
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-xl p-7 w-[420px] max-w-[92vw]">
        <div className="flex items-center gap-3 mb-4">
          <AlertTriangle size={20} className="text-red-500 shrink-0" />
          <h2 className="text-base font-semibold text-gray-900">Confirm Action</h2>
        </div>
        <p className="text-sm text-gray-600 mb-6">{message}</p>
        <div className="flex justify-end gap-3">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm font-medium text-white bg-red-500 rounded-lg hover:bg-red-600"
          >
            Confirm
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Status Badge ──────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  sent: 'text-blue-700 bg-blue-50',
  delivered: 'text-green-700 bg-green-50',
  opened: 'text-emerald-700 bg-emerald-50',
  replied: 'text-purple-700 bg-purple-50',
  failed: 'text-red-700 bg-red-50',
  pending: 'text-gray-600 bg-gray-100',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[status] ?? 'text-gray-600 bg-gray-100'}`}>
      {status}
    </span>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function FollowupAdminPage() {
  const [settings, setSettings] = useState<FollowUpSettings | null>(null)
  const [logs, setLogs] = useState<ResponderLogItem[]>([])
  const [logsTotal, setLogsTotal] = useState(0)
  const [logsPage, setLogsPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [confirmModal, setConfirmModal] = useState<'pause' | 'resume' | null>(null)

  const [form, setForm] = useState({
    enabled: true,
    interval_days: 30,
    max_count: 6,
    hour_utc: 10,
  })

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, r] = await Promise.all([
        getFollowUpSettings(),
        getResponderLogs(logsPage),
      ])
      setSettings(s)
      setForm({
        enabled: s.enabled,
        interval_days: s.interval_days,
        max_count: s.max_count,
        hour_utc: s.hour_utc,
      })
      setLogs(r.items)
      setLogsTotal(r.total)
    } finally {
      setLoading(false)
    }
  }, [logsPage])

  useEffect(() => { load() }, [load])

  const handleSave = async () => {
    setSaving(true)
    try {
      const updated = await patchFollowUpSettings(form)
      setSettings(updated)
    } finally {
      setSaving(false)
    }
  }

  const handlePause = async () => {
    await pauseAllFollowUps()
    setConfirmModal(null)
    load()
  }

  const handleResume = async () => {
    await resumeAllFollowUps()
    setConfirmModal(null)
    load()
  }

  if (loading && !settings) {
    return <div className="text-center py-16 text-gray-400 text-sm">Loading...</div>
  }

  const totalPages = Math.ceil(logsTotal / 20)

  return (
    <>
      {confirmModal === 'pause' && (
        <ConfirmModal
          message="This will immediately disable all automatic follow-up emails. This affects all influencers globally."
          onConfirm={handlePause}
          onCancel={() => setConfirmModal(null)}
        />
      )}
      {confirmModal === 'resume' && (
        <ConfirmModal
          message="This will re-enable automatic follow-up emails globally."
          onConfirm={handleResume}
          onCancel={() => setConfirmModal(null)}
        />
      )}

      <div className="max-w-4xl mx-auto space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Follow-up Strategy</h1>
            <p className="text-sm text-gray-500 mt-0.5">Global auto follow-up policy and Responder audit</p>
          </div>
          <div className="flex items-center gap-3">
            {settings?.enabled ? (
              <button
                onClick={() => setConfirmModal('pause')}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-red-500 rounded-lg hover:bg-red-600"
              >
                <Pause size={14} />
                Emergency Pause
              </button>
            ) : (
              <button
                onClick={() => setConfirmModal('resume')}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-emerald-500 rounded-lg hover:bg-emerald-600"
              >
                <Play size={14} />
                Resume All
              </button>
            )}
          </div>
        </div>

        {/* Status Banner */}
        {settings && !settings.enabled && (
          <div className="flex items-center gap-3 p-4 bg-red-50 border border-red-100 rounded-xl">
            <AlertTriangle size={16} className="text-red-500 shrink-0" />
            <p className="text-sm text-red-700 font-medium">Follow-up emails are currently <strong>paused</strong> globally.</p>
          </div>
        )}

        {/* Strategy Config Card */}
        <div className="bg-white border border-gray-100 rounded-xl p-6">
          <h2 className="text-sm font-semibold text-gray-900 mb-5">Strategy Configuration</h2>
          <div className="grid grid-cols-2 gap-5">
            <div>
              <label className="block text-xs text-gray-500 mb-1.5">Master Toggle</label>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setForm(f => ({ ...f, enabled: !f.enabled }))}
                  className={`relative w-10 h-5 rounded-full transition-colors ${form.enabled ? 'bg-gray-900' : 'bg-gray-200'}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${form.enabled ? 'translate-x-5' : ''}`} />
                </button>
                <span className="text-sm text-gray-700">{form.enabled ? 'Enabled' : 'Disabled'}</span>
              </div>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1.5">Run Hour (UTC)</label>
              <input
                type="number"
                min={0}
                max={23}
                value={form.hour_utc}
                onChange={e => setForm(f => ({ ...f, hour_utc: Number(e.target.value) }))}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1.5">Max Follow-ups per Influencer</label>
              <input
                type="number"
                min={1}
                max={50}
                value={form.max_count}
                onChange={e => setForm(f => ({ ...f, max_count: Number(e.target.value) }))}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1.5">Interval Days (between follow-ups)</label>
              <input
                type="number"
                min={1}
                max={365}
                value={form.interval_days}
                onChange={e => setForm(f => ({ ...f, interval_days: Number(e.target.value) }))}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
              />
            </div>
          </div>
          <div className="flex justify-end mt-5">
            <button
              onClick={handleSave}
              disabled={saving}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800 disabled:opacity-50"
            >
              <Save size={14} />
              {saving ? 'Saving…' : 'Save Settings'}
            </button>
          </div>
        </div>

        {/* Responder Logs */}
        <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-50">
            <h2 className="text-sm font-semibold text-gray-900">Responder Behavior Audit</h2>
            <p className="text-xs text-gray-400 mt-0.5">Follow-up emails generated by the Responder Agent — {logsTotal} total</p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50 text-xs text-gray-400 uppercase tracking-wide">
                  <th className="text-left py-3 px-4 font-medium">Influencer</th>
                  <th className="text-left py-3 px-4 font-medium">Original Reply</th>
                  <th className="text-left py-3 px-4 font-medium">Follow-up Subject</th>
                  <th className="text-center py-3 px-4 font-medium">Status</th>
                  <th className="text-right py-3 px-4 font-medium">Sent At</th>
                </tr>
              </thead>
              <tbody>
                {logs.length === 0 && (
                  <tr>
                    <td colSpan={5} className="text-center py-10 text-gray-400 text-xs">No follow-up logs yet</td>
                  </tr>
                )}
                {logs.map(log => (
                  <tr key={log.email_id} className="border-b border-gray-50 hover:bg-gray-50/50">
                    <td className="py-3 px-4">
                      <div className="font-medium text-gray-900 truncate max-w-[140px]">{log.influencer_name ?? log.influencer_email}</div>
                      <div className="text-xs text-gray-400">{log.influencer_platform ?? '—'}</div>
                    </td>
                    <td className="py-3 px-4 max-w-[180px]">
                      {log.original_reply ? (
                        <p className="text-xs text-gray-600 line-clamp-2">{log.original_reply}</p>
                      ) : (
                        <span className="text-xs text-gray-300 italic">No reply recorded</span>
                      )}
                    </td>
                    <td className="py-3 px-4 text-gray-700 max-w-[200px] truncate">{log.follow_up_subject}</td>
                    <td className="py-3 px-4 text-center">
                      <StatusBadge status={log.follow_up_status} />
                    </td>
                    <td className="py-3 px-4 text-right text-xs text-gray-400">
                      {log.sent_at ? new Date(log.sent_at).toLocaleDateString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div className="flex items-center justify-between px-6 py-3 border-t border-gray-50 text-xs text-gray-500">
              <span>Page {logsPage} of {totalPages}</span>
              <div className="flex gap-2">
                <button
                  disabled={logsPage <= 1}
                  onClick={() => setLogsPage(p => p - 1)}
                  className="px-3 py-1 border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50"
                >
                  Prev
                </button>
                <button
                  disabled={logsPage >= totalPages}
                  onClick={() => setLogsPage(p => p + 1)}
                  className="px-3 py-1 border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
