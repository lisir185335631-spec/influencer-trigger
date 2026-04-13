import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
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
} from 'lucide-react'
import {
  getInfluencerDetail,
  listTags,
  assignTags,
  addNote,
  createTag,
  deleteTag,
  type InfluencerDetail,
  type TagOut,
} from '../api/influencers'

type TabKey = 'emails' | 'tags' | 'notes' | 'collaborations'

const STATUS_LABELS: Record<string, string> = {
  new: 'New',
  contacted: 'Contacted',
  replied: 'Replied',
  archived: 'Archived',
}

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
            {STATUS_LABELS[inf.status] ?? inf.status}
          </span>
          <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PRIORITY_COLORS[inf.priority] ?? 'bg-gray-100 text-gray-500'}`}>
            {inf.priority}
          </span>
        </div>
      </div>

      {/* Details */}
      <div className="flex flex-col gap-3 text-sm">
        {inf.platform && (
          <Row icon={<span>{PLATFORM_ICONS[inf.platform] ?? '🌐'}</span>} label="Platform" value={inf.platform} />
        )}
        <Row icon={<Mail size={14} />} label="Email" value={inf.email} />
        <Row icon={<Users size={14} />} label="Followers" value={formatNumber(inf.followers)} />
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
          <Row icon={<Briefcase size={14} />} label="Industry" value={inf.industry} />
        )}
        {inf.reply_intent && (
          <Row icon={<CheckCircle size={14} />} label="Intent" value={inf.reply_intent} />
        )}
        <Row icon={<Clock size={14} />} label="Follow-ups" value={String(inf.follow_up_count)} />
        <Row
          icon={<Mail size={14} />}
          label="Last sent"
          value={formatShortDate(inf.last_email_sent_at)}
        />
        <Row
          icon={<Clock size={14} />}
          label="Created"
          value={formatShortDate(inf.created_at)}
        />
      </div>

      {/* Bio */}
      {inf.bio && (
        <div className="pt-3 border-t border-gray-50">
          <p className="text-xs text-gray-400 font-medium uppercase tracking-wide mb-1">Bio</p>
          <p className="text-xs text-gray-600 leading-relaxed">{inf.bio}</p>
        </div>
      )}

      {/* Tags preview */}
      {inf.tags.length > 0 && (
        <div className="pt-3 border-t border-gray-50">
          <p className="text-xs text-gray-400 font-medium uppercase tracking-wide mb-2">Tags</p>
          <div className="flex flex-wrap gap-1">
            {inf.tags.map((t) => (
              <span
                key={t.id}
                className="text-xs px-2 py-0.5 rounded-full text-white font-medium"
                style={{ backgroundColor: t.color }}
              >
                {t.name}
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
            <span>Type: {e.email_type}</span>
            {e.sent_at && <span>Sent: {formatDate(e.sent_at)}</span>}
            {e.opened_at && <span>Opened: {formatDate(e.opened_at)}</span>}
            {e.replied_at && <span>Replied: {formatDate(e.replied_at)}</span>}
            {e.bounced_at && <span className="text-red-400">Bounced: {formatDate(e.bounced_at)}</span>}
          </div>
          {e.reply_content && (
            <div className="mt-3 p-3 bg-green-50 rounded text-xs text-gray-700">
              <p className="text-green-600 font-medium mb-1">Reply from {e.reply_from ?? '—'}</p>
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
  const [saving, setSaving] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newTagName, setNewTagName] = useState('')
  const [newTagColor, setNewTagColor] = useState('#6366f1')
  const assignedIds = new Set(inf.tags.map((t) => t.id))

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
    if (!confirm('Delete this tag? It will be removed from all influencers.')) return
    await deleteTag(tagId)
    onRefresh()
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium text-gray-700">
          Select tags to assign to this influencer
        </p>
        <button
          onClick={() => setCreating(!creating)}
          className="flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-700"
        >
          <Plus size={12} />
          New tag
        </button>
      </div>

      {creating && (
        <div className="flex items-center gap-2 p-3 bg-gray-50 rounded-lg">
          <input
            type="text"
            value={newTagName}
            onChange={(e) => setNewTagName(e.target.value)}
            placeholder="Tag name"
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
            Create
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
        {allTags.length === 0 && <Empty text="No tags yet. Create one above." />}
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
          placeholder="Add a note..."
          rows={3}
          className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:border-indigo-400 resize-none"
        />
        <button
          onClick={handleAdd}
          disabled={saving || !text.trim()}
          className="self-end text-xs bg-indigo-600 text-white px-4 py-1.5 rounded-lg hover:bg-indigo-700 disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Add note'}
        </button>
      </div>

      {inf.notes.length === 0 && <Empty text="No notes yet" />}
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
            {c.budget && <span>Budget: {c.budget}</span>}
            <span>Created: {formatShortDate(c.created_at)}</span>
          </div>
        </div>
      ))}
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
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [inf, setInf] = useState<InfluencerDetail | null>(null)
  const [allTags, setAllTags] = useState<TagOut[]>([])
  const [activeTab, setActiveTab] = useState<TabKey>('emails')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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
      setError('Failed to load influencer')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
  }, [id])

  if (loading) {
    return (
      <div className="p-6 text-sm text-gray-400">Loading…</div>
    )
  }

  if (error || !inf) {
    return (
      <div className="p-6">
        <p className="text-sm text-red-500">{error ?? 'Influencer not found'}</p>
      </div>
    )
  }

  const TABS: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    { key: 'emails', label: 'Emails', icon: <Mail size={14} /> },
    { key: 'tags', label: 'Tags', icon: <Tag size={14} /> },
    { key: 'notes', label: 'Notes', icon: <FileText size={14} /> },
    { key: 'collaborations', label: 'Collaborations', icon: <Briefcase size={14} /> },
  ]

  return (
    <div className="p-6 flex flex-col gap-5 max-w-6xl">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate('/crm')}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800"
        >
          <ArrowLeft size={16} />
          CRM
        </button>
        <span className="text-gray-300">/</span>
        <span className="text-sm text-gray-900 font-medium">
          {inf.nickname ?? inf.email}
        </span>
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
    </div>
  )
}
