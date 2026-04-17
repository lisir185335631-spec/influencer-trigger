import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Search,
  ChevronLeft,
  ChevronRight,
  Download,
  Tag,
  Archive,
  ChevronDown,
  X,
} from 'lucide-react'
import {
  listInfluencers,
  listTags,
  batchUpdateInfluencers,
  exportInfluencers,
  updateInfluencer,
  type InfluencerListItem,
  type TagOut,
} from '../api/influencers'

// ── constants ────────────────────────────────────────────────────────────────

const STATUS_COLORS: Record<string, string> = {
  new: 'bg-gray-100 text-gray-600',
  contacted: 'bg-blue-50 text-blue-600',
  replied: 'bg-green-50 text-green-600',
  archived: 'bg-yellow-50 text-yellow-600',
}

const PRIORITY_COLORS: Record<string, string> = {
  high: 'bg-red-50 text-red-600',
  medium: 'bg-amber-50 text-amber-600',
  low: 'bg-gray-100 text-gray-500',
}

const PRIORITY_DOT: Record<string, string> = {
  high: 'bg-red-500',
  medium: 'bg-amber-400',
  low: 'bg-gray-400',
}

const PLATFORM_ICONS: Record<string, string> = {
  tiktok: '🎵',
  instagram: '📸',
  youtube: '▶️',
  twitter: '🐦',
  facebook: '📘',
  other: '🌐',
}


const REPLY_INTENT_COLORS: Record<string, string> = {
  interested: 'bg-green-50 text-green-700',
  pricing: 'bg-blue-50 text-blue-700',
  declined: 'bg-red-50 text-red-600',
  auto_reply: 'bg-gray-100 text-gray-500',
  irrelevant: 'bg-gray-100 text-gray-500',
}

// ── helpers ───────────────────────────────────────────────────────────────────

function formatFollowers(n: number | null): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}

function formatDate(d: string | null): string {
  if (!d) return '—'
  return new Date(d).toLocaleDateString('zh-CN')
}

// ── tag multi-select dropdown ─────────────────────────────────────────────────

function TagMultiSelect({
  allTags,
  selected,
  onChange,
}: {
  allTags: TagOut[]
  selected: number[]
  onChange: (ids: number[]) => void
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [])

  function toggle(id: number) {
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id])
  }

  const label =
    selected.length === 0
      ? t('crm.tagSelect.allTags')
      : selected.length === 1
      ? (allTags.find((tag) => tag.id === selected[0])?.name ?? '1 tag')
      : `${selected.length} tags`

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1 text-sm border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-indigo-400 text-gray-600 bg-white hover:bg-gray-50 min-w-[110px] justify-between"
      >
        <span>{label}</span>
        <ChevronDown size={13} className="text-gray-400 shrink-0" />
      </button>
      {open && (
        <div className="absolute z-20 mt-1 bg-white border border-gray-100 rounded-xl shadow-lg py-1 min-w-[160px] max-h-60 overflow-y-auto">
          {allTags.length === 0 && (
            <p className="text-xs text-gray-400 px-3 py-2">{t('crm.tagSelect.noTags')}</p>
          )}
          {allTags.map((tag) => (
            <label
              key={tag.id}
              className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 cursor-pointer"
            >
              <input
                type="checkbox"
                className="rounded"
                checked={selected.includes(tag.id)}
                onChange={() => toggle(tag.id)}
              />
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: tag.color }}
              />
              <span className="text-sm text-gray-700">{tag.name}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

// ── batch tag modal ───────────────────────────────────────────────────────────

function BatchTagModal({
  allTags,
  onConfirm,
  onClose,
}: {
  allTags: TagOut[]
  onConfirm: (tagIds: number[]) => void
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [selected, setSelected] = useState<number[]>([])

  function toggle(id: number) {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div className="bg-white rounded-2xl shadow-xl p-6 w-80">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-900">{t('crm.tagModal.title')}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={16} />
          </button>
        </div>
        <div className="space-y-1 max-h-52 overflow-y-auto mb-4">
          {allTags.map((tag) => (
            <label
              key={tag.id}
              className="flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-50 cursor-pointer"
            >
              <input
                type="checkbox"
                className="rounded"
                checked={selected.includes(tag.id)}
                onChange={() => toggle(tag.id)}
              />
              <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: tag.color }} />
              <span className="text-sm text-gray-700">{tag.name}</span>
            </label>
          ))}
          {allTags.length === 0 && (
            <p className="text-sm text-gray-400 py-2 text-center">{t('crm.tagModal.noTags')}</p>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 text-sm border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={() => { if (selected.length) onConfirm(selected) }}
            disabled={selected.length === 0}
            className="flex-1 px-4 py-2 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {t('common.apply')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── priority dropdown ─────────────────────────────────────────────────────────

function PriorityDropdown({
  value,
  onChange,
}: {
  value: string
  onChange: (p: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [])

  const options = ['high', 'medium', 'low']

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen((o) => !o) }}
        className={`flex items-center gap-1 text-xs px-2 py-0.5 rounded-full font-medium cursor-pointer ${PRIORITY_COLORS[value] ?? 'bg-gray-100 text-gray-500'}`}
      >
        <span className={`w-1.5 h-1.5 rounded-full ${PRIORITY_DOT[value] ?? 'bg-gray-400'}`} />
        {value}
        <ChevronDown size={10} className="opacity-60" />
      </button>
      {open && (
        <div className="absolute z-30 right-0 mt-1 bg-white border border-gray-100 rounded-xl shadow-lg py-1 min-w-[90px]">
          {options.map((p) => (
            <button
              key={p}
              onClick={(e) => { e.stopPropagation(); onChange(p); setOpen(false) }}
              className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs hover:bg-gray-50 ${p === value ? 'font-semibold' : ''}`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${PRIORITY_DOT[p] ?? 'bg-gray-400'}`} />
              <span className="capitalize">{p}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ── replied view ──────────────────────────────────────────────────────────────

function RepliedView() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [items, setItems] = useState<InfluencerListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(true)
  const [updatingId, setUpdatingId] = useState<number | null>(null)

  useEffect(() => { load() }, [page]) // eslint-disable-line react-hooks/exhaustive-deps

  async function load() {
    setLoading(true)
    try {
      const res = await listInfluencers({
        page,
        page_size: 20,
        status: 'replied',
        sort_by: 'priority',
      })
      setItems(res.items)
      setTotal(res.total)
      setTotalPages(res.total_pages)
    } finally {
      setLoading(false)
    }
  }

  async function handlePriorityChange(id: number, priority: string) {
    setUpdatingId(id)
    try {
      await updateInfluencer(id, { priority })
      setItems((prev) => prev.map((inf) => inf.id === id ? { ...inf, priority } : inf))
    } finally {
      setUpdatingId(null)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-gray-400">{t('crm.replied.subtitle', { count: total })}</p>

      <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('crm.replied.table.influencer')}</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('crm.replied.table.platform')}</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('crm.replied.table.followers')}</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('crm.replied.table.replyIntent')}</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('crm.replied.table.replySummary')}</th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('crm.replied.table.priority')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">{t('crm.replied.loading')}</td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">
                  {t('crm.replied.noReplied')}
                </td>
              </tr>
            )}
            {!loading && items.map((inf) => (
              <tr key={inf.id} className="hover:bg-gray-50 transition-colors">
                <td
                  className="px-4 py-3 cursor-pointer"
                  onClick={() => navigate(`/crm/${inf.id}`)}
                >
                  <p className="font-medium text-gray-900 hover:text-indigo-600 transition-colors">
                    {inf.nickname ?? '—'}
                  </p>
                  <p className="text-xs text-gray-400">{inf.email}</p>
                </td>
                <td className="px-4 py-3 text-gray-600">
                  {inf.platform ? (
                    <span>
                      {PLATFORM_ICONS[inf.platform] ?? '🌐'}{' '}
                      <span className="capitalize">{inf.platform}</span>
                    </span>
                  ) : '—'}
                </td>
                <td className="px-4 py-3 text-gray-600">{formatFollowers(inf.followers)}</td>
                <td className="px-4 py-3">
                  {inf.reply_intent ? (
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${REPLY_INTENT_COLORS[inf.reply_intent] ?? 'bg-gray-100 text-gray-500'}`}>
                      {t(`common.intent.${inf.reply_intent}`, { defaultValue: inf.reply_intent })}
                    </span>
                  ) : '—'}
                </td>
                <td className="px-4 py-3 text-xs text-gray-500 max-w-xs">
                  {inf.reply_summary ? (
                    <span className="line-clamp-2">{inf.reply_summary}</span>
                  ) : '—'}
                </td>
                <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                  {updatingId === inf.id ? (
                    <span className="text-xs text-gray-400">{t('crm.replied.saving')}</span>
                  ) : (
                    <PriorityDropdown
                      value={inf.priority}
                      onChange={(p) => handlePriorityChange(inf.id, p)}
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-gray-500">
          <span>{t('common.pageOf', { current: page, total: totalPages })}</span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="flex items-center gap-1 px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={14} />
              {t('common.prev')}
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="flex items-center gap-1 px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {t('common.next')}
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── main page ─────────────────────────────────────────────────────────────────

export default function CRMPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()

  // tab
  const [tab, setTab] = useState<'all' | 'replied'>('all')

  // data
  const [items, setItems] = useState<InfluencerListItem[]>([])
  const [allTags, setAllTags] = useState<TagOut[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(true)

  // filters
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [platformFilter, setPlatformFilter] = useState('')
  const [tagFilter, setTagFilter] = useState<number[]>([])
  const [followersMin, setFollowersMin] = useState('')
  const [followersMax, setFollowersMax] = useState('')
  const [industryFilter, setIndustryFilter] = useState('')
  const [replyIntentFilter, setReplyIntentFilter] = useState('')

  // selection
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [batchTagOpen, setBatchTagOpen] = useState(false)
  const [batchLoading, setBatchLoading] = useState(false)

  // debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])

  // reset page on filter change
  useEffect(() => {
    setPage(1)
    setSelected(new Set())
  }, [debouncedSearch, statusFilter, platformFilter, tagFilter, followersMin, followersMax, industryFilter, replyIntentFilter])

  // load data (only in "all" tab)
  useEffect(() => {
    if (tab === 'all') load()
  }, [page, debouncedSearch, statusFilter, platformFilter, tagFilter, followersMin, followersMax, industryFilter, replyIntentFilter, tab]) // eslint-disable-line react-hooks/exhaustive-deps

  // load tags once
  useEffect(() => {
    listTags().then(setAllTags).catch(() => {})
  }, [])

  async function load() {
    setLoading(true)
    try {
      const res = await listInfluencers({
        page,
        page_size: 20,
        search: debouncedSearch || undefined,
        status: statusFilter || undefined,
        platform: platformFilter || undefined,
        tag_ids: tagFilter.length ? tagFilter : undefined,
        followers_min: followersMin ? parseInt(followersMin) : undefined,
        followers_max: followersMax ? parseInt(followersMax) : undefined,
        industry: industryFilter || undefined,
        reply_intent: replyIntentFilter || undefined,
      })
      setItems(res.items)
      setTotal(res.total)
      setTotalPages(res.total_pages)
    } finally {
      setLoading(false)
    }
  }

  // ── selection helpers ──────────────────────────────────────────────────────

  const allPageSelected = items.length > 0 && items.every((i) => selected.has(i.id))

  function toggleSelectAll() {
    if (allPageSelected) {
      setSelected((prev) => {
        const next = new Set(prev)
        items.forEach((i) => next.delete(i.id))
        return next
      })
    } else {
      setSelected((prev) => {
        const next = new Set(prev)
        items.forEach((i) => next.add(i.id))
        return next
      })
    }
  }

  function toggleRow(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) { next.delete(id) } else { next.add(id) }
      return next
    })
  }

  // ── batch actions ──────────────────────────────────────────────────────────

  async function handleBatchArchive() {
    if (!selected.size) return
    setBatchLoading(true)
    try {
      await batchUpdateInfluencers({ influencer_ids: [...selected], action: 'archive' })
      setSelected(new Set())
      await load()
    } finally {
      setBatchLoading(false)
    }
  }

  async function handleBatchTag(tagIds: number[]) {
    setBatchLoading(true)
    try {
      await batchUpdateInfluencers({ influencer_ids: [...selected], action: 'assign_tags', tag_ids: tagIds })
      setBatchTagOpen(false)
      setSelected(new Set())
      await load()
    } finally {
      setBatchLoading(false)
    }
  }

  async function handleExport() {
    const blob = await exportInfluencers({
      status: statusFilter || undefined,
      platform: platformFilter || undefined,
      search: debouncedSearch || undefined,
      tag_ids: tagFilter.length ? tagFilter : undefined,
      followers_min: followersMin ? parseInt(followersMin) : undefined,
      followers_max: followersMax ? parseInt(followersMax) : undefined,
      industry: industryFilter || undefined,
      reply_intent: replyIntentFilter || undefined,
    })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'influencers.csv'
    a.click()
    URL.revokeObjectURL(url)
  }

  // ── render ─────────────────────────────────────────────────────────────────

  return (
    <div className="p-6 flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">{t('crm.title')}</h1>
          {tab === 'all' && (
            <p className="text-sm text-gray-400 mt-0.5">
              {t('crm.totalCount', { count: total })}
            </p>
          )}
        </div>
        {tab === 'all' && (
          <button
            onClick={handleExport}
            className="flex items-center gap-1.5 text-sm border border-gray-200 rounded-lg px-3 py-1.5 hover:bg-gray-50 text-gray-600"
          >
            <Download size={14} />
            {t('crm.exportCsv')}
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex gap-0 border-b border-gray-100">
        <button
          onClick={() => setTab('all')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === 'all'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          {t('crm.tabAll')}
        </button>
        <button
          onClick={() => setTab('replied')}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === 'replied'
              ? 'border-indigo-600 text-indigo-600'
              : 'border-transparent text-gray-500 hover:text-gray-700'
          }`}
        >
          {t('crm.tabReplied')}
        </button>
      </div>

      {/* Replied tab */}
      {tab === 'replied' && <RepliedView />}

      {/* All tab */}
      {tab === 'all' && (
        <>
          {/* Filters */}
          <div className="flex flex-wrap gap-2.5">
            {/* Search */}
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('crm.search')}
                className="pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-indigo-400 w-48"
              />
            </div>

            {/* Platform */}
            <select
              value={platformFilter}
              onChange={(e) => setPlatformFilter(e.target.value)}
              className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-indigo-400 text-gray-600"
            >
              <option value="">{t('crm.allPlatforms')}</option>
              <option value="tiktok">{t('common.platform.tiktok')}</option>
              <option value="instagram">{t('common.platform.instagram')}</option>
              <option value="youtube">{t('common.platform.youtube')}</option>
              <option value="twitter">{t('common.platform.twitter')}</option>
              <option value="facebook">{t('common.platform.facebook')}</option>
              <option value="other">{t('common.platform.other')}</option>
            </select>

            {/* Status */}
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-indigo-400 text-gray-600"
            >
              <option value="">{t('crm.allStatuses')}</option>
              <option value="new">{t('common.status.new')}</option>
              <option value="contacted">{t('common.status.contacted')}</option>
              <option value="replied">{t('common.status.replied')}</option>
              <option value="archived">{t('common.status.archived')}</option>
            </select>

            {/* Tags multi-select */}
            <TagMultiSelect allTags={allTags} selected={tagFilter} onChange={setTagFilter} />

            {/* Followers range */}
            <div className="flex items-center gap-1">
              <input
                type="number"
                value={followersMin}
                onChange={(e) => setFollowersMin(e.target.value)}
                placeholder={t('crm.followersMin')}
                className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-indigo-400 w-28 text-gray-600"
              />
              <span className="text-gray-400 text-sm">–</span>
              <input
                type="number"
                value={followersMax}
                onChange={(e) => setFollowersMax(e.target.value)}
                placeholder={t('crm.followersMax')}
                className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-indigo-400 w-20 text-gray-600"
              />
            </div>

            {/* Industry */}
            <input
              type="text"
              value={industryFilter}
              onChange={(e) => setIndustryFilter(e.target.value)}
              placeholder={t('crm.industry')}
              className="text-sm border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:border-indigo-400 w-32 text-gray-600"
            />

            {/* Reply intent */}
            <select
              value={replyIntentFilter}
              onChange={(e) => setReplyIntentFilter(e.target.value)}
              className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-indigo-400 text-gray-600"
            >
              <option value="">{t('crm.allIntents')}</option>
              <option value="interested">{t('common.intent.interested')}</option>
              <option value="pricing">{t('common.intent.pricing')}</option>
              <option value="declined">{t('common.intent.declined')}</option>
              <option value="auto_reply">{t('common.intent.auto_reply')}</option>
              <option value="irrelevant">{t('common.intent.irrelevant')}</option>
            </select>
          </div>

          {/* Table */}
          <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="px-4 py-3 w-8">
                    <input
                      type="checkbox"
                      className="rounded"
                      checked={allPageSelected}
                      onChange={toggleSelectAll}
                    />
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {t('crm.table.influencer')}
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {t('crm.table.platform')}
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {t('crm.table.email')}
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {t('crm.table.followers')}
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {t('crm.table.status')}
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {t('crm.table.tags')}
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {t('crm.table.priority')}
                  </th>
                  <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                    {t('crm.table.lastEmail')}
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {loading && (
                  <tr>
                    <td colSpan={9} className="px-4 py-8 text-center text-sm text-gray-400">
                      {t('crm.loading')}
                    </td>
                  </tr>
                )}
                {!loading && items.length === 0 && (
                  <tr>
                    <td colSpan={9} className="px-4 py-8 text-center text-sm text-gray-400">
                      {t('crm.noInfluencers')}
                    </td>
                  </tr>
                )}
                {!loading &&
                  items.map((inf) => (
                    <tr
                      key={inf.id}
                      className={`hover:bg-gray-50 transition-colors ${selected.has(inf.id) ? 'bg-indigo-50/40' : ''}`}
                    >
                      <td className="px-4 py-3 w-8" onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          className="rounded"
                          checked={selected.has(inf.id)}
                          onChange={() => toggleRow(inf.id)}
                        />
                      </td>
                      <td
                        className="px-4 py-3 cursor-pointer"
                        onClick={() => navigate(`/crm/${inf.id}`)}
                      >
                        <p className="font-medium text-gray-900 hover:text-indigo-600 transition-colors">
                          {inf.nickname ?? '—'}
                        </p>
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {inf.platform ? (
                          <span>
                            {PLATFORM_ICONS[inf.platform] ?? '🌐'}{' '}
                            <span className="capitalize">{inf.platform}</span>
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-500 text-xs">{inf.email}</td>
                      <td className="px-4 py-3 text-gray-600">
                        {formatFollowers(inf.followers)}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLORS[inf.status] ?? 'bg-gray-100 text-gray-600'}`}
                        >
                          {inf.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {inf.tags.slice(0, 3).map((tag) => (
                            <span
                              key={tag.id}
                              className="text-xs px-1.5 py-0.5 rounded-full text-white"
                              style={{ backgroundColor: tag.color }}
                            >
                              {tag.name}
                            </span>
                          ))}
                          {inf.tags.length > 3 && (
                            <span className="text-xs text-gray-400">+{inf.tags.length - 3}</span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`text-xs px-2 py-0.5 rounded-full font-medium ${PRIORITY_COLORS[inf.priority] ?? 'bg-gray-100 text-gray-500'}`}
                        >
                          {inf.priority}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400">
                        {formatDate(inf.last_email_sent_at)}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-gray-500">
              <span>
                {t('common.pageOf', { current: page, total: totalPages })}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="flex items-center gap-1 px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  <ChevronLeft size={14} />
                  {t('common.prev')}
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="flex items-center gap-1 px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {t('common.next')}
                  <ChevronRight size={14} />
                </button>
              </div>
            </div>
          )}

          {/* Batch action bar */}
          {selected.size > 0 && (
            <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-30 flex items-center gap-3 bg-gray-900 text-white px-5 py-3 rounded-2xl shadow-xl">
              <span className="text-sm font-medium">{t('crm.batch.selected', { count: selected.size })}</span>
              <div className="w-px h-4 bg-white/20" />
              <button
                onClick={() => setBatchTagOpen(true)}
                disabled={batchLoading}
                className="flex items-center gap-1.5 text-sm hover:text-indigo-300 transition-colors disabled:opacity-50"
              >
                <Tag size={14} />
                {t('crm.batch.assignTags')}
              </button>
              <button
                onClick={handleBatchArchive}
                disabled={batchLoading}
                className="flex items-center gap-1.5 text-sm hover:text-yellow-300 transition-colors disabled:opacity-50"
              >
                <Archive size={14} />
                {t('crm.batch.archive')}
              </button>
              <button
                onClick={handleExport}
                disabled={batchLoading}
                className="flex items-center gap-1.5 text-sm hover:text-green-300 transition-colors disabled:opacity-50"
              >
                <Download size={14} />
                {t('crm.batch.exportCsv')}
              </button>
              <div className="w-px h-4 bg-white/20" />
              <button
                onClick={() => setSelected(new Set())}
                className="text-white/60 hover:text-white"
              >
                <X size={14} />
              </button>
            </div>
          )}

          {/* Batch tag modal */}
          {batchTagOpen && (
            <BatchTagModal
              allTags={allTags}
              onConfirm={handleBatchTag}
              onClose={() => setBatchTagOpen(false)}
            />
          )}
        </>
      )}
    </div>
  )
}
