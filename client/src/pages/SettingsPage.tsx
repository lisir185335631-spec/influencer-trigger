import { useAuthContext } from '../stores/AuthContext'

export default function SettingsPage() {
  const { role } = useAuthContext()

  if (role === 'operator') {
    return (
      <div className="p-6">
        <div className="border border-gray-100 rounded-lg p-8 text-center text-gray-400 text-sm">
          系统设置 — 仅管理员和经理可访问
        </div>
      </div>
    )
  }

  return (
    <div className="p-6">
      <div className="border border-gray-100 rounded-lg p-8 text-center text-gray-400 text-sm">
        Settings — coming soon
      </div>
    </div>
  )
}
