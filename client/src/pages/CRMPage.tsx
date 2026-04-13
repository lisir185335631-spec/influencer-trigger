import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, ChevronLeft, ChevronRight } from 'lucide-react'
import { listInfluencers, type InfluencerListItem } from '../api/influencers'

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

const PLATFORM_ICONS: Record<string, string> = {
  tiktok: '🎵',
  instagram: '📸',
  youtube: '▶️',
  twitter: '🐦',
  facebook: '📘',
  other: '🌐',
}

export default function CRMPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<InfluencerListItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [platformFilter, setPlatformFilter] = useState('')
  const [loading, setLoading] = useState(true)

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300)
    return () => clearTimeout(t)
  }, [search])

  useEffect(() => {
    setPage(1)
  }, [debouncedSearch, statusFilter, platformFilter])

  useEffect(() => {
    load()
  }, [page, debouncedSearch, statusFilter, platformFilter])

  async function load() {
    setLoading(true)
    try {
      const res = await listInfluencers({
        page,
        page_size: 20,
        search: debouncedSearch || undefined,
        status: statusFilter || undefined,
        platform: platformFilter || undefined,
      })
      setItems(res.items)
      setTotal(res.total)
      setTotalPages(res.total_pages)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="p-6 flex flex-col gap-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-gray-900">CRM</h1>
          <p className="text-sm text-gray-400 mt-0.5">
            {total} influencer{total !== 1 ? 's' : ''} total
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or email…"
            className="pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:border-indigo-400 w-56"
          />
        </div>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-indigo-400 text-gray-600"
        >
          <option value="">All statuses</option>
          <option value="new">New</option>
          <option value="contacted">Contacted</option>
          <option value="replied">Replied</option>
          <option value="archived">Archived</option>
        </select>

        <select
          value={platformFilter}
          onChange={(e) => setPlatformFilter(e.target.value)}
          className="text-sm border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:border-indigo-400 text-gray-600"
        >
          <option value="">All platforms</option>
          <option value="tiktok">TikTok</option>
          <option value="instagram">Instagram</option>
          <option value="youtube">YouTube</option>
          <option value="twitter">Twitter</option>
          <option value="facebook">Facebook</option>
          <option value="other">Other</option>
        </select>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                Influencer
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                Platform
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                Followers
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                Status
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                Priority
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                Tags
              </th>
              <th className="text-left px-4 py-3 text-xs font-medium text-gray-500 uppercase tracking-wide">
                Last Email
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {loading && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-400">
                  Loading…
                </td>
              </tr>
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-400">
                  No influencers found
                </td>
              </tr>
            )}
            {!loading &&
              items.map((inf) => (
                <tr
                  key={inf.id}
                  onClick={() => navigate(`/crm/${inf.id}`)}
                  className="hover:bg-gray-50 cursor-pointer transition-colors"
                >
                  <td className="px-4 py-3">
                    <p className="font-medium text-gray-900">
                      {inf.nickname ?? '—'}
                    </p>
                    <p className="text-xs text-gray-400 mt-0.5">{inf.email}</p>
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
                    <span
                      className={`text-xs px-2 py-0.5 rounded-full font-medium ${PRIORITY_COLORS[inf.priority] ?? 'bg-gray-100 text-gray-500'}`}
                    >
                      {inf.priority}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1">
                      {inf.tags.slice(0, 3).map((t) => (
                        <span
                          key={t.id}
                          className="text-xs px-1.5 py-0.5 rounded-full text-white"
                          style={{ backgroundColor: t.color }}
                        >
                          {t.name}
                        </span>
                      ))}
                      {inf.tags.length > 3 && (
                        <span className="text-xs text-gray-400">
                          +{inf.tags.length - 3}
                        </span>
                      )}
                    </div>
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
            Page {page} of {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="flex items-center gap-1 px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <ChevronLeft size={14} />
              Prev
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="flex items-center gap-1 px-3 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Next
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
