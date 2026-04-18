import { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import AdminSidebar from './AdminSidebar'

export default function AdminLayout({ children }: { children: ReactNode }) {
  const { t } = useTranslation()

  return (
    <div className="flex h-screen overflow-hidden bg-white">
      <aside className="w-56 flex-shrink-0 bg-slate-900 flex flex-col">
        <div className="px-5 py-4 border-b border-slate-700">
          <span className="text-xs font-bold tracking-widest text-slate-400 uppercase">
            {t('admin.layout.console')}
          </span>
        </div>
        <div className="flex-1 overflow-y-auto">
          <AdminSidebar />
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto bg-white">{children}</main>
    </div>
  )
}
