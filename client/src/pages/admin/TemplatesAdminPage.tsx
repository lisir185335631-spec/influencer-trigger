import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, Check, Eye, EyeOff, Plus, ScanLine, Trash2, X } from 'lucide-react'
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
} from 'recharts'
import {
  type ComplianceKeyword,
  type TemplateAdminItem,
  type TemplateRankingItem,
  complianceScan,
  createKeyword,
  deleteKeyword,
  getTemplatesRanking,
  listAdminTemplates,
  listKeywords,
  publishTemplate,
  unpublishTemplate,
} from '../../api/admin/templates_admin'

type Tab = 'review' | 'ranking' | 'keywords'

const SEVERITY_COLORS: Record<string, string> = {
  low: 'text-yellow-700 bg-yellow-50',
  medium: 'text-orange-700 bg-orange-50',
  high: 'text-red-700 bg-red-50',
}

const BAR_COLORS = ['#6366f1', '#8b5cf6', '#a78bfa', '#c4b5fd', '#ddd6fe']

// ─── Preview Modal ─────────────────────────────────────────────────────────────

function PreviewModal({ tmpl, onClose }: { tmpl: TemplateAdminItem; onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-xl p-7 w-[600px] max-w-[92vw] max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900 truncate pr-4">{tmpl.name}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 shrink-0">
            <X size={16} />
          </button>
        </div>
        <div className="text-xs text-gray-500 mb-3">
          {t('admin.templates.preview.subject')}: <span className="text-gray-800">{tmpl.subject}</span>
        </div>
        <div
          className="flex-1 overflow-auto border border-gray-100 rounded-lg p-4 text-sm text-gray-700"
          dangerouslySetInnerHTML={{ __html: tmpl.body_html }}
        />
      </div>
    </div>
  )
}

// ─── Templates Review Tab ──────────────────────────────────────────────────────

function TemplatesReviewTab() {
  const { t } = useTranslation()
  const [items, setItems] = useState<TemplateAdminItem[]>([])
  const [loading, setLoading] = useState(true)
  const [preview, setPreview] = useState<TemplateAdminItem | null>(null)
  const [scanning, setScanning] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listAdminTemplates()
      setItems(data.items)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handlePublish = async (id: number) => {
    await publishTemplate(id)
    setItems(prev => prev.map(tmpl => tmpl.id === id ? { ...tmpl, is_published: true } : tmpl))
  }

  const handleUnpublish = async (id: number) => {
    await unpublishTemplate(id)
    setItems(prev => prev.map(tmpl => tmpl.id === id ? { ...tmpl, is_published: false } : tmpl))
  }

  const handleScan = async (id: number) => {
    setScanning(id)
    try {
      const res = await complianceScan(id)
      setItems(prev => prev.map(tmpl => tmpl.id === id ? { ...tmpl, compliance_flags: res.compliance_flags } : tmpl))
    } finally {
      setScanning(null)
    }
  }

  if (loading) return <div className="text-center py-16 text-gray-400 text-sm">{t('admin.common.loading')}</div>

  return (
    <>
      {preview && <PreviewModal tmpl={preview} onClose={() => setPreview(null)} />}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 text-xs text-gray-500 uppercase tracking-wide">
              <th className="text-left py-3 px-4 font-medium">{t('admin.templates.review.colTemplate')}</th>
              <th className="text-left py-3 px-4 font-medium">{t('admin.templates.review.colCreator')}</th>
              <th className="text-right py-3 px-4 font-medium">{t('admin.templates.review.colUsage')}</th>
              <th className="text-right py-3 px-4 font-medium">{t('admin.templates.review.colSuccess')}</th>
              <th className="text-left py-3 px-4 font-medium">{t('admin.templates.review.colFlags')}</th>
              <th className="text-center py-3 px-4 font-medium">{t('admin.common.status')}</th>
              <th className="text-right py-3 px-4 font-medium">{t('admin.common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {items.map(tmpl => (
              <tr key={tmpl.id} className="border-b border-gray-50 hover:bg-gray-50/50">
                <td className="py-3 px-4">
                  <div className="font-medium text-gray-900 max-w-[200px] truncate">{tmpl.name}</div>
                  <div className="text-xs text-gray-400">{tmpl.industry ?? '—'} · {tmpl.style ?? '—'}</div>
                </td>
                <td className="py-3 px-4 text-gray-600">{tmpl.creator_username ?? '—'}</td>
                <td className="py-3 px-4 text-right text-gray-700">{tmpl.usage_count}</td>
                <td className="py-3 px-4 text-right text-gray-700">{tmpl.send_success_rate}%</td>
                <td className="py-3 px-4">
                  {tmpl.compliance_flags ? (
                    <span className="flex flex-wrap gap-1 max-w-[160px]">
                      {tmpl.compliance_flags.split(',').map(f => (
                        <span key={f} className="text-xs px-1.5 py-0.5 rounded bg-red-50 text-red-600">{f}</span>
                      ))}
                    </span>
                  ) : <span className="text-gray-300 text-xs">{t('admin.templates.review.clean')}</span>}
                </td>
                <td className="py-3 px-4 text-center">
                  {tmpl.is_published ? (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-green-50 text-green-700 font-medium">
                      {t('admin.templates.status.published')}
                    </span>
                  ) : (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
                      {t('admin.templates.status.unpublished')}
                    </span>
                  )}
                </td>
                <td className="py-3 px-4">
                  <div className="flex items-center justify-end gap-2">
                    <button
                      onClick={() => setPreview(tmpl)}
                      className="p-1.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-700"
                      title={t('admin.templates.actions.preview')}
                    >
                      <Eye size={14} />
                    </button>
                    <button
                      onClick={() => handleScan(tmpl.id)}
                      disabled={scanning === tmpl.id}
                      className="p-1.5 rounded hover:bg-blue-50 text-gray-400 hover:text-blue-600 disabled:opacity-40"
                      title={t('admin.templates.actions.scan')}
                    >
                      <ScanLine size={14} />
                    </button>
                    {tmpl.is_published ? (
                      <button
                        onClick={() => handleUnpublish(tmpl.id)}
                        className="p-1.5 rounded hover:bg-orange-50 text-gray-400 hover:text-orange-600"
                        title={t('admin.templates.actions.unpublish')}
                      >
                        <EyeOff size={14} />
                      </button>
                    ) : (
                      <button
                        onClick={() => handlePublish(tmpl.id)}
                        className="p-1.5 rounded hover:bg-green-50 text-gray-400 hover:text-green-600"
                        title={t('admin.templates.actions.publish')}
                      >
                        <Check size={14} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={7} className="py-16 text-center text-gray-400 text-sm">{t('admin.templates.review.noTemplates')}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  )
}

// ─── Ranking Tab ───────────────────────────────────────────────────────────────

function RankingTab() {
  const { t } = useTranslation()
  const [items, setItems] = useState<TemplateRankingItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getTemplatesRanking().then(d => setItems(d.items)).finally(() => setLoading(false))
  }, [])

  if (loading) return <div className="text-center py-16 text-gray-400 text-sm">{t('admin.common.loading')}</div>

  return (
    <div className="space-y-8">
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={items} margin={{ top: 4, right: 16, bottom: 60, left: 0 }}>
            <XAxis
              dataKey="name"
              tick={{ fontSize: 11, fill: '#9ca3af' }}
              angle={-35}
              textAnchor="end"
              interval={0}
            />
            <YAxis tick={{ fontSize: 11, fill: '#9ca3af' }} />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8, border: '1px solid #e5e7eb' }}
            />
            <Bar dataKey="usage_count" name={t('admin.templates.ranking.usageBarName')} radius={[4, 4, 0, 0]}>
              {items.map((_, i) => (
                <Cell key={i} fill={BAR_COLORS[i % BAR_COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-100 text-xs text-gray-500 uppercase tracking-wide">
            <th className="text-left py-2 px-4 font-medium">{t('admin.templates.ranking.colRank')}</th>
            <th className="text-left py-2 px-4 font-medium">{t('admin.templates.ranking.colTemplate')}</th>
            <th className="text-left py-2 px-4 font-medium">{t('admin.templates.ranking.colIndustry')}</th>
            <th className="text-center py-2 px-4 font-medium">{t('admin.common.status')}</th>
            <th className="text-right py-2 px-4 font-medium">{t('admin.templates.ranking.colUsage')}</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr key={item.id} className="border-b border-gray-50 hover:bg-gray-50/50">
              <td className="py-2.5 px-4 text-gray-400 font-medium">#{idx + 1}</td>
              <td className="py-2.5 px-4 font-medium text-gray-900 max-w-[220px] truncate">{item.name}</td>
              <td className="py-2.5 px-4 text-gray-500">{item.industry ?? '—'}</td>
              <td className="py-2.5 px-4 text-center">
                {item.is_published ? (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-green-50 text-green-700">
                    {t('admin.templates.status.published')}
                  </span>
                ) : (
                  <span className="text-xs px-2 py-0.5 rounded-full bg-gray-100 text-gray-500">
                    {t('admin.templates.status.unpublished')}
                  </span>
                )}
              </td>
              <td className="py-2.5 px-4 text-right text-gray-700 font-medium">{item.usage_count}</td>
            </tr>
          ))}
          {items.length === 0 && (
            <tr><td colSpan={5} className="py-12 text-center text-gray-400 text-sm">{t('admin.common.noData')}</td></tr>
          )}
        </tbody>
      </table>
    </div>
  )
}

// ─── Keywords Tab ──────────────────────────────────────────────────────────────

const KEYWORD_CATEGORIES = ['政治', '暴力', '色情', '其他']
const KEYWORD_SEVERITIES = ['low', 'medium', 'high']

function KeywordsTab() {
  const { t } = useTranslation()
  const [items, setItems] = useState<ComplianceKeyword[]>([])
  const [loading, setLoading] = useState(true)
  const [form, setForm] = useState({ keyword: '', category: '政治', severity: 'medium' })
  const [adding, setAdding] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listKeywords()
      setItems(data.items)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const handleAdd = async () => {
    if (!form.keyword.trim()) return
    setAdding(true)
    try {
      const kw = await createKeyword(form.keyword.trim(), form.category, form.severity)
      setItems(prev => [{ ...kw, created_at: new Date().toISOString() }, ...prev])
      setForm(f => ({ ...f, keyword: '' }))
    } catch {
      // keyword may already exist
    } finally {
      setAdding(false)
    }
  }

  const handleDelete = async (id: number) => {
    await deleteKeyword(id)
    setItems(prev => prev.filter(kw => kw.id !== id))
    setConfirmDelete(null)
  }

  return (
    <>
      {confirmDelete !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl shadow-xl p-7 w-[360px]">
            <div className="flex items-center gap-3 mb-4">
              <AlertTriangle className="text-red-500 shrink-0" size={20} />
              <h2 className="text-base font-semibold text-gray-900">{t('admin.templates.keywords.deleteTitle')}</h2>
            </div>
            <p className="text-sm text-gray-600 mb-6">{t('admin.templates.keywords.deleteMessage')}</p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setConfirmDelete(null)}
                className="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
              >{t('admin.common.cancel')}</button>
              <button
                onClick={() => handleDelete(confirmDelete)}
                className="px-4 py-2 text-sm rounded-lg bg-red-600 text-white hover:bg-red-700 font-medium"
              >{t('admin.common.delete')}</button>
            </div>
          </div>
        </div>
      )}

      <div className="mb-6 p-4 bg-gray-50 rounded-xl flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[160px]">
          <label className="block text-xs text-gray-500 mb-1">{t('admin.templates.keywords.labelKeyword')}</label>
          <input
            type="text"
            value={form.keyword}
            onChange={e => setForm(f => ({ ...f, keyword: e.target.value }))}
            onKeyDown={e => e.key === 'Enter' && handleAdd()}
            placeholder={t('admin.templates.keywords.keywordPlaceholder')}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">{t('admin.templates.keywords.labelCategory')}</label>
          <select
            value={form.category}
            onChange={e => setForm(f => ({ ...f, category: e.target.value }))}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
          >
            {KEYWORD_CATEGORIES.map(c => <option key={c}>{c}</option>)}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">{t('admin.templates.keywords.labelSeverity')}</label>
          <select
            value={form.severity}
            onChange={e => setForm(f => ({ ...f, severity: e.target.value }))}
            className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-300"
          >
            {KEYWORD_SEVERITIES.map(s => (
              <option key={s} value={s}>{t(`admin.templates.keywords.severity.${s}`)}</option>
            ))}
          </select>
        </div>
        <button
          onClick={handleAdd}
          disabled={adding || !form.keyword.trim()}
          className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-indigo-600 text-white text-sm font-medium hover:bg-indigo-700 disabled:opacity-40"
        >
          <Plus size={14} />
          {t('admin.common.add')}
        </button>
      </div>

      {loading ? (
        <div className="text-center py-12 text-gray-400 text-sm">{t('admin.common.loading')}</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 text-xs text-gray-500 uppercase tracking-wide">
              <th className="text-left py-2 px-4 font-medium">{t('admin.templates.keywords.labelKeyword')}</th>
              <th className="text-left py-2 px-4 font-medium">{t('admin.templates.keywords.labelCategory')}</th>
              <th className="text-left py-2 px-4 font-medium">{t('admin.templates.keywords.labelSeverity')}</th>
              <th className="text-left py-2 px-4 font-medium">{t('admin.templates.keywords.colAdded')}</th>
              <th className="text-right py-2 px-4 font-medium">{t('admin.common.actions')}</th>
            </tr>
          </thead>
          <tbody>
            {items.map(kw => (
              <tr key={kw.id} className="border-b border-gray-50 hover:bg-gray-50/50">
                <td className="py-2.5 px-4 font-mono text-gray-800">{kw.keyword}</td>
                <td className="py-2.5 px-4 text-gray-600">{kw.category}</td>
                <td className="py-2.5 px-4">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${SEVERITY_COLORS[kw.severity] ?? ''}`}>
                    {t(`admin.templates.keywords.severity.${kw.severity}`)}
                  </span>
                </td>
                <td className="py-2.5 px-4 text-gray-400 text-xs">
                  {new Date(kw.created_at).toLocaleDateString()}
                </td>
                <td className="py-2.5 px-4 text-right">
                  <button
                    onClick={() => setConfirmDelete(kw.id)}
                    className="p-1.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-600"
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr><td colSpan={5} className="py-12 text-center text-gray-400 text-sm">{t('admin.templates.keywords.noKeywords')}</td></tr>
            )}
          </tbody>
        </table>
      )}
    </>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

const TAB_KEYS: Tab[] = ['review', 'ranking', 'keywords']

export default function TemplatesAdminPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('review')

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">{t('admin.templates.title')}</h1>
        <p className="text-sm text-gray-500 mt-1">{t('admin.templates.subtitle')}</p>
      </div>

      <div className="flex gap-1 mb-6 border-b border-gray-100">
        {TAB_KEYS.map(tabKey => (
          <button
            key={tabKey}
            onClick={() => setTab(tabKey)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === tabKey
                ? 'border-indigo-600 text-indigo-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t(`admin.templates.tabs.${tabKey}`)}
          </button>
        ))}
      </div>

      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        {tab === 'review' && <TemplatesReviewTab />}
        {tab === 'ranking' && <div className="p-6"><RankingTab /></div>}
        {tab === 'keywords' && <div className="p-6"><KeywordsTab /></div>}
      </div>
    </div>
  )
}
