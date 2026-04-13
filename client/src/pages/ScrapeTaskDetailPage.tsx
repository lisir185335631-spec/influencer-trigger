import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Send,
  Loader2,
  Users,
  CheckSquare,
  Square,
  ExternalLink,
} from 'lucide-react'
import { scrapeApi, ScrapeTask, ScrapeInfluencerResult, parsePlatforms } from '../api/scrape'

// ── Helpers ───────────────────────────────────────────────────────────────────

function formatFollowers(n: number | null): string {
  if (n === null || n === undefined) return '—'
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

type SortDir = 'desc' | 'asc'

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ScrapeTaskDetailPage() {
  const { taskId } = useParams<{ taskId: string }>()
  const navigate = useNavigate()
  const id = Number(taskId)

  const [task, setTask] = useState<ScrapeTask | null>(null)
  const [results, setResults] = useState<ScrapeInfluencerResult[]>([])
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [sortDir, setSortDir] = useState<SortDir>('desc')

  const fetchData = useCallback(async () => {
    if (!id) return
    setLoading(true)
    try {
      const [taskData, resultsData] = await Promise.all([
        scrapeApi.getTask(id),
        scrapeApi.getTaskResults(id, 'followers'),
      ])
      setTask(taskData)
      setResults(resultsData)
      // Select all by default
      setSelected(new Set(resultsData.map((r) => r.id)))
    } catch {
      /* silent */
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { fetchData() }, [fetchData])

  // ── Sort client-side for asc/desc toggle ───────────────────────────────────
  const sorted = [...results].sort((a, b) => {
    const fa = a.followers ?? -1
    const fb = b.followers ?? -1
    return sortDir === 'desc' ? fb - fa : fa - fb
  })

  // ── Selection helpers ──────────────────────────────────────────────────────
  const allSelected = results.length > 0 && selected.size === results.length
  const someSelected = selected.size > 0 && selected.size < results.length

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set())
    } else {
      setSelected(new Set(results.map((r) => r.id)))
    }
  }

  function toggleOne(id: number) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // ── Send all selected ──────────────────────────────────────────────────────
  function handleSendAll() {
    const ids = [...selected].join(',')
    navigate(`/emails?influencer_ids=${ids}`)
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <Loader2 size={20} className="animate-spin mr-2" />
        <span className="text-sm">Loading results…</span>
      </div>
    )
  }

  if (!task) {
    return (
      <div className="p-6">
        <p className="text-sm text-red-500">Task not found.</p>
      </div>
    )
  }

  const platforms = parsePlatforms(task.platforms)

  return (
    <div className="p-6 space-y-5">
      {/* Back + header */}
      <div className="flex items-start gap-4">
        <button
          onClick={() => navigate('/scrape')}
          className="mt-0.5 text-gray-400 hover:text-gray-700 transition-colors"
        >
          <ArrowLeft size={16} />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-base font-semibold text-gray-900">
            Scrape Results — #{task.id}
          </h1>
          <p className="text-xs text-gray-400 mt-0.5">
            {platforms.join(', ')} · {task.industry} · {task.valid_count} valid emails
          </p>
        </div>
      </div>

      {/* Empty state */}
      {results.length === 0 && (
        <div className="py-16 text-center space-y-2">
          <Users size={32} className="mx-auto text-gray-200" />
          <p className="text-sm text-gray-500">No results yet</p>
          <p className="text-xs text-gray-400">
            {task.status === 'running' || task.status === 'pending'
              ? 'Scraping in progress — results will appear when emails are found.'
              : 'This task found no influencer emails.'}
          </p>
        </div>
      )}

      {/* Results table */}
      {results.length > 0 && (
        <>
          {/* Table controls */}
          <div className="flex items-center justify-between">
            <p className="text-xs text-gray-500">
              <span className="font-medium text-gray-800">{selected.size}</span> of {results.length} selected
            </p>
            <button
              onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}
              className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 transition-colors px-2 py-1 rounded hover:bg-gray-100"
            >
              {sortDir === 'desc' ? <ArrowDown size={12} /> : <ArrowUp size={12} />}
              Followers {sortDir === 'desc' ? '↑ Most' : '↑ Least'}
              <ArrowUpDown size={10} className="opacity-40" />
            </button>
          </div>

          <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/60">
                  <th className="px-4 py-3 text-left w-10">
                    <button onClick={toggleAll} className="text-gray-400 hover:text-gray-700 transition-colors">
                      {allSelected ? (
                        <CheckSquare size={14} className="text-gray-900" />
                      ) : someSelected ? (
                        <CheckSquare size={14} className="text-gray-400" />
                      ) : (
                        <Square size={14} />
                      )}
                    </button>
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Name</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Platform</th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Email</th>
                  <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 cursor-pointer select-none"
                      onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}>
                    <span className="flex items-center justify-end gap-1">
                      Followers
                      {sortDir === 'desc' ? <ArrowDown size={11} /> : <ArrowUp size={11} />}
                    </span>
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Bio</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {sorted.map((inf) => {
                  const isChecked = selected.has(inf.id)
                  return (
                    <tr
                      key={inf.id}
                      className={`transition-colors ${isChecked ? 'bg-white hover:bg-gray-50/60' : 'bg-gray-50/40 opacity-60 hover:opacity-80'}`}
                    >
                      <td className="px-4 py-3">
                        <button
                          onClick={() => toggleOne(inf.id)}
                          className="text-gray-400 hover:text-gray-700 transition-colors"
                        >
                          {isChecked ? (
                            <CheckSquare size={14} className="text-gray-900" />
                          ) : (
                            <Square size={14} />
                          )}
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5">
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
                      <td className="px-4 py-3">
                        <PlatformBadge platform={inf.platform} />
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-700 font-mono truncate max-w-[180px]">
                        {inf.email}
                      </td>
                      <td className="px-4 py-3 text-right text-xs font-medium text-gray-800">
                        {formatFollowers(inf.followers)}
                      </td>
                      <td className="px-4 py-3 text-xs text-gray-400 truncate max-w-[200px]">
                        {inf.bio ? inf.bio.slice(0, 80) + (inf.bio.length > 80 ? '…' : '') : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          {/* Bottom action bar */}
          <div className="flex items-center justify-between pt-1">
            <p className="text-xs text-gray-400">
              Uncheck influencers you don't want to contact, then click Send All.
            </p>
            <button
              onClick={handleSendAll}
              disabled={selected.size === 0}
              className="flex items-center gap-2 px-4 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <Send size={13} />
              Send All ({selected.size})
            </button>
          </div>
        </>
      )}
    </div>
  )
}
