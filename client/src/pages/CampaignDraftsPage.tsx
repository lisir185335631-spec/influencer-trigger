import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  draftsApi,
  AngleOption,
  DraftListItem,
  DraftStatus,
  DraftProgressEvent,
  DraftCompletedEvent,
} from '../api/drafts'
import { useWebSocket, WsMessage } from '../hooks/useWebSocket'

const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.hostname}:6002/ws`

// ── Status badges ─────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<DraftStatus, string> = {
  pending:    'bg-gray-100 text-gray-500',
  generating: 'bg-yellow-50 text-yellow-700',
  ready:      'bg-blue-50 text-blue-700',
  edited:     'bg-emerald-50 text-emerald-700',
  failed:     'bg-red-50 text-red-700',
  sending:    'bg-cyan-50 text-cyan-700',
  sent:       'bg-green-50 text-green-700',
  cancelled:  'bg-gray-100 text-gray-400',
}

function StatusBadge({ status }: { status: DraftStatus }) {
  const cls = STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-500'
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {status}
    </span>
  )
}

// ── Edit modal ────────────────────────────────────────────────────────────────

interface EditModalProps {
  draftId: number
  onClose: () => void
  onSaved: () => void
  angles: AngleOption[]
}

function EditModal({ draftId, onClose, onSaved, angles }: EditModalProps) {
  const [subject, setSubject] = useState('')
  const [bodyHtml, setBodyHtml] = useState('')
  const [angleUsed, setAngleUsed] = useState<string | null>(null)
  const [influencerEmail, setInfluencerEmail] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [showRegen, setShowRegen] = useState(false)
  const [regenAngle, setRegenAngle] = useState('')
  const [regenNotes, setRegenNotes] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    setLoading(true)
    draftsApi.get(draftId)
      .then(d => {
        setSubject(d.subject)
        setBodyHtml(d.body_html)
        setAngleUsed(d.angle_used)
        setRegenAngle(d.angle_used || 'friendly')
        // grab influencer email via list endpoint... or just show ID for now
        setInfluencerEmail(`influencer #${d.influencer_id}`)
      })
      .catch(() => setError('Failed to load draft'))
      .finally(() => setLoading(false))
  }, [draftId])

  const handleSave = async () => {
    setSaving(true); setError('')
    try {
      await draftsApi.update(draftId, { subject, body_html: bodyHtml })
      onSaved()
      onClose()
    } catch {
      setError('Save failed')
    } finally {
      setSaving(false)
    }
  }

  const handleRegenerate = async () => {
    setRegenerating(true); setError('')
    try {
      const updated = await draftsApi.regenerate(draftId, {
        angle: regenAngle,
        extra_notes: regenNotes || undefined,
      })
      setSubject(updated.subject)
      setBodyHtml(updated.body_html)
      setAngleUsed(updated.angle_used)
      setShowRegen(false)
      onSaved()
    } catch {
      setError('Regenerate failed')
    } finally {
      setRegenerating(false)
    }
  }

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-xl w-full max-w-3xl max-h-[90vh] overflow-y-auto"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-base font-semibold text-gray-900">编辑草稿</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">×</button>
        </div>

        {loading ? (
          <div className="p-12 text-center text-gray-400 text-sm">加载中…</div>
        ) : (
          <div className="p-6 space-y-4">
            <div className="text-xs text-gray-400">
              收件人 · {influencerEmail} · 当前角度: <span className="font-mono">{angleUsed || '—'}</span>
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1 uppercase tracking-wide">
                主题
              </label>
              <input
                value={subject}
                onChange={e => setSubject(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1 uppercase tracking-wide">
                正文 (HTML)
              </label>
              <textarea
                value={bodyHtml}
                onChange={e => setBodyHtml(e.target.value)}
                rows={12}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <div className="mt-2 border border-gray-100 rounded-lg p-3 bg-gray-50">
                <div className="text-xs font-medium text-gray-500 mb-1">渲染预览</div>
                <div
                  className="text-sm text-gray-800 prose prose-sm max-w-none"
                  dangerouslySetInnerHTML={{ __html: bodyHtml }}
                />
              </div>
            </div>

            {showRegen && (
              <div className="border border-amber-200 bg-amber-50 rounded-lg p-3 space-y-2">
                <div className="text-xs font-medium text-amber-800">重新生成 (LLM)</div>
                <div className="flex items-center gap-2">
                  <select
                    value={regenAngle}
                    onChange={e => setRegenAngle(e.target.value)}
                    className="text-sm border border-gray-200 rounded px-2 py-1 bg-white"
                  >
                    {angles.map(a => (
                      <option key={a.key} value={a.key}>{a.key}</option>
                    ))}
                  </select>
                  <input
                    placeholder="补充说明（可选）"
                    value={regenNotes}
                    onChange={e => setRegenNotes(e.target.value)}
                    className="flex-1 text-sm border border-gray-200 rounded px-2 py-1"
                  />
                </div>
                <div className="text-xs text-amber-700">
                  会覆盖当前内容，且清除"用户已编辑"标记
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleRegenerate}
                    disabled={regenerating}
                    className="text-sm bg-amber-600 text-white px-3 py-1 rounded hover:bg-amber-700 disabled:opacity-40"
                  >
                    {regenerating ? '生成中…' : '执行'}
                  </button>
                  <button
                    onClick={() => setShowRegen(false)}
                    className="text-sm text-gray-500 px-3 py-1 hover:text-gray-700"
                  >
                    取消
                  </button>
                </div>
              </div>
            )}

            {error && <p className="text-sm text-red-500">{error}</p>}
          </div>
        )}

        <div className="px-6 py-3 border-t border-gray-100 flex items-center justify-between bg-gray-50 rounded-b-xl">
          <button
            onClick={() => setShowRegen(s => !s)}
            disabled={loading || regenerating}
            className="text-sm text-amber-700 hover:text-amber-900 disabled:opacity-40"
          >
            {showRegen ? '收起重生' : '重新生成 (LLM)…'}
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5"
            >
              取消
            </button>
            <button
              onClick={handleSave}
              disabled={saving || loading}
              className="text-sm bg-gray-900 text-white px-4 py-1.5 rounded-lg hover:bg-gray-800 disabled:opacity-40"
            >
              {saving ? '保存中…' : '保存'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CampaignDraftsPage() {
  const { t } = useTranslation()
  const { campaignId } = useParams<{ campaignId: string }>()
  const navigate = useNavigate()
  const cid = Number(campaignId)

  const [items, setItems] = useState<DraftListItem[]>([])
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [angles, setAngles] = useState<AngleOption[]>([])
  const [loading, setLoading] = useState(true)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [progress, setProgress] = useState<{ completed: number; total: number; current?: string } | null>(null)

  const load = useCallback(async () => {
    if (!cid) return
    try {
      const resp = await draftsApi.listForCampaign(cid)
      setItems(resp.items)
      setCounts(resp.counts_by_status)
    } catch {
      setError('加载草稿列表失败')
    }
  }, [cid])

  useEffect(() => {
    setLoading(true)
    Promise.all([
      draftsApi.listAngles().then(setAngles).catch(() => {}),
      load(),
    ]).finally(() => setLoading(false))
  }, [cid, load])

  // WebSocket: live progress while drafts are still being generated
  const handleWs = useCallback((msg: WsMessage) => {
    if (msg.event === 'draft:progress') {
      const data = msg.data as DraftProgressEvent
      if (data.campaign_id !== cid) return
      setProgress({
        completed: data.completed,
        total: data.total,
        current: data.current_influencer,
      })
      // refresh list periodically
      if (data.completed % 5 === 0 || data.completed === data.total) {
        load()
      }
    } else if (msg.event === 'draft:completed') {
      const data = msg.data as DraftCompletedEvent
      if (data.campaign_id !== cid) return
      setProgress({ completed: data.total, total: data.total })
      load()
    }
  }, [cid, load])

  useWebSocket(WS_URL, handleWs)

  const totals = useMemo(() => {
    const ready = (counts.ready || 0) + (counts.edited || 0)
    const inflight = (counts.pending || 0) + (counts.generating || 0)
    const failed = counts.failed || 0
    const sent = counts.sent || 0
    const cancelled = counts.cancelled || 0
    const total = items.length
    return { ready, inflight, failed, sent, cancelled, total }
  }, [counts, items])

  const handleRegenerate = async (id: number) => {
    try {
      await draftsApi.regenerate(id, {})
      await load()
    } catch {
      setError('重生失败')
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm('确定删除（取消）这个草稿吗？')) return
    try {
      await draftsApi.remove(id)
      await load()
    } catch {
      setError('删除失败')
    }
  }

  const handleSendAll = async () => {
    if (!cid) return
    if (!confirm(`确定发送 ${totals.ready} 个草稿吗？发送后不可撤回`)) return
    setSending(true); setError('')
    try {
      const resp = await draftsApi.send(cid)
      alert(`已开始发送 ${resp.sendable_drafts} / ${resp.total_drafts}`)
      await load()
    } catch {
      setError('发送失败')
    } finally {
      setSending(false)
    }
  }

  if (loading) {
    return <div className="p-8 text-sm text-gray-400">加载中…</div>
  }

  return (
    <div className="max-w-7xl mx-auto p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <button
            onClick={() => navigate('/emails')}
            className="text-sm text-gray-400 hover:text-gray-700 mb-2"
          >
            ← 返回邮件
          </button>
          <h1 className="text-xl font-semibold text-gray-900">
            草稿审核 · Campaign #{cid}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            review per-recipient personalized drafts before sending
          </p>
        </div>
        <button
          onClick={handleSendAll}
          disabled={sending || totals.ready === 0}
          className="bg-gray-900 text-white text-sm font-medium px-4 py-2 rounded-lg hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {sending ? '发送中…' : `发送 ${totals.ready} 封`}
        </button>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-5 gap-3 mb-6">
        {[
          { label: '总数', value: totals.total, color: 'text-gray-700' },
          { label: '可发送 (ready/edited)', value: totals.ready, color: 'text-blue-600' },
          { label: '生成中', value: totals.inflight, color: 'text-yellow-600' },
          { label: '失败', value: totals.failed, color: 'text-red-600' },
          { label: '已发', value: totals.sent, color: 'text-green-600' },
        ].map((s, i) => (
          <div key={i} className="border border-gray-100 rounded-lg p-3">
            <div className={`text-xl font-semibold ${s.color}`}>{s.value}</div>
            <div className="text-xs text-gray-400 mt-1">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Live progress */}
      {progress && progress.completed < progress.total && (
        <div className="mb-4 p-3 border border-blue-100 bg-blue-50 rounded-lg">
          <div className="flex items-center justify-between text-sm text-blue-700">
            <span>生成中 {progress.completed}/{progress.total}</span>
            {progress.current && <span className="text-xs text-blue-500">{progress.current}</span>}
          </div>
          <div className="mt-2 h-1.5 bg-blue-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all"
              style={{ width: `${(progress.completed / Math.max(1, progress.total)) * 100}%` }}
            />
          </div>
        </div>
      )}

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-100 rounded-lg text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Draft list */}
      <div className="border border-gray-100 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50">
            <tr>
              <th className="text-left px-4 py-2 font-medium text-gray-500">收件人</th>
              <th className="text-left px-4 py-2 font-medium text-gray-500">主题</th>
              <th className="text-left px-4 py-2 font-medium text-gray-500">正文摘要</th>
              <th className="text-left px-4 py-2 font-medium text-gray-500">角度</th>
              <th className="text-left px-4 py-2 font-medium text-gray-500">状态</th>
              <th className="text-right px-4 py-2 font-medium text-gray-500">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {items.map(item => (
              <tr key={item.id} className="hover:bg-gray-50">
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900 text-sm">
                    {item.influencer_name || '—'}
                  </div>
                  <div className="text-xs text-gray-400">{item.influencer_email}</div>
                  <div className="text-xs text-gray-300 mt-0.5">
                    {item.influencer_platform}
                    {item.influencer_followers ? ` · ${item.influencer_followers.toLocaleString()}` : ''}
                  </div>
                </td>
                <td className="px-4 py-3 max-w-xs truncate text-gray-700">{item.subject}</td>
                <td className="px-4 py-3 max-w-md truncate text-xs text-gray-500">
                  {item.body_html_preview}
                </td>
                <td className="px-4 py-3 text-xs font-mono text-gray-500">
                  {item.angle_used || '—'}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={item.status} />
                  {item.edited_by_user && (
                    <span className="ml-1 text-xs text-emerald-600" title="已编辑">✎</span>
                  )}
                  {item.error_message && (
                    <div className="text-xs text-red-500 mt-0.5" title={item.error_message}>
                      ⚠ {item.error_message.slice(0, 40)}…
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-right space-x-2 whitespace-nowrap">
                  <button
                    onClick={() => setEditingId(item.id)}
                    className="text-xs text-blue-600 hover:text-blue-800"
                    disabled={item.status === 'sent' || item.status === 'sending'}
                  >
                    查看 / 编辑
                  </button>
                  <button
                    onClick={() => handleRegenerate(item.id)}
                    className="text-xs text-amber-600 hover:text-amber-800"
                    disabled={['sent', 'sending', 'generating'].includes(item.status)}
                  >
                    重生
                  </button>
                  <button
                    onClick={() => handleDelete(item.id)}
                    className="text-xs text-red-500 hover:text-red-700"
                    disabled={['sent', 'sending'].includes(item.status)}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-400">
                  无草稿
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {editingId !== null && (
        <EditModal
          draftId={editingId}
          onClose={() => setEditingId(null)}
          onSaved={load}
          angles={angles}
        />
      )}
    </div>
  )
}
