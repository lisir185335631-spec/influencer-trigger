import { useEffect, useState } from 'react'
import { UserPlus, Pencil, Ban, CheckCircle, X } from 'lucide-react'
import { useAuthContext } from '../stores/AuthContext'
import { usersApi, UserItem, UserRole, UserCreateRequest } from '../api/users'

const ROLE_LABELS: Record<UserRole, string> = {
  admin: 'Admin',
  manager: 'Manager',
  operator: 'Operator',
}

const ROLE_COLORS: Record<UserRole, string> = {
  admin: 'bg-purple-50 text-purple-700',
  manager: 'bg-blue-50 text-blue-700',
  operator: 'bg-gray-50 text-gray-600',
}

function RoleBadge({ role }: { role: UserRole }) {
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
        'Failed to create member'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20">
      <div className="bg-white rounded-lg shadow-lg w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-900">Add Team Member</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={16} />
          </button>
        </div>

        {error && (
          <div className="mb-4 text-xs text-red-600 bg-red-50 rounded px-3 py-2">{error}</div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Username</label>
            <input
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400"
              value={form.username}
              onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))}
              required
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Email</label>
            <input
              type="email"
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400"
              value={form.email}
              onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
              required
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Password</label>
            <input
              type="password"
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400"
              value={form.password}
              onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
              required
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Role</label>
            <select
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400"
              value={form.role}
              onChange={(e) => setForm((f) => ({ ...f, role: e.target.value as UserRole }))}
            >
              <option value="operator">Operator</option>
              <option value="manager">Manager</option>
              <option value="admin">Admin</option>
            </select>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-500 hover:text-gray-700"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              className="px-4 py-2 text-sm bg-gray-900 text-white rounded hover:bg-gray-700 disabled:opacity-50"
            >
              {loading ? 'Creating…' : 'Create'}
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
      <option value="operator">Operator</option>
      <option value="manager">Manager</option>
      <option value="admin">Admin</option>
    </select>
  )
}

export default function TeamPage() {
  const { role: currentRole, username: currentUsername } = useAuthContext()
  const [users, setUsers] = useState<UserItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [actionLoading, setActionLoading] = useState<number | null>(null)

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
          Access denied — admin only
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

  return (
    <div className="p-6 max-w-4xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-base font-semibold text-gray-900">Team Management</h1>
          <p className="text-xs text-gray-400 mt-0.5">
            {total} / 10 members
          </p>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          disabled={total >= 10}
          className="flex items-center gap-1.5 px-3 py-2 text-sm bg-gray-900 text-white rounded hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <UserPlus size={14} />
          Add Member
        </button>
      </div>

      {/* Permission matrix info */}
      <div className="mb-5 p-4 bg-gray-50 rounded-lg border border-gray-100">
        <p className="text-xs font-medium text-gray-600 mb-2">Role Permissions</p>
        <div className="grid grid-cols-3 gap-3 text-xs text-gray-500">
          <div>
            <span className="font-medium text-purple-700">Admin</span>
            <p className="mt-0.5">Full access — all features</p>
          </div>
          <div>
            <span className="font-medium text-blue-700">Manager</span>
            <p className="mt-0.5">Dashboard, CRM, Templates</p>
          </div>
          <div>
            <span className="font-medium text-gray-600">Operator</span>
            <p className="mt-0.5">Scrape tasks, CRM, Replies</p>
          </div>
        </div>
      </div>

      {/* Members table */}
      <div className="border border-gray-100 rounded-lg overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-sm text-gray-400">Loading…</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50">
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Username</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Email</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Role</th>
                <th className="text-left text-xs font-medium text-gray-500 px-4 py-3">Status</th>
                <th className="text-right text-xs font-medium text-gray-500 px-4 py-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id} className="border-b border-gray-50 last:border-0 hover:bg-gray-50/50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-gray-800">{user.username}</span>
                      {user.id === currentUserId && (
                        <span className="text-xs text-gray-400">(you)</span>
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
                      {user.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {user.id !== currentUserId && (
                      <button
                        onClick={() => handleToggleActive(user)}
                        disabled={actionLoading === user.id}
                        title={user.is_active ? 'Disable member' : 'Enable member'}
                        className="inline-flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 disabled:opacity-40 transition-colors"
                      >
                        {user.is_active ? (
                          <>
                            <Ban size={13} />
                            Disable
                          </>
                        ) : (
                          <>
                            <CheckCircle size={13} />
                            Enable
                          </>
                        )}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-gray-400 text-sm">
                    No team members yet
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
    </div>
  )
}
