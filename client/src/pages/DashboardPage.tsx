import { useNavigate } from 'react-router-dom'
import { useAuthContext } from '../stores/AuthContext'

export default function DashboardPage() {
  const { username, role, logout } = useAuthContext()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen bg-white">
      <header className="border-b border-gray-100 px-6 py-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">Influencer Trigger</h1>
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-500">
            {username}{' '}
            <span className="inline-block px-2 py-0.5 text-xs bg-gray-100 text-gray-600 rounded-full">
              {role}
            </span>
          </span>
          <button
            onClick={handleLogout}
            className="text-sm text-gray-500 hover:text-gray-900 transition-colors"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="px-6 py-10 max-w-5xl mx-auto">
        <div className="border border-gray-100 rounded-lg p-8 text-center text-gray-400 text-sm">
          Dashboard — coming soon
        </div>
      </main>
    </div>
  )
}
