import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuthContext } from '../stores/AuthContext'
import {
  getSettings,
  updateSettings,
  testWebhook,
  SystemSettings,
  SystemSettingsUpdate,
} from '../api/settings'

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'
type TestStatus = Record<string, 'idle' | 'testing' | 'ok' | 'fail'>

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

  useEffect(() => {
    if (role === 'operator') return
    getSettings()
      .then((data) => {
        setForm(data)
      })
      .catch(() => setError(t('settings.loadFailed')))
      .finally(() => setLoading(false))
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
      }
      const updated = await updateSettings(patch)
      setForm(updated)
      setSaveStatus('saved')
      setTimeout(() => setSaveStatus('idle'), 2500)
    } catch {
      setSaveStatus('error')
      setTimeout(() => setSaveStatus('idle'), 3000)
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
