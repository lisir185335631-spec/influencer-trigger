import { useCallback, useRef, useState } from 'react'
import { Upload, FileSpreadsheet, AlertCircle, CheckCircle2, X, ChevronDown } from 'lucide-react'
import {
  ColumnMappingItem,
  ImportPreviewResponse,
  ImportConfirmResponse,
  FIELD_OPTIONS,
  importApi,
} from '../api/import_'

// ─── Email regex (mirrors backend) ───────────────────────────────────────────
const EMAIL_RE = /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/

function isValidEmail(v: string): boolean {
  return EMAIL_RE.test(v.trim())
}

// ─── Stage types ─────────────────────────────────────────────────────────────
type Stage = 'upload' | 'preview' | 'done'

// ─── Column mapping selector ─────────────────────────────────────────────────
function MappingSelect({
  value,
  onChange,
}: {
  value: string | null
  onChange: (v: string | null) => void
}) {
  return (
    <div className="relative">
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        className="appearance-none w-full text-xs border border-gray-200 rounded px-2 py-1 pr-6 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-400"
      >
        <option value="">— skip —</option>
        {FIELD_OPTIONS.map((f) => (
          <option key={f.value} value={f.value}>
            {f.label}
          </option>
        ))}
      </select>
      <ChevronDown size={12} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
    </div>
  )
}

// ─── Upload zone ─────────────────────────────────────────────────────────────
function UploadZone({ onFile }: { onFile: (f: File) => void }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [error, setError] = useState('')

  const validate = (f: File): boolean => {
    const ext = f.name.split('.').pop()?.toLowerCase()
    if (!ext || !['csv', 'xlsx', 'xls'].includes(ext)) {
      setError('Only .csv, .xlsx, .xls files are allowed.')
      return false
    }
    setError('')
    return true
  }

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      setDragOver(false)
      const file = e.dataTransfer.files[0]
      if (file && validate(file)) onFile(file)
    },
    [onFile],
  )

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file && validate(file)) onFile(file)
  }

  return (
    <div className="flex flex-col items-center justify-center h-full gap-6">
      <div
        onDrop={handleDrop}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onClick={() => inputRef.current?.click()}
        className={`w-full max-w-lg border-2 border-dashed rounded-xl p-12 flex flex-col items-center gap-4 cursor-pointer transition-colors ${
          dragOver ? 'border-gray-400 bg-gray-50' : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
        }`}
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-gray-100">
          <Upload size={24} className="text-gray-500" />
        </div>
        <div className="text-center">
          <p className="text-sm font-medium text-gray-700">Drop your file here, or click to browse</p>
          <p className="mt-1 text-xs text-gray-400">Supports .csv, .xlsx, .xls</p>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".csv,.xlsx,.xls"
          className="hidden"
          onChange={handleChange}
        />
      </div>
      {error && (
        <p className="flex items-center gap-1.5 text-sm text-red-600">
          <AlertCircle size={14} />
          {error}
        </p>
      )}
    </div>
  )
}

// ─── Preview + mapping stage ──────────────────────────────────────────────────
function PreviewStage({
  file,
  preview,
  mapping,
  overwrite,
  onMappingChange,
  onOverwriteChange,
  onConfirm,
  onReset,
  confirming,
}: {
  file: File
  preview: ImportPreviewResponse
  mapping: ColumnMappingItem[]
  overwrite: boolean
  onMappingChange: (idx: number, field: string | null) => void
  onOverwriteChange: (v: boolean) => void
  onConfirm: () => void
  onReset: () => void
  confirming: boolean
}) {
  // Find which csv_column maps to 'email'
  const emailCsvCol = mapping.find((m) => m.field === 'email')?.csv_column ?? null
  const hasEmail = emailCsvCol !== null

  return (
    <div className="flex flex-col h-full">
      {/* Header bar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-100 shrink-0">
        <div className="flex items-center gap-2">
          <FileSpreadsheet size={16} className="text-gray-500" />
          <span className="text-sm font-medium text-gray-800">{file.name}</span>
          <span className="text-xs text-gray-400">· {preview.total_rows} rows</span>
        </div>
        <button onClick={onReset} className="text-gray-400 hover:text-gray-600 transition-colors">
          <X size={16} />
        </button>
      </div>

      {/* Column mapping */}
      <div className="px-6 py-4 border-b border-gray-100 shrink-0">
        <p className="text-xs font-medium text-gray-500 mb-3 uppercase tracking-wide">Column Mapping</p>
        <div className="flex flex-wrap gap-3">
          {mapping.map((m, idx) => (
            <div key={m.csv_column} className="flex flex-col gap-1 min-w-[140px]">
              <span className="text-xs text-gray-500 truncate" title={m.csv_column}>
                {m.csv_column}
              </span>
              <MappingSelect
                value={m.field}
                onChange={(v) => onMappingChange(idx, v)}
              />
            </div>
          ))}
        </div>
        {!hasEmail && (
          <p className="mt-2 flex items-center gap-1 text-xs text-amber-600">
            <AlertCircle size={12} />
            Please map a column to <strong>Email</strong> before importing.
          </p>
        )}
      </div>

      {/* Preview table */}
      <div className="flex-1 overflow-auto px-6 py-4">
        <p className="text-xs font-medium text-gray-500 mb-3 uppercase tracking-wide">
          Preview (first {preview.rows.length} of {preview.total_rows} rows)
        </p>
        <div className="overflow-x-auto border border-gray-100 rounded-lg">
          <table className="min-w-full text-xs">
            <thead>
              <tr className="bg-gray-50 border-b border-gray-100">
                <th className="px-3 py-2 text-left font-medium text-gray-500">#</th>
                {preview.columns.map((col) => {
                  const m = mapping.find((x) => x.csv_column === col)
                  return (
                    <th key={col} className="px-3 py-2 text-left font-medium text-gray-500 whitespace-nowrap">
                      <span>{col}</span>
                      {m?.field && (
                        <span className="ml-1 text-gray-400 font-normal">→ {m.field}</span>
                      )}
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, i) => {
                const emailVal = emailCsvCol ? String(row[emailCsvCol] ?? '') : ''
                const emailInvalid = emailCsvCol && emailVal && !isValidEmail(emailVal)
                return (
                  <tr key={i} className="border-b border-gray-50 last:border-0 hover:bg-gray-50">
                    <td className="px-3 py-2 text-gray-400">{i + 1}</td>
                    {preview.columns.map((col) => {
                      const val = String(row[col] ?? '')
                      const isEmailCol = col === emailCsvCol
                      const cellInvalid = isEmailCol && emailInvalid
                      return (
                        <td
                          key={col}
                          className={`px-3 py-2 whitespace-nowrap ${
                            cellInvalid
                              ? 'text-red-600 bg-red-50 font-medium'
                              : 'text-gray-700'
                          }`}
                          title={cellInvalid ? 'Invalid email format' : undefined}
                        >
                          {val || <span className="text-gray-300">—</span>}
                          {cellInvalid && (
                            <AlertCircle size={10} className="inline ml-1 text-red-400" />
                          )}
                        </td>
                      )
                    })}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Footer actions */}
      <div className="flex items-center justify-between px-6 py-4 border-t border-gray-100 shrink-0 bg-white">
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={overwrite}
            onChange={(e) => onOverwriteChange(e.target.checked)}
            className="rounded border-gray-300 text-gray-900 focus:ring-gray-400"
          />
          <span className="text-xs text-gray-600">Overwrite duplicates</span>
          <span className="text-xs text-gray-400">(uncheck = skip existing emails)</span>
        </label>
        <button
          onClick={onConfirm}
          disabled={!hasEmail || confirming}
          className="flex items-center gap-2 px-4 py-2 text-sm font-medium bg-gray-900 text-white rounded-lg hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          {confirming ? (
            <>
              <span className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              Importing…
            </>
          ) : (
            <>Import {preview.total_rows} rows</>
          )}
        </button>
      </div>
    </div>
  )
}

// ─── Result stage ─────────────────────────────────────────────────────────────
function ResultStage({
  result,
  onReset,
}: {
  result: ImportConfirmResponse
  onReset: () => void
}) {
  const stats = [
    { label: 'Imported', value: result.imported, color: 'text-emerald-600' },
    { label: 'Duplicates', value: result.duplicates, color: 'text-amber-600' },
    { label: 'Invalid', value: result.invalid, color: 'text-red-600' },
    { label: 'Total rows', value: result.total, color: 'text-gray-700' },
  ]

  return (
    <div className="flex flex-col items-center justify-center h-full gap-8">
      <div className="flex flex-col items-center gap-3">
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50">
          <CheckCircle2 size={28} className="text-emerald-500" />
        </div>
        <h2 className="text-lg font-semibold text-gray-900">Import Complete</h2>
      </div>

      <div className="flex gap-8">
        {stats.map((s) => (
          <div key={s.label} className="flex flex-col items-center gap-1">
            <span className={`text-3xl font-bold tabular-nums ${s.color}`}>{s.value}</span>
            <span className="text-xs text-gray-500">{s.label}</span>
          </div>
        ))}
      </div>

      {result.errors.length > 0 && (
        <div className="w-full max-w-lg rounded-lg border border-red-100 bg-red-50 p-4">
          <p className="text-xs font-medium text-red-700 mb-2">
            Issues ({result.errors.length})
          </p>
          <ul className="space-y-1">
            {result.errors.map((e, i) => (
              <li key={i} className="text-xs text-red-600">
                {e}
              </li>
            ))}
          </ul>
        </div>
      )}

      <button
        onClick={onReset}
        className="px-4 py-2 text-sm font-medium border border-gray-200 rounded-lg text-gray-700 hover:bg-gray-50 transition-colors"
      >
        Import another file
      </button>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function ImportPage() {
  const [stage, setStage] = useState<Stage>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null)
  const [mapping, setMapping] = useState<ColumnMappingItem[]>([])
  const [overwrite, setOverwrite] = useState(false)
  const [result, setResult] = useState<ImportConfirmResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingError, setLoadingError] = useState('')
  const [confirming, setConfirming] = useState(false)

  const handleFile = async (f: File) => {
    setFile(f)
    setLoadingError('')
    setLoading(true)
    try {
      const data = await importApi.preview(f)
      setPreview(data)
      setMapping(data.suggested_mapping)
      setStage('preview')
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            'Failed to parse file'
      setLoadingError(msg)
    } finally {
      setLoading(false)
    }
  }

  const handleMappingChange = (idx: number, field: string | null) => {
    setMapping((prev) => prev.map((m, i) => (i === idx ? { ...m, field } : m)))
  }

  const handleConfirm = async () => {
    if (!file || !preview) return
    setConfirming(true)
    try {
      const res = await importApi.confirm(file, mapping, overwrite)
      setResult(res)
      setStage('done')
    } catch (err: unknown) {
      const msg =
        err instanceof Error
          ? err.message
          : (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            'Import failed'
      setLoadingError(msg)
    } finally {
      setConfirming(false)
    }
  }

  const handleReset = () => {
    setStage('upload')
    setFile(null)
    setPreview(null)
    setMapping([])
    setResult(null)
    setLoadingError('')
  }

  return (
    <div className="flex flex-col h-full">
      {/* Page header */}
      <div className="px-6 py-5 border-b border-gray-100 shrink-0">
        <h1 className="text-base font-semibold text-gray-900">Import Influencers</h1>
        <p className="mt-0.5 text-sm text-gray-400">
          Upload a CSV or Excel file to bulk-import influencer contacts.
        </p>
      </div>

      {/* Error banner */}
      {loadingError && (
        <div className="mx-6 mt-4 flex items-center gap-2 rounded-lg border border-red-100 bg-red-50 px-4 py-3">
          <AlertCircle size={14} className="text-red-500 shrink-0" />
          <span className="text-sm text-red-700">{loadingError}</span>
          <button onClick={() => setLoadingError('')} className="ml-auto text-red-400 hover:text-red-600">
            <X size={14} />
          </button>
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {loading ? (
          <div className="flex h-full items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <span className="h-8 w-8 border-2 border-gray-200 border-t-gray-700 rounded-full animate-spin" />
              <span className="text-sm text-gray-500">Parsing file…</span>
            </div>
          </div>
        ) : stage === 'upload' ? (
          <div className="px-6 py-8 h-full">
            <UploadZone onFile={handleFile} />
          </div>
        ) : stage === 'preview' && file && preview ? (
          <PreviewStage
            file={file}
            preview={preview}
            mapping={mapping}
            overwrite={overwrite}
            onMappingChange={handleMappingChange}
            onOverwriteChange={setOverwrite}
            onConfirm={handleConfirm}
            onReset={handleReset}
            confirming={confirming}
          />
        ) : stage === 'done' && result ? (
          <ResultStage result={result} onReset={handleReset} />
        ) : null}
      </div>
    </div>
  )
}
