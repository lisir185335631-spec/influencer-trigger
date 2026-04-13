import { useState, useEffect, useCallback } from 'react'
import { Plus, Pencil, Trash2, Zap, X, CheckCircle, XCircle, Loader2 } from 'lucide-react'
import { Mailbox, MailboxCreate, MailboxUpdate, mailboxesApi } from '../api/mailboxes'

// ─── Status badge ────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  active: 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200',
  inactive: 'bg-gray-50 text-gray-500 ring-1 ring-gray-200',
  error: 'bg-red-50 text-red-600 ring-1 ring-red-200',
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${STATUS_STYLES[status] ?? STATUS_STYLES.inactive}`}>
      {status}
    </span>
  )
}

// ─── Form fields ─────────────────────────────────────────────────────────────

type FormValues = {
  email: string
  display_name: string
  smtp_host: string
  smtp_port: string
  smtp_password: string
  smtp_use_tls: boolean
  imap_host: string
  imap_port: string
  daily_limit: string
  hourly_limit: string
}

const EMPTY_FORM: FormValues = {
  email: '',
  display_name: '',
  smtp_host: '',
  smtp_port: '587',
  smtp_password: '',
  smtp_use_tls: true,
  imap_host: '',
  imap_port: '993',
  daily_limit: '500',
  hourly_limit: '50',
}

function mailboxToForm(m: Mailbox): FormValues {
  return {
    email: m.email,
    display_name: m.display_name ?? '',
    smtp_host: m.smtp_host,
    smtp_port: String(m.smtp_port),
    smtp_password: '',
    smtp_use_tls: m.smtp_use_tls,
    imap_host: m.imap_host ?? '',
    imap_port: String(m.imap_port),
    daily_limit: String(m.daily_limit),
    hourly_limit: String(m.hourly_limit),
  }
}

// ─── Modal ───────────────────────────────────────────────────────────────────

type ModalProps = {
  editing: Mailbox | null
  onClose: () => void
  onSaved: (m: Mailbox) => void
}

function MailboxModal({ editing, onClose, onSaved }: ModalProps) {
  const [form, setForm] = useState<FormValues>(editing ? mailboxToForm(editing) : EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const set = (field: keyof FormValues) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      if (editing) {
        const payload: MailboxUpdate = {
          display_name: form.display_name || undefined,
          smtp_host: form.smtp_host,
          smtp_port: Number(form.smtp_port),
          smtp_use_tls: form.smtp_use_tls,
          imap_host: form.imap_host || undefined,
          imap_port: Number(form.imap_port),
          daily_limit: Number(form.daily_limit),
          hourly_limit: Number(form.hourly_limit),
        }
        if (form.smtp_password) payload.smtp_password = form.smtp_password
        const updated = await mailboxesApi.update(editing.id, payload)
        onSaved(updated)
      } else {
        const payload: MailboxCreate = {
          email: form.email,
          display_name: form.display_name || undefined,
          smtp_host: form.smtp_host,
          smtp_port: Number(form.smtp_port),
          smtp_password: form.smtp_password,
          smtp_use_tls: form.smtp_use_tls,
          imap_host: form.imap_host || undefined,
          imap_port: Number(form.imap_port),
          daily_limit: Number(form.daily_limit),
          hourly_limit: Number(form.hourly_limit),
        }
        const created = await mailboxesApi.create(payload)
        onSaved(created)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Save failed'
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-lg mx-4">
        <div className="flex items-center justify-between px-6 pt-6 pb-4 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-900">
            {editing ? 'Edit Mailbox' : 'Add Mailbox'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {/* Email + Display name */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Email *</label>
              <input
                type="email"
                required={!editing}
                disabled={!!editing}
                value={form.email}
                onChange={set('email')}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400 disabled:bg-gray-50 disabled:text-gray-400"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Display Name</label>
              <input
                type="text"
                value={form.display_name}
                onChange={set('display_name')}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
              />
            </div>
          </div>

          {/* SMTP */}
          <div>
            <p className="text-xs font-medium text-gray-700 mb-2">SMTP</p>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="block text-xs text-gray-500 mb-1">Host *</label>
                <input
                  type="text"
                  required
                  placeholder="smtp.gmail.com"
                  value={form.smtp_host}
                  onChange={set('smtp_host')}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Port</label>
                <input
                  type="number"
                  required
                  value={form.smtp_port}
                  onChange={set('smtp_port')}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
                />
              </div>
            </div>
            <div className="mt-3">
              <label className="block text-xs text-gray-500 mb-1">
                Password {editing && <span className="text-gray-400">(leave blank to keep current)</span>}
              </label>
              <input
                type="password"
                required={!editing}
                value={form.smtp_password}
                onChange={set('smtp_password')}
                autoComplete="new-password"
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
              />
            </div>
            <label className="mt-2 flex items-center gap-2 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={form.smtp_use_tls}
                onChange={set('smtp_use_tls')}
                className="rounded border-gray-300 text-blue-500"
              />
              <span className="text-xs text-gray-600">STARTTLS</span>
            </label>
          </div>

          {/* IMAP */}
          <div>
            <p className="text-xs font-medium text-gray-700 mb-2">IMAP <span className="font-normal text-gray-400">(optional)</span></p>
            <div className="grid grid-cols-3 gap-3">
              <div className="col-span-2">
                <label className="block text-xs text-gray-500 mb-1">Host</label>
                <input
                  type="text"
                  placeholder="imap.gmail.com"
                  value={form.imap_host}
                  onChange={set('imap_host')}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Port</label>
                <input
                  type="number"
                  value={form.imap_port}
                  onChange={set('imap_port')}
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
                />
              </div>
            </div>
          </div>

          {/* Limits */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Daily Limit</label>
              <input
                type="number"
                min="1"
                value={form.daily_limit}
                onChange={set('daily_limit')}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Hourly Limit</label>
              <input
                type="number"
                min="1"
                value={form.hourly_limit}
                onChange={set('hourly_limit')}
                className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-100 focus:border-blue-400"
              />
            </div>
          </div>

          {error && <p className="text-xs text-red-500">{error}</p>}

          <div className="flex justify-end gap-2 pt-2 border-t border-gray-100">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800 transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-1.5 px-4 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 disabled:opacity-50 transition-colors"
            >
              {saving && <Loader2 size={13} className="animate-spin" />}
              {editing ? 'Save' : 'Add Mailbox'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

type TestState = { status: 'idle' | 'loading' | 'ok' | 'error'; msg: string }

export default function MailboxesPage() {
  const [mailboxes, setMailboxes] = useState<Mailbox[]>([])
  const [loading, setLoading] = useState(true)
  const [modal, setModal] = useState<'add' | Mailbox | null>(null)
  const [deletingId, setDeletingId] = useState<number | null>(null)
  const [testStates, setTestStates] = useState<Record<number, TestState>>({})

  const fetchMailboxes = useCallback(async () => {
    try {
      const data = await mailboxesApi.list()
      setMailboxes(data)
    } catch {
      /* handled silently */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchMailboxes() }, [fetchMailboxes])

  function handleSaved(m: Mailbox) {
    setMailboxes((prev) => {
      const idx = prev.findIndex((x) => x.id === m.id)
      if (idx >= 0) {
        const next = [...prev]
        next[idx] = m
        return next
      }
      return [m, ...prev]
    })
    setModal(null)
  }

  async function handleDelete(id: number) {
    if (!window.confirm('Delete this mailbox?')) return
    setDeletingId(id)
    try {
      await mailboxesApi.delete(id)
      setMailboxes((prev) => prev.filter((m) => m.id !== id))
    } finally {
      setDeletingId(null)
    }
  }

  async function handleTest(mailbox: Mailbox) {
    setTestStates((prev) => ({ ...prev, [mailbox.id]: { status: 'loading', msg: '' } }))
    try {
      const result = await mailboxesApi.test(mailbox.id)
      setTestStates((prev) => ({
        ...prev,
        [mailbox.id]: {
          status: result.success ? 'ok' : 'error',
          msg: result.success ? (result.message ?? 'OK') : (result.error ?? 'Failed'),
        },
      }))
      if (result.success) {
        setMailboxes((prev) =>
          prev.map((m) => (m.id === mailbox.id ? { ...m, status: 'active' } : m))
        )
      } else {
        setMailboxes((prev) =>
          prev.map((m) => (m.id === mailbox.id ? { ...m, status: 'error' } : m))
        )
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Test failed'
      setTestStates((prev) => ({ ...prev, [mailbox.id]: { status: 'error', msg } }))
    }
    // Clear after 4 s
    setTimeout(() => {
      setTestStates((prev) => ({ ...prev, [mailbox.id]: { status: 'idle', msg: '' } }))
    }, 4000)
  }

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Mailboxes</h1>
          <p className="text-xs text-gray-400 mt-0.5">Sending accounts with SMTP configuration</p>
        </div>
        <button
          onClick={() => setModal('add')}
          className="flex items-center gap-1.5 px-3 py-2 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-700 transition-colors"
        >
          <Plus size={14} />
          Add Mailbox
        </button>
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-100 overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-16 text-gray-400">
            <Loader2 size={18} className="animate-spin mr-2" />
            <span className="text-sm">Loading…</span>
          </div>
        ) : mailboxes.length === 0 ? (
          <div className="py-16 text-center text-sm text-gray-400">
            No mailboxes yet. Add one to get started.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Account</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">SMTP</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500">Today / Daily</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500">Bounce Rate</th>
                <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 w-36">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {mailboxes.map((m) => {
                const ts = testStates[m.id] ?? { status: 'idle', msg: '' }
                return (
                  <tr key={m.id} className="hover:bg-gray-50/60 transition-colors">
                    <td className="px-4 py-3">
                      <p className="font-medium text-gray-900 text-xs">{m.email}</p>
                      {m.display_name && (
                        <p className="text-gray-400 text-xs mt-0.5">{m.display_name}</p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-xs text-gray-500">
                      {m.smtp_host}:{m.smtp_port}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={m.status} />
                    </td>
                    <td className="px-4 py-3 text-right text-xs text-gray-700 tabular-nums">
                      <span className={m.today_sent >= m.daily_limit ? 'text-red-500 font-medium' : ''}>
                        {m.today_sent}
                      </span>
                      <span className="text-gray-300 mx-1">/</span>
                      {m.daily_limit}
                    </td>
                    <td className="px-4 py-3 text-right text-xs tabular-nums">
                      <span className={m.bounce_rate > 0.05 ? 'text-red-500' : 'text-gray-500'}>
                        {(m.bounce_rate * 100).toFixed(1)}%
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1">
                        {/* Test button */}
                        <button
                          onClick={() => handleTest(m)}
                          disabled={ts.status === 'loading'}
                          title="Test SMTP connection"
                          className="flex items-center gap-1 px-2 py-1.5 text-xs rounded-md text-gray-500 hover:text-blue-600 hover:bg-blue-50 disabled:opacity-50 transition-colors"
                        >
                          {ts.status === 'loading' ? (
                            <Loader2 size={12} className="animate-spin" />
                          ) : ts.status === 'ok' ? (
                            <CheckCircle size={12} className="text-emerald-500" />
                          ) : ts.status === 'error' ? (
                            <XCircle size={12} className="text-red-500" />
                          ) : (
                            <Zap size={12} />
                          )}
                          {ts.status === 'ok' ? 'OK' : ts.status === 'error' ? 'Fail' : 'Test'}
                        </button>

                        {/* Edit */}
                        <button
                          onClick={() => setModal(m)}
                          title="Edit"
                          className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
                        >
                          <Pencil size={13} />
                        </button>

                        {/* Delete */}
                        <button
                          onClick={() => handleDelete(m.id)}
                          disabled={deletingId === m.id}
                          title="Delete"
                          className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-md transition-colors disabled:opacity-50"
                        >
                          {deletingId === m.id ? (
                            <Loader2 size={13} className="animate-spin" />
                          ) : (
                            <Trash2 size={13} />
                          )}
                        </button>
                      </div>
                      {ts.msg && (
                        <p className={`text-right text-xs mt-1 truncate max-w-[140px] ${ts.status === 'error' ? 'text-red-400' : 'text-emerald-500'}`}>
                          {ts.msg}
                        </p>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Modal */}
      {modal !== null && (
        <MailboxModal
          editing={modal === 'add' ? null : modal}
          onClose={() => setModal(null)}
          onSaved={handleSaved}
        />
      )}
    </div>
  )
}
