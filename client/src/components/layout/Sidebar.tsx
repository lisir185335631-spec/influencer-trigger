import { useState } from 'react'
import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard,
  Search,
  Mail,
  Users,
  FileText,
  Inbox,
  RefreshCw,
  Users2,
  Settings,
  ChevronLeft,
  ChevronRight,
  Zap,
  FileUp,
  Gift,
} from 'lucide-react'
import { useAuthContext } from '../../stores/AuthContext'

interface NavItem {
  label: string
  to: string
  icon: React.ElementType
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', to: '/dashboard', icon: LayoutDashboard },
  { label: 'Scrape', to: '/scrape', icon: Search },
  { label: 'Import', to: '/import', icon: FileUp },
  { label: 'Emails', to: '/emails', icon: Mail },
  { label: 'CRM', to: '/crm', icon: Users },
  { label: 'Templates', to: '/templates', icon: FileText },
  { label: 'Mailboxes', to: '/mailboxes', icon: Inbox },
  { label: 'Follow-up', to: '/followup', icon: RefreshCw },
  { label: 'Holidays', to: '/holidays', icon: Gift },
]

const SETTINGS_NAV: NavItem = { label: 'Settings', to: '/settings', icon: Settings }
const TEAM_NAV: NavItem = { label: 'Team', to: '/team', icon: Users2 }

const ACTIVE_CLASS =
  'bg-gray-50 text-gray-900 font-medium border-l-2 border-gray-900'
const INACTIVE_CLASS =
  'text-gray-500 hover:bg-gray-50 hover:text-gray-800 border-l-2 border-transparent'

function NavItemRow({ item, collapsed }: { item: NavItem; collapsed: boolean }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2 text-sm rounded-r-md transition-colors ${
          isActive ? ACTIVE_CLASS : INACTIVE_CLASS
        }`
      }
    >
      <Icon size={16} className="shrink-0" />
      {!collapsed && <span className="truncate">{item.label}</span>}
    </NavLink>
  )
}

export default function Sidebar() {
  const [collapsed, setCollapsed] = useState(false)
  const { role } = useAuthContext()

  const bottomNavItems: NavItem[] = [
    ...(role === 'admin' ? [TEAM_NAV] : []),
    SETTINGS_NAV,
  ]

  return (
    <aside
      className={`flex flex-col bg-white border-r border-gray-100 transition-all duration-200 ${
        collapsed ? 'w-14' : 'w-52'
      }`}
    >
      {/* Logo */}
      <div className="flex items-center gap-2 px-3 py-4 border-b border-gray-100">
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-gray-900">
          <Zap size={14} className="text-white" />
        </div>
        {!collapsed && (
          <span className="text-sm font-semibold text-gray-900 truncate">
            Influencer
          </span>
        )}
      </div>

      {/* Main nav */}
      <nav className="flex-1 py-3 space-y-0.5 overflow-y-auto">
        {NAV_ITEMS.map((item) => (
          <NavItemRow key={item.to} item={item} collapsed={collapsed} />
        ))}
      </nav>

      {/* Divider + bottom nav */}
      <div className="border-t border-gray-100 py-3 space-y-0.5">
        {bottomNavItems.map((item) => (
          <NavItemRow key={item.to} item={item} collapsed={collapsed} />
        ))}
      </div>

      {/* Collapse toggle */}
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="flex items-center justify-center h-9 border-t border-gray-100 text-gray-400 hover:text-gray-700 hover:bg-gray-50 transition-colors"
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
      </button>
    </aside>
  )
}
