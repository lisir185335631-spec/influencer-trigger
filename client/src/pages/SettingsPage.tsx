import { useEffect, useState } from 'react'
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
  const { role } = useAuthContext()

  const [settings, setSettings] = useState<SystemSettings | null>(null)
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
        setSettings(data)
        setForm(data)
      })
      .catch(() => setError('加载设置失败'))
      .finally(() => setLoading(false))
  }, [role])

  if (role === 'operator') {
    return (
      <div className="p-6">
        <div className="border border-gray-100 rounded-lg p-8 text-center text-gray-400 text-sm">
          系统设置 — 仅管理员和经理可访问
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
      setSettings(updated)
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
      <div className="p-6 text-sm text-gray-400">加载设置中…</div>
    )
  }

  if (error || !form) {
    return (
      <div className="p-6 text-sm text-red-500">{error || '加载失败'}</div>
    )
  }

  return (
    <div className="p-6 max-w-2xl">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-lg font-semibold text-gray-900">系统设置</h1>
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
            ? '保存中…'
            : saveStatus === 'saved'
            ? '✓ 已保存'
            : saveStatus === 'error'
            ? '保存失败'
            : '保存设置'}
        </button>
      </div>

      {/* Follow-up strategy */}
      <section className="mb-8">
        <h2 className="text-sm font-medium text-gray-500 uppercase tracking-wide mb-4">
          追发策略
        </h2>
        <div className="space-y-4">
          <div className="flex items-center justify-between py-3 border-b border-gray-50">
            <div>
              <div className="text-sm font-medium text-gray-800">启用自动追发</div>
              <div className="text-xs text-gray-400 mt-0.5">
                开启后定时检查并发送追发邮件
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
              <div className="text-sm font-medium text-gray-800">追发间隔天数</div>
              <div className="text-xs text-gray-400 mt-0.5">
                距上次邮件多少天后触发追发
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
              <div className="text-sm font-medium text-gray-800">最大追发次数</div>
              <div className="text-xs text-gray-400 mt-0.5">
                每位网红最多追发几封邮件
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
              <div className="text-sm font-medium text-gray-800">执行时间（UTC 小时）</div>
              <div className="text-xs text-gray-400 mt-0.5">
                每天定时执行追发检查的 UTC 小时（0–23）
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
          抓取配置
        </h2>
        <div className="flex items-center justify-between py-3 border-b border-gray-50">
          <div>
            <div className="text-sm font-medium text-gray-800">抓取并发数</div>
            <div className="text-xs text-gray-400 mt-0.5">
              同时启动的 Playwright 浏览器实例数量
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
          Webhook 通知
        </h2>
        <div className="space-y-4">
          {/* Feishu */}
          <div className="py-3 border-b border-gray-50">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-medium text-gray-800">飞书 Webhook</div>
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
                  ? '发送中…'
                  : testStatus.feishu === 'ok'
                  ? '✓ 发送成功'
                  : testStatus.feishu === 'fail'
                  ? '✗ 发送失败'
                  : '测试'}
              </button>
            </div>
            <input
              type="url"
              placeholder="https://open.feishu.cn/open-apis/bot/v2/hook/…"
              value={form.webhook_feishu}
              onChange={(e) => handleChange('webhook_feishu', e.target.value)}
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400 placeholder-gray-300"
            />
          </div>

          {/* Slack */}
          <div className="py-3 border-b border-gray-50">
            <div className="flex items-center justify-between mb-2">
              <div className="text-sm font-medium text-gray-800">Slack Webhook</div>
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
                  ? '发送中…'
                  : testStatus.slack === 'ok'
                  ? '✓ 发送成功'
                  : testStatus.slack === 'fail'
                  ? '✗ 发送失败'
                  : '测试'}
              </button>
            </div>
            <input
              type="url"
              placeholder="https://hooks.slack.com/services/…"
              value={form.webhook_slack}
              onChange={(e) => handleChange('webhook_slack', e.target.value)}
              className="w-full border border-gray-200 rounded px-3 py-2 text-sm focus:outline-none focus:border-gray-400 placeholder-gray-300"
            />
          </div>
        </div>
      </section>

      <div className="pt-2 text-xs text-gray-400">
        修改后点击右上角「保存设置」立即生效
      </div>
    </div>
  )
}
