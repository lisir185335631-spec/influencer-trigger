import { NavLink } from 'react-router-dom'

const NAV_ITEMS = [
  { label: 'Overview', path: '/admin/overview' },
  { label: 'Users', path: '/admin/users' },
  { label: 'Emails', path: '/admin/emails' },
  { label: 'Mailboxes', path: '/admin/mailboxes' },
  { label: 'Influencers', path: '/admin/influencers' },
  { label: 'Scrape', path: '/admin/scrape' },
  { label: 'Templates', path: '/admin/templates' },
  { label: 'Agents', path: '/admin/agents' },
  { label: 'Usage', path: '/admin/usage' },
  { label: 'Follow-up', path: '/admin/followup' },
  { label: 'Holidays', path: '/admin/holidays' },
  { label: 'Settings', path: '/admin/settings' },
  { label: 'Security', path: '/admin/security' },
  { label: 'Audit Log', path: '/admin/audit' },
  { label: 'Diagnostics', path: '/admin/diagnostics' },
  { label: '← Back to App', path: '/dashboard' },
]

export default function AdminSidebar() {
  return (
    <nav className="flex flex-col h-full py-4">
      {NAV_ITEMS.map(({ label, path }) => (
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
          {label}
        </NavLink>
      ))}
    </nav>
  )
}
