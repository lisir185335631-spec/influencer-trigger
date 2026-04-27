import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { UserPlus, Ban, CheckCircle, X, Trash2, AlertTriangle, Loader2 } from 'lucide-react'
import { useAuthContext } from '../stores/AuthContext'
import { usersApi, UserItem, UserRole, UserCreateRequest } from '../api/users'

const ROLE_COLORS: Record<UserRole, string> = {
  admin: 'bg-purple-50 text-purple-700',
  manager: 'bg-blue-50 text-blue-700',
  operator: 'bg-gray-50 text-gray-600',
}

function RoleBadge({ role }: { role: UserRole }) {
  const { t } = useTranslation()
  const ROLE_LABELS: Record<UserRole, string> = {
    admin: t('common.role.admin'),
    manager: t('common.role.manager'),
    operator: t('common.role.operator'),
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${ROLE_COLORS[role]}`}>
      {ROLE_LABELS[role]}
    </span>
  )
}

interface AddMemberModalProps {
  onClose: () => void
  onCreated: (user: UserItem) => void
}

function AddMemberModal({ onClose, onCreated }: AddMemberModalProps) {
  const { t } = useTranslation()
  const [form, setForm] = useState<UserCreateRequest>({
    username: '',
    email: '',
    password: '',
    role: 'operator',
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const user = await usersApi.create(form)
      onCreated(user)
    } catch (err: unknown) {
      const msg =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        t('team.modal.createFailed')
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div className="bg-white rounded-lg shadow-lg w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-900">{t('team.modal.title')}</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={16} />
          </button>
        </div>

        {error && (
          <div className="mb-4 text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('team.modal.username')}</label>
            <input
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400"
              value={form.username}
              onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              required
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('team.modal.email')}</label>
            <input
              type="email"
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400"
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              required
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('team.modal.password')}</label>
            <input
              type="password"
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400"
              value={form.password}
              onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              required
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">{t('team.modal.role')}</label>
            <select
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400"
              value={form.role}
              onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as UserRole }))}
            >
              <option value="operator">{t('common.role.operator')}</option>
              <option value="manager">{t('common.role.manager')}</option>
              <option value="admin">{t('common.role.admin')}</option>
            </select>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700"
            >
              {t('team.modal.cancel')}
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 text-sm bg-gray-900 text-white rounded hover:bg-gray-700 disabled:opacity-50"
            >
              {loading ? t('team.modal.creating') : t('team.modal.create')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

interface EditRoleDropdownProps {
  user: UserItem
  currentUserId: number | null
  onUpdated: (user: UserItem) => void
}

function EditRoleDropdown({ user, currentUserId, onUpdated }: EditRoleDropdownProps) {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)

  const handleChange = async (role: UserRole) => {
    if (role === user.role) return
    setLoading(true)
    try {
      const updated = await usersApi.update(user.id, { role })
      onUpdated(updated)
    } finally {
      setLoading(false)
    }
  }

  const isSelf = user.id === currentUserId

  return (
    <select
      disabled={loading || isSelf}
      value={user.role}
      onChange={(e) => handleChange(e.target.value as UserRole)}
      className="border border-gray-200 rounded px-2 py-1 text-xs focus:outline-none focus:border-gray-400 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      <option value="operator">{t('common.role.operator')}</option>
      <option value="manager">{t('common.role.manager')}</option>
      <option value="admin">{t('common.role.admin')}</option>
    </select>
  )
}

export default function TeamPage() {
  const { t } = useTranslation()
  const { role: currentRole, username: currentUsername } = useAuthContext()
  const [users, setUsers] = useState<UserItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  // Hard-delete confirmation flow — null = idle; UserItem = modal open
  // for that user. `deleting` blocks the modal's confirm button + cancel
  // affordances while the PATCH is in flight.
  const [deleteTarget, setDeleteTarget] = useState<UserItem | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Derive current user id from users list by username
  const currentUserId =
    users.find((u) => u.username === currentUsername)?.id ?? null

  const fetchUsers = async () => {
    setLoading(true)
    try {
      const data = await usersApi.list()
      setUsers(data.items)
      setTotal(data.total)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (currentRole === 'admin') {
      fetchUsers()
    }
  }, [currentRole])

  if (currentRole !== 'admin') {
    return (
      <div className="p-6">
        <div className="border border-gray-100 rounded-lg p-8 text-center text-gray-400 text-sm">
          {t('team.accessDenied')}
        </div>
      </div>
    )
  }

  const handleToggleActive = async (user: UserItem) => {
    setActionLoading(user.id)
    try {
      if (user.is_active) {
        await usersApi.disable(user.id)
        setUsers((prev) => prev.map((u) => (u.id === user.id ? { ...u, is_active: false } : u)))
      } else {
        const updated = await usersApi.enable(user.id)
        setUsers((prev) => prev.map((u) => (u.id === user.id ? updated : u)))
      }
    } finally {
      setActionLoading(null)
    }
  }

  const handleRoleUpdated = (updated: UserItem) => {
    setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))
  }

  // Permanently remove the user row (via /users/{id}/hard-delete).
  // Reuses backend's "cannot delete yourself" guard, but the button is
  // also hidden client-side for the current user so the modal never
  // even opens for self-deletion.
  const handleHardDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await usersApi.hardDelete(deleteTarget.id)
      setUsers((prev) => prev.filter((u) => u.id !== deleteTarget.id))
      setTotal((c) => c - 1)
      setDeleteTarget(null)
    } catch {
      window.alert(t('team.table.deleteFailed'))
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="p-6 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-base font-semibold text-gray-900">{t('team.title')}</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            {t('team.memberCount', { count: total })}
          </p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          disabled={total >= 10}
          className="flex items-center gap-1.5 px-3 py-2 text-sm bg-gray-900 text-white rounded hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <UserPlus size={14} />
          {t('team.addMember')}
        </button>
      </div>

      {/* Permission matrix info */}
      <div className="mb-5 p-4 bg-gray-50 rounded-lg border border-gray-100">
        <p className="text-xs font-medium text-gray-600 mb-2">{t('team.permissions.title')}</p>
        <div className="grid grid-cols-3 gap-3 text-xs text-gray-500">
          <div>
            <span className="font-medium text-purple-700">{t('team.permissions.admin')}</span>
            <p className="mt-0.5">{t('team.permissions.adminDesc')}</p>
          </div>
          <div>
            <span className="font-medium text-blue-700">{t('team.permissions.manager')}</span>
            <p className="mt-0.5">{t('team.permissions.managerDesc')}</p>
          </div>
          <div>
            <span className="font-medium text-gray-600">{t('team.permissions.operator')}</span>
            <p className="mt-0.5">{t('team.permissions.operatorDesc')}</p>
          </div>
        </div>
      </div>

      {/* Members table */}
      <div className="border border-gray-100 rounded-lg overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-sm text-gray-400">{t('team.loading')}</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">{t('team.table.username')}</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">{t('team.table.email')}</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">{t('team.table.role')}</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">{t('team.table.status')}</th>
                <th className="text-right text-xs font-medium text-gray-500 px-4 py-3">{t('team.table.actions')}</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-800">{user.username}</span>
                      {user.id === currentUserId && (
                        <span className="text-xs text-gray-400">{t('team.table.you')}</span>
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-500">{user.email}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <RoleBadge role={user.role} />
                      <EditRoleDropdown
                        user={user}
                        currentUserId={currentUserId}
                        onUpdated={handleRoleUpdated}
                      />
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center gap-1 text-xs ${
                        user.is_active ? 'text-emerald-600' : 'text-gray-400'
                      }`}
                    >
                      <span
                        className={`h-1.5 w-1.5 rounded-full ${
                          user.is_active ? 'bg-emerald-400' : 'bg-gray-300'
                        }`}
                      />
                      {user.is_active ? t('team.table.active') : t('team.table.disabled')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {user.id !== currentUserId && (
                      <div className="inline-flex items-center gap-3">
                        <button
                          onClick={() => handleToggleActive(user)}
                          disabled={actionLoading === user.id || deleting}
                          title={user.is_active ? t('team.table.disableTooltip') : t('team.table.enableTooltip')}
                          className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 disabled:opacity-40 transition-colors"
                        >
                          {user.is_active ? (
                            <>
                              <Ban size={13} />
                              {t('team.table.disable')}
                            </>
                          ) : (
                            <>
                              <CheckCircle size={13} />
                              {t('team.table.enable')}
                            </>
                          )}
                        </button>
                        {/* Hard delete — destructive, opens confirm modal */}
                        <button
                          onClick={() => setDeleteTarget(user)}
                          disabled={actionLoading === user.id || deleting}
                          title={t('team.table.deleteTooltip')}
                          className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-red-600 disabled:opacity-40 transition-colors"
                        >
                          <Trash2 size={13} />
                          {t('team.table.delete')}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">
                    {t('team.noMembers')}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {showAdd && (
        <AddMemberModal
          onClose={() => setShowAdd(false)}
          onCreated={(user) => {
            setUsers((prev) => [...prev, user])
            setTotal((t) => t + 1)
            setShowAdd(false)
          }}
        />
      )}

      {deleteTarget && (
        <ConfirmHardDeleteModal
          user={deleteTarget}
          loading={deleting}
          onCancel={() => setDeleteTarget(null)}
          onConfirm={handleHardDelete}
        />
      )}
    </div>
  )
}

// ── Hard-delete confirmation modal ────────────────────────────────────────────
// Same look-and-feel as CRMPage's ConfirmDeleteModal so destructive
// surfaces stay consistent. ESC and outside-click both cancel (unless an
// action is in-flight, in which case both are blocked to prevent the
// dialog from being dismissed mid-PATCH).

function ConfirmHardDeleteModal({
  user,
  loading,
  onCancel,
  onConfirm,
}: {
  user: UserItem
  loading: boolean
  onCancel: () => void
  onConfirm: () => void
}) {
  const { t } = useTranslation()

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape' && !loading) onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [loading, onCancel])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4"
      onClick={() => !loading && onCancel()}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        role="alertdialog"
        aria-modal="true"
        className="bg-white rounded-xl shadow-xl w-full max-w-md"
      >
        <div className="p-5">
          <div className="flex gap-3">
            <div className="shrink-0 w-10 h-10 rounded-full bg-red-50 flex items-center justify-center">
              <AlertTriangle size={20} className="text-red-600" />
            </div>
            <div className="flex-1 min-w-0">
              <h2 className="text-base font-semibold text-gray-900 mb-1">
                {t('team.table.deleteConfirmTitle', { name: user.username })}
              </h2>
              <p className="text-sm text-gray-500 leading-relaxed whitespace-pre-line">
                {t('team.table.deleteConfirm')}
              </p>
            </div>
          </div>
        </div>
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-100 bg-gray-50/50">
          <button
            type="button"
            onClick={onCancel}
            disabled={loading}
            className="px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-100 rounded transition-colors disabled:opacity-50"
          >
            {t('common.cancel')}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={loading}
            className="inline-flex items-center gap-1 px-4 py-1.5 text-xs bg-red-600 text-white rounded hover:bg-red-700 disabled:opacity-50 transition-colors"
          >
            {loading && <Loader2 size={12} className="animate-spin" />}
            {t('team.table.delete')}
          </button>
        </div>
      </div>
    </div>
  )
}
