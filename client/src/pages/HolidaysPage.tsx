import { useState, useEffect, useCallback } from 'react'
import {
  Calendar,
  Plus,
  Pencil,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Mail,
  PlayCircle,
  CheckCircle,
  X,
  AlertCircle,
} from 'lucide-react'
import { holidaysApi, Holiday, HolidayCreate, HolidayUpdate, HolidayGreetingLogItem } from '../api/holidays'

const MONTH_NAMES = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const PAGE_SIZE = 20

// ── Helpers ──────────────────────────────────────────────────────────────────

function parseLocalDate(isoStr: string): Date {
  const [y, m, d] = isoStr.split('-').map(Number)
  return new Date(y, m - 1, d)
}

function formatDate(isoStr: string): string {
  const d = parseLocalDate(isoStr)
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function toIso(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// ── Status badge ─────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  sent:      'bg-blue-50 text-blue-600',
  delivered: 'bg-cyan-50 text-cyan-600',
  opened:    'bg-yellow-50 text-yellow-600',
  replied:   'bg-green-50 text-green-700',
  failed:    'bg-red-50 text-red-600',
}

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-500'
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {status}
    </span>
  )
}

// ── Calendar ─────────────────────────────────────────────────────────────────

function CalendarView({ holidays }: { holidays: Holiday[] }) {
  const today = new Date()
  const [year, setYear] = useState(today.getFullYear())
  const [month, setMonth] = useState(today.getMonth()) // 0-indexed

  const firstDay = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()

  // Build lookup: "month-day" → holiday names
  const holidayByDay = new Map<string, string[]>()
  holidays.forEach((h) => {
    const d = parseLocalDate(h.date)
    const key = h.is_recurring
      ? `${d.getMonth()}-${d.getDate()}`
      : `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
    const arr = holidayByDay.get(key) ?? []
    arr.push(h.name)
    holidayByDay.set(key, arr)
  })

  const getHolidaysForDay = (day: number): string[] => {
    const recurKey = `${month}-${day}`
    const exactKey = `${year}-${month}-${day}`
    return [...(holidayByDay.get(recurKey) ?? []), ...(holidayByDay.get(exactKey) ?? [])]
  }

  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ]

  const isToday = (day: number) =>
    day === today.getDate() && month === today.getMonth() && year === today.getFullYear()

  return (
    <div className="bg-white border border-gray-100 rounded-xl p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <button
          onClick={() => {
            if (month === 0) { setMonth(11); setYear(y => y - 1) }
            else setMonth(m => m - 1)
          }}
          className="p-1.5 rounded-md hover:bg-gray-50 text-gray-400 hover:text-gray-700"
        >
          <ChevronLeft size={16} />
        </button>
        <span className="text-sm font-semibold text-gray-900">
          {MONTH_NAMES[month]} {year}
        </span>
        <button
          onClick={() => {
            if (month === 11) { setMonth(0); setYear(y => y + 1) }
            else setMonth(m => m + 1)
          }}
          className="p-1.5 rounded-md hover:bg-gray-50 text-gray-400 hover:text-gray-700"
        >
          <ChevronRight size={16} />
        </button>
      </div>

      {/* Day headers */}
      <div className="grid grid-cols-7 mb-1">
        {DAY_NAMES.map((d) => (
          <div key={d} className="text-center text-xs font-medium text-gray-400 py-1">
            {d}
          </div>
        ))}
      </div>

      {/* Day cells */}
      <div className="grid grid-cols-7 gap-1">
        {cells.map((day, idx) => {
          if (day === null) return <div key={`e-${idx}`} />
          const names = getHolidaysForDay(day)
          const hasHoliday = names.length > 0
          const todayCell = isToday(day)
          return (
            <div
              key={day}
              title={names.join(', ')}
              className={`relative flex flex-col items-center justify-start pt-1 pb-1 rounded-lg min-h-[48px] cursor-default transition-colors ${
                hasHoliday
                  ? 'bg-amber-50 border border-amber-200'
                  : todayCell
                  ? 'bg-gray-50 border border-gray-200'
                  : 'hover:bg-gray-50'
              }`}
            >
              <span
                className={`text-xs font-medium ${
                  todayCell
                    ? 'text-white bg-gray-900 w-5 h-5 flex items-center justify-center rounded-full'
                    : hasHoliday
                    ? 'text-amber-700'
                    : 'text-gray-600'
                }`}
              >
                {day}
              </span>
              {hasHoliday && (
                <span className="mt-0.5 text-[9px] leading-tight text-amber-600 text-center px-0.5 truncate w-full">
                  {names[0]}
                </span>
              )}
              {names.length > 1 && (
                <span className="text-[9px] text-amber-400">+{names.length - 1}</span>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Holiday form modal ────────────────────────────────────────────────────────

interface HolidayModalProps {
  initial?: Holiday | null
  onSave: (data: HolidayCreate | HolidayUpdate) => Promise<void>
  onClose: () => void
}

function HolidayModal({ initial, onSave, onClose }: HolidayModalProps) {
  const [name, setName] = useState(initial?.name ?? '')
  const [date, setDate] = useState(initial?.date ?? toIso(new Date()))
  const [isRecurring, setIsRecurring] = useState(initial?.is_recurring ?? true)
  const [isActive, setIsActive] = useState(initial?.is_active ?? true)
  const [greetingTemplate, setGreetingTemplate] = useState(initial?.greeting_template ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) { setError('Name is required'); return }
    setSaving(true)
    setError('')
    try {
      await onSave({
        name: name.trim(),
        date,
        is_recurring: isRecurring,
        is_active: isActive,
        greeting_template: greetingTemplate.trim() || null,
      })
      onClose()
    } catch {
      setError('Failed to save holiday')
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md mx-4 p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-sm font-semibold text-gray-900">
            {initial ? 'Edit Holiday' : 'Add Holiday'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={16} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          {error && (
            <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 rounded-lg px-3 py-2">
              <AlertCircle size={14} />
              {error}
            </div>
          )}
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Name *</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Christmas"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-gray-300"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Date *</label>
            <input
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-gray-300"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">
              Custom Greeting Template
            </label>
            <textarea
              value={greetingTemplate}
              onChange={(e) => setGreetingTemplate(e.target.value)}
              placeholder="Optional. Use {name} and {holiday} as placeholders. Leave empty to use AI-generated greeting."
              rows={3}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-gray-300 resize-none"
            />
          </div>
          <div className="flex items-center gap-6">
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isRecurring}
                onChange={(e) => setIsRecurring(e.target.checked)}
                className="rounded border-gray-300"
              />
              Recurring (every year)
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="rounded border-gray-300"
              />
              Active
            </label>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-200 rounded-lg"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-1.5 text-sm font-medium bg-gray-900 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Greeting Logs ─────────────────────────────────────────────────────────────

function PlatformBadge({ platform }: { platform: string | null }) {
  if (!platform) return <span className="text-gray-300">—</span>
  const colors: Record<string, string> = {
    tiktok: 'bg-black text-white',
    instagram: 'bg-pink-100 text-pink-700',
    youtube: 'bg-red-50 text-red-600',
    twitter: 'bg-sky-50 text-sky-600',
    facebook: 'bg-blue-50 text-blue-600',
  }
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${colors[platform] ?? 'bg-gray-100 text-gray-600'}`}>
      {platform}
    </span>
  )
}

function GreetingLogsTab() {
  const [logs, setLogs] = useState<HolidayGreetingLogItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async (p: number) => {
    setLoading(true)
    setError('')
    try {
      const res = await holidaysApi.listLogs(p, PAGE_SIZE)
      setLogs(res.items)
      setTotal(res.total)
      setPage(p)
    } catch {
      setError('Failed to load greeting logs')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load(1) }, [load])

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  if (loading) return <div className="py-12 text-center text-sm text-gray-400">Loading…</div>
  if (error) return (
    <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 rounded-lg px-4 py-3">
      <AlertCircle size={14} /> {error}
    </div>
  )

  if (logs.length === 0) return (
    <div className="py-16 text-center text-gray-400">
      <Mail size={32} className="mx-auto mb-3 opacity-30" />
      <p className="text-sm">No holiday greetings sent yet</p>
    </div>
  )

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100">
              {['Influencer', 'Platform', 'Subject', 'Status', 'Sent At'].map((h) => (
                <th key={h} className="text-left text-xs font-medium text-gray-400 py-2 px-3 first:pl-0">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {logs.map((log) => (
              <tr key={log.id} className="hover:bg-gray-50 transition-colors">
                <td className="py-2.5 px-3 first:pl-0">
                  <div className="font-medium text-gray-900 text-sm">
                    {log.influencer_name || '—'}
                  </div>
                  <div className="text-xs text-gray-400">{log.influencer_email}</div>
                </td>
                <td className="py-2.5 px-3">
                  <PlatformBadge platform={log.influencer_platform} />
                </td>
                <td className="py-2.5 px-3 max-w-xs truncate text-gray-700">{log.subject}</td>
                <td className="py-2.5 px-3">
                  <StatusBadge status={log.status} />
                </td>
                <td className="py-2.5 px-3 text-xs text-gray-400">
                  {log.sent_at ? new Date(log.sent_at).toLocaleString() : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4 pt-3 border-t border-gray-100">
          <span className="text-xs text-gray-400">{total} total greetings</span>
          <div className="flex gap-1">
            <button
              disabled={page === 1}
              onClick={() => load(page - 1)}
              className="px-2 py-1 text-xs border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50"
            >
              Prev
            </button>
            <span className="px-3 py-1 text-xs text-gray-500">{page} / {totalPages}</span>
            <button
              disabled={page === totalPages}
              onClick={() => load(page + 1)}
              className="px-2 py-1 text-xs border border-gray-200 rounded disabled:opacity-40 hover:bg-gray-50"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Tab = 'calendar' | 'list' | 'logs'

export default function HolidaysPage() {
  const [tab, setTab] = useState<Tab>('calendar')
  const [holidays, setHolidays] = useState<Holiday[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [modalOpen, setModalOpen] = useState(false)
  const [editTarget, setEditTarget] = useState<Holiday | null>(null)
  const [deleteId, setDeleteId] = useState<number | null>(null)
  const [triggering, setTriggering] = useState(false)
  const [triggerOk, setTriggerOk] = useState(false)

  const loadHolidays = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await holidaysApi.list()
      setHolidays(data)
    } catch {
      setError('Failed to load holidays')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadHolidays() }, [loadHolidays])

  const handleAdd = async (data: Parameters<typeof holidaysApi.create>[0]) => {
    await holidaysApi.create(data)
    await loadHolidays()
  }

  const handleEdit = async (data: Parameters<typeof holidaysApi.update>[1]) => {
    if (!editTarget) return
    await holidaysApi.update(editTarget.id, data)
    await loadHolidays()
  }

  const handleDelete = async (id: number) => {
    await holidaysApi.delete(id)
    setDeleteId(null)
    await loadHolidays()
  }

  const handleTrigger = async () => {
    setTriggering(true)
    setTriggerOk(false)
    try {
      await holidaysApi.trigger()
      setTriggerOk(true)
      setTimeout(() => setTriggerOk(false), 3000)
    } catch {
      // ignore
    } finally {
      setTriggering(false)
    }
  }

  const TABS: { key: Tab; label: string }[] = [
    { key: 'calendar', label: 'Calendar' },
    { key: 'list', label: 'Manage' },
    { key: 'logs', label: 'Greeting Logs' },
  ]

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-amber-50">
            <Calendar size={16} className="text-amber-600" />
          </div>
          <div>
            <h1 className="text-base font-semibold text-gray-900">Holiday Greetings</h1>
            <p className="text-xs text-gray-400">Automatically send greetings on international holidays</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleTrigger}
            disabled={triggering}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600 disabled:opacity-50"
          >
            {triggerOk ? <CheckCircle size={13} className="text-green-500" /> : <PlayCircle size={13} />}
            {triggerOk ? 'Triggered!' : triggering ? 'Running…' : 'Trigger Now'}
          </button>
          <button
            onClick={() => { setEditTarget(null); setModalOpen(true) }}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium bg-gray-900 text-white rounded-lg hover:bg-gray-700"
          >
            <Plus size={13} />
            Add Holiday
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-50 rounded-lg p-1 mb-5 w-fit">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-1.5 text-xs font-medium rounded-md transition-colors ${
              tab === key
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 text-red-600 text-sm bg-red-50 rounded-lg px-4 py-3 mb-4">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* Calendar tab */}
      {tab === 'calendar' && (
        loading ? (
          <div className="py-12 text-center text-sm text-gray-400">Loading…</div>
        ) : (
          <CalendarView holidays={holidays} />
        )
      )}

      {/* List/manage tab */}
      {tab === 'list' && (
        <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
          {loading ? (
            <div className="py-12 text-center text-sm text-gray-400">Loading…</div>
          ) : holidays.length === 0 ? (
            <div className="py-16 text-center text-gray-400">
              <Calendar size={32} className="mx-auto mb-3 opacity-30" />
              <p className="text-sm">No holidays configured</p>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {['Holiday', 'Date', 'Recurring', 'Active', 'Custom Template', ''].map((h) => (
                    <th key={h} className="text-left text-xs font-medium text-gray-400 py-2.5 px-4 first:pl-5">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {holidays.map((h) => (
                  <tr key={h.id} className="hover:bg-gray-50 transition-colors">
                    <td className="py-3 px-4 first:pl-5 font-medium text-gray-900">{h.name}</td>
                    <td className="py-3 px-4 text-gray-600">{formatDate(h.date)}</td>
                    <td className="py-3 px-4">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        h.is_recurring ? 'bg-blue-50 text-blue-600' : 'bg-gray-100 text-gray-500'
                      }`}>
                        {h.is_recurring ? 'Annual' : 'One-time'}
                      </span>
                    </td>
                    <td className="py-3 px-4">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        h.is_active ? 'bg-green-50 text-green-600' : 'bg-gray-100 text-gray-400'
                      }`}>
                        {h.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="py-3 px-4 text-xs text-gray-400 max-w-xs truncate">
                      {h.greeting_template ? (
                        <span className="text-gray-600">{h.greeting_template.slice(0, 60)}{h.greeting_template.length > 60 ? '…' : ''}</span>
                      ) : (
                        <span className="italic">AI-generated</span>
                      )}
                    </td>
                    <td className="py-3 px-4 pr-5">
                      <div className="flex items-center gap-1 justify-end">
                        <button
                          onClick={() => { setEditTarget(h); setModalOpen(true) }}
                          className="p-1.5 rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100"
                          title="Edit"
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          onClick={() => setDeleteId(h.id)}
                          className="p-1.5 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50"
                          title="Delete"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Logs tab */}
      {tab === 'logs' && (
        <div className="bg-white border border-gray-100 rounded-xl p-5">
          <GreetingLogsTab />
        </div>
      )}

      {/* Add/Edit modal */}
      {modalOpen && (
        <HolidayModal
          initial={editTarget}
          onSave={editTarget ? handleEdit : handleAdd}
          onClose={() => { setModalOpen(false); setEditTarget(null) }}
        />
      )}

      {/* Delete confirm */}
      {deleteId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
          <div className="bg-white rounded-xl shadow-lg w-full max-w-sm mx-4 p-6">
            <h2 className="text-sm font-semibold text-gray-900 mb-2">Delete Holiday</h2>
            <p className="text-sm text-gray-500 mb-5">
              Are you sure you want to delete this holiday? This cannot be undone.
            </p>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setDeleteId(null)}
                className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg text-gray-600 hover:text-gray-900"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteId)}
                className="px-4 py-1.5 text-sm font-medium bg-red-600 text-white rounded-lg hover:bg-red-700"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
