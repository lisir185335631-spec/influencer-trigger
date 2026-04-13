import { Bell } from 'lucide-react'
import { useWebSocketContext } from '../stores/WebSocketContext'

export default function NotificationBell() {
  const { unreadCount, clearUnread } = useWebSocketContext()

  return (
    <button
      onClick={clearUnread}
      className="relative p-2 text-gray-400 hover:text-gray-700 transition-colors"
      aria-label="Notifications"
    >
      <Bell size={18} />
      {unreadCount > 0 && (
        <span className="absolute top-1 right-1 flex h-4 w-4 items-center justify-center rounded-full bg-rose-500 text-white text-[10px] font-medium leading-none">
          {unreadCount > 99 ? '99+' : unreadCount}
        </span>
      )}
    </button>
  )
}
