import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Globe } from 'lucide-react'

const NAV_KEYS: { key: string; path: string }[] = [
  { key: 'overview', path: '/admin/overview' },
  { key: 'users', path: '/admin/users' },
  { key: 'emails', path: '/admin/emails' },
  { key: 'mailboxes', path: '/admin/mailboxes' },
  { key: 'influencers', path: '/admin/influencers' },
  { key: 'scrape', path: '/admin/scrape' },
  { key: 'templates', path: '/admin/templates' },
  { key: 'agents', path: '/admin/agents' },
  { key: 'usage', path: '/admin/usage' },
  { key: 'followup', path: '/admin/followup' },
  { key: 'holidays', path: '/admin/holidays' },
  { key: 'settings', path: '/admin/settings' },
  { key: 'security', path: '/admin/security' },
  { key: 'audit', path: '/admin/audit' },
  { key: 'diagnostics', path: '/admin/diagnostics' },
  { key: 'backToApp', path: '/dashboard' },
]

export default function AdminSidebar() {
  const { t, i18n } = useTranslation()

  return (
    <nav className="flex flex-col h-full py-4">
      {NAV_KEYS.map(({ key, path }) => (
        <NavLink
          key={path}
          to={path}
          className={({ isActive }) =>
            `px-5 py-2 text-sm font-medium transition-colors ${
              isActive
                ? 'bg-slate-700 text-white'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`
          }
        >
          {t(`admin.sidebar.${key}`)}
        </NavLink>
      ))}

      <div className="mt-auto pt-4 border-t border-slate-800">
        <button
          onClick={() => i18n.changeLanguage(i18n.language === 'zh' ? 'en' : 'zh')}
          className="flex items-center gap-2 px-3 py-2 w-full text-sm text-slate-300 hover:bg-slate-800 hover:text-white rounded-md transition-colors"
          title={i18n.language === 'zh' ? 'Switch to English' : '切换为中文'}
        >
          <Globe size={16} />
          <span>{i18n.language === 'zh' ? 'EN' : '中文'}</span>
        </button>
      </div>
    </nav>
  )
}
