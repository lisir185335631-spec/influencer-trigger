import { useState, useEffect, useCallback } from 'react'
import { useTranslation } from 'react-i18next'
import { X, RefreshCw, CheckCircle, XCircle } from 'lucide-react'
import { webhookLogsApi, WebhookLogItem } from '../api/webhook_logs'
import { useWebSocket, WsMessage } from '../hooks/useWebSocket'
import { WS_URL } from '../api/websocket'

interface Props {
  open: boolean
  onClose: () => void
  /** Channel to display. Defaults to 'serverchan' since the dashboard
   *  card is Server酱-specific; pass empty string to show every channel
   *  (used by future "all channels" entry-points). */
  channel?: string
}

const formatTime = (iso: string): string => {
  try {
    return new Date(iso).toLocaleString()
  } catch {
    return iso
  }
}

const truncate = (s: string, n: number): string =>
  s.length > n ? s.slice(0, n - 1) + '…' : s

export default function WebhookPushLogsModal({
  open,
  onClose,
  channel = 'serverchan',
}: Props) {
  const { t } = useTranslation()
  const [items, setItems] = useState<WebhookLogItem[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const res = await webhookLogsApi.list({ channel, limit: 50 })
      setItems(res.items)
    } catch {
      setError(t('webhookLogs.modal.loadFailed'))
    } finally {
      setLoading(false)
    }
  }, [channel, t])

  // Reload whenever the modal transitions from closed → open. Cleared
  // payload on close keeps a stale list from flashing on next open.
  useEffect(() => {
    if (open) {
      load()
    } else {
      setItems([])
      setError('')
    }
  }, [open, load])

  // Real-time prepend on new push events. Filter by channel so a future
  // multi-channel surface still gets the right rows. Cap the in-memory
  // list at 100 to avoid pathological memory growth on long sessions.
  useWebSocket(
    WS_URL,
    useCallback(
      (msg: WsMessage) => {
        if (!open) return
        if (msg.event !== 'webhook:pushed') return
        const data = msg.data as WebhookLogItem
        if (channel && data.channel !== channel) return
        setItems((prev) => [data, ...prev].slice(0, 100))
      },
      [open, channel],
    ),
  )

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl w-full max-w-6xl mx-4 max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-900">
            {t('webhookLogs.modal.title')}
          </h2>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              disabled={loading}
              className="p-1.5 rounded hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-colors disabled:opacity-50"
              aria-label={t('common.refresh')}
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-colors"
              aria-label={t('common.close')}
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">
          {error && (
            <div className="m-4 p-3 bg-red-50 border border-red-100 rounded-lg text-sm text-red-700">
              {error}
            </div>
          )}

          {!loading && items.length === 0 && !error && (
            <div className="p-12 text-center text-sm text-gray-400">
              {t('webhookLogs.modal.empty')}
            </div>
          )}

          {items.length > 0 && (
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0 z-10">
                <tr className="text-xs font-medium text-gray-500">
                  <th className="px-4 py-2 text-left">{t('webhookLogs.col.time')}</th>
                  <th className="px-4 py-2 text-left">{t('webhookLogs.col.channel')}</th>
                  <th className="px-4 py-2 text-left">{t('webhookLogs.col.email')}</th>
                  <th className="px-4 py-2 text-left">{t('webhookLogs.col.content')}</th>
                  <th className="px-4 py-2 text-center">{t('webhookLogs.col.status')}</th>
                  <th className="px-4 py-2 text-left">{t('webhookLogs.col.error')}</th>
                  <th className="px-4 py-2 text-right">{t('webhookLogs.col.duration')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {items.map((item) => (
                  <tr
                    key={item.id}
                    className={
                      item.status === 'failed'
                        ? 'bg-red-50/50 hover:bg-red-50'
                        : 'hover:bg-gray-50'
                    }
                  >
                    <td className="px-4 py-2.5 text-xs text-gray-500 whitespace-nowrap">
                      {formatTime(item.created_at)}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className="inline-block px-2 py-0.5 rounded text-xs font-medium bg-purple-50 text-purple-700">
                        {item.channel}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-600 whitespace-nowrap">
                      {item.email_id ? `#${item.email_id}` : '—'}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-700 max-w-[420px]">
                      <div className="font-medium">{truncate(item.title, 60)}</div>
                      <div className="text-gray-400">
                        {truncate(item.content_preview, 100)}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      {item.status === 'success' ? (
                        <CheckCircle size={14} className="inline text-green-500" />
                      ) : (
                        <XCircle size={14} className="inline text-red-500" />
                      )}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-600 max-w-[260px]">
                      {item.http_code ? `HTTP ${item.http_code}` : ''}
                      {item.http_code && item.error_message ? ' · ' : ''}
                      <span className="text-gray-500">
                        {item.error_message ? truncate(item.error_message, 80) : ''}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-xs text-gray-500 text-right tabular-nums whitespace-nowrap">
                      {item.duration_ms}ms
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-100 text-xs text-gray-400">
          {t('webhookLogs.modal.footerHint', { count: items.length })}
        </div>
      </div>
    </div>
  )
}
