import { useState, useEffect, useCallback } from 'react'
import {
  Plus,
  Pencil,
  Trash2,
  X,
  Loader2,
  Sparkles,
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
  return html.replace(/\{\{(\w+)\}\}/g, (_, key: string) => SAMPLE_VARS[key] ?? `{{${key}}}`)
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
      setError(err instanceof Error ? err.message : 'Save failed')
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
            {editing ? 'Edit Template' : 'New Template'}
          </h2>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPreview((v) => !v)}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-gray-500 hover:text-gray-800 hover:bg-gray-100 rounded-lg transition-colors"
            >
              {preview ? <EyeOff size={13} /> : <Eye size={13} />}
              {preview ? 'Edit' : 'Preview'}
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
                <p className="text-xs text-gray-400 mb-1">Subject preview</p>
                <p className="text-sm font-medium text-gray-900">
                  {renderPreview(form.subject) || '(no subject)'}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-400 mb-1">Body preview</p>
                <div
                  className="prose prose-sm max-w-none text-gray-700 border border-gray-100 rounded-lg p-4 bg-gray-50"
                  dangerouslySetInnerHTML={{ __html: renderPreview(form.body_html) }}
                />
              </div>
              <p className="text-xs text-gray-400">
                Sample values: {Object.entries(SAMPLE_VARS).map(([k, v]) => `{{${k}}} → ${v}`).join(' · ')}
              </p>
            </div>
          ) : (
            <form id="template-form" onSubmit={handleSubmit} className="p-6 space-y-4">
              {/* Name */}
              <div>
                <label className="block text-xs text-gray-500 mb-1">Template Name *</label>
                <input
                  type="text"
                  required
                  value={form.name}
                  onChange={set('name')}
                  placeholder="e.g. Formal Fitness Pitch"
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
                />
              </div>

              {/* Industry + Style + Language */}
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Industry</label>
                  <input
                    type="text"
                    value={form.industry}
                    onChange={set('industry')}
                    placeholder="fitness"
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Style</label>
                  <div className="relative">
                    <select
                      value={form.style}
                      onChange={set('style')}
                      className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400 appearance-none pr-8"
                    >
                      <option value="">— any —</option>
                      <option value="formal">Formal</option>
                      <option value="casual">Casual</option>
                      <option value="direct">Direct</option>
                    </select>
                    <ChevronDown size={13} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Language</label>
                  <input
                    type="text"
                    value={form.language}
                    onChange={set('language')}
                    placeholder="en"
                    className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
                  />
                </div>
              </div>

              {/* Subject */}
              <div>
                <label className="block text-xs text-gray-500 mb-1">Subject *</label>
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
                  <label className="text-xs text-gray-500">Body HTML *</label>
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
            Cancel
          </button>
          <button
            type="submit"
            form="template-form"
            disabled={saving || preview}
            className="flex items-center gap-1.5 px-4 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            {saving && <Loader2 size={13} className="animate-spin" />}
            {editing ? 'Save Changes' : 'Create Template'}
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
      setError(err instanceof Error ? err.message : 'Generation failed')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-xl mx-4 flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-6 pt-6 pb-4 border-b border-gray-100 shrink-0">
          <div className="flex items-center gap-2">
            <Sparkles size={15} className="text-violet-500" />
            <h2 className="text-sm font-semibold text-gray-900">AI Template Generator</h2>
          </div>
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
              placeholder="Industry keyword, e.g. fitness, beauty, gaming"
              className="flex-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-violet-100 focus:border-violet-400"
            />
            <button
              onClick={handleGenerate}
              disabled={generating || !industry.trim()}
              className="flex items-center gap-1.5 px-4 py-2 text-sm bg-violet-600 text-white rounded-lg hover:bg-violet-700 disabled:opacity-50 transition-colors whitespace-nowrap"
            >
              {generating ? (
                <Loader2 size={13} className="animate-spin" />
              ) : (
                <Sparkles size={13} />
              )}
              Generate
            </button>
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}

          {/* Results */}
          {results.length > 0 && (
            <div className="space-y-3">
              <p className="text-xs text-gray-400">
                3 templates generated — expand to preview, then click "Use this template" to edit and save.
              </p>
              {results.map((t, i) => (
                <div key={i} className="border border-gray-100 rounded-xl overflow-hidden">
                  <button
                    type="button"
                    onClick={() => setExpanded(expanded === i ? null : i)}
                    className="w-full flex items-center justify-between px-4 py-3 hover:bg-gray-50 transition-colors text-left"
                  >
                    <div className="flex items-center gap-2">
                      <StyleBadge style={t.style} />
                      <span className="text-sm font-medium text-gray-900">{t.name}</span>
                    </div>
                    <ChevronDown
                      size={14}
                      className={`text-gray-400 transition-transform ${expanded === i ? 'rotate-180' : ''}`}
                    />
                  </button>

                  {expanded === i && (
                    <div className="px-4 pb-4 space-y-3 border-t border-gray-50">
                      <div className="pt-3">
                        <p className="text-xs text-gray-400 mb-1">Subject</p>
                        <p className="text-sm text-gray-700">{renderPreview(t.subject)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-400 mb-1">Preview</p>
                        <div
                          className="prose prose-sm max-w-none text-gray-700 border border-gray-100 rounded-lg p-3 bg-gray-50 text-xs"
                          dangerouslySetInnerHTML={{ __html: renderPreview(t.body_html) }}
                        />
                      </div>
                      <div className="flex justify-end">
                        <button
                          type="button"
                          onClick={() => onSelect(t)}
                          className="px-3 py-1.5 text-xs bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition-colors"
                        >
                          Use this template
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
    if (!window.confirm('Delete this template?')) return
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
    new Set(templates.map((t) => t.industry).filter(Boolean) as string[])
  ).sort()

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Templates</h1>
          <p className="text-xs text-gray-400 mt-0.5">Email templates with variable substitution</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setGeneratePanel(true)}
            className="flex items-center gap-1.5 px-3 py-2 text-sm text-violet-700 bg-violet-50 hover:bg-violet-100 rounded-lg border border-violet-200 transition-colors"
          >
            <Sparkles size={14} />
            AI Generate
          </button>
          <button
            onClick={() => { setPrefill(null); setModal('add') }}
            className="flex items-center gap-1.5 px-3 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition-colors"
          >
            <Plus size={14} />
            New Template
          </button>
        </div>
      </div>

      {/* Industry filter chips */}
      {industries.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs text-gray-400">Filter:</span>
          <button
            onClick={() => setIndustryFilter('')}
            className={`px-2.5 py-1 text-xs rounded-full border transition-colors ${
              industryFilter === ''
                ? 'bg-gray-900 text-white border-gray-900'
                : 'text-gray-600 border-gray-200 hover:bg-gray-50'
            }`}
          >
            All
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
            <span className="text-sm">Loading…</span>
          </div>
        ) : templates.length === 0 ? (
          <div className="py-16 text-center text-sm text-gray-400">
            {industryFilter
              ? `No templates for "${industryFilter}".`
              : 'No templates yet. Create one or use AI Generate.'}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Subject</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Industry</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Style</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Created</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 w-24">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {templates.map((t) => (
                <tr key={t.id} className="hover:bg-gray-50/60 transition-colors">
                  <td className="px-4 py-3">
                    <p className="font-medium text-gray-900 text-xs">{t.name}</p>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500 max-w-[220px] truncate">
                    {t.subject}
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">
                    {t.industry ?? <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <StyleBadge style={t.style} />
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {new Date(t.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        onClick={() => setModal(t)}
                        title="Edit"
                        className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        onClick={() => handleDelete(t.id)}
                        disabled={deletingId === t.id}
                        title="Delete"
                        className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors disabled:opacity-50"
                      >
                        {deletingId === t.id ? (
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
