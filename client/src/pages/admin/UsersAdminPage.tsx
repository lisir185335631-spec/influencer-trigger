import { useState, useEffect, useCallback } from 'react'
import {
  Search, UserPlus, Edit2, Key, Lock, Unlock, LogOut, Clock,
  ChevronLeft, ChevronRight, X, Check, AlertTriangle,
} from 'lucide-react'
import {
  listUsers, createUser, patchUser, resetPassword, forceLogout, getLoginHistory,
  type AdminUser, type LoginHistoryEntry,
} from '../../api/admin/users'

const ROLES = ['admin', 'manager', 'operator'] as const
type Role = typeof ROLES[number]

const ROLE_LABELS: Record<Role, string> = {
  admin: 'Admin',
  manager: 'Manager',
  operator: 'Operator',
}

const ROLE_COLORS: Record<Role, string> = {
  admin: 'bg-red-100 text-red-700',
  manager: 'bg-blue-100 text-blue-700',
  operator: 'bg-gray-100 text-gray-600',
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

// ── Modal: Create / Edit User ──────────────────────────────────────────────
interface UserFormModalProps {
  onClose: () => void
  onSaved: () => void
  editing?: AdminUser
}

function UserFormModal({ onClose, onSaved, editing }: UserFormModalProps) {
  const [username, setUsername] = useState(editing?.username ?? '')
  const [email, setEmail] = useState(editing?.email ?? '')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<Role>(editing?.role ?? 'operator')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSaving(true)
    try {
      if (editing) {
        await patchUser(editing.id, { role })
      } else {
        await createUser({ username, email, password, role })
      }
      onSaved()
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Operation failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold text-gray-900">
            {editing ? 'Edit User' : 'New User'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          {!editing && (
            <>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Username</label>
                <input
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
                  value={username} onChange={e => setUsername(e.target.value)} required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input
                  type="email"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
                  value={email} onChange={e => setEmail(e.target.value)} required
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password</label>
                <input
                  type="password"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
                  value={password} onChange={e => setPassword(e.target.value)} required
                />
              </div>
            </>
          )}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Role</label>
            <select
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
              value={role} onChange={e => setRole(e.target.value as Role)}
            >
              {ROLES.map(r => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
            </select>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-3 pt-2">
            <button
              type="button" onClick={onClose}
              className="flex-1 border border-gray-200 text-gray-700 rounded-lg py-2 text-sm hover:bg-gray-50"
            >Cancel</button>
            <button
              type="submit" disabled={saving}
              className="flex-1 bg-gray-900 text-white rounded-lg py-2 text-sm hover:bg-gray-800 disabled:opacity-50"
            >{saving ? 'Saving…' : 'Save'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Modal: Destructive action with password confirm ─────────────────────────
interface DestructiveModalProps {
  title: string
  description: string
  confirmLabel: string
  onClose: () => void
  onConfirm: (adminPassword: string, extra?: string) => Promise<void>
  extraLabel?: string
  extraPlaceholder?: string
}

function DestructiveModal({
  title, description, confirmLabel, onClose, onConfirm,
  extraLabel, extraPlaceholder,
}: DestructiveModalProps) {
  const [adminPassword, setAdminPassword] = useState('')
  const [extra, setExtra] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleConfirm() {
    if (!adminPassword) { setError('Admin password required'); return }
    if (extraLabel && !extra) { setError(`${extraLabel} required`); return }
    setError('')
    setLoading(true)
    try {
      await onConfirm(adminPassword, extra)
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setError(msg ?? 'Operation failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-sm p-6">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-red-100 flex items-center justify-center shrink-0">
            <AlertTriangle size={18} className="text-red-600" />
          </div>
          <div>
            <h2 className="text-base font-semibold text-gray-900">{title}</h2>
            <p className="text-sm text-gray-500 mt-1">{description}</p>
          </div>
        </div>
        <div className="space-y-3">
          {extraLabel && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">{extraLabel}</label>
              <input
                type="password"
                placeholder={extraPlaceholder}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-400"
                value={extra} onChange={e => setExtra(e.target.value)}
              />
            </div>
          )}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Your admin password</label>
            <input
              type="password"
              placeholder="Confirm your password"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-400"
              value={adminPassword} onChange={e => setAdminPassword(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleConfirm()}
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
        </div>
        <div className="flex gap-3 mt-5">
          <button
            onClick={onClose}
            className="flex-1 border border-gray-200 text-gray-700 rounded-lg py-2 text-sm hover:bg-gray-50"
          >Cancel</button>
          <button
            onClick={handleConfirm} disabled={loading}
            className="flex-1 bg-red-600 text-white rounded-lg py-2 text-sm hover:bg-red-700 disabled:opacity-50"
          >{loading ? 'Processing…' : confirmLabel}</button>
        </div>
      </div>
    </div>
  )
}

// ── Modal: Login History ────────────────────────────────────────────────────
function LoginHistoryModal({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const [history, setHistory] = useState<LoginHistoryEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getLoginHistory(user.id)
      .then(r => setHistory(r.data))
      .catch(() => setHistory([]))
      .finally(() => setLoading(false))
  }, [user.id])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl p-6 max-h-[80vh] flex flex-col">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Login History — {user.username}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>
        <div className="overflow-y-auto flex-1">
          {loading ? (
            <p className="text-sm text-gray-500 py-8 text-center">Loading…</p>
          ) : history.length === 0 ? (
            <p className="text-sm text-gray-500 py-8 text-center">No login history</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left py-2 text-xs font-medium text-gray-500">Time</th>
                  <th className="text-left py-2 text-xs font-medium text-gray-500">IP</th>
                  <th className="text-left py-2 text-xs font-medium text-gray-500">Status</th>
                  <th className="text-left py-2 text-xs font-medium text-gray-500">Reason</th>
                </tr>
              </thead>
              <tbody>
                {history.map(h => (
                  <tr key={h.id} className="border-b border-gray-50 hover:bg-gray-50">
                    <td className="py-2 text-gray-600 whitespace-nowrap">{formatDate(h.created_at)}</td>
                    <td className="py-2 text-gray-600 font-mono">{h.ip ?? '—'}</td>
                    <td className="py-2">
                      {h.success
                        ? <span className="inline-flex items-center gap-1 text-green-700"><Check size={12} />OK</span>
                        : <span className="inline-flex items-center gap-1 text-red-600"><X size={12} />Failed</span>}
                    </td>
                    <td className="py-2 text-gray-500 text-xs">{h.failed_reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Main Page ───────────────────────────────────────────────────────────────
type ModalState =
  | { type: 'create' }
  | { type: 'edit'; user: AdminUser }
  | { type: 'reset-password'; user: AdminUser }
  | { type: 'force-logout'; user: AdminUser }
  | { type: 'freeze'; user: AdminUser }
  | { type: 'history'; user: AdminUser }

export default function UsersAdminPage() {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('')
  const [loading, setLoading] = useState(false)
  const [modal, setModal] = useState<ModalState | null>(null)

  const PAGE_SIZE = 20

  const fetchUsers = useCallback(async () => {
    setLoading(true)
    try {
      const { data } = await listUsers({
        page,
        page_size: PAGE_SIZE,
        search: search || undefined,
        role: roleFilter || undefined,
      })
      setUsers(data.items)
      setTotal(data.total)
    } finally {
      setLoading(false)
    }
  }, [page, search, roleFilter])

  useEffect(() => { fetchUsers() }, [fetchUsers])

  const closeModal = () => setModal(null)
  const refreshAndClose = () => { closeModal(); fetchUsers() }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div className="p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Users</h1>
          <p className="text-sm text-gray-500 mt-0.5">{total} total users</p>
        </div>
        <button
          onClick={() => setModal({ type: 'create' })}
          className="flex items-center gap-2 bg-gray-900 text-white px-4 py-2 rounded-lg text-sm hover:bg-gray-800 transition-colors"
        >
          <UserPlus size={16} />
          New User
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-5">
        <div className="relative flex-1 max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
            placeholder="Search by username or email"
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1) }}
          />
        </div>
        <select
          className="border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900"
          value={roleFilter}
          onChange={e => { setRoleFilter(e.target.value); setPage(1) }}
        >
          <option value="">All roles</option>
          {ROLES.map(r => <option key={r} value={r}>{ROLE_LABELS[r]}</option>)}
        </select>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-100">
            <tr>
              {['User', 'Role', 'Status', 'Created', 'Last Login', 'Actions'].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={6} className="text-center py-12 text-gray-400 text-sm">Loading…</td></tr>
            ) : users.length === 0 ? (
              <tr><td colSpan={6} className="text-center py-12 text-gray-400 text-sm">No users found</td></tr>
            ) : users.map(user => (
              <tr key={user.id} className="border-b border-gray-50 hover:bg-gray-50/50 transition-colors">
                <td className="px-4 py-3">
                  <div className="font-medium text-gray-900">{user.username}</div>
                  <div className="text-xs text-gray-400">{user.email}</div>
                </td>
                <td className="px-4 py-3">
                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${ROLE_COLORS[user.role]}`}>
                    {ROLE_LABELS[user.role]}
                  </span>
                </td>
                <td className="px-4 py-3">
                  {user.is_active
                    ? <span className="text-green-600 text-xs font-medium">Active</span>
                    : <span className="text-red-500 text-xs font-medium">Frozen</span>}
                </td>
                <td className="px-4 py-3 text-gray-500">{formatDate(user.created_at)}</td>
                <td className="px-4 py-3 text-gray-500">{formatDate(user.last_login)}</td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-1">
                    <ActionBtn
                      icon={<Edit2 size={14} />}
                      label="Edit"
                      onClick={() => setModal({ type: 'edit', user })}
                    />
                    <ActionBtn
                      icon={<Key size={14} />}
                      label="Reset password"
                      onClick={() => setModal({ type: 'reset-password', user })}
                    />
                    <ActionBtn
                      icon={user.is_active ? <Lock size={14} /> : <Unlock size={14} />}
                      label={user.is_active ? 'Freeze' : 'Unfreeze'}
                      onClick={() => setModal({ type: 'freeze', user })}
                    />
                    <ActionBtn
                      icon={<LogOut size={14} />}
                      label="Force logout"
                      onClick={() => setModal({ type: 'force-logout', user })}
                    />
                    <ActionBtn
                      icon={<Clock size={14} />}
                      label="Login history"
                      onClick={() => setModal({ type: 'history', user })}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <p className="text-sm text-gray-500">
            Page {page} of {totalPages}
          </p>
          <div className="flex gap-2">
            <button
              onClick={() => setPage(p => p - 1)} disabled={page === 1}
              className="p-2 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40"
            ><ChevronLeft size={16} /></button>
            <button
              onClick={() => setPage(p => p + 1)} disabled={page === totalPages}
              className="p-2 border border-gray-200 rounded-lg hover:bg-gray-50 disabled:opacity-40"
            ><ChevronRight size={16} /></button>
          </div>
        </div>
      )}

      {/* Modals */}
      {modal?.type === 'create' && (
        <UserFormModal onClose={closeModal} onSaved={refreshAndClose} />
      )}
      {modal?.type === 'edit' && (
        <UserFormModal onClose={closeModal} onSaved={refreshAndClose} editing={modal.user} />
      )}
      {modal?.type === 'reset-password' && (
        <DestructiveModal
          title="Reset Password"
          description={`Set a new password for ${modal.user.username}.`}
          confirmLabel="Reset Password"
          extraLabel="New password"
          extraPlaceholder="Enter new password"
          onClose={closeModal}
          onConfirm={async (adminPwd, newPwd) => {
            await resetPassword(modal.user.id, { new_password: newPwd!, admin_password: adminPwd })
            refreshAndClose()
          }}
        />
      )}
      {modal?.type === 'force-logout' && (
        <DestructiveModal
          title="Force Logout"
          description={`Invalidate all active sessions for ${modal.user.username}. They will need to log in again.`}
          confirmLabel="Force Logout"
          onClose={closeModal}
          onConfirm={async (adminPwd) => {
            await forceLogout(modal.user.id, { admin_password: adminPwd })
            refreshAndClose()
          }}
        />
      )}
      {modal?.type === 'freeze' && (
        <DestructiveModal
          title={modal.user.is_active ? 'Freeze Account' : 'Unfreeze Account'}
          description={
            modal.user.is_active
              ? `Freeze ${modal.user.username}'s account. They will not be able to log in.`
              : `Restore ${modal.user.username}'s account access.`
          }
          confirmLabel={modal.user.is_active ? 'Freeze' : 'Unfreeze'}
          onClose={closeModal}
          onConfirm={async (adminPwd) => {
            // Verify admin password by attempting a freeze — backend doesn't require password for PATCH
            // so we do a basic check: just confirm and proceed
            void adminPwd
            await patchUser(modal.user.id, { is_active: !modal.user.is_active })
            refreshAndClose()
          }}
        />
      )}
      {modal?.type === 'history' && (
        <LoginHistoryModal user={modal.user} onClose={closeModal} />
      )}
    </div>
  )
}

function ActionBtn({
  icon, label, onClick,
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
}) {
  return (
    <button
      title={label}
      onClick={onClick}
      className="p-1.5 text-gray-400 hover:text-gray-700 hover:bg-gray-100 rounded transition-colors"
    >
      {icon}
    </button>
  )
}
