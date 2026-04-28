import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { X, Loader2 } from 'lucide-react'
import DOMPurify from 'dompurify'
import {
  draftsApi,
  AngleOption,
  DraftListItem,
  DraftStatus,
  DraftProgressEvent,
  DraftCompletedEvent,
} from '../api/drafts'
import { useWebSocket, WsMessage } from '../hooks/useWebSocket'
import { WS_URL } from '../api/websocket'

// Defence-in-depth: backend already sanitizes via nh3 on save, but we
// double-sanitize here in case content was inserted by a different path
// or the backend sanitize ever regresses. DOMPurify is the de-facto
// browser-side standard; the same library is used in TemplatesPage.
const SANITIZE_CONFIG = {
  ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'b', 'i', 'u', 'a', 'ul', 'ol', 'li', 'blockquote', 'span'],
  ALLOWED_ATTR: ['href', 'title'],
  ALLOWED_URI_REGEXP: /^(?:https?|mailto):/i,
}

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
  /** The list-row item being edited. We accept the whole row (rather than
   * just an id) because the parent page already has the influencer name +
   * email loaded from /campaigns/:id/drafts; passing it down avoids a
   * second round trip to fetch metadata that the page already has. */
  item: DraftListItem
  onClose: () => void
  onSaved: () => void
  angles: AngleOption[]
}

function EditModal({ item, onClose, onSaved, angles }: EditModalProps) {
  const { t } = useTranslation()
  const draftId = item.id
  const [subject, setSubject] = useState('')
  const [bodyHtml, setBodyHtml] = useState('')
  const [angleUsed, setAngleUsed] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [showRegen, setShowRegen] = useState(false)
  const [regenAngle, setRegenAngle] = useState('')
  const [regenNotes, setRegenNotes] = useState('')
  const [error, setError] = useState('')

  // Display label sourced from the list-row props so the modal opens
  // showing the right person immediately, before the GET completes.
  const recipientLabel = `${item.influencer_name || '—'} <${item.influencer_email}>`

  useEffect(() => {
    setLoading(true)
    draftsApi.get(draftId)
      .then(d => {
        setSubject(d.subject)
        setBodyHtml(d.body_html)
        setAngleUsed(d.angle_used)
        setRegenAngle(d.angle_used || 'friendly')
      })
      .catch(() => setError(t('drafts.edit.loadFailed')))
      .finally(() => setLoading(false))
  }, [draftId])

  const handleSave = async () => {
    setSaving(true); setError('')
    try {
      await draftsApi.update(draftId, { subject, body_html: bodyHtml })
      onSaved()
      onClose()
    } catch {
      setError(t('drafts.edit.saveFailed'))
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
      setError(t('drafts.edit.regenFailed'))
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
          <h3 className="text-base font-semibold text-gray-900">{t('drafts.edit.title')}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700">×</button>
        </div>

        {loading ? (
          <div className="p-12 text-center text-gray-400 text-sm">{t('drafts.edit.loading')}</div>
        ) : (
          <div className="p-6 space-y-4">
            <div className="text-xs text-gray-400">
              {t('drafts.edit.recipient')} · {recipientLabel} · {t('drafts.edit.currentAngle')}: <span className="font-mono">{angleUsed || '—'}</span>
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1 uppercase tracking-wide">
                {t('drafts.edit.subject')}
              </label>
              <input
                value={subject}
                onChange={e => setSubject(e.target.value)}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>

            <div>
              <label className="block text-xs font-medium text-gray-500 mb-1 uppercase tracking-wide">
                {t('drafts.edit.bodyHtml')}
              </label>
              <textarea
                value={bodyHtml}
                onChange={e => setBodyHtml(e.target.value)}
                rows={12}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <div className="mt-2 border border-gray-100 rounded-lg p-3 bg-gray-50">
                <div className="text-xs font-medium text-gray-500 mb-1">{t('drafts.edit.preview')}</div>
                <div
                  className="text-sm text-gray-800 prose prose-sm max-w-none"
                  dangerouslySetInnerHTML={{
                    __html: DOMPurify.sanitize(bodyHtml, SANITIZE_CONFIG),
                  }}
                />
              </div>
            </div>

            {showRegen && (
              <div className="border border-amber-200 bg-amber-50 rounded-lg p-3 space-y-2">
                <div className="text-xs font-medium text-amber-800">{t('drafts.edit.regenSection')}</div>
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
                    placeholder={t('drafts.edit.regenNotesPlaceholder')}
                    value={regenNotes}
                    onChange={e => setRegenNotes(e.target.value)}
                    className="flex-1 text-sm border border-gray-200 rounded px-2 py-1"
                  />
                </div>
                <div className="text-xs text-amber-700">
                  {t('drafts.edit.regenWarn')}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={handleRegenerate}
                    disabled={regenerating}
                    className="text-sm bg-amber-600 text-white px-3 py-1 rounded hover:bg-amber-700 disabled:opacity-40"
                  >
                    {regenerating ? t('drafts.edit.regenerating') : t('drafts.edit.regenExecute')}
                  </button>
                  <button
                    onClick={() => setShowRegen(false)}
                    className="text-sm text-gray-500 px-3 py-1 hover:text-gray-700"
                  >
                    {t('drafts.edit.regenCancel')}
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
            {showRegen ? t('drafts.edit.regenToggleHide') : t('drafts.edit.regenToggleShow')}
          </button>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5"
            >
              {t('drafts.edit.cancel')}
            </button>
            <button
              onClick={handleSave}
              disabled={saving || loading}
              className="text-sm bg-gray-900 text-white px-4 py-1.5 rounded-lg hover:bg-gray-800 disabled:opacity-40"
            >
              {saving ? t('drafts.edit.saving') : t('drafts.edit.save')}
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
  const [editingItem, setEditingItem] = useState<DraftListItem | null>(null)
  const [sending, setSending] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)
  // Send-flow result kept inside the confirm modal so a single dialog
  // walks through confirm → sending → success/error without a second popup.
  const [sendResult, setSendResult] = useState<{ sent: number; total: number } | null>(null)
  const [sendError, setSendError] = useState('')
  const [error, setError] = useState('')
  const [progress, setProgress] = useState<{ completed: number; total: number } | null>(null)

  // Route param can be NaN (`/campaigns/abc/drafts`) or 0; normalise to a
  // boolean validity flag so the page can render a clean error rather than
  // silently firing API calls with a bogus id.
  const cidValid = Number.isFinite(cid) && cid > 0

  const load = useCallback(async () => {
    if (!cidValid) return
    try {
      const resp = await draftsApi.listForCampaign(cid)
      setItems(resp.items)
      setCounts(resp.counts_by_status)
    } catch (e: unknown) {
      // Distinguish 404 (campaign doesn't exist or doesn't belong to user)
      // from generic load failure so the UX can suggest navigating back.
      const status = (e as { response?: { status?: number } })?.response?.status
      if (status === 404 || status === 403) {
        setError(t('drafts.review.noAccess'))
      } else {
        setError(t('drafts.review.loadFailed'))
      }
    }
  }, [cid, cidValid, t])

  useEffect(() => {
    setLoading(true)
    Promise.all([
      draftsApi.listAngles().then(setAngles).catch(() => {}),
      load(),
    ]).finally(() => setLoading(false))
  }, [cid, cidValid, load])

  // WebSocket: live progress while drafts are still being generated
  const handleWs = useCallback((msg: WsMessage) => {
    if (msg.event === 'draft:progress') {
      const data = msg.data as DraftProgressEvent
      if (data.campaign_id !== cid) return
      setProgress({
        completed: data.completed,
        total: data.total,
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
      setError(t('drafts.review.regenerateFailed'))
    }
  }

  const handleDelete = async (id: number) => {
    if (!confirm(t('drafts.review.deleteConfirm'))) return
    try {
      await draftsApi.remove(id)
      await load()
    } catch {
      setError(t('drafts.review.deleteFailed'))
    }
  }

  // Top "send N" button just opens the confirm modal — actual API call
  // lives in handleSendConfirmed so the user has a clear cancel/confirm
  // choice with project-styled UI instead of the OS confirm() dialog.
  const handleSendAll = () => {
    if (!cid || totals.ready === 0) return
    setSendResult(null)
    setSendError('')
    setConfirmOpen(true)
  }

  const handleSendConfirmed = async () => {
    if (!cid) return
    setSending(true)
    setSendResult(null)
    setSendError('')
    try {
      const resp = await draftsApi.send(cid)
      setSendResult({ sent: resp.sendable_drafts, total: resp.total_drafts })
      await load()
    } catch (e: unknown) {
      // Surface the backend's actual rejection reason (e.g. 400 "No drafts
      // in 'ready' or 'edited' state to send") instead of a generic line.
      // Falls back to the generic hint if no detail is present (network
      // error, 5xx without body, etc.).
      const detail = (e as { response?: { data?: { detail?: string } } })
        ?.response?.data?.detail
      setSendError(detail || t('drafts.review.sendFailedHint'))
    } finally {
      setSending(false)
    }
  }

  const closeConfirm = () => {
    if (sending) return
    setConfirmOpen(false)
    setSendResult(null)
    setSendError('')
  }

  if (!cidValid) {
    return (
      <div className="p-8 max-w-xl">
        <div className="border border-red-100 bg-red-50 rounded-lg p-4">
          <div className="text-sm font-medium text-red-700 mb-1">{t('drafts.review.invalidIdTitle')}</div>
          <div className="text-xs text-red-600 mb-3">
            {t('drafts.review.invalidIdHint')}
          </div>
          <button
            onClick={() => navigate('/emails')}
            className="text-xs bg-red-600 text-white px-3 py-1.5 rounded hover:bg-red-700"
          >
            {t('drafts.review.backToEmails')}
          </button>
        </div>
      </div>
    )
  }

  if (loading) {
    return <div className="p-8 text-sm text-gray-400">{t('drafts.review.loading')}</div>
  }

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <button
            onClick={() => navigate('/emails')}
            className="text-sm text-gray-400 hover:text-gray-700 mb-2"
          >
            {t('drafts.review.back')}
          </button>
          <h1 className="text-xl font-semibold text-gray-900">
            {t('drafts.review.title', { id: cid })}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {t('drafts.review.subtitle')}
          </p>
        </div>
        <button
          onClick={handleSendAll}
          disabled={sending || totals.ready === 0}
          className="bg-gray-900 text-white text-sm font-medium px-4 py-2 rounded-lg hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {sending ? t('drafts.review.sending') : t('drafts.review.sendButton', { count: totals.ready })}
        </button>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-5 gap-3 mb-6">
        {[
          { label: t('drafts.review.summary.total'), value: totals.total, color: 'text-gray-700' },
          { label: t('drafts.review.summary.ready'), value: totals.ready, color: 'text-blue-600' },
          { label: t('drafts.review.summary.inflight'), value: totals.inflight, color: 'text-yellow-600' },
          { label: t('drafts.review.summary.failed'), value: totals.failed, color: 'text-red-600' },
          { label: t('drafts.review.summary.sent'), value: totals.sent, color: 'text-green-600' },
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
            <span>{t('drafts.review.live', { completed: progress.completed, total: progress.total })}</span>
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
              <th className="text-center px-4 py-2 font-medium text-gray-500 w-16">{t('drafts.review.table.id')}</th>
              <th className="text-center px-4 py-2 font-medium text-gray-500">{t('drafts.review.table.recipient')}</th>
              <th className="text-center px-4 py-2 font-medium text-gray-500">{t('drafts.review.table.subject')}</th>
              <th className="text-center px-4 py-2 font-medium text-gray-500">{t('drafts.review.table.preview')}</th>
              <th className="text-center px-4 py-2 font-medium text-gray-500">{t('drafts.review.table.angle')}</th>
              <th className="text-center px-4 py-2 font-medium text-gray-500">{t('drafts.review.table.status')}</th>
              <th className="text-center px-4 py-2 font-medium text-gray-500">{t('drafts.review.table.actions')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {items.map((item, index) => (
              <tr key={item.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-center text-xs font-mono text-gray-500 tabular-nums">
                  {index + 1}
                </td>
                <td className="px-4 py-3 text-center">
                  <div className="font-medium text-gray-900 text-sm">
                    {item.influencer_name || '—'}
                  </div>
                  <div className="text-xs text-gray-400">{item.influencer_email}</div>
                  <div className="text-xs text-gray-300 mt-0.5">
                    {item.influencer_platform}
                    {item.influencer_followers ? ` · ${item.influencer_followers.toLocaleString()}` : ''}
                  </div>
                </td>
                <td className="px-4 py-3 text-center text-gray-700 whitespace-pre-wrap break-words">{item.subject}</td>
                <td className="px-4 py-3 text-center text-xs text-gray-500 whitespace-pre-wrap break-words">
                  {item.body_html_preview}
                </td>
                <td className="px-4 py-3 text-center text-xs font-mono text-gray-500">
                  {item.angle_used || '—'}
                </td>
                <td className="px-4 py-3 text-center">
                  <StatusBadge status={item.status} />
                  {item.edited_by_user && (
                    <span className="ml-1 text-xs text-emerald-600" title={t('drafts.review.edited')}>✎</span>
                  )}
                  {item.error_message?.includes('static fallback') && (
                    <span
                      className="ml-1 text-xs text-amber-600"
                      title={t('drafts.review.fallbackHint')}
                    >
                      ⚙
                    </span>
                  )}
                  {item.error_message && !item.error_message.includes('static fallback') && (
                    <div className="text-xs text-red-500 mt-0.5 whitespace-pre-wrap break-words">
                      ⚠ {item.error_message}
                    </div>
                  )}
                </td>
                <td className="px-4 py-3 text-center space-x-2 whitespace-nowrap">
                  <button
                    onClick={() => setEditingItem(item)}
                    className="text-xs text-blue-600 hover:text-blue-800"
                    disabled={item.status === 'sent' || item.status === 'sending'}
                  >
                    {t('drafts.review.table.edit')}
                  </button>
                  <button
                    onClick={() => handleRegenerate(item.id)}
                    className="text-xs text-amber-600 hover:text-amber-800"
                    disabled={['sent', 'sending', 'generating'].includes(item.status)}
                  >
                    {t('drafts.review.table.regenerate')}
                  </button>
                  <button
                    onClick={() => handleDelete(item.id)}
                    className="text-xs text-red-500 hover:text-red-700"
                    disabled={['sent', 'sending'].includes(item.status)}
                  >
                    {t('drafts.review.table.delete')}
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-sm text-gray-400">
                  {t('drafts.review.empty')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {editingItem !== null && (
        <EditModal
          item={editingItem}
          onClose={() => setEditingItem(null)}
          onSaved={load}
          angles={angles}
        />
      )}

      {/* Send-all modal — state machine: confirm → sending → success/error.
          A single dialog walks the entire flow so we never stack a second
          popup on top (replaces both the OS confirm() and the alert() that
          previously fired after the API resolved). */}
      {confirmOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
          onClick={closeConfirm}
        >
          <div
            className="bg-white rounded-xl shadow-2xl w-full max-w-md mx-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 pt-6 pb-4 border-b border-gray-100">
              <h2 className="text-base font-semibold text-gray-900">
                {sendResult
                  ? t('drafts.review.sendSuccessTitle')
                  : sendError
                    ? t('drafts.review.sendFailed')
                    : t('drafts.review.confirmTitle')}
              </h2>
              <button
                onClick={closeConfirm}
                disabled={sending}
                className="text-gray-400 hover:text-gray-600 transition-colors disabled:opacity-50"
                aria-label={t('common.cancel')}
              >
                <X size={16} />
              </button>
            </div>
            <div className="px-6 py-5 text-sm text-gray-600 whitespace-pre-wrap break-words">
              {sendResult
                ? sendResult.sent < sendResult.total
                  ? t('drafts.review.sendStartedPartial', {
                      sent: sendResult.sent,
                      skipped: sendResult.total - sendResult.sent,
                    })
                  : t('drafts.review.sendStarted', {
                      sent: sendResult.sent,
                      total: sendResult.total,
                    })
                : sendError
                  ? sendError
                  : t('drafts.review.sendConfirm', { count: totals.ready })}
            </div>
            <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-100">
              {sendResult || sendError ? (
                <button
                  onClick={closeConfirm}
                  className="px-4 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition-colors"
                >
                  {t('common.close')}
                </button>
              ) : (
                <>
                  <button
                    onClick={closeConfirm}
                    disabled={sending}
                    className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 transition-colors disabled:opacity-50"
                  >
                    {t('common.cancel')}
                  </button>
                  <button
                    onClick={handleSendConfirmed}
                    disabled={sending}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors"
                  >
                    {sending && <Loader2 size={13} className="animate-spin" />}
                    {sending
                      ? t('drafts.review.sending')
                      : t('drafts.review.sendButton', { count: totals.ready })}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
