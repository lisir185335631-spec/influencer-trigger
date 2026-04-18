import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import { Calendar, ChevronDown, ChevronRight, Globe, List, Pencil, Plus, Trash2, X } from 'lucide-react'
import {
  type HolidayAdminItem,
  type InvestmentReport,
  createAdminHoliday,
  deleteAdminHoliday,
  getInvestmentReport,
  listAdminHolidays,
  patchAdminHoliday,
  setSensitiveRegions,
} from '../../api/admin/holidays_admin'

const BAR_COLORS = ['#6366f1', '#8b5cf6', '#a78bfa', '#c4b5fd', '#ddd6fe']

// ─── Holiday Form Modal ────────────────────────────────────────────────────────

interface HolidayFormModal {
  item: Partial<HolidayAdminItem> | null
  onSave: (data: Partial<HolidayAdminItem>) => Promise<void>
  onClose: () => void
}

function HolidayFormModal({ item, onSave, onClose }: HolidayFormModal) {
  const { t } = useTranslation()
  const [form, setForm] = useState({
    name: item?.name ?? '',
    date: item?.date ?? '',
    is_recurring: item?.is_recurring ?? true,
    is_active: item?.is_active ?? true,
    greeting_template: item?.greeting_template ?? '',
  })
  const [saving, setSaving] = useState(false)

  const handleSubmit = async () => {
    setSaving(true)
    try {
      await onSave(form)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-xl p-7 w-[520px] max-w-[92vw]">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-base font-semibold text-gray-900">
            {item?.id ? t('admin.holidays.modal.editTitle') : t('admin.holidays.modal.addTitle')}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
        </div>
        <div className="space-y-4">
          <div>
            <label className="block text-xs text-gray-500 mb-1.5">{t('admin.holidays.modal.nameLabel')}</label>
            <input
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
              placeholder={t('admin.holidays.modal.namePlaceholder')}
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1.5">{t('admin.holidays.modal.dateLabel')}</label>
            <input
              type="date"
              value={form.date}
              onChange={e => setForm(f => ({ ...f, date: e.target.value }))}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1.5">{t('admin.holidays.modal.greetingLabel')}</label>
            <textarea
              value={form.greeting_template}
              onChange={e => setForm(f => ({ ...f, greeting_template: e.target.value }))}
              rows={3}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-none"
              placeholder={t('admin.holidays.modal.greetingPlaceholder')}
            />
          </div>
          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input
                type="checkbox"
                checked={form.is_recurring}
                onChange={e => setForm(f => ({ ...f, is_recurring: e.target.checked }))}
                className="rounded"
              />
              {t('admin.holidays.modal.recurringLabel')}
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
              <input
                type="checkbox"
                checked={form.is_active}
                onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))}
                className="rounded"
              />
              {t('admin.holidays.modal.activeLabel')}
            </label>
          </div>
        </div>
        <div className="flex justify-end gap-3 mt-6">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50">
            {t('admin.common.cancel')}
          </button>
          <button
            onClick={handleSubmit}
            disabled={saving || !form.name || !form.date}
            className="px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800 disabled:opacity-50"
          >
            {saving ? t('admin.common.saving') : t('admin.common.save')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Sensitive Regions Modal ───────────────────────────────────────────────────

function SensitiveRegionsModal({
  holiday,
  onSave,
  onClose,
}: {
  holiday: HolidayAdminItem
  onSave: (regions: string) => Promise<void>
  onClose: () => void
}) {
  const { t } = useTranslation()
  const [regions, setRegions] = useState(holiday.sensitive_regions)
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await onSave(regions)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-xl p-7 w-[460px] max-w-[92vw]">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900">
            {t('admin.holidays.sensitiveRegions.title')} — {holiday.name}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={16} /></button>
        </div>
        <p className="text-xs text-gray-500 mb-4">{t('admin.holidays.sensitiveRegions.hint')}</p>
        <input
          value={regions}
          onChange={e => setRegions(e.target.value)}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
          placeholder={t('admin.holidays.sensitiveRegions.placeholder')}
        />
        <div className="flex justify-end gap-3 mt-5">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50">
            {t('admin.common.cancel')}
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800 disabled:opacity-50"
          >
            {saving ? t('admin.common.saving') : t('admin.common.save')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Investment Report Row ──────────────────────────────────────────────────────

function InvestmentReportRow({ holidayId }: { holidayId: number }) {
  const { t } = useTranslation()
  const [report, setReport] = useState<InvestmentReport | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getInvestmentReport(holidayId).then(r => {
      setReport(r)
      setLoading(false)
    })
  }, [holidayId])

  if (loading) return <div className="py-6 text-center text-xs text-gray-400">{t('admin.holidays.report.loading')}</div>
  if (!report || report.yearly.length === 0) {
    return <div className="py-6 text-center text-xs text-gray-400">{t('admin.holidays.report.noData')}</div>
  }

  return (
    <div className="px-6 py-4 bg-gray-50/50">
      <p className="text-xs font-medium text-gray-600 mb-3">{t('admin.holidays.report.title')}</p>
      <div className="h-40">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={report.yearly} margin={{ top: 0, right: 10, left: -20, bottom: 0 }}>
            <XAxis dataKey="year" tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
              formatter={(value, name) => [
                name === 'total' ? Number(value) : `${Number(value)}%`,
                name === 'total'
                  ? t('admin.holidays.report.labelSent')
                  : name === 'open_rate'
                  ? t('admin.holidays.report.labelOpenRate')
                  : t('admin.holidays.report.labelReplyRate'),
              ]}
            />
            <Bar dataKey="total" name="total" radius={[3, 3, 0, 0]}>
              {report.yearly.map((_, i) => <Cell key={i} fill={BAR_COLORS[i % BAR_COLORS.length]} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="flex gap-6 mt-3 text-xs text-gray-500">
        {report.yearly.map(y => (
          <span key={y.year}>
            <strong className="text-gray-700">{y.year}:</strong>{' '}
            {t('admin.holidays.report.yearSummary', {
              sent: y.total,
              openRate: y.open_rate,
              replyRate: y.reply_rate,
            })}
          </span>
        ))}
      </div>
    </div>
  )
}

// ─── Holiday Row ────────────────────────────────────────────────────────────────

function HolidayRow({
  holiday,
  onEdit,
  onDelete,
  onRegions,
}: {
  holiday: HolidayAdminItem
  onEdit: (h: HolidayAdminItem) => void
  onDelete: (id: number) => void
  onRegions: (h: HolidayAdminItem) => void
}) {
  const { t } = useTranslation()
  const [expanded, setExpanded] = useState(false)

  return (
    <>
      <tr className="border-b border-gray-50 hover:bg-gray-50/50">
        <td className="py-3 px-4">
          <button
            onClick={() => setExpanded(e => !e)}
            className="flex items-center gap-2 text-gray-700 hover:text-gray-900"
          >
            {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            <span className="font-medium text-sm">{holiday.name}</span>
          </button>
        </td>
        <td className="py-3 px-4 text-sm text-gray-600">{holiday.date}</td>
        <td className="py-3 px-4 text-center">
          <span className={`px-2 py-0.5 rounded-full text-xs ${holiday.is_active ? 'text-green-700 bg-green-50' : 'text-gray-500 bg-gray-100'}`}>
            {holiday.is_active ? t('admin.common.active') : t('admin.common.inactive')}
          </span>
        </td>
        <td className="py-3 px-4 text-center text-sm text-gray-600">{holiday.send_count}</td>
        <td className="py-3 px-4 text-center text-sm text-gray-600">{holiday.open_rate}%</td>
        <td className="py-3 px-4 text-center text-sm text-gray-600">{holiday.reply_rate}%</td>
        <td className="py-3 px-4 text-xs text-gray-400 max-w-[120px] truncate">
          {holiday.sensitive_regions || <span className="italic text-gray-300">{t('admin.holidays.table.noRegions')}</span>}
        </td>
        <td className="py-3 px-4 text-right">
          <div className="flex items-center justify-end gap-1">
            <button
              onClick={() => onRegions(holiday)}
              title={t('admin.holidays.actions.sensitiveRegions')}
              className="p-1.5 text-gray-400 hover:text-blue-600 rounded"
            >
              <Globe size={14} />
            </button>
            <button
              onClick={() => onEdit(holiday)}
              className="p-1.5 text-gray-400 hover:text-gray-600 rounded"
              title={t('admin.common.edit')}
            >
              <Pencil size={14} />
            </button>
            <button
              onClick={() => onDelete(holiday.id)}
              className="p-1.5 text-gray-400 hover:text-red-500 rounded"
              title={t('admin.common.delete')}
            >
              <Trash2 size={14} />
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-gray-50">
          <td colSpan={8} className="p-0">
            <InvestmentReportRow holidayId={holiday.id} />
          </td>
        </tr>
      )}
    </>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

type ViewMode = 'list' | 'calendar'

export default function HolidaysAdminPage() {
  const { t } = useTranslation()
  const [holidays, setHolidays] = useState<HolidayAdminItem[]>([])
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState<ViewMode>('list')
  const [formModal, setFormModal] = useState<{ item: Partial<HolidayAdminItem> | null } | null>(null)
  const [regionsModal, setRegionsModal] = useState<HolidayAdminItem | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listAdminHolidays()
      setHolidays(data)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleSave = async (data: Partial<HolidayAdminItem>) => {
    if (formModal?.item?.id) {
      await patchAdminHoliday(formModal.item.id, data)
    } else {
      await createAdminHoliday({
        name: data.name!,
        date: data.date!,
        is_recurring: data.is_recurring,
        is_active: data.is_active,
        greeting_template: data.greeting_template,
      })
    }
    await load()
  }

  const handleDelete = async (id: number) => {
    if (!window.confirm(t('admin.holidays.deleteConfirm'))) return
    await deleteAdminHoliday(id)
    setHolidays(prev => prev.filter(h => h.id !== id))
  }

  const handleSaveRegions = async (regions: string) => {
    if (!regionsModal) return
    await setSensitiveRegions(regionsModal.id, regions)
    setHolidays(prev => prev.map(h => h.id === regionsModal.id ? { ...h, sensitive_regions: regions } : h))
  }

  // Group holidays by month for calendar view
  const byMonth = holidays.reduce<Record<string, HolidayAdminItem[]>>((acc, h) => {
    const month = h.date.slice(0, 7)
    if (!acc[month]) acc[month] = []
    acc[month].push(h)
    return acc
  }, {})

  return (
    <>
      {formModal && (
        <HolidayFormModal
          item={formModal.item}
          onSave={handleSave}
          onClose={() => setFormModal(null)}
        />
      )}
      {regionsModal && (
        <SensitiveRegionsModal
          holiday={regionsModal}
          onSave={handleSaveRegions}
          onClose={() => setRegionsModal(null)}
        />
      )}

      <div className="space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">{t('admin.holidays.title')}</h1>
            <p className="text-sm text-gray-500 mt-0.5">{t('admin.holidays.subtitle')}</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex border border-gray-200 rounded-lg overflow-hidden">
              <button
                onClick={() => setView('list')}
                className={`px-3 py-1.5 text-xs flex items-center gap-1.5 ${view === 'list' ? 'bg-gray-900 text-white' : 'text-gray-500 hover:bg-gray-50'}`}
              >
                <List size={12} /> {t('admin.holidays.viewList')}
              </button>
              <button
                onClick={() => setView('calendar')}
                className={`px-3 py-1.5 text-xs flex items-center gap-1.5 ${view === 'calendar' ? 'bg-gray-900 text-white' : 'text-gray-500 hover:bg-gray-50'}`}
              >
                <Calendar size={12} /> {t('admin.holidays.viewCalendar')}
              </button>
            </div>
            <button
              onClick={() => setFormModal({ item: {} })}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800"
            >
              <Plus size={14} />
              {t('admin.holidays.addHoliday')}
            </button>
          </div>
        </div>

        {/* Content */}
        {loading ? (
          <div className="text-center py-16 text-gray-400 text-sm">{t('admin.common.loading')}</div>
        ) : view === 'list' ? (
          <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-50 text-xs text-gray-400 uppercase tracking-wide">
                  <th className="text-left py-3 px-4 font-medium">{t('admin.holidays.table.colHoliday')}</th>
                  <th className="text-left py-3 px-4 font-medium">{t('admin.holidays.table.colDate')}</th>
                  <th className="text-center py-3 px-4 font-medium">{t('admin.common.status')}</th>
                  <th className="text-center py-3 px-4 font-medium">{t('admin.holidays.table.colSent')}</th>
                  <th className="text-center py-3 px-4 font-medium">{t('admin.holidays.table.colOpenPct')}</th>
                  <th className="text-center py-3 px-4 font-medium">{t('admin.holidays.table.colReplyPct')}</th>
                  <th className="text-left py-3 px-4 font-medium">{t('admin.holidays.table.colRegions')}</th>
                  <th className="text-right py-3 px-4 font-medium">{t('admin.common.actions')}</th>
                </tr>
              </thead>
              <tbody>
                {holidays.length === 0 && (
                  <tr>
                    <td colSpan={8} className="text-center py-10 text-gray-400 text-xs">{t('admin.holidays.noHolidays')}</td>
                  </tr>
                )}
                {holidays.map(h => (
                  <HolidayRow
                    key={h.id}
                    holiday={h}
                    onEdit={item => setFormModal({ item })}
                    onDelete={handleDelete}
                    onRegions={item => setRegionsModal(item)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          // Calendar view: group by month
          <div className="space-y-6">
            {Object.entries(byMonth).sort(([a], [b]) => a.localeCompare(b)).map(([month, items]) => (
              <div key={month} className="bg-white border border-gray-100 rounded-xl overflow-hidden">
                <div className="px-5 py-3 border-b border-gray-50 text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  {new Date(month + '-01').toLocaleDateString('en-US', { month: 'long', year: 'numeric' })}
                </div>
                <div className="divide-y divide-gray-50">
                  {items.map(h => (
                    <div key={h.id} className="flex items-center justify-between px-5 py-3">
                      <div className="flex items-center gap-3">
                        <span className="text-2xl font-light text-gray-300 w-8 text-center">{h.date.slice(8, 10)}</span>
                        <div>
                          <p className="text-sm font-medium text-gray-900">{h.name}</p>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className={`text-xs ${h.is_active ? 'text-green-600' : 'text-gray-400'}`}>
                              {h.is_active ? t('admin.common.active') : t('admin.common.inactive')}
                            </span>
                            {h.sensitive_regions && (
                              <span className="text-xs text-orange-500">
                                {t('admin.holidays.calendar.blocked', { regions: h.sensitive_regions })}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-gray-400">
                          {t('admin.holidays.calendar.sentCount', { count: h.send_count })}
                        </span>
                        <button onClick={() => setRegionsModal(h)} className="p-1 text-gray-400 hover:text-blue-500"><Globe size={13} /></button>
                        <button onClick={() => setFormModal({ item: h })} className="p-1 text-gray-400 hover:text-gray-600"><Pencil size={13} /></button>
                        <button onClick={() => handleDelete(h.id)} className="p-1 text-gray-400 hover:text-red-500"><Trash2 size={13} /></button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {Object.keys(byMonth).length === 0 && (
              <div className="text-center py-16 text-gray-400 text-sm">{t('admin.holidays.noHolidays')}</div>
            )}
          </div>
        )}
      </div>
    </>
  )
}
