import { useCallback, useEffect, useRef, useState } from 'react'
import { CheckCircle2, Merge, RefreshCw, Search, Users, X } from 'lucide-react'
import { Cell, Pie, PieChart, Tooltip } from 'recharts'
import {
  type BatchVerifyStatus,
  type DuplicateGroup,
  type InfluencersAdminResponse,
  type QualityReport,
  getBatchVerifyStatus,
  getDuplicates,
  getQualityReport,
  listAdminInfluencers,
  mergeInfluencers,
  startBatchVerify,
} from '../../api/admin/influencers_admin'

type Tab = 'all' | 'duplicates' | 'quality'

const STATUS_BADGE: Record<string, string> = {
  new: 'text-blue-600 bg-blue-50',
  contacted: 'text-yellow-700 bg-yellow-50',
  replied: 'text-green-700 bg-green-50',
  archived: 'text-gray-500 bg-gray-100',
}

function formatTs(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    month: '2-digit',
    day: '2-digit',
    year: '2-digit',
  })
}

// ─── Pie Chart ────────────────────────────────────────────────────────────────

function QualityPie({
  label,
  metric,
  total,
  color,
}: {
  label: string
  metric: { count: number; pct: number }
  total: number
  color: string
}) {
  const ok = total - metric.count
  const data = [
    { name: 'Issue', value: metric.count },
    { name: 'OK', value: ok },
  ]
  return (
    <div className="bg-white border border-gray-100 rounded-xl p-5 flex flex-col items-center gap-2">
      <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
        {label}
      </div>
      <PieChart width={140} height={140}>
        <Pie
          data={data}
          cx={70}
          cy={70}
          outerRadius={58}
          innerRadius={36}
          dataKey="value"
          startAngle={90}
          endAngle={-270}
        >
          <Cell fill={color} />
          <Cell fill="#e5e7eb" />
        </Pie>
        <Tooltip
          formatter={(value: number, name: string) => [value, name]}
        />
      </PieChart>
      <div className="text-center">
        <div className="text-2xl font-bold text-gray-900">{metric.pct}%</div>
        <div className="text-xs text-gray-400">
          {metric.count.toLocaleString()} / {total.toLocaleString()}
        </div>
      </div>
    </div>
  )
}

// ─── Merge Confirm Modal ──────────────────────────────────────────────────────

function MergeModal({
  group,
  primaryId,
  onConfirm,
  onCancel,
}: {
  group: DuplicateGroup
  primaryId: number
  onConfirm: () => void
  onCancel: () => void
}) {
  const primary = group.influencers.find((i) => i.id === primaryId)
  const secondaries = group.influencers.filter((i) => i.id !== primaryId)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">Confirm Merge</h2>
          <button onClick={onCancel} className="text-gray-400 hover:text-gray-700">
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="px-6 py-4 space-y-4 max-h-96 overflow-y-auto">
          <div>
            <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">
              Keep (Primary)
            </div>
            {primary && (
              <div className="bg-green-50 border border-green-200 rounded-lg px-3 py-2 text-sm">
                <div className="font-medium text-gray-800">{primary.nickname ?? '—'}</div>
                <div className="text-gray-500 text-xs">{primary.email}</div>
              </div>
            )}
          </div>
          <div>
            <div className="text-xs font-medium text-gray-400 uppercase tracking-wider mb-1">
              Delete (Secondaries)
            </div>
            <div className="space-y-2">
              {secondaries.map((s) => (
                <div
                  key={s.id}
                  className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm"
                >
                  <div className="font-medium text-gray-800">{s.nickname ?? '—'}</div>
                  <div className="text-gray-500 text-xs">{s.email}</div>
                  <div className="flex gap-3 mt-1 text-xs text-gray-400">
                    <span>{s.email_count} emails will be re-linked</span>
                    {s.tags.length > 0 && (
                      <span>{s.tags.length} tags: {s.tags.join(', ')}</span>
                    )}
                    {s.task_ids.length > 0 && (
                      <span>{s.task_ids.length} task(s)</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
            This action is irreversible. All emails, tags, and task links from deleted records will be
            migrated to the primary record.
          </p>
        </div>
        <div className="flex justify-end gap-3 px-6 py-4 border-t border-gray-100">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-700"
          >
            Merge & Delete
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── All Influencers Tab ──────────────────────────────────────────────────────

function AllTab() {
  const [data, setData] = useState<InfluencersAdminResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listAdminInfluencers({ page, page_size: 50, search: search || undefined })
      setData(res)
    } catch { /* silent */ } finally {
      setLoading(false)
    }
  }, [page, search])

  useEffect(() => { load() }, [load])

  const totalPages = data ? Math.ceil(data.total / 50) : 1

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input
            className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-200"
            placeholder="Search by name or email…"
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1) }}
          />
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
        {loading && !data ? (
          <div className="flex items-center justify-center h-40">
            <RefreshCw className="w-5 h-5 text-gray-300 animate-spin" />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100 text-xs text-gray-500 uppercase tracking-wider">
                  <th className="px-4 py-3 text-left">Name</th>
                  <th className="px-4 py-3 text-left">Email</th>
                  <th className="px-4 py-3 text-left">Platform</th>
                  <th className="px-4 py-3 text-left">Status</th>
                  <th className="px-4 py-3 text-right">Followers</th>
                  <th className="px-4 py-3 text-right">Emails Sent</th>
                  <th className="px-4 py-3 text-left">Tasks</th>
                  <th className="px-4 py-3 text-left">Tags</th>
                  <th className="px-4 py-3 text-left">Created</th>
                </tr>
              </thead>
              <tbody>
                {(data?.items ?? []).map((inf) => (
                  <tr
                    key={inf.id}
                    className="border-b border-gray-50 hover:bg-gray-50/60 transition-colors"
                  >
                    <td className="px-4 py-3">
                      <div className="font-medium text-gray-800 text-xs">{inf.nickname ?? '—'}</div>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 max-w-[180px] truncate">
                      {inf.email}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500 capitalize">{inf.platform ?? '—'}</td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-block text-xs font-medium px-2 py-0.5 rounded capitalize ${STATUS_BADGE[inf.status] ?? 'text-gray-600 bg-gray-100'}`}
                      >
                        {inf.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-right tabular-nums text-gray-600">
                      {inf.followers != null ? inf.followers.toLocaleString() : '—'}
                    </td>
                    <td className="px-4 py-3 text-xs text-right tabular-nums text-gray-600">
                      {inf.email_count}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400">
                      {inf.task_ids.length > 0 ? inf.task_ids.join(', ') : '—'}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {inf.tags.map((t) => (
                          <span
                            key={t}
                            className="text-xs bg-indigo-50 text-indigo-600 px-1.5 py-0.5 rounded"
                          >
                            {t}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-400 whitespace-nowrap">
                      {formatTs(inf.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {data && (
        <div className="flex items-center justify-between text-xs text-gray-500">
          <span>{data.total.toLocaleString()} total</span>
          <div className="flex items-center gap-2">
            <button
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
              className="px-3 py-1.5 border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
            >
              Prev
            </button>
            <span>
              {page} / {totalPages}
            </span>
            <button
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
              className="px-3 py-1.5 border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Duplicates Tab ───────────────────────────────────────────────────────────

function DuplicatesTab() {
  const [groups, setGroups] = useState<DuplicateGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [primaryIds, setPrimaryIds] = useState<Record<number, number>>({})
  const [mergeTarget, setMergeTarget] = useState<{ groupIdx: number; group: DuplicateGroup } | null>(null)
  const [merging, setMerging] = useState(false)
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null)

  const showToast = (msg: string, ok: boolean) => {
    setToast({ msg, ok })
    setTimeout(() => setToast(null), 4000)
  }

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await getDuplicates()
      setGroups(res)
      const init: Record<number, number> = {}
      res.forEach((g, i) => { init[i] = g.influencers[0].id })
      setPrimaryIds(init)
    } catch { /* silent */ } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleMerge() {
    if (!mergeTarget) return
    const { groupIdx, group } = mergeTarget
    const primaryId = primaryIds[groupIdx] ?? group.influencers[0].id
    const secondaryIds = group.influencers.filter((i) => i.id !== primaryId).map((i) => i.id)

    setMerging(true)
    try {
      await mergeInfluencers({ primary_id: primaryId, secondary_ids: secondaryIds })
      showToast('Merge successful', true)
      setMergeTarget(null)
      await load()
    } catch {
      showToast('Merge failed', false)
    } finally {
      setMerging(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-400">
          Influencers on the same platform with name similarity &gt; 90%
        </p>
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-40">
          <RefreshCw className="w-5 h-5 text-gray-300 animate-spin" />
        </div>
      ) : groups.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 text-sm text-gray-400">
          <CheckCircle2 className="w-8 h-8 mb-2 text-green-400" />
          No duplicate groups found.
        </div>
      ) : (
        <div className="space-y-3">
          {groups.map((group, groupIdx) => {
            const selectedPrimary = primaryIds[groupIdx] ?? group.influencers[0].id
            return (
              <div
                key={groupIdx}
                className="bg-white border border-gray-100 rounded-xl overflow-hidden"
              >
                <div className="flex items-center justify-between px-4 py-3 border-b border-gray-50 bg-gray-50/50">
                  <span className="text-xs font-medium text-gray-500">
                    {group.influencers.length} similar records · {group.type.replace('_', ' ')}
                  </span>
                  <button
                    onClick={() => setMergeTarget({ groupIdx, group })}
                    className="flex items-center gap-1.5 text-xs font-medium text-indigo-600 hover:text-indigo-800 border border-indigo-200 rounded-lg px-3 py-1.5 hover:bg-indigo-50"
                  >
                    <Merge className="w-3.5 h-3.5" />
                    Merge Group
                  </button>
                </div>
                <div className="divide-y divide-gray-50">
                  {group.influencers.map((inf) => {
                    const isPrimary = inf.id === selectedPrimary
                    return (
                      <div
                        key={inf.id}
                        className={`flex items-center gap-4 px-4 py-3 cursor-pointer transition-colors ${isPrimary ? 'bg-indigo-50/60' : 'hover:bg-gray-50/60'}`}
                        onClick={() =>
                          setPrimaryIds((p) => ({ ...p, [groupIdx]: inf.id }))
                        }
                      >
                        <div className="flex-shrink-0">
                          <div
                            className={`w-4 h-4 rounded-full border-2 flex items-center justify-center ${isPrimary ? 'border-indigo-500 bg-indigo-500' : 'border-gray-300'}`}
                          >
                            {isPrimary && (
                              <div className="w-1.5 h-1.5 rounded-full bg-white" />
                            )}
                          </div>
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-gray-800">
                              {inf.nickname ?? '—'}
                            </span>
                            {isPrimary && (
                              <span className="text-xs bg-indigo-100 text-indigo-600 px-1.5 py-0.5 rounded font-medium">
                                Primary
                              </span>
                            )}
                            <span className="text-xs text-gray-400 capitalize">{inf.platform}</span>
                          </div>
                          <div className="text-xs text-gray-400">{inf.email}</div>
                        </div>
                        <div className="flex gap-4 text-xs text-gray-400">
                          <span>{inf.email_count} emails</span>
                          {inf.tags.length > 0 && (
                            <span>{inf.tags.length} tags</span>
                          )}
                          {inf.task_ids.length > 0 && (
                            <span>{inf.task_ids.length} tasks</span>
                          )}
                        </div>
                        <div className="text-xs text-gray-400">{formatTs(inf.created_at)}</div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}

      {mergeTarget && (
        <MergeModal
          group={mergeTarget.group}
          primaryId={primaryIds[mergeTarget.groupIdx] ?? mergeTarget.group.influencers[0].id}
          onConfirm={handleMerge}
          onCancel={() => !merging && setMergeTarget(null)}
        />
      )}

      {toast && (
        <div
          className={`fixed bottom-5 right-5 z-50 px-4 py-3 rounded-xl shadow-lg text-sm font-medium text-white ${toast.ok ? 'bg-green-600' : 'bg-red-600'}`}
        >
          {toast.msg}
        </div>
      )}
    </div>
  )
}

// ─── Quality Report Tab ───────────────────────────────────────────────────────

function QualityTab() {
  const [report, setReport] = useState<QualityReport | null>(null)
  const [loading, setLoading] = useState(false)
  const [verifyTaskId, setVerifyTaskId] = useState<string | null>(null)
  const [verifyStatus, setVerifyStatus] = useState<BatchVerifyStatus | null>(null)
  const [verifying, setVerifying] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setReport(await getQualityReport())
    } catch { /* silent */ } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!verifyTaskId) return
    pollRef.current = setInterval(async () => {
      try {
        const s = await getBatchVerifyStatus(verifyTaskId)
        setVerifyStatus(s)
        if (s.status === 'done') {
          clearInterval(pollRef.current!)
          setVerifying(false)
        }
      } catch { /* silent */ }
    }, 1500)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [verifyTaskId])

  async function handleStartVerify() {
    setVerifying(true)
    setVerifyStatus(null)
    try {
      const res = await startBatchVerify()
      setVerifyTaskId(res.task_id)
      setVerifyStatus({
        status: 'pending',
        total: res.total,
        done: 0,
        passed: 0,
        failed: 0,
        results: {},
      })
    } catch {
      setVerifying(false)
    }
  }

  const progress =
    verifyStatus && verifyStatus.total > 0
      ? Math.round((verifyStatus.done / verifyStatus.total) * 100)
      : 0

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <p className="text-xs text-gray-400">Data quality overview across all influencers</p>
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-700"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {loading && !report ? (
        <div className="flex items-center justify-center h-40">
          <RefreshCw className="w-5 h-5 text-gray-300 animate-spin" />
        </div>
      ) : report ? (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <QualityPie
              label="Empty Email"
              metric={report.empty_email}
              total={report.total}
              color="#ef4444"
            />
            <QualityPie
              label="Invalid Email"
              metric={report.invalid_email}
              total={report.total}
              color="#f97316"
            />
            <QualityPie
              label="No Followers"
              metric={report.missing_followers}
              total={report.total}
              color="#eab308"
            />
            <QualityPie
              label="No Bio"
              metric={report.missing_bio}
              total={report.total}
              color="#8b5cf6"
            />
          </div>

          <div className="bg-white border border-gray-100 rounded-xl p-5 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-gray-800">Batch MX Verification</h3>
                <p className="text-xs text-gray-400 mt-0.5">
                  Verify email domains via DNS MX record lookup for all {report.total.toLocaleString()} influencers
                </p>
              </div>
              <button
                disabled={verifying}
                onClick={handleStartVerify}
                className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {verifying ? (
                  <RefreshCw className="w-4 h-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-4 h-4" />
                )}
                {verifying ? 'Verifying…' : 'Start MX Verify'}
              </button>
            </div>

            {verifyStatus && (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span>
                    {verifyStatus.done} / {verifyStatus.total} checked
                    {verifyStatus.status === 'done' && ' · Done'}
                  </span>
                  <span>
                    <span className="text-green-600 font-medium">{verifyStatus.passed} passed</span>
                    {' · '}
                    <span className="text-red-500 font-medium">{verifyStatus.failed} failed</span>
                  </span>
                </div>
                <div className="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                  <div
                    className={`h-2 rounded-full transition-all duration-300 ${verifyStatus.status === 'done' ? 'bg-green-500' : 'bg-indigo-500'}`}
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

const TABS: { key: Tab; label: string }[] = [
  { key: 'all', label: 'All Influencers' },
  { key: 'duplicates', label: 'Duplicates' },
  { key: 'quality', label: 'Quality Report' },
]

export default function InfluencersAdminPage() {
  const [tab, setTab] = useState<Tab>('all')

  return (
    <div className="p-6 space-y-5 max-w-screen-2xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Influencer Governance</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            Deduplicate records, monitor data quality, and bulk-verify email domains
          </p>
        </div>
        <Users className="w-6 h-6 text-gray-300" />
      </div>

      <div className="flex border-b border-gray-100">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-5 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === key
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'all' && <AllTab />}
      {tab === 'duplicates' && <DuplicatesTab />}
      {tab === 'quality' && <QualityTab />}
    </div>
  )
}
