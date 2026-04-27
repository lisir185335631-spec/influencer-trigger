import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  ArrowLeft,
  Mail,
  Globe,
  Users,
  Tag,
  FileText,
  Briefcase,
  Clock,
  Plus,
  X,
  CheckCircle,
  Circle,
  Pause,
  Play,
  RotateCcw,
  Loader2,
} from 'lucide-react'
import {
  getInfluencerDetail,
  listTags,
  assignTags,
  addNote,
  createTag,
  deleteTag,
  updateInfluencer,
  type InfluencerDetail,
  type InfluencerUpdate,
  type TagOut,
} from '../api/influencers'
import { useAuthContext } from '../stores/AuthContext'

type TabKey = 'emails' | 'tags' | 'notes' | 'collaborations'


const STATUS_COLORS: Record<string, string> = {
  new: 'bg-gray-100 text-gray-600',
  contacted: 'bg-blue-50 text-blue-600',
  replied: 'bg-green-50 text-green-600',
  archived: 'bg-yellow-50 text-yellow-600',
}

const PRIORITY_COLORS: Record<string, string> = {
  high: 'bg-red-50 text-red-600',
  medium: 'bg-orange-50 text-orange-600',
  low: 'bg-gray-100 text-gray-500',
}

const EMAIL_STATUS_COLORS: Record<string, string> = {
  pending: 'text-gray-400',
  sent: 'text-blue-500',
  delivered: 'text-blue-600',
  opened: 'text-indigo-600',
  clicked: 'text-violet-600',
  replied: 'text-green-600',
  bounced: 'text-red-500',
  failed: 'text-red-600',
}

const PLATFORM_ICONS: Record<string, string> = {
  tiktok: '🎵',
  instagram: '📸',
  youtube: '▶️',
  twitter: '🐦',
  facebook: '📘',
  other: '🌐',
}

function formatNumber(n: number | null): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function formatDate(d: string | null): string {
  if (!d) return '—'
  return new Date(d).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatShortDate(d: string | null): string {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('zh-CN')
}

// ── Left info card ────────────────────────────────────────────────────────────

function InfoCard({ inf }: { inf: InfluencerDetail }) {
  const { t } = useTranslation()
  const initials = inf.nickname
    ? inf.nickname.slice(0, 2).toUpperCase()
    : inf.email.slice(0, 2).toUpperCase()

  return (
    <div className="bg-white border border-gray-100 rounded-xl p-6 flex flex-col gap-4">
      {/* Avatar */}
      <div className="flex flex-col items-center gap-3 pb-4 border-b border-gray-50">
        <div className="w-16 h-16 rounded-full bg-indigo-100 flex items-center justify-center text-xl font-bold text-indigo-600">
          {initials}
        </div>
        <div className="text-center">
          <p className="font-semibold text-gray-900 text-base leading-tight">
            {inf.nickname ?? '—'}
          </p>
          <p className="text-xs text-gray-400 mt-0.5">{inf.email}</p>
        </div>
        <div className="flex gap-2">
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLORS[inf.status] ?? 'bg-gray-100 text-gray-600'}`}>
            {t(`common.status.${inf.status}`, { defaultValue: inf.status })}
          </span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PRIORITY_COLORS[inf.priority] ?? 'bg-gray-100 text-gray-500'}`}>
            {inf.priority}
          </span>
        </div>
      </div>

      {/* Details */}
      <div className="flex flex-col gap-3 text-sm">
        {inf.platform && (
          <Row icon={<span>{PLATFORM_ICONS[inf.platform] ?? '🌐'}</span>} label={t('influencer.info.platform')} value={inf.platform} />
        )}
        <Row icon={<Mail size={14} />} label={t('influencer.info.email')} value={inf.email} />
        <Row icon={<Users size={14} />} label={t('influencer.info.followers')} value={formatNumber(inf.followers)} />
        {inf.profile_url && (
          <div className="flex items-start gap-2 text-gray-600">
            <Globe size={14} className="mt-0.5 shrink-0 text-gray-400" />
            <a
              href={inf.profile_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-indigo-500 hover:underline truncate text-xs"
            >
              {inf.profile_url}
            </a>
          </div>
        )}
        {inf.industry && (
          <Row icon={<Briefcase size={14} />} label={t('influencer.info.industry')} value={inf.industry} />
        )}
        {inf.reply_intent && (
          <Row icon={<CheckCircle size={14} />} label={t('influencer.info.intent')} value={inf.reply_intent} />
        )}
        <Row icon={<Clock size={14} />} label={t('influencer.info.followUps')} value={String(inf.follow_up_count)} />
        <Row
          icon={<Mail size={14} />}
          label={t('influencer.info.lastSent')}
          value={formatShortDate(inf.last_email_sent_at)}
        />
        <Row
          icon={<Clock size={14} />}
          label={t('influencer.info.created')}
          value={formatShortDate(inf.created_at)}
        />
      </div>

      {/* Bio */}
      {inf.bio && (
        <div className="pt-3 border-t border-gray-50">
          <p className="text-xs text-gray-400 font-medium uppercase tracking-wide mb-1">{t('influencer.bio')}</p>
          <p className="text-xs text-gray-600 leading-relaxed">{inf.bio}</p>
        </div>
      )}

      {/* Tags preview */}
      {inf.tags.length > 0 && (
        <div className="pt-3 border-t border-gray-50">
          <p className="text-xs text-gray-400 font-medium uppercase tracking-wide mb-2">{t('influencer.tags.title')}</p>
          <div className="flex flex-wrap gap-1">
            {inf.tags.map((tag) => (
              <span
                key={tag.id}
                className="text-xs px-2 py-0.5 rounded-full text-white font-medium"
                style={{ backgroundColor: tag.color }}
              >
                {tag.name}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function Row({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 text-gray-600">
      <span className="text-gray-400 shrink-0">{icon}</span>
      <span className="text-gray-400 text-xs w-16 shrink-0">{label}</span>
      <span className="text-gray-800 text-xs truncate">{value}</span>
    </div>
  )
}

// ── Email timeline tab ────────────────────────────────────────────────────────

function EmailsTab({ inf }: { inf: InfluencerDetail }) {
  const { t } = useTranslation()
  if (inf.emails.length === 0) {
    return <Empty text="No emails yet" />
  }

  return (
    <div className="flex flex-col gap-3">
      {inf.emails.map((e) => (
        <div key={e.id} className="border border-gray-100 rounded-lg p-4">
          <div className="flex items-center justify-between gap-2 mb-2">
            <p className="text-sm font-medium text-gray-900 truncate">{e.subject}</p>
            <span className={`text-xs font-medium shrink-0 ${EMAIL_STATUS_COLORS[e.status] ?? 'text-gray-500'}`}>
              {e.status}
            </span>
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-gray-400">
            <span>{t('influencer.emails.type', { type: e.email_type })}</span>
            {e.sent_at && <span>{t('influencer.emails.sent', { date: formatDate(e.sent_at) })}</span>}
            {e.opened_at && <span>{t('influencer.emails.opened', { date: formatDate(e.opened_at) })}</span>}
            {e.replied_at && <span>{t('influencer.emails.replied', { date: formatDate(e.replied_at) })}</span>}
            {e.bounced_at && <span className="text-red-400">{t('influencer.emails.bounced', { date: formatDate(e.bounced_at) })}</span>}
          </div>
          {e.reply_content && (
            <div className="mt-3 p-3 bg-green-50 rounded text-xs text-gray-700">
              <p className="text-green-600 font-medium mb-1">{t('influencer.emails.replyFrom', { name: e.reply_from ?? '—' })}</p>
              <p className="whitespace-pre-wrap">{e.reply_content}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ── Tags management tab ───────────────────────────────────────────────────────

function TagsTab({
  inf,
  allTags,
  onRefresh,
}: {
  inf: InfluencerDetail
  allTags: TagOut[]
  onRefresh: () => void
}) {
  const { t } = useTranslation()
  const [saving, setSaving] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newTagName, setNewTagName] = useState('')
  const [newTagColor, setNewTagColor] = useState('#6366f1')
  const assignedIds = new Set(inf.tags.map((tag) => tag.id))

  async function handleToggle(tagId: number) {
    const next = assignedIds.has(tagId)
      ? [...assignedIds].filter((id) => id !== tagId)
      : [...assignedIds, tagId]
    setSaving(true)
    try {
      await assignTags(inf.id, next)
      onRefresh()
    } finally {
      setSaving(false)
    }
  }

  async function handleCreateTag() {
    if (!newTagName.trim()) return
    setSaving(true)
    try {
      await createTag(newTagName.trim(), newTagColor)
      setNewTagName('')
      setCreating(false)
      onRefresh()
    } finally {
      setSaving(false)
    }
  }

  async function handleDeleteTag(tagId: number) {
    if (!confirm(t('influencer.tags.deleteConfirm'))) return
    await deleteTag(tagId)
    onRefresh()
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-700">
          {t('influencer.tags.selectHint')}
        </p>
        <button
          onClick={() => setCreating(!creating)}
          className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-700"
        >
          <Plus size={12} />
          {t('influencer.tags.newTag')}
        </button>
      </div>

      {creating && (
        <div className="flex items-center gap-2 p-3 bg-gray-50 rounded-lg">
          <input
            type="text"
            value={newTagName}
            onChange={(e) => setNewTagName(e.target.value)}
            placeholder={t('influencer.tags.tagPlaceholder')}
            className="flex-1 text-sm border border-gray-200 rounded px-2 py-1 focus:outline-none focus:border-indigo-400"
          />
          <input
            type="color"
            value={newTagColor}
            onChange={(e) => setNewTagColor(e.target.value)}
            className="w-8 h-7 rounded cursor-pointer border border-gray-200"
          />
          <button
            onClick={handleCreateTag}
            disabled={saving || !newTagName.trim()}
            className="text-xs bg-indigo-600 text-white px-3 py-1 rounded hover:bg-indigo-700 disabled:opacity-50"
          >
            {t('influencer.tags.create')}
          </button>
          <button
            onClick={() => setCreating(false)}
            className="text-gray-400 hover:text-gray-600"
          >
            <X size={14} />
          </button>
        </div>
      )}

      <div className="flex flex-col gap-1">
        {allTags.length === 0 && <Empty text={t('influencer.tags.noTags')} />}
        {allTags.map((tag) => {
          const assigned = assignedIds.has(tag.id)
          return (
            <div
              key={tag.id}
              className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-gray-50 group"
            >
              <button
                onClick={() => handleToggle(tag.id)}
                disabled={saving}
                className="flex items-center gap-3 flex-1 text-left"
              >
                {assigned ? (
                  <CheckCircle size={16} className="text-indigo-500 shrink-0" />
                ) : (
                  <Circle size={16} className="text-gray-300 shrink-0" />
                )}
                <span
                  className="text-xs px-2 py-0.5 rounded-full text-white font-medium"
                  style={{ backgroundColor: tag.color }}
                >
                  {tag.name}
                </span>
              </button>
              <button
                onClick={() => handleDeleteTag(tag.id)}
                className="text-gray-200 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <X size={13} />
              </button>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Notes tab ─────────────────────────────────────────────────────────────────

function NotesTab({ inf, onRefresh }: { inf: InfluencerDetail; onRefresh: () => void }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)

  async function handleAdd() {
    if (!text.trim()) return
    setSaving(true)
    try {
      await addNote(inf.id, text.trim())
      setText('')
      onRefresh()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={t('influencer.notes.placeholder')}
          rows={3}
          className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-400 resize-none"
        />
        <button
          onClick={handleAdd}
          disabled={saving || !text.trim()}
          className="self-end text-xs bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? t('influencer.notes.saving') : t('influencer.notes.addNote')}
        </button>
      </div>

      {inf.notes.length === 0 && <Empty text={t('influencer.notes.noNotes')} />}
      {inf.notes.map((note) => (
        <div key={note.id} className="border border-gray-100 rounded-lg p-4">
          <p className="text-sm text-gray-800 whitespace-pre-wrap">{note.content}</p>
          <p className="text-xs text-gray-400 mt-2">{formatDate(note.created_at)}</p>
        </div>
      ))}
    </div>
  )
}

// ── Collaborations tab ────────────────────────────────────────────────────────

const COLLAB_STATUS_COLORS: Record<string, string> = {
  negotiating: 'bg-yellow-50 text-yellow-600',
  signed: 'bg-blue-50 text-blue-600',
  completed: 'bg-green-50 text-green-600',
  cancelled: 'bg-gray-100 text-gray-500',
}

function CollaborationsTab({ inf }: { inf: InfluencerDetail }) {
  const { t } = useTranslation()
  if (inf.collaborations.length === 0) {
    return <Empty text="No collaboration records yet" />
  }

  return (
    <div className="flex flex-col gap-3">
      {inf.collaborations.map((c) => (
        <div key={c.id} className="border border-gray-100 rounded-lg p-4">
          <div className="flex items-center justify-between mb-2">
            <p className="text-sm font-medium text-gray-900">{c.title}</p>
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${COLLAB_STATUS_COLORS[c.status] ?? 'bg-gray-100 text-gray-500'}`}>
              {c.status}
            </span>
          </div>
          {c.description && (
            <p className="text-xs text-gray-600 mb-2">{c.description}</p>
          )}
          <div className="flex flex-wrap gap-3 text-xs text-gray-400">
            {c.budget && <span>{t('influencer.collaborations.budget', { budget: c.budget })}</span>}
            <span>{t('influencer.collaborations.created', { date: formatShortDate(c.created_at) })}</span>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Restart confirmation modal ────────────────────────────────────────────────
// In-app replacement for the previous window.confirm() — same look & feel
// as the CRMPage delete-confirmation dialog so the destructive surfaces
// stay consistent. ESC and outside-click both cancel (unless the action
// is in flight, in which case both are blocked to prevent the user from
// dismissing the dialog while the PATCH is mid-air).

function ConfirmRestartModal({
  inf,
  loading,
  onCancel,
  onConfirm,
}: {
  inf: InfluencerDetail
  loading: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useTranslation()
  const name = inf.nickname || inf.email || String(inf.id)

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !loading) onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [loading, onCancel])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4"
      onClick={() => !loading && onCancel()}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="alertdialog"
        aria-modal="true"
        className="bg-white rounded-xl shadow-xl w-full max-w-md"
      >
        <div className="p-5">
          <div className="flex gap-3">
            <div className="shrink-0 w-10 h-10 rounded-full bg-amber-50 flex items-center justify-center">
              <RotateCcw size={20} className="text-amber-600" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-base font-semibold text-gray-900 mb-1">
                {t('influencer.actions.restartConfirmTitle', { name })}
              </h2>
              {/* whitespace-pre-line preserves the \n line breaks in the
                  i18n string — same source text as the old confirm()
                  payload, but rendered with proper paragraph spacing. */}
              <p className="text-sm text-gray-500 leading-relaxed whitespace-pre-line">
                {t('influencer.actions.confirmRestart')}
              </p>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-100 bg-gray-50/50">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 rounded transition-colors disabled:opacity-50"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className="inline-flex items-center gap-1 px-4 py-1.5 text-xs bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-50 transition-colors"
          >
            {loading && <Loader2 size={12} className="animate-spin" />}
            {t('influencer.actions.restart')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function Empty({ text }: { text: string }) {
  return (
    <div className="py-10 text-center text-sm text-gray-400 border border-dashed border-gray-200 rounded-lg">
      {text}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function InfluencerDetailPage() {
  const { t } = useTranslation()
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  // Role gate: "重启从头" mutates follow_up_count which the backend now
  // restricts to manager+ (see /influencers/{id} PATCH). Hide the button
  // for operators rather than show-then-403 to keep the UX clean.
  const { role } = useAuthContext()
  const canResetCadence = role === 'admin' || role === 'manager'
  const [inf, setInf] = useState<InfluencerDetail | null>(null)
  const [allTags, setAllTags] = useState<TagOut[]>([])
  const [activeTab, setActiveTab] = useState<TabKey>('emails')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  // Tracks which quick-action is in flight; null = idle. Used to disable
  // all 3 buttons during a PATCH so a fast double-click doesn't dispatch
  // duplicate writes (and to give a visible disabled state).
  const [actionPending, setActionPending] = useState<'pause' | 'resume' | 'restart' | null>(null)
  // "Restart from beginning" is destructive enough to warrant an in-app
  // confirmation modal instead of a native browser confirm() (which can't
  // be styled and renders \n inconsistently across browsers).
  const [showRestartConfirm, setShowRestartConfirm] = useState(false)

  async function loadData() {
    if (!id) return
    try {
      const [detail, tags] = await Promise.all([
        getInfluencerDetail(Number(id)),
        listTags(),
      ])
      setInf(detail)
      setAllTags(tags)
    } catch {
      setError(t('influencer.loadFailed'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [id])

  // Quick-action handlers — pause / resume / restart the auto follow-up
  // cadence for this single influencer. All three reuse the existing
  // PATCH /influencers/{id} endpoint; backend's update_influencer applies
  // partial setattr so we only send the fields we want to change.
  // pause / resume execute immediately; restart routes through the
  // confirmation modal first (see runStatusUpdate for the actual PATCH).
  function handleStatusAction(action: 'pause' | 'resume' | 'restart') {
    if (!inf || actionPending) return
    if (action === 'restart') {
      setShowRestartConfirm(true)
      return
    }
    void runStatusUpdate(action)
  }

  // Execute the PATCH for any of the three actions. Extracted from the
  // entry point so the confirmation modal can call it directly after the
  // user clicks "Confirm restart".
  async function runStatusUpdate(action: 'pause' | 'resume' | 'restart') {
    if (!inf) return
    let payload: InfluencerUpdate
    if (action === 'pause') {
      // status=archived: follow_up_service skips this row on next scan
      payload = { status: 'archived' }
    } else if (action === 'resume') {
      // status=contacted: re-enters the cadence at the current
      // follow_up_count (so phase-2 progress is preserved)
      payload = { status: 'contacted' }
    } else {
      // restart: status=new + counter=0; user must re-pick this lead in
      // the SendPanel to actually trigger the next initial outreach
      payload = { status: 'new', follow_up_count: 0 }
    }
    setActionPending(action)
    try {
      await updateInfluencer(inf.id, payload)
      await loadData()
    } catch {
      window.alert(t('influencer.actions.actionFailed'))
    } finally {
      setActionPending(null)
    }
  }

  if (loading) {
    return (
      <div className="p-6 text-sm text-gray-400">{t('influencer.loading')}</div>
    )
  }

  if (error || !inf) {
    return (
      <div className="p-6">
        <p className="text-sm text-red-500">{error ?? t('influencer.notFound')}</p>
      </div>
    )
  }

  const TABS: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    { key: 'emails', label: t('influencer.tabEmails'), icon: <Mail size={14} /> },
    { key: 'tags', label: t('influencer.tabTags'), icon: <Tag size={14} /> },
    { key: 'notes', label: t('influencer.tabNotes'), icon: <FileText size={14} /> },
    { key: 'collaborations', label: t('influencer.tabCollaborations'), icon: <Briefcase size={14} /> },
  ]

  return (
    <div className="p-6 flex flex-col gap-5 max-w-6xl">
      {/* Header — breadcrumb + manual-intervention quick actions */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate('/crm')}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
        >
          <ArrowLeft size={16} />
          {t('influencer.breadcrumb')}
        </button>
        <span className="text-gray-300">/</span>
        <span className="text-sm text-gray-900 font-medium">
          {inf.nickname ?? inf.email}
        </span>

        {/* Right-aligned quick actions. Buttons render conditionally so the
            available action always matches the influencer's current status —
            avoids "pause" when there's nothing to pause, etc. */}
        <div className="ml-auto flex items-center gap-2">
          {inf.status === 'contacted' && (
            <button
              onClick={() => handleStatusAction('pause')}
              disabled={actionPending !== null}
              className="flex items-center gap-1 px-3 py-1.5 text-xs text-amber-700 bg-amber-50 hover:bg-amber-100 border border-amber-200 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title={t('influencer.actions.pauseFollowUpHint')}
            >
              <Pause size={13} />
              {t('influencer.actions.pauseFollowUp')}
            </button>
          )}
          {inf.status === 'archived' && (
            <button
              onClick={() => handleStatusAction('resume')}
              disabled={actionPending !== null}
              className="flex items-center gap-1 px-3 py-1.5 text-xs text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title={t('influencer.actions.resumeFollowUpHint')}
            >
              <Play size={13} />
              {t('influencer.actions.resumeFollowUp')}
            </button>
          )}
          {/* Restart resets follow_up_count → manager+ only (backend
              enforces same rule via 403). Operators can still
              pause/resume because those only change `status`. */}
          {canResetCadence && (
            <button
              onClick={() => handleStatusAction('restart')}
              disabled={actionPending !== null}
              className="flex items-center gap-1 px-3 py-1.5 text-xs text-gray-600 bg-gray-50 hover:bg-gray-100 border border-gray-200 rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title={t('influencer.actions.restartHint')}
            >
              <RotateCcw size={13} />
              {t('influencer.actions.restart')}
            </button>
          )}
        </div>
      </div>

      <div className="flex gap-5 items-start">
        {/* Left info card */}
        <div className="w-64 shrink-0">
          <InfoCard inf={inf} />
        </div>

        {/* Right tabs */}
        <div className="flex-1 min-w-0 bg-white border border-gray-100 rounded-xl">
          {/* Tab bar */}
          <div className="flex border-b border-gray-100 px-4">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={[
                  'flex items-center gap-1.5 px-3 py-3.5 text-sm border-b-2 transition-colors',
                  activeTab === tab.key
                    ? 'border-indigo-500 text-indigo-600 font-medium'
                    : 'border-transparent text-gray-500 hover:text-gray-700',
                ].join(' ')}
              >
                {tab.icon}
                {tab.label}
                {tab.key === 'emails' && inf.emails.length > 0 && (
                  <span className="ml-1 text-xs bg-gray-100 text-gray-500 rounded-full px-1.5 py-0.5">
                    {inf.emails.length}
                  </span>
                )}
                {tab.key === 'notes' && inf.notes.length > 0 && (
                  <span className="ml-1 text-xs bg-gray-100 text-gray-500 rounded-full px-1.5 py-0.5">
                    {inf.notes.length}
                  </span>
                )}
                {tab.key === 'collaborations' && inf.collaborations.length > 0 && (
                  <span className="ml-1 text-xs bg-gray-100 text-gray-500 rounded-full px-1.5 py-0.5">
                    {inf.collaborations.length}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="p-5">
            {activeTab === 'emails' && <EmailsTab inf={inf} />}
            {activeTab === 'tags' && (
              <TagsTab inf={inf} allTags={allTags} onRefresh={loadData} />
            )}
            {activeTab === 'notes' && <NotesTab inf={inf} onRefresh={loadData} />}
            {activeTab === 'collaborations' && <CollaborationsTab inf={inf} />}
          </div>
        </div>
      </div>

      {/* Restart confirmation modal — destructive cadence reset, deserves
          an in-app modal rather than a styling-poor browser confirm() */}
      {showRestartConfirm && (
        <ConfirmRestartModal
          inf={inf}
          loading={actionPending === 'restart'}
          onCancel={() => setShowRestartConfirm(false)}
          onConfirm={async () => {
            setShowRestartConfirm(false)
            await runStatusUpdate('restart')
          }}
        />
      )}
    </div>
  )
}
