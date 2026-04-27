import { Bell, Check, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { notificationsApi, NotificationItem } from '../api/notifications'
import { useWebSocketContext } from '../stores/WebSocketContext'

// Intent priority for sorting (lower number = higher priority)
const INTENT_ORDER: Record<string, number> = {
  interested: 0,
  pricing: 1,
  declined: 2,
  irrelevant: 3,
}

const INTENT_BADGE: Record<string, string> = {
  interested: 'bg-emerald-100 text-emerald-700',
  pricing: 'bg-blue-100 text-blue-700',
  declined: 'bg-red-100 text-red-700',
  irrelevant: 'bg-gray-100 text-gray-500',
  auto_reply: 'bg-gray-100 text-gray-400',
}

const LEVEL_DOT: Record<string, string> = {
  urgent: 'bg-red-500',
  warning: 'bg-amber-400',
  info: 'bg-blue-400',
}

function sortNotifications(items: NotificationItem[]): NotificationItem[] {
  return [...items].sort((a, b) => {
    // Unread first
    if (a.is_read !== b.is_read) return a.is_read ? 1 : -1
    // By intent priority
    const aO = INTENT_ORDER[a.intent ?? ''] ?? 99
    const bO = INTENT_ORDER[b.intent ?? ''] ?? 99
    if (aO !== bO) return aO - bO
    // Newest first
    return new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
  })
}

function formatTime(iso: string, t: (key: string, opts?: Record<string, unknown>) => string): string {
  const d = new Date(iso)
  const now = Date.now()
  const diff = now - d.getTime()
  if (diff < 60_000) return t('common.time.justNow')
  if (diff < 3_600_000) { const m = Math.floor(diff / 60_000); return t('common.time.minutesAgo', { n: m }) }
  if (diff < 86_400_000) { const h = Math.floor(diff / 3_600_000); return t('common.time.hoursAgo', { n: h }) }
  return d.toLocaleDateString()
}

export default function NotificationBell() {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [notifications, setNotifications] = useState<NotificationItem[]>([])
  const [unreadCount, setUnreadCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()
  const { notificationTick } = useWebSocketContext()

  const fetchNotifications = useCallback(async () => {
    setLoading(true)
    try {
      const res = await notificationsApi.list({ limit: 50 })
      setNotifications(sortNotifications(res.items))
      setUnreadCount(res.unread_count)
    } catch {
      // silently ignore network errors
    } finally {
      setLoading(false)
    }
  }, [])

  // Load initial unread count on mount
  useEffect(() => {
    notificationsApi
      .list({ is_read: false, limit: 1 })
      .then((r) => setUnreadCount(r.unread_count))
      .catch(() => {})
  }, [])

  // React to incoming WS notification events
  useEffect(() => {
    if (notificationTick === 0) return
    setUnreadCount((prev) => prev + 1)
    if (open) fetchNotifications()
  }, [notificationTick]) // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch full list when dropdown opens
  useEffect(() => {
    if (open) fetchNotifications()
  }, [open, fetchNotifications])

  // Close dropdown on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const handleClickItem = async (item: NotificationItem) => {
    if (!item.is_read) {
      try {
        await notificationsApi.markRead(item.id)
        setNotifications((prev) =>
          sortNotifications(prev.map((n) => (n.id === item.id ? { ...n, is_read: true } : n))),
        )
        setUnreadCount((prev) => Math.max(0, prev - 1))
      } catch {
        // ignore
      }
    }
    setOpen(false)
    if (item.influencer_id) {
      // Jump straight to the influencer detail page (not the CRM list) so
      // the user lands on the email timeline + manual-intervention buttons
      // for the exact creator who replied — saves an extra click in the
      // common case ("got reply notification → take action").
      navigate(`/crm/${item.influencer_id}`)
    }
  }

  const handleMarkAllRead = async () => {
    try {
      await notificationsApi.markAllRead()
      setNotifications((prev) => sortNotifications(prev.map((n) => ({ ...n, is_read: true }))))
      setUnreadCount(0)
    } catch {
      // ignore
    }
  }

  return (
    <div className="relative" ref={panelRef}>
      {/* Bell button */}
      <button
        onClick={() => setOpen((o) => !o)}
        className="relative p-2 text-gray-400 hover:text-gray-700 transition-colors"
        aria-label={t('notification.title')}
      >
        <Bell size={18} />
        {unreadCount > 0 && (
          <span className="absolute top-1 right-1 flex h-4 w-4 items-center justify-center rounded-full bg-rose-500 text-white text-[10px] font-medium leading-none">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {/* Dropdown panel */}
      {open && (
        <div className="absolute right-0 top-full mt-2 w-96 bg-white rounded-xl border border-gray-100 shadow-xl z-50 overflow-hidden">
          {/* Header */}
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
            <span className="text-sm font-semibold text-gray-800">
              {t('notification.title')}
              {unreadCount > 0 && (
                <span className="ml-2 text-xs font-normal text-rose-500">
                  {t('notification.unread', { count: unreadCount })}
                </span>
              )}
            </span>
            <div className="flex items-center gap-3">
              {unreadCount > 0 && (
                <button
                  onClick={handleMarkAllRead}
                  className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-700 transition-colors"
                >
                  <Check size={12} />
                  {t('notification.markAllRead')}
                </button>
              )}
              <button
                onClick={() => setOpen(false)}
                className="text-gray-300 hover:text-gray-600 transition-colors"
                aria-label={t('common.close')}
              >
                <X size={14} />
              </button>
            </div>
          </div>

          {/* Notification list */}
          <div className="max-h-[420px] overflow-y-auto divide-y divide-gray-50">
            {loading && (
              <div className="px-4 py-10 text-center text-sm text-gray-400">{t('notification.loading')}</div>
            )}
            {!loading && notifications.length === 0 && (
              <div className="px-4 py-10 text-center text-sm text-gray-400">
                {t('notification.noNotifications')}
              </div>
            )}
            {!loading &&
              notifications.map((item) => (
                <button
                  key={item.id}
                  onClick={() => handleClickItem(item)}
                  className={`w-full text-left px-4 py-3 hover:bg-gray-50 transition-colors ${
                    !item.is_read ? 'bg-rose-50 hover:bg-rose-100/60' : ''
                  }`}
                >
                  <div className="flex items-start gap-3">
                    {/* Severity dot */}
                    <span
                      className={`mt-1.5 h-2 w-2 flex-shrink-0 rounded-full ${
                        LEVEL_DOT[item.level] ?? 'bg-gray-300'
                      }`}
                    />

                    <div className="flex-1 min-w-0">
                      {/* Title + intent badge */}
                      <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                        <span className="text-sm font-medium text-gray-800 truncate">
                          {item.title}
                        </span>
                        {item.intent && (
                          <span
                            className={`flex-shrink-0 text-[10px] px-1.5 py-0.5 rounded font-medium ${
                              INTENT_BADGE[item.intent] ?? 'bg-gray-100 text-gray-500'
                            }`}
                          >
                            {item.intent}
                          </span>
                        )}
                      </div>

                      {/* Content */}
                      <p className="text-xs text-gray-500 line-clamp-2 leading-relaxed">
                        {item.content}
                      </p>

                      {/* Meta row */}
                      <div className="flex items-center justify-between mt-1">
                        {item.influencer_name && (
                          <span className="text-xs text-gray-400 truncate">
                            {item.influencer_name}
                          </span>
                        )}
                        <span className="text-[10px] text-gray-300 ml-auto flex-shrink-0">
                          {formatTime(item.created_at, t)}
                        </span>
                      </div>
                    </div>

                    {/* Unread indicator dot */}
                    {!item.is_read && (
                      <span className="mt-1.5 h-2 w-2 flex-shrink-0 rounded-full bg-rose-400" />
                    )}
                  </div>
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  )
}
