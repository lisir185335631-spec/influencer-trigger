import { ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthContext } from '../../stores/AuthContext'
import { useWebSocketContext } from '../../stores/WebSocketContext'
import Sidebar from './Sidebar'
import NotificationBell from '../NotificationBell'
import LanguageSwitch from '../LanguageSwitch'

const PAGE_TITLES: Record<string, string> = {
  '/dashboard': 'mainLayout.pageTitles.dashboard',
  '/scrape': 'mainLayout.pageTitles.scrape',
  '/import': 'mainLayout.pageTitles.import',
  '/emails': 'mainLayout.pageTitles.emails',
  '/crm': 'mainLayout.pageTitles.crm',
  '/templates': 'mainLayout.pageTitles.templates',
  '/mailboxes': 'mainLayout.pageTitles.mailboxes',
  '/followup': 'mainLayout.pageTitles.followUp',
  '/team': 'mainLayout.pageTitles.team',
  '/settings': 'mainLayout.pageTitles.settings',
}

const WS_STATUS_COLOR: Record<string, string> = {
  connected: 'bg-emerald-400',
  connecting: 'bg-amber-400 animate-pulse',
  disconnected: 'bg-gray-300',
}

export default function MainLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  const { username, logout } = useAuthContext()
  const { status } = useWebSocketContext()
  const location = useLocation()
  const navigate = useNavigate()

  const pageTitle = t(PAGE_TITLES[location.pathname] ?? 'mainLayout.fallbackTitle')

  const handleLogout = () => {
    logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-screen min-w-[1280px] bg-white overflow-hidden">
      <Sidebar />

      <div className="flex flex-col flex-1 overflow-hidden">
        {/* Top bar */}
        <header className="flex items-center justify-between px-6 py-3 border-b border-gray-100 bg-white shrink-0">
          {/* Breadcrumb */}
          <nav className="flex items-center gap-2 text-sm text-gray-400">
            <span>{t('mainLayout.home')}</span>
            <span>/</span>
            <span className="text-gray-800 font-medium">{pageTitle}</span>
          </nav>

          {/* Right: ws status + bell + user */}
          <div className="flex items-center gap-3">
            <LanguageSwitch />

            {/* WebSocket status dot */}
            <span title={t('mainLayout.wsTooltip', { status })}>
              <span
                className={`inline-block h-2 w-2 rounded-full ${WS_STATUS_COLOR[status]}`}
              />
            </span>

            <NotificationBell />

            <div className="h-4 w-px bg-gray-100" />

            <span className="text-sm text-gray-500">{username}</span>
            <button
              onClick={handleLogout}
              className="text-sm text-gray-400 hover:text-gray-700 transition-colors"
            >
              {t('mainLayout.signOut')}
            </button>
          </div>
        </header>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto bg-white">
          {children}
        </main>
      </div>
    </div>
  )
}
