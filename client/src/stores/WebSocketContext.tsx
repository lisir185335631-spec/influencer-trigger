import { createContext, useContext, ReactNode, useState, useCallback } from 'react'
import { useWebSocket, WsMessage, WsStatus } from '../hooks/useWebSocket'

interface WebSocketContextValue {
  status: WsStatus
  unreadCount: number
  clearUnread: () => void
  notificationTick: number
}

const WebSocketContext = createContext<WebSocketContextValue | null>(null)

const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const [unreadCount, setUnreadCount] = useState(0)
  const [notificationTick, setNotificationTick] = useState(0)

  const handleMessage = useCallback((msg: WsMessage) => {
    if (msg.event === 'notification') {
      setUnreadCount((prev) => prev + 1)
      setNotificationTick((prev) => prev + 1)
    }
  }, [])

  const { status } = useWebSocket(WS_URL, handleMessage)

  const clearUnread = useCallback(() => setUnreadCount(0), [])

  return (
    <WebSocketContext.Provider value={{ status, unreadCount, clearUnread, notificationTick }}>
      {children}
    </WebSocketContext.Provider>
  )
}

export function useWebSocketContext() {
  const ctx = useContext(WebSocketContext)
  if (!ctx) throw new Error('useWebSocketContext must be inside WebSocketProvider')
  return ctx
}
