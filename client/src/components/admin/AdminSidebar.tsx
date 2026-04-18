import { NavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Globe,
  LayoutDashboard,
  Users,
  Mail,
  Inbox,
  Star,
  Radar,
  FileText,
  Bot,
  TrendingUp,
  Repeat,
  Calendar,
  Settings,
  Shield,
  FileSearch,
  Activity,
  ArrowLeft,
  type LucideIcon,
} from 'lucide-react'

const NAV_KEYS: { key: string; path: string; Icon: LucideIcon }[] = [
  { key: 'overview', path: '/admin/overview', Icon: LayoutDashboard },
  { key: 'users', path: '/admin/users', Icon: Users },
  { key: 'emails', path: '/admin/emails', Icon: Mail },
  { key: 'mailboxes', path: '/admin/mailboxes', Icon: Inbox },
  { key: 'influencers', path: '/admin/influencers', Icon: Star },
  { key: 'scrape', path: '/admin/scrape', Icon: Radar },
  { key: 'templates', path: '/admin/templates', Icon: FileText },
  { key: 'agents', path: '/admin/agents', Icon: Bot },
  { key: 'usage', path: '/admin/usage', Icon: TrendingUp },
  { key: 'followup', path: '/admin/followup', Icon: Repeat },
  { key: 'holidays', path: '/admin/holidays', Icon: Calendar },
  { key: 'settings', path: '/admin/settings', Icon: Settings },
  { key: 'security', path: '/admin/security', Icon: Shield },
  { key: 'audit', path: '/admin/audit', Icon: FileSearch },
  { key: 'diagnostics', path: '/admin/diagnostics', Icon: Activity },
  { key: 'backToApp', path: '/dashboard', Icon: ArrowLeft },
]

export default function AdminSidebar() {
  const { t, i18n } = useTranslation()

  return (
    <nav className="flex flex-col h-full py-4">
      {NAV_KEYS.map(({ key, path, Icon }) => (
        <NavLink
          key={path}
          to={path}
          className={({ isActive }) =>
            `flex items-center gap-3 px-5 py-2 text-sm font-medium transition-colors ${
              isActive
                ? 'bg-slate-700 text-white'
                : 'text-slate-400 hover:text-white hover:bg-slate-800'
            }`
          }
        >
          <Icon size={16} className="shrink-0" />
          <span>{t(`admin.sidebar.${key}`)}</span>
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
