import { useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { templatesApi, Template } from '../api/templates'
import { emailsApi, Campaign, EmailProgressEvent } from '../api/emails'
import { useWebSocket, WsMessage } from '../hooks/useWebSocket'

const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`

type Phase = 'setup' | 'sending' | 'done'

interface ProgressState {
  sent: number
  success: number
  failed: number
  total: number
  current_email: string
}

export default function EmailsPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [templates, setTemplates] = useState<Template[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | ''>('')
  const [campaignName, setCampaignName] = useState('')
  const [phase, setPhase] = useState<Phase>('setup')
  const [campaign, setCampaign] = useState<Campaign | null>(null)
  const [progress, setProgress] = useState<ProgressState>({ sent: 0, success: 0, failed: 0, total: 0, current_email: '' })
  const [error, setError] = useState('')
  const [loadingTemplates, setLoadingTemplates] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const influencerIds: number[] = (() => {
    const raw = searchParams.get('influencer_ids')
    if (!raw) return []
    return raw.split(',').map(Number).filter(n => !isNaN(n) && n > 0)
  })()

  // Load templates
  useEffect(() => {
    templatesApi.list()
      .then(setTemplates)
      .catch(() => setError('Failed to load templates'))
      .finally(() => setLoadingTemplates(false))
  }, [])

  // WebSocket listener for real-time progress
  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.event === 'email:progress') {
      const data = msg.data as EmailProgressEvent
      if (campaign && data.campaign_id !== campaign.id) return
      setProgress({
        sent: data.sent,
        success: data.success,
        failed: data.failed,
        total: data.total,
        current_email: data.current_email ?? '',
      })
    } else if (msg.event === 'email:completed') {
      const data = msg.data as EmailProgressEvent
      if (campaign && data.campaign_id !== campaign.id) return
      setProgress({
        sent: data.sent,
        success: data.success,
        failed: data.failed,
        total: data.total,
        current_email: '',
      })
      setPhase('done')
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [campaign])

  useWebSocket(WS_URL, handleWsMessage)

  // Poll campaign status as fallback
  useEffect(() => {
    if (phase !== 'sending' || !campaign) return
    pollRef.current = setInterval(async () => {
      try {
        const updated = await emailsApi.getCampaign(campaign.id)
        setProgress(prev => ({
          ...prev,
          sent: updated.sent_count,
          success: updated.success_count,
          failed: updated.failed_count,
          total: updated.total_count,
        }))
        if (updated.status === 'completed' || updated.status === 'failed') {
          setPhase('done')
          clearInterval(pollRef.current!)
        }
      } catch {
        // ignore poll errors
      }
    }, 5000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [phase, campaign])

  const handleSend = async () => {
    if (!selectedTemplateId || influencerIds.length === 0) return
    setSubmitting(true)
    setError('')
    try {
      const resp = await emailsApi.sendBatch({
        influencer_ids: influencerIds,
        template_id: selectedTemplateId as number,
        campaign_name: campaignName.trim() || undefined,
      })
      const camp = await emailsApi.getCampaign(resp.campaign_id)
      setCampaign(camp)
      setProgress({ sent: 0, success: 0, failed: 0, total: resp.total_count, current_email: '' })
      setPhase('sending')
    } catch {
      setError('Failed to start send. Check that mailboxes are configured.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleReset = () => {
    setCampaign(null)
    setProgress({ sent: 0, success: 0, failed: 0, total: 0, current_email: '' })
    setSelectedTemplateId('')
    setCampaignName('')
    setPhase('setup')
    setSearchParams({})
  }

  const progressPct = progress.total > 0 ? Math.round((progress.sent / progress.total) * 100) : 0

  // ── No influencers selected ────────────────────────────────────────────────
  if (phase === 'setup' && influencerIds.length === 0) {
    return (
      <div className="p-6">
        <div className="max-w-xl">
          <h1 className="text-xl font-semibold text-gray-900 mb-2">Batch Send</h1>
          <p className="text-sm text-gray-500 mb-6">
            Send personalised emails to influencers at scale using multi-mailbox rotation.
          </p>
          <div className="border border-gray-100 rounded-xl p-8 text-center">
            <div className="w-10 h-10 bg-gray-50 rounded-full flex items-center justify-center mx-auto mb-3">
              <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                  d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
              </svg>
            </div>
            <p className="text-sm text-gray-500 mb-1">No influencers selected</p>
            <p className="text-xs text-gray-400">
              Go to <a href="/scrape" className="text-blue-500 hover:underline">Scrape</a>, open a task, select influencers, and click "Send All".
            </p>
          </div>
        </div>
      </div>
    )
  }

  // ── Setup form ─────────────────────────────────────────────────────────────
  if (phase === 'setup') {
    return (
      <div className="p-6">
        <div className="max-w-xl">
          <h1 className="text-xl font-semibold text-gray-900 mb-1">Batch Send</h1>
          <p className="text-sm text-gray-500 mb-6">
            Configure and launch your email campaign.
          </p>

          {/* Influencer count badge */}
          <div className="flex items-center gap-2 mb-6 p-3 bg-blue-50 rounded-lg border border-blue-100">
            <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white text-xs font-semibold">
              {influencerIds.length}
            </span>
            <span className="text-sm text-blue-700">
              influencer{influencerIds.length !== 1 ? 's' : ''} selected
            </span>
          </div>

          {/* Campaign name */}
          <div className="mb-4">
            <label className="block text-xs font-medium text-gray-500 mb-1 uppercase tracking-wide">
              Campaign Name <span className="text-gray-300 font-normal normal-case">(optional)</span>
            </label>
            <input
              type="text"
              value={campaignName}
              onChange={e => setCampaignName(e.target.value)}
              placeholder={`Campaign ${new Date().toISOString().slice(0, 10)}`}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          {/* Template selector */}
          <div className="mb-6">
            <label className="block text-xs font-medium text-gray-500 mb-1 uppercase tracking-wide">
              Email Template <span className="text-red-400">*</span>
            </label>
            {loadingTemplates ? (
              <div className="h-10 bg-gray-50 rounded-lg animate-pulse" />
            ) : templates.length === 0 ? (
              <p className="text-sm text-gray-400">
                No templates found.{' '}
                <a href="/templates" className="text-blue-500 hover:underline">Create one first.</a>
              </p>
            ) : (
              <select
                value={selectedTemplateId}
                onChange={e => setSelectedTemplateId(Number(e.target.value))}
                className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white"
              >
                <option value="">Select a template…</option>
                {templates.map(t => (
                  <option key={t.id} value={t.id}>
                    {t.name}{t.industry ? ` · ${t.industry}` : ''}{t.style ? ` · ${t.style}` : ''}
                  </option>
                ))}
              </select>
            )}
          </div>

          {error && (
            <p className="text-sm text-red-500 mb-4">{error}</p>
          )}

          <button
            onClick={handleSend}
            disabled={!selectedTemplateId || submitting || influencerIds.length === 0}
            className="w-full bg-gray-900 text-white text-sm font-medium py-2.5 rounded-lg hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? 'Starting…' : `Send to ${influencerIds.length} Influencer${influencerIds.length !== 1 ? 's' : ''}`}
          </button>

          <p className="text-xs text-gray-400 mt-3 text-center">
            Emails are sent with 30-60s intervals using your active mailboxes.
          </p>
        </div>
      </div>
    )
  }

  // ── Progress / Done panel ──────────────────────────────────────────────────
  const isDone = phase === 'done'

  return (
    <div className="p-6">
      <div className="max-w-xl">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">
              {isDone ? 'Campaign Complete' : 'Sending…'}
            </h1>
            {campaign && (
              <p className="text-sm text-gray-400 mt-0.5">{campaign.name}</p>
            )}
          </div>
          {isDone && (
            <span className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full bg-green-50 text-green-700 border border-green-100">
              <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
              Done
            </span>
          )}
          {!isDone && (
            <span className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-100">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
              Running
            </span>
          )}
        </div>

        {/* Stat cards */}
        <div className="grid grid-cols-4 gap-3 mb-6">
          {[
            { label: 'Total', value: progress.total, color: 'text-gray-900' },
            { label: 'Sent', value: progress.sent, color: 'text-gray-900' },
            { label: 'Success', value: progress.success, color: 'text-green-600' },
            { label: 'Failed', value: progress.failed, color: 'text-red-500' },
          ].map(({ label, value, color }) => (
            <div key={label} className="border border-gray-100 rounded-xl p-3 text-center">
              <div className={`text-2xl font-semibold ${color}`}>{value}</div>
              <div className="text-xs text-gray-400 mt-0.5">{label}</div>
            </div>
          ))}
        </div>

        {/* Progress bar */}
        <div className="mb-4">
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span>{progressPct}% complete</span>
            <span>{progress.sent} / {progress.total}</span>
          </div>
          <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-gray-900 rounded-full transition-all duration-500"
              style={{ width: `${progressPct}%` }}
            />
          </div>
        </div>

        {/* Current email */}
        {!isDone && progress.current_email && (
          <p className="text-xs text-gray-400 mb-6">
            Sending to <span className="text-gray-600 font-medium">{progress.current_email}</span>…
          </p>
        )}

        {/* Note on delays */}
        {!isDone && (
          <p className="text-xs text-gray-400 mb-6">
            Sending with 30-60s intervals to avoid rate limits. This may take a while.
          </p>
        )}

        {isDone && (
          <button
            onClick={handleReset}
            className="w-full border border-gray-200 text-gray-700 text-sm font-medium py-2.5 rounded-lg hover:bg-gray-50 transition-colors"
          >
            Send Another Batch
          </button>
        )}
      </div>
    </div>
  )
}
