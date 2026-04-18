import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { AlertTriangle, CheckCircle, Clock, Key, RefreshCw, Shield, X } from 'lucide-react'
import {
  type KeyRotationHistoryOut,
  type SecurityAlertOut,
  type TwoFAConfig,
  acknowledgeAlert,
  get2FAConfig,
  getKeyRotationHistory,
  listAlerts,
  patch2FAConfig,
  rotateKeys,
} from '../../api/admin/security_admin'

type Tab = 'alerts' | '2fa' | 'keys'

// ─── Rotate Keys Modal ────────────────────────────────────────────────────────

function RotateKeysModal({
  keyAgeDays,
  onClose,
  onSuccess,
}: {
  keyAgeDays: number | null
  onClose: () => void
  onSuccess: () => void
}) {
  const { t } = useTranslation()
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')

  const handleRotate = async () => {
    if (!password.trim()) {
      setErr(t('admin.security.rotateModal.adminPasswordRequired'))
      return
    }
    setLoading(true)
    setErr('')
    try {
      await rotateKeys(password)
      onSuccess()
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      setErr(msg ?? t('admin.security.rotateModal.rotationFailed'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-2xl shadow-xl p-7 w-[480px] max-w-[92vw]">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2">
            <Key size={16} className="text-orange-500" /> {t('admin.security.rotateModal.title')}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={16} />
          </button>
        </div>

        <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 mb-5 text-sm text-orange-800">
          <p className="font-medium mb-1">{t('admin.security.rotateModal.destructiveTitle')}</p>
          <ul className="list-disc list-inside space-y-1 text-xs">
            <li>{t('admin.security.rotateModal.warningJwt')}</li>
            <li>{t('admin.security.rotateModal.warningSessions')}</li>
            <li>{t('admin.security.rotateModal.warningLogin')}</li>
            {keyAgeDays !== null && keyAgeDays > 90 && (
              <li className="text-orange-700 font-medium">
                {t('admin.security.rotateModal.warningOldKeys', { count: keyAgeDays })}
              </li>
            )}
          </ul>
        </div>

        <div className="mb-5">
          <label className="block text-xs font-medium text-gray-600 mb-1">
            {t('admin.security.rotateModal.adminPasswordLabel')}
          </label>
          <input
            type="password"
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder={t('admin.security.rotateModal.adminPasswordPlaceholder')}
            onKeyDown={e => e.key === 'Enter' && handleRotate()}
          />
        </div>

        {err && <p className="text-xs text-red-500 mb-4">{err}</p>}

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm border border-gray-200 rounded-lg text-gray-600 hover:bg-gray-50"
          >
            {t('admin.common.cancel')}
          </button>
          <button
            onClick={handleRotate}
            disabled={loading}
            className="px-4 py-2 text-sm bg-orange-500 text-white rounded-lg hover:bg-orange-600 disabled:opacity-50"
          >
            {loading ? t('admin.security.rotateModal.rotating') : t('admin.security.rotateModal.confirmRotate')}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Alerts Tab ───────────────────────────────────────────────────────────────

function AlertsTab() {
  const { t } = useTranslation()
  const [alerts, setAlerts] = useState<SecurityAlertOut[]>([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const load = async () => {
    setLoading(true)
    try {
      const res = await listAlerts()
      setAlerts(res.items)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleAck = async (id: number) => {
    await acknowledgeAlert(id)
    setAlerts(prev => prev.map(a => a.id === id ? { ...a, acknowledged: true } : a))
  }

  const toggleExpand = (id: number) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) { next.delete(id) } else { next.add(id) }
      return next
    })
  }

  const formatDetails = (raw: string | null): string => {
    if (!raw) return ''
    try {
      return JSON.stringify(JSON.parse(raw), null, 2)
    } catch {
      return raw
    }
  }

  const alertTypeLabel = (t: string) =>
    t === 'brute_force' ? '暴力破解' : t === 'new_ip' ? '新 IP 登录' : t

  if (loading) return <p className="text-sm text-gray-400 py-8 text-center">{t('admin.common.loading')}</p>

  if (!alerts.length)
    return (
      <div className="py-16 text-center">
        <CheckCircle size={36} className="mx-auto text-emerald-400 mb-3" />
        <p className="text-sm text-gray-500">{t('admin.security.alerts.noAlerts')}</p>
      </div>
    )

  return (
    <div className="space-y-2">
      {alerts.map(alert => (
        <div
          key={alert.id}
          className={`border rounded-lg overflow-hidden transition-colors ${
            alert.acknowledged ? 'border-gray-100 bg-gray-50' : 'border-red-200 bg-red-50'
          }`}
        >
          <div
            className="flex items-center gap-3 px-4 py-3 cursor-pointer"
            onClick={() => toggleExpand(alert.id)}
          >
            <AlertTriangle
              size={16}
              className={alert.acknowledged ? 'text-gray-400' : 'text-red-500'}
            />
            <div className="flex-1 min-w-0">
              <span className={`text-sm font-medium ${alert.acknowledged ? 'text-gray-500' : 'text-red-700'}`}>
                {alertTypeLabel(alert.alert_type)}
              </span>
              {alert.user_id && (
                <span className="ml-2 text-xs text-gray-400">user #{alert.user_id}</span>
              )}
            </div>
            <span className="text-xs text-gray-400 shrink-0">
              {new Date(alert.created_at).toLocaleString()}
            </span>
            {!alert.acknowledged && (
              <button
                onClick={e => { e.stopPropagation(); handleAck(alert.id) }}
                className="text-xs px-2 py-1 bg-white border border-red-200 text-red-600 rounded hover:bg-red-50 shrink-0"
              >
                {t('admin.security.alerts.markHandled')}
              </button>
            )}
            {alert.acknowledged && (
              <span className="text-xs text-gray-400 shrink-0">{t('admin.security.alerts.handled')}</span>
            )}
          </div>
          {expanded.has(alert.id) && alert.details_json && (
            <div className="border-t border-gray-200 px-4 py-3 bg-white">
              <pre className="text-xs text-gray-600 whitespace-pre-wrap font-mono">
                {formatDetails(alert.details_json)}
              </pre>
              {alert.acknowledged_at && (
                <p className="text-xs text-gray-400 mt-2">
                  {t('admin.security.alerts.handledAt', { time: new Date(alert.acknowledged_at).toLocaleString() })}
                </p>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ─── 2FA Tab ──────────────────────────────────────────────────────────────────

function TwoFATab() {
  const { t } = useTranslation()
  const [config, setConfig] = useState<TwoFAConfig | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    get2FAConfig().then(setConfig)
  }, [])

  const toggle = async (field: keyof TwoFAConfig) => {
    if (!config) return
    const next = { ...config, [field]: !config[field] }
    setConfig(next)
    setSaving(true)
    setSaved(false)
    try {
      const updated = await patch2FAConfig({ [field]: next[field] })
      setConfig(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } finally {
      setSaving(false)
    }
  }

  if (!config) return <p className="text-sm text-gray-400 py-8 text-center">{t('admin.common.loading')}</p>

  return (
    <div className="space-y-5 max-w-lg">
      <div className="bg-white border border-gray-100 rounded-lg divide-y divide-gray-100">
        <div className="flex items-start justify-between px-5 py-4">
          <div>
            <p className="text-sm font-medium text-gray-900">{t('admin.security.twofa.sensitiveReauthTitle')}</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {t('admin.security.twofa.sensitiveReauthDesc')}
            </p>
          </div>
          <button
            onClick={() => toggle('require_password_for_sensitive')}
            disabled={saving}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
              config.require_password_for_sensitive ? 'bg-indigo-600' : 'bg-gray-200'
            }`}
          >
            <span
              className={`pointer-events-none block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform ${
                config.require_password_for_sensitive ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
        <div className="flex items-start justify-between px-5 py-4">
          <div>
            <p className="text-sm font-medium text-gray-900">{t('admin.security.twofa.totpTitle')}</p>
            <p className="text-xs text-gray-500 mt-0.5">
              {t('admin.security.twofa.totpDesc')}
            </p>
          </div>
          <button
            onClick={() => toggle('totp_enabled')}
            disabled={saving}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
              config.totp_enabled ? 'bg-indigo-600' : 'bg-gray-200'
            }`}
          >
            <span
              className={`pointer-events-none block h-5 w-5 rounded-full bg-white shadow ring-0 transition-transform ${
                config.totp_enabled ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
        </div>
      </div>
      {saved && (
        <p className="text-xs text-emerald-600 flex items-center gap-1">
          <CheckCircle size={12} /> {t('admin.security.twofa.saved')}
        </p>
      )}
    </div>
  )
}

// ─── Keys Tab ─────────────────────────────────────────────────────────────────

function KeysTab() {
  const { t } = useTranslation()
  const [history, setHistory] = useState<KeyRotationHistoryOut[]>([])
  const [keyAgeDays, setKeyAgeDays] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [successMsg, setSuccessMsg] = useState('')

  const load = async () => {
    setLoading(true)
    try {
      const res = await getKeyRotationHistory()
      setHistory(res.items)
      setKeyAgeDays(res.key_age_days)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleSuccess = () => {
    setShowModal(false)
    setSuccessMsg(t('admin.security.keys.rotateSuccess'))
    setTimeout(() => setSuccessMsg(''), 5000)
    load()
  }

  return (
    <div>
      {showModal && (
        <RotateKeysModal
          keyAgeDays={keyAgeDays}
          onClose={() => setShowModal(false)}
          onSuccess={handleSuccess}
        />
      )}

      <div className="flex items-start justify-between mb-5">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">{t('admin.security.keys.systemKeyStatus')}</h3>
          {keyAgeDays !== null ? (
            <p className={`text-xs mt-1 ${keyAgeDays > 90 ? 'text-orange-600 font-medium' : 'text-gray-500'}`}>
              {keyAgeDays > 90 && '⚠ '}{t('admin.security.keys.keyAgeDays', { count: keyAgeDays })}
              {keyAgeDays > 90 && t('admin.security.keys.rotationRecommended')}
            </p>
          ) : (
            <p className="text-xs text-gray-400 mt-1">{t('admin.security.keys.noHistory')}</p>
          )}
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="flex items-center gap-2 px-4 py-2 text-sm bg-orange-500 text-white rounded-lg hover:bg-orange-600"
        >
          <RefreshCw size={14} /> {t('admin.security.keys.rotateKeys')}
        </button>
      </div>

      {successMsg && (
        <div className="bg-emerald-50 border border-emerald-200 text-emerald-700 text-sm rounded-lg px-4 py-3 mb-5 flex items-center gap-2">
          <CheckCircle size={14} /> {successMsg}
        </div>
      )}

      <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">{t('admin.security.keys.rotationHistory')}</h3>

      {loading ? (
        <p className="text-sm text-gray-400">{t('admin.common.loading')}</p>
      ) : !history.length ? (
        <div className="text-center py-12 text-gray-400">
          <Clock size={32} className="mx-auto mb-2 opacity-40" />
          <p className="text-sm">{t('admin.security.keys.noRotationHistory')}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {history.map(item => (
            <div key={item.id} className="flex items-start gap-3 bg-white border border-gray-100 rounded-lg px-4 py-3">
              <Key size={14} className="text-gray-400 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-900">
                  {t('admin.security.keys.rotatedBy')} <span className="font-medium">{item.rotated_by_username}</span>
                </p>
                {item.note && <p className="text-xs text-gray-500 mt-0.5">{item.note}</p>}
              </div>
              <span className="text-xs text-gray-400 shrink-0">
                {new Date(item.created_at).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

const TABS: { id: Tab; labelKey: string; icon: typeof Shield }[] = [
  { id: 'alerts', labelKey: 'admin.security.tabs.alerts', icon: AlertTriangle },
  { id: '2fa', labelKey: 'admin.security.tabs.twofa', icon: Shield },
  { id: 'keys', labelKey: 'admin.security.tabs.keys', icon: Key },
]

export default function SecurityPage() {
  const { t } = useTranslation()
  const [tab, setTab] = useState<Tab>('alerts')

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
          <Shield size={20} className="text-indigo-500" /> {t('admin.security.title')}
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          {t('admin.security.subtitle')}
        </p>
      </div>

      <div className="flex gap-1 border-b border-gray-200 mb-6">
        {TABS.map(({ id, labelKey, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              tab === id
                ? 'border-indigo-500 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            <Icon size={14} />
            {t(labelKey)}
          </button>
        ))}
      </div>

      {tab === 'alerts' && <AlertsTab />}
      {tab === '2fa' && <TwoFATab />}
      {tab === 'keys' && <KeysTab />}
    </div>
  )
}
