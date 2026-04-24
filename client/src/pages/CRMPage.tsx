import { useEffect, useState, useCallback, type FormEvent, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, ExternalLink, Loader2, Pencil, Trash2, X } from 'lucide-react'
import {
  deleteInfluencer,
  listInfluencers,
  updateInfluencer,
  type InfluencerListItem,
  type InfluencerUpdate,
} from '../api/influencers'
import { useWebSocket, type WsMessage } from '../hooks/useWebSocket'
import AvatarBadge from '../components/AvatarBadge'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatFollowers(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function PlatformBadge({ platform }: { platform: string | null }) {
  if (!platform) return <span className="text-gray-400 text-xs">—</span>
  const colors: Record<string, string> = {
    instagram: 'bg-pink-50 text-pink-700',
    youtube: 'bg-red-50 text-red-700',
    tiktok: 'bg-gray-900 text-white',
    twitter: 'bg-sky-50 text-sky-700',
    facebook: 'bg-blue-50 text-blue-700',
  }
  const cls = colors[platform] ?? 'bg-gray-100 text-gray-600'
  return (
    <span className={`inline-block px-1.5 py-0.5 text-[11px] font-medium rounded capitalize ${cls}`}>
      {platform}
    </span>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function CRMPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [items, setItems] = useState<InfluencerListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await listInfluencers({ page, page_size: pageSize })
      // Backend returns items ordered by created_at DESC (newest first), which
      // matches the "real-time sync" narrative — new scraped influencers
      // surface on page 1 automatically.
      setItems(resp.items)
      setTotal(resp.total)
      setTotalPages(Math.max(1, resp.total_pages))
    } catch {
      setItems([])
      setTotal(0)
      setTotalPages(1)
    } finally {
      setLoading(false)
    }
  }, [page, pageSize])

  useEffect(() => { load() }, [load])

  // If pageSize change puts current page past the new last page, step back.
  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  // ── WebSocket: new influencers from scraper land here in real time ─────────
  const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`
  useWebSocket(wsUrl, useCallback((msg: WsMessage) => {
    if (msg.event !== 'influencer:created') return
    const newItem = msg.data as InfluencerListItem
    if (!newItem || typeof newItem.id !== 'number') return
    // Only prepend live when the user is on page 1 — otherwise pagination
    // would break (the bottom item of page 1 would overlap with the top of
    // page 2). Users on other pages will see the new data when they navigate
    // back to page 1 (which triggers a fresh fetch).
    if (page !== 1) {
      setTotal((t) => t + 1)
      return
    }
    setItems((prev) => {
      if (prev.some((r) => r.id === newItem.id)) return prev
      // Prepend + cap length to keep page size stable; the displaced last
      // item has moved to page 2 logically and will appear there on refetch.
      return [newItem, ...prev].slice(0, pageSize)
    })
    setTotal((t) => t + 1)
  }, [page, pageSize]))

  // ── Row actions: edit + delete ──────────────────────────────────────────────
  const [editing, setEditing] = useState<InfluencerListItem | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<InfluencerListItem | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  async function confirmDelete() {
    if (!deleteTarget) return
    const inf = deleteTarget
    setDeletingId(inf.id)
    try {
      await deleteInfluencer(inf.id)
      setDeleteTarget(null)
      // If we just removed the last row on a non-first page, step back one
      // page so the user doesn't land on an empty view.
      if (items.length === 1 && page > 1) {
        setPage((p) => p - 1)
      } else {
        await load()
      }
    } catch {
      setDeleteTarget(null)
      window.alert(t('crm.actions.deleteFailed'))
    } finally {
      setDeletingId(null)
    }
  }

  async function handleSaveEdit(id: number, data: InfluencerUpdate) {
    await updateInfluencer(id, data)
    setEditing(null)
    await load()
  }

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold text-gray-900">{t('crm.title')}</h1>
        <p className="text-xs text-gray-400 mt-1">{t('crm.totalCount', { count: total })}</p>
      </div>

      {loading && items.length === 0 ? (
        <div className="flex items-center justify-center h-64 text-gray-400">
          <Loader2 size={20} className="animate-spin mr-2" />
          <span className="text-sm">{t('crm.loading')}</span>
        </div>
      ) : items.length === 0 ? (
        <div className="flex items-center justify-center h-64 text-gray-400">
          <span className="text-sm">{t('crm.noInfluencers')}</span>
        </div>
      ) : (
        <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/60">
                <th className="px-3 py-3 text-center text-xs font-medium text-gray-500 w-14">{t('crm.table.id')}</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">{t('scrapeDetail.table.name')}</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">{t('scrapeDetail.table.platform')}</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">{t('scrapeDetail.table.email')}</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">{t('scrapeDetail.table.followers')}</th>
                <th className="px-4 py-3 text-center text-xs font-medium text-gray-500">{t('scrapeDetail.table.bio')}</th>
                <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('scrapeDetail.table.relevance')}</th>
                <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase">{t('scrapeDetail.table.matchReason')}</th>
                <th className="px-3 py-3 text-center text-xs font-medium text-gray-500 w-24">{t('crm.table.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {items.map((inf, idx) => (
                <tr
                  key={inf.id}
                  className="transition-colors bg-white hover:bg-gray-50/60 cursor-pointer"
                  onClick={() => navigate(`/crm/${inf.id}`)}
                >
                  <td className="px-3 py-3 text-center text-xs font-mono text-gray-500 align-middle" style={{ verticalAlign: 'middle' }}>
                    {(page - 1) * pageSize + idx + 1}
                  </td>
                  <td className="px-4 py-3 text-left align-middle" style={{ verticalAlign: 'middle' }}>
                    <div className="flex items-center gap-1.5">
                      <AvatarBadge url={inf.avatar_url} name={inf.nickname} size={24} />
                      <span className="text-xs font-medium text-gray-800 truncate max-w-[120px]">
                        {inf.nickname || '—'}
                      </span>
                      {inf.profile_url && (
                        <a
                          href={inf.profile_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-gray-300 hover:text-gray-600 transition-colors shrink-0"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <ExternalLink size={10} />
                        </a>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center align-middle" style={{ verticalAlign: 'middle' }}>
                    <PlatformBadge platform={inf.platform} />
                  </td>
                  <td className="px-4 py-3 text-center text-xs text-gray-700 font-mono align-middle" style={{ verticalAlign: 'middle' }}>
                    {inf.email}
                  </td>
                  <td className="px-4 py-3 text-center text-xs font-medium text-gray-800 align-middle" style={{ verticalAlign: 'middle' }}>
                    {formatFollowers(inf.followers)}
                  </td>
                  <td className="px-4 py-3 text-center text-xs text-gray-400 align-middle whitespace-pre-wrap max-w-[320px]" style={{ verticalAlign: 'middle' }}>
                    {inf.bio || '—'}
                  </td>
                  <td className="px-3 py-2 text-center text-sm align-middle" style={{ verticalAlign: 'middle' }}>
                    {inf.relevance_score != null ? (
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        inf.relevance_score >= 0.7 ? 'bg-green-50 text-green-700' :
                        inf.relevance_score >= 0.4 ? 'bg-yellow-50 text-yellow-700' :
                        'bg-gray-50 text-gray-500'
                      }`}>
                        {(inf.relevance_score * 100).toFixed(0)}%
                      </span>
                    ) : (
                      <span className="text-gray-300">—</span>
                    )}
                  </td>
                  <td
                    className="px-3 py-2 text-center text-sm text-gray-600 align-middle whitespace-pre-wrap max-w-[240px]"
                    style={{ verticalAlign: 'middle' }}
                    title={inf.match_reason || ''}
                  >
                    {inf.match_reason ? inf.match_reason : <span className="text-gray-300">—</span>}
                  </td>
                  <td
                    className="px-3 py-3 text-center align-middle"
                    style={{ verticalAlign: 'middle' }}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <div className="inline-flex items-center gap-1.5">
                      <button
                        onClick={() => setEditing(inf)}
                        className="p-1.5 rounded text-gray-500 hover:bg-gray-100 hover:text-indigo-600 transition-colors"
                        title={t('crm.actions.edit')}
                        aria-label={t('crm.actions.edit')}
                      >
                        <Pencil size={16} />
                      </button>
                      <button
                        onClick={() => setDeleteTarget(inf)}
                        disabled={deletingId === inf.id}
                        className="p-1.5 rounded text-gray-500 hover:bg-red-50 hover:text-red-600 transition-colors disabled:opacity-50 disabled:cursor-wait"
                        title={t('crm.actions.delete')}
                        aria-label={t('crm.actions.delete')}
                      >
                        {deletingId === inf.id ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination footer */}
      {total > 0 && (
        <div className="flex items-center justify-end gap-6 text-xs text-gray-500 pt-2">
          {/* Left: page size selector */}
          <div className="flex items-center gap-2">
            <span>每页</span>
            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1) }}
              className="border border-gray-200 rounded px-2 py-1 text-xs bg-white focus:outline-none focus:border-gray-400 cursor-pointer"
            >
              <option value={10}>10</option>
              <option value={20}>20</option>
            </select>
            <span>条</span>
          </div>

          {/* Middle: page navigator */}
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              ‹ 上一页
            </button>
            {renderPageButtons(page, totalPages, setPage)}
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-2 py-1 rounded hover:bg-gray-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              下一页 ›
            </button>
          </div>

          {/* Right: counters */}
          <div className="text-gray-400">
            共 {total} 条 · 第 {page}/{totalPages} 页
          </div>
        </div>
      )}

      {editing && (
        <EditInfluencerModal
          inf={editing}
          onClose={() => setEditing(null)}
          onSave={(data) => handleSaveEdit(editing.id, data)}
        />
      )}

      {deleteTarget && (
        <ConfirmDeleteModal
          inf={deleteTarget}
          loading={deletingId === deleteTarget.id}
          onCancel={() => setDeleteTarget(null)}
          onConfirm={confirmDelete}
        />
      )}
    </div>
  )
}

// Build a compact page-number list: always show first / last / current ±1
// with '…' collapsing the rest. Keeps the footer scannable even at 100+ pages.
function renderPageButtons(cur: number, total: number, setPage: (n: number) => void) {
  if (total <= 1) return null
  const pages: (number | '...')[] = []
  const add = (n: number) => { if (!pages.includes(n)) pages.push(n) }
  add(1)
  if (cur - 1 > 2) pages.push('...')
  for (let n = Math.max(2, cur - 1); n <= Math.min(total - 1, cur + 1); n++) add(n)
  if (cur + 1 < total - 1) pages.push('...')
  if (total > 1) add(total)
  return pages.map((p, i) =>
    p === '...' ? (
      <span key={`gap-${i}`} className="px-1 text-gray-300">…</span>
    ) : (
      <button
        key={p}
        onClick={() => setPage(p)}
        className={`min-w-[28px] px-2 py-1 rounded transition-colors ${
          p === cur
            ? 'bg-gray-900 text-white'
            : 'hover:bg-gray-100 text-gray-600'
        }`}
      >
        {p}
      </button>
    ),
  )
}

// ── Edit modal ────────────────────────────────────────────────────────────────

const PLATFORM_OPTIONS = ['tiktok', 'instagram', 'youtube', 'twitter', 'facebook', 'other'] as const
const STATUS_OPTIONS = ['new', 'contacted', 'replied', 'archived'] as const
const PRIORITY_OPTIONS = ['high', 'medium', 'low'] as const

function EditInfluencerModal({
  inf,
  onClose,
  onSave,
}: {
  inf: InfluencerListItem
  onClose: () => void
  onSave: (data: InfluencerUpdate) => Promise<void>
}) {
  const { t } = useTranslation()
  const [form, setForm] = useState({
    nickname: inf.nickname ?? '',
    platform: inf.platform ?? '',
    profile_url: inf.profile_url ?? '',
    followers: inf.followers != null ? String(inf.followers) : '',
    industry: inf.industry ?? '',
    bio: inf.bio ?? '',
    status: inf.status ?? 'new',
    priority: inf.priority ?? 'medium',
  })
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  function update<K extends keyof typeof form>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function submit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError(null)
    const payload: InfluencerUpdate = {}
    const trim = (s: string) => s.trim()
    if (trim(form.nickname) !== (inf.nickname ?? '')) payload.nickname = trim(form.nickname)
    if (trim(form.platform) !== (inf.platform ?? '')) payload.platform = trim(form.platform) || undefined
    if (trim(form.profile_url) !== (inf.profile_url ?? '')) payload.profile_url = trim(form.profile_url)
    if (trim(form.industry) !== (inf.industry ?? '')) payload.industry = trim(form.industry)
    if (form.bio !== (inf.bio ?? '')) payload.bio = form.bio
    if (form.status !== inf.status) payload.status = form.status
    if (form.priority !== inf.priority) payload.priority = form.priority
    const followersStr = trim(form.followers)
    const followersNum = followersStr === '' ? null : Number(followersStr)
    const prevFollowers = inf.followers ?? null
    if (followersNum !== prevFollowers && !Number.isNaN(followersNum as number)) {
      payload.followers = followersNum ?? undefined
    }
    try {
      await onSave(payload)
    } catch {
      setError(t('crm.editModal.saveFailed'))
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4"
      onClick={onClose}
    >
      <form
        onClick={(e) => e.stopPropagation()}
        onSubmit={submit}
        className="bg-white rounded-xl shadow-xl w-full max-w-lg max-h-[90vh] overflow-auto"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-900">{t('crm.editModal.title')}</h2>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-700">
            <X size={18} />
          </button>
        </div>

        <div className="p-5 grid grid-cols-2 gap-4">
          <Field label={t('crm.editModal.nickname')}>
            <input
              type="text"
              value={form.nickname}
              onChange={(e) => update('nickname', e.target.value)}
              className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:border-indigo-400"
            />
          </Field>
          <Field label={t('crm.editModal.platform')}>
            <select
              value={form.platform}
              onChange={(e) => update('platform', e.target.value)}
              className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 bg-white focus:outline-none focus:border-indigo-400"
            >
              <option value="">{t('crm.editModal.platformNone')}</option>
              {PLATFORM_OPTIONS.map((p) => (
                <option key={p} value={p}>{p}</option>
              ))}
            </select>
          </Field>
          <Field label={t('crm.editModal.profileUrl')} span={2}>
            <input
              type="url"
              value={form.profile_url}
              onChange={(e) => update('profile_url', e.target.value)}
              className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:border-indigo-400"
            />
          </Field>
          <Field label={t('crm.editModal.followers')}>
            <input
              type="number"
              min={0}
              value={form.followers}
              onChange={(e) => update('followers', e.target.value)}
              className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:border-indigo-400"
            />
          </Field>
          <Field label={t('crm.editModal.industry')}>
            <input
              type="text"
              value={form.industry}
              onChange={(e) => update('industry', e.target.value)}
              className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:border-indigo-400"
            />
          </Field>
          <Field label={t('crm.editModal.status')}>
            <select
              value={form.status}
              onChange={(e) => update('status', e.target.value)}
              className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 bg-white focus:outline-none focus:border-indigo-400"
            >
              {STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {t(`crm.editModal.status${s.charAt(0).toUpperCase() + s.slice(1)}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('crm.editModal.priority')}>
            <select
              value={form.priority}
              onChange={(e) => update('priority', e.target.value)}
              className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 bg-white focus:outline-none focus:border-indigo-400"
            >
              {PRIORITY_OPTIONS.map((p) => (
                <option key={p} value={p}>
                  {t(`crm.editModal.priority${p.charAt(0).toUpperCase() + p.slice(1)}`)}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('crm.editModal.bio')} span={2}>
            <textarea
              value={form.bio}
              onChange={(e) => update('bio', e.target.value)}
              rows={4}
              className="w-full text-sm border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:border-indigo-400 resize-none"
            />
          </Field>
        </div>

        {error && (
          <div className="px-5 pb-2 text-xs text-red-500">{error}</div>
        )}

        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-100 bg-gray-50/50">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 rounded transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-1 px-4 py-1.5 text-xs bg-gray-900 text-white rounded hover:bg-gray-800 disabled:opacity-50 transition-colors"
          >
            {saving && <Loader2 size={12} className="animate-spin" />}
            {saving ? t('crm.editModal.saving') : t('common.save')}
          </button>
        </div>
      </form>
    </div>
  )
}

function Field({ label, span = 1, children }: { label: string; span?: 1 | 2; children: ReactNode }) {
  return (
    <label className={`flex flex-col gap-1 ${span === 2 ? 'col-span-2' : ''}`}>
      <span className="text-xs text-gray-500 font-medium">{label}</span>
      {children}
    </label>
  )
}

// ── Delete confirmation modal ─────────────────────────────────────────────────

function ConfirmDeleteModal({
  inf,
  loading,
  onCancel,
  onConfirm,
}: {
  inf: InfluencerListItem
  loading: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useTranslation()
  const name = inf.nickname || inf.email || String(inf.id)

  // Esc closes the modal unless a delete is in flight.
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
            <div className="shrink-0 w-10 h-10 rounded-full bg-red-50 flex items-center justify-center">
              <AlertTriangle size={20} className="text-red-600" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-base font-semibold text-gray-900 mb-1">
                {t('crm.actions.confirmTitle')}
              </h2>
              <p className="text-sm text-gray-500 leading-relaxed">
                {t('crm.actions.deleteConfirm', { name })}
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
            className="inline-flex items-center gap-1 px-4 py-1.5 text-xs bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 transition-colors"
          >
            {loading && <Loader2 size={12} className="animate-spin" />}
            {t('crm.actions.delete')}
          </button>
        </div>
      </div>
    </div>
  )
}
