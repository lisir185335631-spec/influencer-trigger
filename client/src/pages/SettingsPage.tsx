import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuthContext } from '../stores/AuthContext'
import {
  getSettings,
  updateSettings,
  testWebhook,
  testApifyActor,
  SystemSettings,
  SystemSettingsUpdate,
  ApifyPlatform,
  getYouTubeCookiesStatus,
  saveYouTubeCookies,
  deleteYouTubeCookies,
  YouTubeCookiesStatus,
} from '../api/settings'

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'
type TestStatus = Record<string, 'idle' | 'testing' | 'ok' | 'fail'>
type CookieSaveState =
  | { kind: 'idle' }
  | { kind: 'saving' }
  | { kind: 'saved' }
  | { kind: 'error'; message: string }

type ApifyTestState = {
  status: 'idle' | 'testing' | 'ok' | 'fail'
  message?: string
}

const APIFY_PLATFORMS: {
  key: ApifyPlatform
  labelKey: string
  tokenField: 'apify_tiktok_token' | 'apify_ig_token'
  tokenSetField: 'apify_tiktok_token_set' | 'apify_ig_token_set'
  actorField: 'apify_tiktok_actor' | 'apify_ig_actor'
  actorPlaceholder: string
}[] = [
  {
    key: 'tiktok',
    labelKey: 'settings.apify.tiktok',
    tokenField: 'apify_tiktok_token',
    tokenSetField: 'apify_tiktok_token_set',
    actorField: 'apify_tiktok_actor',
    actorPlaceholder: 'jurassic_jove~tiktok-email-scraper',
  },
  {
    key: 'instagram',
    labelKey: 'settings.apify.instagram',
    tokenField: 'apify_ig_token',
    tokenSetField: 'apify_ig_token_set',
    actorField: 'apify_ig_actor',
    actorPlaceholder: 'apify~instagram-profile-scraper',
  },
]

export default function SettingsPage() {
  const { t } = useTranslation()
  const { role } = useAuthContext()

  const [form, setForm] = useState<SystemSettings | null>(null)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const [testStatus, setTestStatus] = useState<TestStatus>({
    feishu: 'idle',
    slack: 'idle',
  })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Track which Apify token fields the user has actually edited. The GET
  // response gives us masked tokens like "****abcd"; if the user doesn't
  // touch the field we must NOT send that masked value back as the new token
  // — the server would write the literal "****abcd" string and break the
  // scraper. Only fields in this set get included in the PUT payload.
  const apifyTokenDirty = useRef<Set<ApifyPlatform>>(new Set())
  const [apifyTest, setApifyTest] = useState<Record<ApifyPlatform, ApifyTestState>>({
    tiktok: { status: 'idle' },
    instagram: { status: 'idle' },
  })

  // YouTube cookies state — independent from the main `form` because it's
  // a file-backed config (server/data/youtube-cookies.json), not a DB row,
  // and has its own GET/POST/DELETE endpoints.
  const [cookiesStatus, setCookiesStatus] = useState<YouTubeCookiesStatus | null>(null)
  const [cookiesRaw, setCookiesRaw] = useState('')
  const [cookieSave, setCookieSave] = useState<CookieSaveState>({ kind: 'idle' })
  const [showInstructions, setShowInstructions] = useState(false)
  const [cookiesDeleting, setCookiesDeleting] = useState(false)

  const refreshCookiesStatus = async () => {
    try {
      const s = await getYouTubeCookiesStatus()
      setCookiesStatus(s)
    } catch {
      // Status fetch failure is non-fatal: leave the section showing the
      // last known state. Save/delete actions surface their own errors.
    }
  }

  useEffect(() => {
    if (role === 'operator') return
    getSettings()
      .then((data) => {
        setForm(data)
      })
      .catch(() => setError(t('settings.loadFailed')))
      .finally(() => setLoading(false))
    refreshCookiesStatus()
  }, [role])

  if (role === 'operator') {
    return (
      <div className="p-6">
        <div className="border border-gray-100 rounded-lg p-8 text-center text-gray-400 text-sm">
          {t('settings.accessDenied')}
        </div>
      </div>
    )
  }

  const handleChange = <K extends keyof SystemSettings>(
    key: K,
    value: SystemSettings[K],
  ) => {
    setForm((prev) => (prev ? { ...prev, [key]: value } : prev))
  }

  const handleSave = async () => {
    if (!form) return
    setSaveStatus('saving')
    try {
      const patch: SystemSettingsUpdate = {
        follow_up_enabled: form.follow_up_enabled,
        interval_days: form.interval_days,
        max_count: form.max_count,
        hour_utc: form.hour_utc,
        scrape_concurrency: form.scrape_concurrency,
        webhook_feishu: form.webhook_feishu,
        webhook_slack: form.webhook_slack,
        // Actors are not secrets — always send them so cleared/edited values
        // round-trip correctly.
        apify_tiktok_actor: form.apify_tiktok_actor,
        apify_ig_actor: form.apify_ig_actor,
      }
      // Tokens: only send fields the user actually touched (otherwise we'd
      // overwrite real tokens with masked placeholders).
      if (apifyTokenDirty.current.has('tiktok')) {
        patch.apify_tiktok_token = form.apify_tiktok_token
      }
      if (apifyTokenDirty.current.has('instagram')) {
        patch.apify_ig_token = form.apify_ig_token
      }
      const updated = await updateSettings(patch)
      setForm(updated)
      apifyTokenDirty.current.clear()
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus('idle'), 2500)
    } catch {
      setSaveStatus('error')
      setTimeout(() => setSaveStatus('idle'), 3000)
    }
  }

  const handleApifyTokenChange = (platform: ApifyPlatform, value: string) => {
    apifyTokenDirty.current.add(platform)
    if (platform === 'tiktok') {
      handleChange('apify_tiktok_token', value)
    } else {
      handleChange('apify_ig_token', value)
    }
    // Reset test state when user edits the token.
    setApifyTest((prev) => ({ ...prev, [platform]: { status: 'idle' } }))
  }

  const handleTestApify = async (platform: ApifyPlatform) => {
    if (!form) return
    setApifyTest((prev) => ({ ...prev, [platform]: { status: 'testing' } }))
    try {
      // Send the in-memory token only if user has edited it (otherwise the
      // server-side resolver uses the saved DB value). Always send the actor
      // since it's not secret and the user may be testing an unsaved actor.
      const token = apifyTokenDirty.current.has(platform)
        ? form[platform === 'tiktok' ? 'apify_tiktok_token' : 'apify_ig_token']
        : undefined
      const actor =
        platform === 'tiktok' ? form.apify_tiktok_actor : form.apify_ig_actor
      const result = await testApifyActor(platform, token, actor || undefined)
      setApifyTest((prev) => ({
        ...prev,
        [platform]: {
          status: result.success ? 'ok' : 'fail',
          message: result.message,
        },
      }))
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } }
      setApifyTest((prev) => ({
        ...prev,
        [platform]: {
          status: 'fail',
          message: err?.response?.data?.detail || t('settings.apify.testError'),
        },
      }))
    }
    setTimeout(() => {
      setApifyTest((prev) => ({ ...prev, [platform]: { status: 'idle' } }))
    }, 6000)
  }

  const handleSaveCookies = async () => {
    if (!cookiesRaw.trim()) return
    setCookieSave({ kind: 'saving' })
    try {
      const updated = await saveYouTubeCookies(cookiesRaw)
      setCookiesStatus(updated)
      setCookiesRaw('')
      setCookieSave({ kind: 'saved' })
      setTimeout(() => setCookieSave({ kind: 'idle' }), 2500)
    } catch (e: unknown) {
      // FastAPI HTTPException returns {detail: "..."}; axios surfaces it
      // at err.response.data.detail. Anything else is a network/unknown
      // error so we fall back to the i18n string.
      const err = e as { response?: { data?: { detail?: string } } }
      const detail =
        err?.response?.data?.detail || t('settings.youtubeCookies.saveError', { message: '' })
      setCookieSave({ kind: 'error', message: detail })
      setTimeout(() => setCookieSave({ kind: 'idle' }), 6000)
    }
  }

  const handleDeleteCookies = async () => {
    if (!confirm(t('settings.youtubeCookies.deleteConfirm'))) return
    setCookiesDeleting(true)
    try {
      const updated = await deleteYouTubeCookies()
      setCookiesStatus(updated)
    } catch {
      // ignored: status will refresh on next visit
    } finally {
      setCookiesDeleting(false)
    }
  }

  const handleTest = async (platform: 'feishu' | 'slack') => {
    const url =
      platform === 'feishu' ? form?.webhook_feishu : form?.webhook_slack
    if (!url) return
    setTestStatus((prev) => ({ ...prev, [platform]: 'testing' }))
    try {
      const result = await testWebhook(platform, url)
      setTestStatus((prev) => ({
        ...prev,
        [platform]: result.success ? 'ok' : 'fail',
      }))
    } catch {
      setTestStatus((prev) => ({ ...prev, [platform]: 'fail' }))
    }
    setTimeout(() => {
      setTestStatus((prev) => ({ ...prev, [platform]: 'idle' }))
    }, 3000)
  }

  if (loading) {
    return (
      <div className="p-6 text-sm text-gray-400">{t('settings.loading')}</div>
    )
  }

  if (error || !form) {
    return (
      <div className="p-6 text-sm text-red-500">{error || t('settings.loadFailed')}</div>
    )
  }

  return (
    <div className="p-6 max-w-2xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-semibold text-gray-900">{t('settings.title')}</h1>
        <button
          onClick={handleSave}
          disabled={saveStatus === 'saving'}
          className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
            saveStatus === 'saving'
              ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
              : saveStatus === 'saved'
              ? 'bg-green-50 text-green-700 border border-green-200'
              : saveStatus === 'error'
              ? 'bg-red-50 text-red-700 border border-red-200'
              : 'bg-gray-900 text-white hover:bg-gray-700'
          }`}
        >
          {saveStatus === 'saving'
            ? t('settings.save.saving')
            : saveStatus === 'saved'
            ? t('settings.save.saved')
            : saveStatus === 'error'
            ? t('settings.save.failed')
            : t('settings.save.button')}
        </button>
      </div>

      {/* Follow-up strategy */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-4">
          {t('settings.followUp.title')}
        </h2>
        <div className="space-y-4">
          <div className="flex items-center justify-between py-3 border-b border-gray-50">
            <div>
              <div className="text-sm font-medium text-gray-800">{t('settings.followUp.enable')}</div>
              <div className="text-xs text-gray-400 mt-0.5">
                {t('settings.followUp.enableHint')}
              </div>
            </div>
            <button
              onClick={() =>
                handleChange('follow_up_enabled', !form.follow_up_enabled)
              }
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
                form.follow_up_enabled ? 'bg-gray-900' : 'bg-gray-200'
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow transition-transform ${
                  form.follow_up_enabled ? 'translate-x-5' : 'translate-x-1'
                }`}
              />
            </button>
          </div>

          <div className="flex items-center justify-between py-3 border-b border-gray-50">
            <div>
              <div className="text-sm font-medium text-gray-800">{t('settings.followUp.interval')}</div>
              <div className="text-xs text-gray-400 mt-0.5">
                {t('settings.followUp.intervalHint')}
              </div>
            </div>
            <input
              type="number"
              min={1}
              max={365}
              value={form.interval_days}
              onChange={(e) =>
                handleChange('interval_days', parseInt(e.target.value) || 1)
              }
              className="w-20 text-right border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:border-gray-400"
            />
          </div>

          <div className="flex items-center justify-between py-3 border-b border-gray-50">
            <div>
              <div className="text-sm font-medium text-gray-800">{t('settings.followUp.max')}</div>
              <div className="text-xs text-gray-400 mt-0.5">
                {t('settings.followUp.maxHint')}
              </div>
            </div>
            <input
              type="number"
              min={1}
              max={50}
              value={form.max_count}
              onChange={(e) =>
                handleChange('max_count', parseInt(e.target.value) || 1)
              }
              className="w-20 text-right border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:border-gray-400"
            />
          </div>

          <div className="flex items-center justify-between py-3 border-b border-gray-50">
            <div>
              <div className="text-sm font-medium text-gray-800">{t('settings.followUp.sendTime')}</div>
              <div className="text-xs text-gray-400 mt-0.5">
                {t('settings.followUp.sendTimeHint')}
              </div>
            </div>
            <input
              type="number"
              min={0}
              max={23}
              value={form.hour_utc}
              onChange={(e) =>
                handleChange('hour_utc', parseInt(e.target.value) || 0)
              }
              className="w-20 text-right border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:border-gray-400"
            />
          </div>
        </div>
      </section>

      {/* Scrape config */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-4">
          {t('settings.scrape.title')}
        </h2>
        <div className="flex items-center justify-between py-3 border-b border-gray-50">
          <div>
            <div className="text-sm font-medium text-gray-800">{t('settings.scrape.concurrency')}</div>
            <div className="text-xs text-gray-400 mt-0.5">
              {t('settings.scrape.concurrencyHint')}
            </div>
          </div>
          <input
            type="number"
            min={1}
            max={50}
            value={form.scrape_concurrency}
            onChange={(e) =>
              handleChange('scrape_concurrency', parseInt(e.target.value) || 1)
            }
            className="w-20 text-right border border-gray-200 rounded px-2 py-1 text-sm focus:outline-none focus:border-gray-400"
          />
        </div>
      </section>

      {/* Apify per-platform configuration */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-2">
          {t('settings.apify.title')}
        </h2>
        <div className="text-xs text-gray-400 mb-4">
          {t('settings.apify.subtitle')}
        </div>

        <div className="space-y-6">
          {APIFY_PLATFORMS.map((p) => {
            const tokenSet = form[p.tokenSetField]
            const tokenValue = form[p.tokenField]
            const dirty = apifyTokenDirty.current.has(p.key)
            const test = apifyTest[p.key]

            return (
              <div key={p.key} className="border border-gray-100 rounded-lg p-4">
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span
                      className={`inline-block w-2 h-2 rounded-full ${
                        tokenSet ? 'bg-green-500' : 'bg-gray-300'
                      }`}
                    />
                    <div className="text-sm font-medium text-gray-800">
                      {t(p.labelKey)}
                    </div>
                    <span className="text-xs text-gray-400">
                      {tokenSet
                        ? t('settings.apify.statusConfigured')
                        : t('settings.apify.statusNotConfigured')}
                    </span>
                  </div>
                  <button
                    onClick={() => handleTestApify(p.key)}
                    disabled={test.status === 'testing'}
                    className={`text-xs px-3 py-1 rounded border transition-colors ${
                      test.status === 'ok'
                        ? 'border-green-200 text-green-600 bg-green-50'
                        : test.status === 'fail'
                        ? 'border-red-200 text-red-600 bg-red-50'
                        : 'border-gray-200 text-gray-500 hover:border-gray-400 disabled:opacity-40 disabled:cursor-not-allowed'
                    }`}
                  >
                    {test.status === 'testing'
                      ? t('settings.apify.test.testing')
                      : test.status === 'ok'
                      ? t('settings.apify.test.success')
                      : test.status === 'fail'
                      ? t('settings.apify.test.failed')
                      : t('settings.apify.test.button')}
                  </button>
                </div>

                <div className="space-y-3">
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">
                      {t('settings.apify.tokenLabel')}
                    </label>
                    <input
                      type="password"
                      autoComplete="off"
                      value={tokenValue}
                      placeholder={
                        tokenSet && !dirty
                          ? t('settings.apify.tokenMasked')
                          : t('settings.apify.tokenPlaceholder')
                      }
                      onChange={(e) =>
                        handleApifyTokenChange(p.key, e.target.value)
                      }
                      className="w-full border border-gray-200 rounded px-3 py-2 text-sm font-mono focus:outline-none focus:border-gray-400 placeholder-gray-300"
                    />
                    {tokenSet && !dirty && (
                      <div className="text-xs text-gray-400 mt-1">
                        {t('settings.apify.tokenMaskedHint', { masked: tokenValue })}
                      </div>
                    )}
                  </div>

                  <div>
                    <label className="text-xs text-gray-500 block mb-1">
                      {t('settings.apify.actorLabel')}
                    </label>
                    <input
                      type="text"
                      value={form[p.actorField]}
                      placeholder={p.actorPlaceholder}
                      onChange={(e) =>
                        handleChange(p.actorField, e.target.value)
                      }
                      className="w-full border border-gray-200 rounded px-3 py-2 text-sm font-mono focus:outline-none focus:border-gray-400 placeholder-gray-300"
                    />
                    <div className="text-xs text-gray-400 mt-1">
                      {t('settings.apify.actorHint', { fallback: p.actorPlaceholder })}
                    </div>
                  </div>
                </div>

                {test.status === 'fail' && test.message && (
                  <div className="mt-3 px-3 py-2 bg-red-50 border border-red-100 rounded text-xs text-red-700">
                    {test.message}
                  </div>
                )}
                {test.status === 'ok' && test.message && (
                  <div className="mt-3 px-3 py-2 bg-green-50 border border-green-100 rounded text-xs text-green-700">
                    {test.message}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        <div className="mt-3 px-3 py-2 bg-amber-50 border border-amber-100 rounded text-xs text-amber-700">
          {t('settings.apify.warning')}
        </div>
      </section>

      {/* YouTube cookies */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-2">
          {t('settings.youtubeCookies.title')}
        </h2>
        <div className="text-xs text-gray-400 mb-4">
          {t('settings.youtubeCookies.subtitle')}
        </div>

        {/* Status row */}
        <div className="flex items-center justify-between py-3 border-b border-gray-50">
          <div>
            {cookiesStatus === null ? (
              <div className="text-sm text-gray-400">
                {t('settings.youtubeCookies.loading')}
              </div>
            ) : cookiesStatus.configured ? (
              <div className="space-y-1">
                <div className="flex items-center gap-2 text-sm">
                  {cookiesStatus.auth_complete ? (
                    <span className="inline-block w-2 h-2 rounded-full bg-green-500" />
                  ) : (
                    <span className="inline-block w-2 h-2 rounded-full bg-amber-500" />
                  )}
                  <span className="font-medium text-gray-800">
                    {t('settings.youtubeCookies.statusConfigured')}
                  </span>
                  <span className="text-xs text-gray-400">
                    {t('settings.youtubeCookies.statusCount', { count: cookiesStatus.count })}
                  </span>
                </div>
                {!cookiesStatus.auth_complete && (
                  <div className="text-xs text-amber-600">
                    {t('settings.youtubeCookies.statusIncomplete')}
                  </div>
                )}
                {cookiesStatus.updated_at && (
                  <div className="text-xs text-gray-400">
                    {t('settings.youtubeCookies.statusUpdatedAt', {
                      time: new Date(cookiesStatus.updated_at).toLocaleString(),
                    })}
                  </div>
                )}
              </div>
            ) : (
              <div className="flex items-center gap-2 text-sm">
                <span className="inline-block w-2 h-2 rounded-full bg-gray-300" />
                <span className="text-gray-500">
                  {t('settings.youtubeCookies.statusNotConfigured')}
                </span>
              </div>
            )}
          </div>
          {cookiesStatus?.configured && (
            <button
              onClick={handleDeleteCookies}
              disabled={cookiesDeleting}
              className="text-xs px-3 py-1 rounded border border-gray-200 text-gray-500 hover:border-red-300 hover:text-red-600 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {cookiesDeleting
                ? t('settings.youtubeCookies.deleting')
                : t('settings.youtubeCookies.delete')}
            </button>
          )}
        </div>

        {/* Warning */}
        <div className="mt-3 px-3 py-2 bg-amber-50 border border-amber-100 rounded text-xs text-amber-700">
          {t('settings.youtubeCookies.warning')}
        </div>

        {/* Instructions toggle */}
        <button
          type="button"
          onClick={() => setShowInstructions((v) => !v)}
          className="mt-3 text-xs text-gray-500 hover:text-gray-800 transition-colors flex items-center gap-1"
        >
          <span
            className={`inline-block transform transition-transform ${
              showInstructions ? 'rotate-90' : ''
            }`}
          >
            ▸
          </span>
          {t('settings.youtubeCookies.instructionsToggle')}
        </button>
        {showInstructions && (
          <div className="mt-2 px-4 py-3 bg-gray-50 rounded text-xs text-gray-600 leading-relaxed space-y-1">
            <div>{t('settings.youtubeCookies.instructionsStep1')}</div>
            <div>{t('settings.youtubeCookies.instructionsStep2')}</div>
            <div>{t('settings.youtubeCookies.instructionsStep3')}</div>
            <div>{t('settings.youtubeCookies.instructionsStep4')}</div>
            <div>{t('settings.youtubeCookies.instructionsStep5')}</div>
            <div>{t('settings.youtubeCookies.instructionsStep6')}</div>
            <div>{t('settings.youtubeCookies.instructionsStep7')}</div>
            <div className="mt-2 pt-2 border-t border-gray-200 text-gray-500">
              {t('settings.youtubeCookies.instructionsTip')}
            </div>
          </div>
        )}

        {/* Paste textarea */}
        <textarea
          value={cookiesRaw}
          onChange={(e) => setCookiesRaw(e.target.value)}
          placeholder={t('settings.youtubeCookies.placeholder')}
          rows={6}
          spellCheck={false}
          className="mt-3 w-full border border-gray-200 rounded px-3 py-2 text-xs font-mono focus:outline-none focus:border-gray-400 placeholder-gray-300 resize-y"
        />

        {/* Save row */}
        <div className="mt-3 flex items-center gap-3">
          <button
            onClick={handleSaveCookies}
            disabled={!cookiesRaw.trim() || cookieSave.kind === 'saving'}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
              cookieSave.kind === 'saving'
                ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                : cookieSave.kind === 'saved'
                ? 'bg-green-50 text-green-700 border border-green-200'
                : cookieSave.kind === 'error'
                ? 'bg-red-50 text-red-700 border border-red-200'
                : 'bg-gray-900 text-white hover:bg-gray-700 disabled:bg-gray-200 disabled:text-gray-400 disabled:cursor-not-allowed'
            }`}
          >
            {cookieSave.kind === 'saving'
              ? t('settings.youtubeCookies.saving')
              : cookieSave.kind === 'saved'
              ? t('settings.youtubeCookies.saved')
              : t('settings.youtubeCookies.save')}
          </button>
          {cookieSave.kind === 'error' && (
            <div className="text-xs text-red-600 flex-1">
              {cookieSave.message}
            </div>
          )}
        </div>
      </section>

      {/* Webhook notifications */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-4">
          {t('settings.webhook.title')}
        </h2>
        <div className="space-y-4">
          {/* Feishu */}
          <div className="py-3 border-b border-gray-50">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-medium text-gray-800">{t('settings.webhook.feishu')}</div>
              <button
                onClick={() => handleTest('feishu')}
                disabled={!form.webhook_feishu || testStatus.feishu === 'testing'}
                className={`text-xs px-3 py-1 rounded border transition-colors ${
                  testStatus.feishu === 'ok'
                    ? 'border-green-200 text-green-600 bg-green-50'
                    : testStatus.feishu === 'fail'
                    ? 'border-red-200 text-red-600 bg-red-50'
                    : 'border-gray-200 text-gray-500 hover:border-gray-400 disabled:opacity-40 disabled:cursor-not-allowed'
                }`}
              >
                {testStatus.feishu === 'testing'
                  ? t('settings.webhook.test.sending')
                  : testStatus.feishu === 'ok'
                  ? t('settings.webhook.test.success')
                  : testStatus.feishu === 'fail'
                  ? t('settings.webhook.test.failed')
                  : t('settings.webhook.test.button')}
              </button>
            </div>
            <input
              type="url"
              placeholder={t('settings.webhook.feishuPlaceholder')}
              value={form.webhook_feishu}
              onChange={(e) => handleChange('webhook_feishu', e.target.value)}
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400 placeholder-gray-300"
            />
          </div>

          {/* Slack */}
          <div className="py-3 border-b border-gray-50">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-medium text-gray-800">{t('settings.webhook.slack')}</div>
              <button
                onClick={() => handleTest('slack')}
                disabled={!form.webhook_slack || testStatus.slack === 'testing'}
                className={`text-xs px-3 py-1 rounded border transition-colors ${
                  testStatus.slack === 'ok'
                    ? 'border-green-200 text-green-600 bg-green-50'
                    : testStatus.slack === 'fail'
                    ? 'border-red-200 text-red-600 bg-red-50'
                    : 'border-gray-200 text-gray-500 hover:border-gray-400 disabled:opacity-40 disabled:cursor-not-allowed'
                }`}
              >
                {testStatus.slack === 'testing'
                  ? t('settings.webhook.test.sending')
                  : testStatus.slack === 'ok'
                  ? t('settings.webhook.test.success')
                  : testStatus.slack === 'fail'
                  ? t('settings.webhook.test.failed')
                  : t('settings.webhook.test.button')}
              </button>
            </div>
            <input
              type="url"
              placeholder={t('settings.webhook.slackPlaceholder')}
              value={form.webhook_slack}
              onChange={(e) => handleChange('webhook_slack', e.target.value)}
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400 placeholder-gray-300"
            />
          </div>
        </div>
      </section>

      <div className="pt-2 text-xs text-gray-400">
        {t('settings.footer')}
      </div>
    </div>
  )
}
