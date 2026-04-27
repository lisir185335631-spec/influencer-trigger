import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import DOMPurify from 'dompurify'
import {
  Plus,
  Pencil,
  Trash2,
  X,
  Loader2,
  Eye,
  EyeOff,
  ChevronDown,
} from 'lucide-react'
import {
  Template,
  TemplateCreate,
  TemplateUpdate,
  GeneratedTemplate,
  templatesApi,
} from '../api/templates'

// ─── Helpers ─────────────────────────────────────────────────────────────────

const STYLE_COLORS: Record<string, string> = {
  formal: 'bg-blue-50 text-blue-700 ring-1 ring-blue-200',
  casual: 'bg-amber-50 text-amber-700 ring-1 ring-amber-200',
  direct: 'bg-violet-50 text-violet-700 ring-1 ring-violet-200',
}

function StyleBadge({ style }: { style: string | null }) {
  if (!style) return null
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
        STYLE_COLORS[style] ?? 'bg-gray-50 text-gray-500 ring-1 ring-gray-200'
      }`}
    >
      {style}
    </span>
  )
}

const SAMPLE_VARS: Record<string, string> = {
  influencer_name: 'Alex Johnson',
  platform: 'Instagram',
  followers: '120K',
  industry: 'fitness',
}

function renderPreview(html: string): string {
  const replaced = html.replace(/\{\{(\w+)\}\}/g, (_, key: string) => SAMPLE_VARS[key] ?? `{{${key}}}`)
  return DOMPurify.sanitize(replaced)
}

// ─── Template Form Modal ──────────────────────────────────────────────────────

type ModalProps = {
  editing: Template | null
  prefill?: GeneratedTemplate | null
  onClose: () => void
  onSaved: (t: Template) => void
}

type FormValues = {
  name: string
  subject: string
  body_html: string
  industry: string
  style: string
  language: string
}

const EMPTY_FORM: FormValues = {
  name: '',
  subject: '',
  body_html: '',
  industry: '',
  style: '',
  language: 'en',
}

function templateToForm(t: Template): FormValues {
  return {
    name: t.name,
    subject: t.subject,
    body_html: t.body_html,
    industry: t.industry ?? '',
    style: t.style ?? '',
    language: t.language,
  }
}

function generatedToForm(g: GeneratedTemplate): FormValues {
  return {
    name: g.name,
    subject: g.subject,
    body_html: g.body_html,
    industry: '',
    style: g.style,
    language: 'en',
  }
}

function TemplateModal({ editing, prefill, onClose, onSaved }: ModalProps) {
  const { t } = useTranslation()
  const [form, setForm] = useState<FormValues>(
    editing
      ? templateToForm(editing)
      : prefill
        ? generatedToForm(prefill)
        : EMPTY_FORM
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [preview, setPreview] = useState(false)

  const set =
    (field: keyof FormValues) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
      setForm((prev) => ({ ...prev, [field]: e.target.value }))
    }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      if (editing) {
        const payload: TemplateUpdate = {
          name: form.name,
          subject: form.subject,
          body_html: form.body_html,
          industry: form.industry || undefined,
          style: form.style || undefined,
          language: form.language,
        }
        const updated = await templatesApi.update(editing.id, payload)
        onSaved(updated)
      } else {
        const payload: TemplateCreate = {
          name: form.name,
          subject: form.subject,
          body_html: form.body_html,
          industry: form.industry || undefined,
          style: form.style || undefined,
          language: form.language,
        }
        const created = await templatesApi.create(payload)
        onSaved(created)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t('templates.modal.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl mx-4 flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4 border-b border-gray-100 shrink-0">
          <h2 className="text-sm font-semibold text-gray-900">
            {editing ? t('templates.modal.editTitle') : t('templates.modal.newTitle')}
          </h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPreview((v) => !v)}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
            >
              {preview ? <EyeOff size={13} /> : <Eye size={13} />}
              {preview ? t('templates.modal.editTab') : t('templates.modal.previewTab')}
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
              <X size={16} />
            </button>
          </div>
        </div>

        <div className="overflow-y-auto flex-1">
          {preview ? (
            <div className="p-6 space-y-3">
              <div>
                <p className="text-xs text-gray-400 mb-1">{t('templates.modal.subjectPreview')}</p>
                <p className="text-sm font-medium text-gray-900">
                  {renderPreview(form.subject) || t('templates.modal.noSubject')}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-400 mb-1">{t('templates.modal.bodyPreview')}</p>
                <div
                  className="prose prose-sm max-w-none text-gray-700 border border-gray-100 rounded-lg p-4 bg-gray-50"
                  dangerouslySetInnerHTML={{ __html: renderPreview(form.body_html) }}
                />
              </div>
              <p className="text-xs text-gray-400">
                {t('templates.modal.sampleValues')}
              </p>
            </div>
          ) : (
            <form id="template-form" onSubmit={handleSubmit} className="p-6 space-y-4">
              {/* Name */}
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('templates.modal.nameLabel')}</label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={set('name')}
                  placeholder={t('templates.modal.namePlaceholder')}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
                />
              </div>

              {/* Industry + Style + Language */}
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('templates.modal.industryLabel')}</label>
                  <input
                    type="text"
                    value={form.industry}
                    onChange={set('industry')}
                    placeholder={t('templates.modal.industryPlaceholder')}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('templates.modal.styleLabel')}</label>
                  <div className="relative">
                    <select
                      value={form.style}
                      onChange={set('style')}
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400 appearance-none pr-8"
                    >
                      <option value="">{t('templates.modal.anyStyle')}</option>
                      <option value="formal">{t('templates.modal.formal')}</option>
                      <option value="casual">{t('templates.modal.casual')}</option>
                      <option value="direct">{t('templates.modal.direct')}</option>
                    </select>
                    <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">{t('templates.modal.languageLabel')}</label>
                  <input
                    type="text"
                    value={form.language}
                    onChange={set('language')}
                    placeholder={t('templates.modal.languagePlaceholder')}
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
                  />
                </div>
              </div>

              {/* Subject */}
              <div>
                <label className="block text-xs text-gray-500 mb-1">{t('templates.modal.subjectLabel')}</label>
                <input
                  type="text"
                  required
                  value={form.subject}
                  onChange={set('subject')}
                  placeholder="Use {{influencer_name}}, {{platform}}, etc."
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
                />
              </div>

              {/* Body */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs text-gray-500">{t('templates.modal.bodyLabel')}</label>
                  <span className="text-xs text-gray-400">
                    {'{{influencer_name}}'} {'{{platform}}'} {'{{followers}}'} {'{{industry}}'}
                  </span>
                </div>
                <textarea
                  required
                  value={form.body_html}
                  onChange={set('body_html')}
                  rows={10}
                  placeholder="<p>Dear {{influencer_name}},</p><p>...</p>"
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400 font-mono text-xs leading-relaxed"
                />
              </div>

              {error && <p className="text-xs text-red-500">{error}</p>}
            </form>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-100 shrink-0">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            type="submit"
            form="template-form"
            disabled={saving || preview}
            className="flex items-center gap-1.5 px-4 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            {saving && <Loader2 size={13} className="animate-spin" />}
            {editing ? t('templates.modal.saveChanges') : t('templates.modal.createTemplate')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── AI Generate Panel ────────────────────────────────────────────────────────

type GeneratePanelProps = {
  onClose: () => void
  onSelect: (t: GeneratedTemplate) => void
}

function GeneratePanel({ onClose, onSelect }: GeneratePanelProps) {
  const { t } = useTranslation()
  const [industry, setIndustry] = useState('')
  const [generating, setGenerating] = useState(false)
  const [results, setResults] = useState<GeneratedTemplate[]>([])
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)

  async function handleGenerate() {
    if (!industry.trim()) return
    setGenerating(true)
    setError('')
    setResults([])
    try {
      const data = await templatesApi.generate(industry.trim())
      setResults(data)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : t('templates.ai.generateFailed'))
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-xl mx-4 flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4 border-b border-gray-100 shrink-0">
          <h2 className="text-sm font-semibold text-gray-900">{t('templates.ai.title')}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="overflow-y-auto flex-1 p-6 space-y-4">
          {/* Input */}
          <div className="flex gap-2">
            <input
              type="text"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleGenerate()}
              placeholder={t('templates.ai.placeholder')}
              className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-violet-100 focus:border-violet-400"
            />
            <button
              onClick={handleGenerate}
              disabled={generating || !industry.trim()}
              className="flex items-center gap-1.5 px-4 py-2 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              {generating && (
                <Loader2 size={13} className="animate-spin" />
              )}
              {t('templates.ai.generate')}
            </button>
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}

          {/* Results */}
          {results.length > 0 && (
            <div className="space-y-3">
              <p className="text-xs text-gray-400">
                {t('templates.ai.generatedHint')}
              </p>
              {results.map((tpl, i) => (
                <div key={i} className="border border-gray-100 rounded-xl overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setExpanded(expanded === i ? null : i)}
                    className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors text-left"
                  >
                    <div className="flex items-center gap-2">
                      <StyleBadge style={tpl.style} />
                      <span className="text-sm font-medium text-gray-900">{tpl.name}</span>
                    </div>
                    <ChevronDown
                      size={14}
                      className={`text-gray-400 transition-transform ${expanded === i ? 'rotate-180' : ''}`}
                    />
                  </button>

                  {expanded === i && (
                    <div className="px-4 pb-4 space-y-3 border-t border-gray-50">
                      <div className="pt-3">
                        <p className="text-xs text-gray-400 mb-1">{t('templates.ai.subject')}</p>
                        <p className="text-sm text-gray-700">{renderPreview(tpl.subject)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-400 mb-1">{t('templates.ai.preview')}</p>
                        <div
                          className="prose prose-sm max-w-none text-gray-700 border border-gray-100 rounded-lg p-3 bg-gray-50 text-xs"
                          dangerouslySetInnerHTML={{ __html: renderPreview(tpl.body_html) }}
                        />
                      </div>
                      <div className="flex justify-end">
                        <button
                          type="button"
                          onClick={() => onSelect(tpl)}
                          className="px-3 py-1.5 text-xs bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition-colors"
                        >
                          {t('templates.ai.useTemplate')}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function TemplatesPage() {
  const { t } = useTranslation()
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)
  const [industryFilter, setIndustryFilter] = useState('')
  const [modal, setModal] = useState<'add' | Template | null>(null)
  const [generatePanel, setGeneratePanel] = useState(false)
  const [prefill, setPrefill] = useState<GeneratedTemplate | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const fetchTemplates = useCallback(async () => {
    try {
      const data = await templatesApi.list(industryFilter || undefined)
      setTemplates(data)
    } catch {
      /* silent */
    } finally {
      setLoading(false)
    }
  }, [industryFilter])

  useEffect(() => { fetchTemplates() }, [fetchTemplates])

  function handleSaved(t: Template) {
    setTemplates((prev) => {
      const idx = prev.findIndex((x) => x.id === t.id)
      if (idx >= 0) {
        const next = [...prev]
        next[idx] = t
        return next
      }
      return [t, ...prev]
    })
    setModal(null)
    setPrefill(null)
  }

  async function handleDelete(id: number) {
    if (!window.confirm(t('templates.deleteConfirm'))) return
    setDeletingId(id)
    try {
      await templatesApi.delete(id)
      setTemplates((prev) => prev.filter((t) => t.id !== id))
    } finally {
      setDeletingId(null)
    }
  }

  function handleSelectGenerated(t: GeneratedTemplate) {
    setPrefill(t)
    setGeneratePanel(false)
    setModal('add')
  }

  // Collect unique industries for filter chip bar
  const industries = Array.from(
    new Set(templates.map((tpl) => tpl.industry).filter(Boolean) as string[])
  ).sort()

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-gray-900">{t('templates.title')}</h1>
          <p className="text-xs text-gray-400 mt-0.5">{t('templates.subtitle')}</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setGeneratePanel(true)}
            className="flex items-center gap-1.5 px-3 py-2 text-sm text-violet-700 bg-violet-50 hover:bg-violet-100 rounded-lg border border-violet-200 transition-colors"
          >
            {t('templates.aiGenerate')}
          </button>
          <button
            onClick={() => { setPrefill(null); setModal('add') }}
            className="flex items-center gap-1.5 px-3 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition-colors"
          >
            <Plus size={14} />
            {t('templates.newTemplate')}
          </button>
        </div>
      </div>

      {/* Industry filter chips */}
      {industries.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-gray-400">{t('templates.filter')}</span>
          <button
            onClick={() => setIndustryFilter('')}
            className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
              industryFilter === ''
                ? 'bg-gray-900 text-white border-gray-900'
                : 'text-gray-600 border-gray-200 hover:bg-gray-50'
            }`}
          >
            {t('templates.all')}
          </button>
          {industries.map((ind) => (
            <button
              key={ind}
              onClick={() => setIndustryFilter(industryFilter === ind ? '' : ind)}
              className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
                industryFilter === ind
                  ? 'bg-gray-900 text-white border-gray-900'
                  : 'text-gray-600 border-gray-200 hover:bg-gray-50'
              }`}
            >
              {ind}
            </button>
          ))}
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <Loader2 size={18} className="animate-spin mr-2" />
            <span className="text-sm">{t('templates.loading')}</span>
          </div>
        ) : templates.length === 0 ? (
          <div className="py-16 text-center text-sm text-gray-400">
            {industryFilter
              ? t('templates.noTemplatesFor', { filter: industryFilter })
              : t('templates.noTemplates')}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('templates.table.name')}</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('templates.table.subject')}</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('templates.table.industry')}</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('templates.table.style')}</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">{t('templates.table.created')}</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 w-24">{t('templates.table.actions')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {templates.map((tpl) => (
                <tr key={tpl.id} className="hover:bg-gray-50/60 transition-colors">
                  <td className="px-4 py-3">
                    <p className="font-medium text-gray-900 text-xs">{tpl.name}</p>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500 max-w-[220px] truncate">
                    {tpl.subject}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {tpl.industry ?? <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <StyleBadge style={tpl.style} />
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {new Date(tpl.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => setModal(tpl)}
                        title={t('common.edit')}
                        className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        onClick={() => handleDelete(tpl.id)}
                        disabled={deletingId === tpl.id}
                        title={t('common.delete')}
                        className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors disabled:opacity-50"
                      >
                        {deletingId === tpl.id ? (
                          <Loader2 size={13} className="animate-spin" />
                        ) : (
                          <Trash2 size={13} />
                        )}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Modals */}
      {generatePanel && (
        <GeneratePanel
          onClose={() => setGeneratePanel(false)}
          onSelect={handleSelectGenerated}
        />
      )}

      {modal !== null && (
        <TemplateModal
          editing={modal === 'add' ? null : modal}
          prefill={modal === 'add' ? prefill : null}
          onClose={() => { setModal(null); setPrefill(null) }}
          onSaved={handleSaved}
        />
      )}
    </div>
  )
}
