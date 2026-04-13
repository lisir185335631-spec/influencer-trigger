import { useEffect, useRef, useState, useCallback } from 'react'

export type WsMessage = { event: string; data: unknown }
export type WsStatus = 'connecting' | 'connected' | 'disconnected'

export function useWebSocket(url: string, onMessage?: (msg: WsMessage) => void) {
  const wsRef = useRef<WebSocket | null>(null)
  const [status, setStatus] = useState<WsStatus>('disconnected')
  const retryRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return

    setStatus('connecting')
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => {
      setStatus('connected')
      retryRef.current = 0
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string) as WsMessage
        onMessageRef.current?.(msg)
      } catch {
        // ignore malformed messages
      }
    }

    ws.onclose = () => {
      setStatus('disconnected')
      wsRef.current = null
      // Exponential backoff: 1s → 2s → 4s → … max 30s
      const delay = Math.min(1000 * Math.pow(2, retryRef.current), 30000)
      retryRef.current++
      timerRef.current = setTimeout(connect, delay)
    }

    ws.onerror = () => {
      ws.close()
    }
  }, [url])

  useEffect(() => {
    connect()
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
      if (wsRef.current) {
        wsRef.current.onclose = null // prevent auto-reconnect on unmount
        wsRef.current.close()
      }
    }
  }, [connect])

  return { status }
}
