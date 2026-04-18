import { useTranslation } from 'react-i18next'
import { Globe } from 'lucide-react'

export default function LanguageSwitch({ collapsed }: { collapsed?: boolean }) {
  const { i18n } = useTranslation()
  const isZh = i18n.language === 'zh'

  const toggle = () => {
    i18n.changeLanguage(isZh ? 'en' : 'zh')
  }

  return (
    <button
      onClick={toggle}
      className="flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-900 transition-colors"
      title={isZh ? 'Switch to English' : '切换为中文'}
    >
      <Globe size={16} />
      {!collapsed && <span>{isZh ? 'EN' : '中文'}</span>}
    </button>
  )
}
