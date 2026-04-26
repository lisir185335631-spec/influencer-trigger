import { useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { templatesApi, Template } from '../api/templates'
import {
  emailsApi,
  Campaign,
  EmailProgressEvent,
  EmailListItem,
  EmailStats,
} from '../api/emails'
import { draftsApi, AngleOption } from '../api/drafts'
import { useWebSocket, WsMessage } from '../hooks/useWebSocket'

// See WebSocketContext.tsx for why we hardcode :6002 instead of using window.location.host.
const WS_URL = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.hostname}:6002/ws`

// ── Status badge ─────────────────────────────────────────────────────────────

const STATUS_STYLES: Record<string, string> = {
  pending:   'bg-gray-100 text-gray-500',
  sent:      'bg-blue-50 text-blue-600',
  delivered: 'bg-cyan-50 text-cyan-600',
  opened:    'bg-yellow-50 text-yellow-600',
  clicked:   'bg-amber-50 text-amber-600',
  replied:   'bg-green-50 text-green-700',
  bounced:   'bg-red-50 text-red-600',
  failed:    'bg-orange-50 text-orange-600',
}

function StatusBadge({ status }: { status: string }) {
  const cls = STATUS_STYLES[status] ?? 'bg-gray-100 text-gray-500'
  return (
    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${cls}`}>
      {status}
    </span>
  )
}

// ── Status Dashboard tab ──────────────────────────────────────────────────────

const PLATFORMS = ['tiktok', 'instagram', 'youtube', 'twitter', 'facebook', 'other']
const STATUSES  = ['pending', 'sent', 'delivered', 'opened', 'clicked', 'replied', 'bounced', 'failed']
const PAGE_SIZE = 20

function StatusDashboard() {
  const { t } = useTranslation()
  const [stats, setStats]       = useState<EmailStats | null>(null)
  const [items, setItems]       = useState<EmailListItem[]>([])
  const [total, setTotal]       = useState(0)
  const [page, setPage]         = useState(1)
  const [loading, setLoading]   = useState(true)
  const [campaigns, setCampaigns] = useState<Campaign[]>([])

  const [campaignFilter, setCampaignFilter] = useState<number | ''>('')
  const [platformFilter, setPlatformFilter] = useState('')
  const [statusFilter,   setStatusFilter]   = useState('')

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const [statsRes, listRes] = await Promise.all([
        emailsApi.getStats(),
        emailsApi.listEmails({
          campaign_id: campaignFilter || undefined,
          platform:    platformFilter || undefined,
          status:      statusFilter   || undefined,
          page,
          page_size:   PAGE_SIZE,
        }),
      ])
      setStats(statsRes)
      setItems(listRes.items)
      setTotal(listRes.total)
    } catch {
      // ignore — stale data is acceptable
    } finally {
      setLoading(false)
    }
  }, [campaignFilter, platformFilter, statusFilter, page])

  useEffect(() => { loadData() }, [loadData])

  useEffect(() => {
    emailsApi.listCampaigns().then(setCampaigns).catch(() => {})
  }, [])

  // Real-time updates via WebSocket
  const handleWs = useCallback((msg: WsMessage) => {
    if (msg.event === 'email:status_change') {
      loadData()
    }
  }, [loadData])
  useWebSocket(WS_URL, handleWs)

  const resetFilters = () => {
    setCampaignFilter('')
    setPlatformFilter('')
    setStatusFilter('')
    setPage(1)
  }

  // When any filter changes, reset to page 1
  const handleCampaignFilter = (v: number | '') => { setCampaignFilter(v); setPage(1) }
  const handlePlatformFilter = (v: string)       => { setPlatformFilter(v); setPage(1) }
  const handleStatusFilter   = (v: string)       => { setStatusFilter(v);   setPage(1) }

  const statCards = stats ? [
    { label: t('emails.stats.totalSent'),  value: stats.total_sent, color: 'text-gray-900' },
    { label: t('emails.stats.delivered'),  value: stats.delivered,  color: 'text-cyan-600' },
    { label: t('emails.stats.opened'),     value: stats.opened,     color: 'text-yellow-600' },
    { label: t('emails.stats.replied'),    value: stats.replied,    color: 'text-green-600' },
    { label: t('emails.stats.noReply'),    value: stats.no_reply,   color: 'text-gray-400' },
    { label: t('emails.stats.bounced'),    value: stats.bounced,    color: 'text-red-500' },
  ] : []

  return (
    <div>
      {/* Stats cards */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-3 mb-6">
        {statCards.map(({ label, value, color }) => (
          <div key={label} className="border border-gray-100 rounded-xl p-4 text-center">
            <div className={`text-2xl font-semibold ${color}`}>{value}</div>
            <div className="text-xs text-gray-400 mt-0.5">{label}</div>
          </div>
        ))}
        {!stats && Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="border border-gray-100 rounded-xl p-4 text-center animate-pulse">
            <div className="h-8 bg-gray-100 rounded mb-1" />
            <div className="h-3 bg-gray-100 rounded w-2/3 mx-auto" />
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={campaignFilter}
          onChange={e => handleCampaignFilter(e.target.value ? Number(e.target.value) : '')}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">{t('emails.filter.allCampaigns')}</option>
          {campaigns.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>

        <select
          value={platformFilter}
          onChange={e => handlePlatformFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">{t('emails.filter.allPlatforms')}</option>
          {PLATFORMS.map(p => (
            <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
          ))}
        </select>

        <select
          value={statusFilter}
          onChange={e => handleStatusFilter(e.target.value)}
          className="border border-gray-200 rounded-lg px-3 py-1.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">{t('emails.filter.allStatuses')}</option>
          {STATUSES.map(s => (
            <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
          ))}
        </select>

        {(campaignFilter !== '' || platformFilter || statusFilter) && (
          <button
            onClick={resetFilters}
            className="text-xs text-gray-400 hover:text-gray-600 px-2"
          >
            {t('emails.filter.clearFilters')}
          </button>
        )}

        <span className="ml-auto text-xs text-gray-400 self-center">
          {t('emails.emailCount', { count: total })}
        </span>
      </div>

      {/* Email list table */}
      <div className="border border-gray-100 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.influencer')}</th>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.email')}</th>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.campaign')}</th>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.sentAt')}</th>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.status')}</th>
              <th className="text-left px-4 py-2.5 text-xs font-medium text-gray-500 uppercase tracking-wide">{t('emails.table.lastUpdated')}</th>
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 && (
              Array.from({ length: 5 }).map((_, i) => (
                <tr key={i} className="border-b border-gray-50">
                  {Array.from({ length: 6 }).map((_, j) => (
                    <td key={j} className="px-4 py-3">
                      <div className="h-4 bg-gray-100 rounded animate-pulse" />
                    </td>
                  ))}
                </tr>
              ))
            )}
            {!loading && items.length === 0 && (
              <tr>
                <td colSpan={6} className="text-center py-12 text-sm text-gray-400">
                  {t('emails.noEmails')}
                </td>
              </tr>
            )}
            {items.map(item => (
              <tr key={item.id} className="border-b border-gray-50 hover:bg-gray-50 transition-colors">
                <td className="px-4 py-3 font-medium text-gray-800">
                  {item.influencer_name || '—'}
                  {item.influencer_platform && (
                    <span className="ml-1.5 text-xs text-gray-400">{item.influencer_platform}</span>
                  )}
                </td>
                <td className="px-4 py-3 text-gray-500 font-mono text-xs">{item.influencer_email}</td>
                <td className="px-4 py-3 text-gray-500">{item.campaign_name || '—'}</td>
                <td className="px-4 py-3 text-gray-400 text-xs">
                  {item.sent_at ? new Date(item.sent_at).toLocaleString() : '—'}
                </td>
                <td className="px-4 py-3">
                  <StatusBadge status={item.status} />
                </td>
                <td className="px-4 py-3 text-gray-400 text-xs">
                  {new Date(item.updated_at).toLocaleString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-4">
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50 transition-colors"
          >
            {t('emails.prev')}
          </button>
          <span className="text-xs text-gray-400">
            {t('emails.pageOf', { current: page, total: totalPages })}
          </span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg disabled:opacity-40 hover:bg-gray-50 transition-colors"
          >
            {t('emails.next')}
          </button>
        </div>
      )}
    </div>
  )
}

// ── Send Panel (existing batch send UI) ───────────────────────────────────────

type Phase = 'setup' | 'sending' | 'done'

interface ProgressState {
  sent: number
  success: number
  failed: number
  total: number
  current_email: string
}

function SendPanel() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const [templates, setTemplates]       = useState<Template[]>([])
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | ''>('')
  const [campaignName, setCampaignName] = useState('')
  const [phase, setPhase]               = useState<Phase>('setup')
  const [campaign, setCampaign]         = useState<Campaign | null>(null)
  const [progress, setProgress]         = useState<ProgressState>({
    sent: 0, success: 0, failed: 0, total: 0, current_email: '',
  })
  const [error, setError]               = useState('')
  const [loadingTemplates, setLoadingTemplates] = useState(true)
  const [submitting, setSubmitting]     = useState(false)
  // Draft-mode (Phase 1 personalization workflow)
  const [angles, setAngles]             = useState<AngleOption[]>([])
  const [selectedAngle, setSelectedAngle] = useState<string>('friendly')
  const [extraNotes, setExtraNotes]     = useState('')
  const [creatingDraft, setCreatingDraft] = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const influencerIds: number[] = (() => {
    const raw = searchParams.get('influencer_ids')
    if (!raw) return []
    return raw.split(',').map(Number).filter(n => !isNaN(n) && n > 0)
  })()

  useEffect(() => {
    templatesApi.list()
      .then(setTemplates)
      .catch(() => setError(t('emails.batch.loadTemplatesFailed')))
      .finally(() => setLoadingTemplates(false))
    draftsApi.listAngles().then(setAngles).catch(() => { /* non-blocking */ })
  }, [])

  const handleWsMessage = useCallback((msg: WsMessage) => {
    if (msg.event === 'email:progress') {
      const data = msg.data as EmailProgressEvent
      if (campaign && data.campaign_id !== campaign.id) return
      setProgress({
        sent: data.sent, success: data.success, failed: data.failed,
        total: data.total, current_email: data.current_email ?? '',
      })
    } else if (msg.event === 'email:completed') {
      const data = msg.data as EmailProgressEvent
      if (campaign && data.campaign_id !== campaign.id) return
      setProgress({
        sent: data.sent, success: data.success, failed: data.failed,
        total: data.total, current_email: '',
      })
      setPhase('done')
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [campaign])

  useWebSocket(WS_URL, handleWsMessage)

  useEffect(() => {
    if (phase !== 'sending' || !campaign) return
    pollRef.current = setInterval(async () => {
      try {
        const updated = await emailsApi.getCampaign(campaign.id)
        setProgress(prev => ({
          ...prev,
          sent: updated.sent_count, success: updated.success_count,
          failed: updated.failed_count, total: updated.total_count,
        }))
        if (updated.status === 'completed' || updated.status === 'failed') {
          setPhase('done')
          clearInterval(pollRef.current!)
        }
      } catch { /* ignore */ }
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
      setError(t('emails.batch.sendFailed'))
    } finally {
      setSubmitting(false)
    }
  }

  // Draft mode — generates LLM-personalized content per recipient, then
  // jumps to the review page where the user can edit/regenerate before
  // the actual send.
  const handleCreateDraft = async () => {
    if (!selectedTemplateId || influencerIds.length === 0) return
    setCreatingDraft(true); setError('')
    try {
      const resp = await draftsApi.generate({
        influencer_ids: influencerIds,
        template_id: selectedTemplateId as number,
        campaign_name: campaignName.trim() || undefined,
        angle: selectedAngle,
        extra_notes: extraNotes.trim() || undefined,
      })
      navigate(`/campaigns/${resp.campaign_id}/drafts`)
    } catch {
      setError('草稿创建失败')
    } finally {
      setCreatingDraft(false)
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

  // ── No influencers selected ──────────────────────────────────────────────
  if (phase === 'setup' && influencerIds.length === 0) {
    return (
      <div className="max-w-xl">
        <h2 className="text-base font-semibold text-gray-900 mb-2">{t('emails.batch.title')}</h2>
        <p className="text-sm text-gray-500 mb-6">
          {t('emails.batch.subtitle')}
        </p>
        <div className="border border-gray-100 rounded-xl p-8 text-center">
          <div className="w-10 h-10 bg-gray-50 rounded-full flex items-center justify-center mx-auto mb-3">
            <svg className="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
          </div>
          <p className="text-sm text-gray-500 mb-1">{t('emails.batch.noInfluencers')}</p>
          <p className="text-xs text-gray-400">
            {t('emails.batch.noInfluencersHint')}
          </p>
        </div>
      </div>
    )
  }

  // ── Setup form ────────────────────────────────────────────────────────────
  if (phase === 'setup') {
    return (
      <div className="max-w-xl">
        <h2 className="text-base font-semibold text-gray-900 mb-1">{t('emails.batch.title')}</h2>
        <p className="text-sm text-gray-500 mb-6">{t('emails.batch.configureHint')}</p>

        <div className="flex items-center gap-2 mb-6 p-3 bg-blue-50 rounded-lg border border-blue-100">
          <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-blue-500 text-white text-xs font-semibold">
            {influencerIds.length}
          </span>
          <span className="text-sm text-blue-700">
            {t('emails.batch.influencersSelected', { count: influencerIds.length })}
          </span>
        </div>

        <div className="mb-4">
          <label className="block text-xs font-medium text-gray-500 mb-1 uppercase tracking-wide">
            {t('emails.batch.campaignName')} <span className="text-gray-300 font-normal normal-case">{t('emails.batch.optional')}</span>
          </label>
          <input
            type="text"
            value={campaignName}
            onChange={e => setCampaignName(e.target.value)}
            placeholder={`Campaign ${new Date().toISOString().slice(0, 10)}`}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          />
        </div>

        <div className="mb-6">
          <label className="block text-xs font-medium text-gray-500 mb-1 uppercase tracking-wide">
            {t('emails.batch.emailTemplate')} <span className="text-red-400">*</span>
          </label>
          {loadingTemplates ? (
            <div className="h-10 bg-gray-50 rounded-lg animate-pulse" />
          ) : templates.length === 0 ? (
            <p className="text-sm text-gray-400">
              {t('emails.batch.noTemplates')}{' '}
              <a href="/templates" className="text-blue-500 hover:underline">{t('emails.batch.createFirst')}</a>
            </p>
          ) : (
            <select
              value={selectedTemplateId}
              onChange={e => setSelectedTemplateId(Number(e.target.value))}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white"
            >
              <option value="">{t('emails.batch.selectTemplate')}</option>
              {templates.map(tmpl => (
                <option key={tmpl.id} value={tmpl.id}>
                  {tmpl.name}{tmpl.industry ? ` · ${tmpl.industry}` : ''}{tmpl.style ? ` · ${tmpl.style}` : ''}
                </option>
              ))}
            </select>
          )}
        </div>

        {error && <p className="text-sm text-red-500 mb-4">{error}</p>}

        {/* ── Personalized draft mode (preferred for BD outreach) ───────── */}
        <div className="mb-4 p-4 border border-emerald-100 bg-emerald-50 rounded-lg">
          <div className="flex items-start gap-2 mb-3">
            <span className="text-emerald-600 text-base">✨</span>
            <div className="flex-1">
              <div className="text-sm font-medium text-emerald-900">
                AI 个性化草稿模式（推荐）
              </div>
              <div className="text-xs text-emerald-700 mt-0.5">
                为每个网红基于其平台/粉丝/简介/抓取理由生成专属话术，发送前可逐条审阅修改
              </div>
            </div>
          </div>

          <div className="mb-3">
            <label className="block text-xs font-medium text-emerald-800 mb-1 uppercase tracking-wide">
              个性化角度
            </label>
            <select
              value={selectedAngle}
              onChange={e => setSelectedAngle(e.target.value)}
              disabled={angles.length === 0}
              className="w-full border border-emerald-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              {angles.length === 0 && <option>加载中…</option>}
              {angles.map(a => (
                <option key={a.key} value={a.key}>
                  {a.key} — {a.description.slice(0, 60)}
                </option>
              ))}
            </select>
          </div>

          <div className="mb-3">
            <label className="block text-xs font-medium text-emerald-800 mb-1 uppercase tracking-wide">
              品牌补充信息 <span className="text-emerald-500 font-normal normal-case">(可选,会传给 LLM)</span>
            </label>
            <input
              value={extraNotes}
              onChange={e => setExtraNotes(e.target.value)}
              placeholder="例：我们是一家专注创作者经济的 SaaS 公司，预算 $500-$2000/合作"
              className="w-full border border-emerald-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <button
            onClick={handleCreateDraft}
            disabled={!selectedTemplateId || creatingDraft || influencerIds.length === 0}
            className="w-full bg-emerald-600 text-white text-sm font-medium py-2.5 rounded-lg hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {creatingDraft
              ? '创建草稿中…'
              : `创建 ${influencerIds.length} 个个性化草稿（去审核页）`}
          </button>
          <p className="text-xs text-emerald-600 mt-2 text-center">
            ≈ ${(influencerIds.length * 0.0001).toFixed(4)} LLM 成本 (gpt-4o-mini)
          </p>
        </div>

        {/* ── Plain Jinja2 batch send (legacy, still available) ──────────── */}
        <details className="mb-4">
          <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
            或者直接批量发送（仅 Jinja2 占位符替换，无 LLM 个性化）
          </summary>
          <div className="mt-3">
            <button
              onClick={handleSend}
              disabled={!selectedTemplateId || submitting || influencerIds.length === 0}
              className="w-full bg-gray-900 text-white text-sm font-medium py-2.5 rounded-lg hover:bg-gray-800 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {submitting ? t('emails.batch.starting') : t('emails.batch.sendTo', { count: influencerIds.length })}
            </button>
            <p className="text-xs text-gray-400 mt-2 text-center">
              {t('emails.batch.rateHint')}
            </p>
          </div>
        </details>
      </div>
    )
  }

  // ── Progress / Done panel ─────────────────────────────────────────────────
  const isDone = phase === 'done'

  return (
    <div className="max-w-xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-base font-semibold text-gray-900">
            {isDone ? t('emails.batch.complete') : t('emails.batch.sending')}
          </h2>
          {campaign && <p className="text-sm text-gray-400 mt-0.5">{campaign.name}</p>}
        </div>
        {isDone ? (
          <span className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full bg-green-50 text-green-700 border border-green-100">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500" />{t('emails.batch.done')}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-100">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />{t('emails.batch.running')}
          </span>
        )}
      </div>

      <div className="grid grid-cols-4 gap-3 mb-6">
        {[
          { label: t('emails.batch.statsTotal'),   value: progress.total,   color: 'text-gray-900' },
          { label: t('emails.batch.statsSent'),    value: progress.sent,    color: 'text-gray-900' },
          { label: t('emails.batch.statsSuccess'), value: progress.success, color: 'text-green-600' },
          { label: t('emails.batch.statsFailed'),  value: progress.failed,  color: 'text-red-500' },
        ].map(({ label, value, color }) => (
          <div key={label} className="border border-gray-100 rounded-xl p-3 text-center">
            <div className={`text-2xl font-semibold ${color}`}>{value}</div>
            <div className="text-xs text-gray-400 mt-0.5">{label}</div>
          </div>
        ))}
      </div>

      <div className="mb-4">
        <div className="flex justify-between text-xs text-gray-400 mb-1">
          <span>{t('emails.batch.percentComplete', { percent: progressPct })}</span>
          <span>{progress.sent} / {progress.total}</span>
        </div>
        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-gray-900 rounded-full transition-all duration-500"
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {!isDone && progress.current_email && (
        <p className="text-xs text-gray-400 mb-6">
          {t('emails.batch.sendingTo', { email: progress.current_email })}
        </p>
      )}
      {!isDone && (
        <p className="text-xs text-gray-400 mb-6">
          {t('emails.batch.sendingHint')}
        </p>
      )}
      {isDone && (
        <button
          onClick={handleReset}
          className="w-full border border-gray-200 text-gray-700 text-sm font-medium py-2.5 rounded-lg hover:bg-gray-50 transition-colors"
        >
          {t('emails.batch.sendAnother')}
        </button>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

type Tab = 'status' | 'send'

export default function EmailsPage() {
  const { t } = useTranslation()
  const [searchParams] = useSearchParams()
  const hasInfluencerIds = !!searchParams.get('influencer_ids')

  const [activeTab, setActiveTab] = useState<Tab>(hasInfluencerIds ? 'send' : 'status')

  useEffect(() => {
    if (hasInfluencerIds) setActiveTab('send')
  }, [hasInfluencerIds])

  return (
    <div className="p-6">
      {/* Tab bar */}
      <div className="flex border-b border-gray-200 mb-6">
        {([
          { key: 'status', label: t('emails.tabStatus') },
          { key: 'send',   label: t('emails.tabBatchSend') },
        ] as { key: Tab; label: string }[]).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              activeTab === key
                ? 'border-gray-900 text-gray-900'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'status' ? <StatusDashboard /> : <SendPanel />}
    </div>
  )
}
