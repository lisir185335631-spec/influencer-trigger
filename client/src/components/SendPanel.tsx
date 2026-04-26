/* eslint-disable react-refresh/only-export-components --
   InfluencerPicker is an internal helper component used only by SendPanel
   in this file. The lint rule wants files to export only components for
   Fast Refresh; we deliberately co-locate the helper rather than split
   into two files for cohesion. */
import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { templatesApi, Template } from '../api/templates'
import {
  emailsApi,
  Campaign,
  EmailProgressEvent,
} from '../api/emails'
import { draftsApi, AngleOption } from '../api/drafts'
import {
  listInfluencers,
  InfluencerListItem,
} from '../api/influencers'
import { useWebSocket, WsMessage } from '../hooks/useWebSocket'
import { WS_URL } from '../api/websocket'

// ── Influencer picker modal ───────────────────────────────────────────────────
// Self-contained selector for use inside SendPanel — lets users pick recipients
// directly in the email-sending workflow, no detour through the CRM page. Reuses
// the same listInfluencers API the CRM page is built on so filters / pagination
// behave identically. Selection is committed only when the user clicks
// "confirm"; cancel discards.

const PLATFORMS_FOR_PICKER = ['', 'tiktok', 'instagram', 'youtube', 'twitter', 'facebook', 'other'] as const
const PICKER_PAGE_SIZE = 20

interface InfluencerPickerProps {
  onClose: () => void
  onConfirm: (ids: number[]) => void
  initiallySelected?: number[]
}

function InfluencerPicker({ onClose, onConfirm, initiallySelected = [] }: InfluencerPickerProps) {
  const { t } = useTranslation()
  const [items, setItems] = useState<InfluencerListItem[]>([])
  const [loading, setLoading] = useState(false)
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [platform, setPlatform] = useState('')
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  // selectedIds is a Set for O(1) toggle; preserved as a ref-like state across
  // pages so paginating doesn't lose selections.
  const [selectedIds, setSelectedIds] = useState<Set<number>>(
    () => new Set(initiallySelected),
  )

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const resp = await listInfluencers({
        page,
        page_size: PICKER_PAGE_SIZE,
        search: search || undefined,
        platform: platform || undefined,
      })
      setItems(resp.items)
      setTotalPages(resp.total_pages)
      setTotal(resp.total)
    } finally {
      setLoading(false)
    }
  }, [page, search, platform])

  useEffect(() => { reload() }, [reload])

  const visibleIds = useMemo(() => items.map(i => i.id), [items])
  const allVisibleSelected = visibleIds.length > 0 && visibleIds.every(id => selectedIds.has(id))
  // Selections persist across pagination/filter/search changes (avoids losing
  // earlier picks when the user explores). But that means the count shown in
  // the header can include rows the user can no longer see — flag the gap so
  // they don't think confirm only sends visible ones.
  const visibleSelectedCount = useMemo(
    () => visibleIds.filter(id => selectedIds.has(id)).length,
    [visibleIds, selectedIds],
  )
  const hiddenSelectedCount = selectedIds.size - visibleSelectedCount

  const toggleOne = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAllVisible = () => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (allVisibleSelected) {
        for (const id of visibleIds) next.delete(id)
      } else {
        for (const id of visibleIds) next.add(id)
      }
      return next
    })
  }

  const submitSearch = () => {
    setPage(1)
    setSearch(searchInput.trim())
  }

  return (
    <div
      className="fixed inset-0 bg-black bg-opacity-30 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-gray-900">
              {t('influencerPicker.title')}
            </h3>
            <p className="text-xs text-gray-400 mt-0.5">
              {t('influencerPicker.subtitle', { count: selectedIds.size })}
              {hiddenSelectedCount > 0 && (
                <span className="ml-1 text-amber-600">
                  · {t('influencerPicker.hiddenHint', { count: hiddenSelectedCount })}
                </span>
              )}
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-700 text-xl">×</button>
        </div>

        {/* Filters */}
        <div className="px-6 py-3 border-b border-gray-100 flex flex-wrap items-center gap-2">
          <input
            type="text"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submitSearch() }}
            placeholder={t('influencerPicker.searchPlaceholder')}
            className="flex-1 min-w-[180px] border border-gray-200 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <select
            value={platform}
            onChange={e => { setPage(1); setPlatform(e.target.value) }}
            className="border border-gray-200 rounded-lg px-2 py-1.5 text-sm bg-white"
          >
            {PLATFORMS_FOR_PICKER.map(p => (
              <option key={p || 'all'} value={p}>
                {p ? p : t('influencerPicker.allPlatforms')}
              </option>
            ))}
          </select>
          <button
            onClick={submitSearch}
            className="px-3 py-1.5 text-sm bg-gray-900 text-white rounded-lg hover:bg-gray-800"
          >
            {t('influencerPicker.searchButton')}
          </button>
          {selectedIds.size > 0 && (
            <button
              onClick={() => setSelectedIds(new Set())}
              className="text-xs text-gray-500 hover:text-red-600 ml-auto"
            >
              {t('influencerPicker.clearSelection')}
            </button>
          )}
        </div>

        {/* Table */}
        <div className="flex-1 overflow-y-auto">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 sticky top-0">
              <tr>
                <th className="px-3 py-2 w-10 text-left">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleAllVisible}
                    aria-label={t('influencerPicker.toggleAllVisible')}
                  />
                </th>
                <th className="text-left px-3 py-2 font-medium text-gray-500 text-xs">
                  {t('influencerPicker.col.recipient')}
                </th>
                <th className="text-left px-3 py-2 font-medium text-gray-500 text-xs">
                  {t('influencerPicker.col.platform')}
                </th>
                <th className="text-right px-3 py-2 font-medium text-gray-500 text-xs">
                  {t('influencerPicker.col.followers')}
                </th>
                <th className="text-left px-3 py-2 font-medium text-gray-500 text-xs">
                  {t('influencerPicker.col.industry')}
                </th>
                <th className="text-left px-3 py-2 font-medium text-gray-500 text-xs">
                  {t('influencerPicker.col.status')}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading && items.length === 0 ? (
                <tr><td colSpan={6} className="px-3 py-12 text-center text-gray-400 text-xs">
                  {t('influencerPicker.loading')}
                </td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={6} className="px-3 py-12 text-center text-gray-400 text-xs">
                  {t('influencerPicker.empty')}
                </td></tr>
              ) : items.map(inf => {
                const checked = selectedIds.has(inf.id)
                return (
                  <tr
                    key={inf.id}
                    className={`cursor-pointer hover:bg-blue-50/50 ${checked ? 'bg-blue-50' : ''}`}
                    onClick={() => toggleOne(inf.id)}
                  >
                    <td className="px-3 py-2">
                      {/* Both onChange and the row's onClick fire toggleOne.
                          The checkbox's onClick stopPropagation prevents
                          the row's onClick from re-firing — so a click on
                          the checkbox results in EXACTLY one toggle (via
                          onChange), not two. Click on the row away from
                          the checkbox routes only the row's onClick. */}
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleOne(inf.id)}
                        onClick={e => e.stopPropagation()}
                      />
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-medium text-gray-900 text-sm truncate max-w-[260px]">
                        {inf.nickname || '—'}
                      </div>
                      <div className="text-xs text-gray-400 truncate max-w-[260px]">{inf.email}</div>
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">{inf.platform || '—'}</td>
                    <td className="px-3 py-2 text-right text-xs text-gray-700 tabular-nums">
                      {inf.followers ? inf.followers.toLocaleString() : '—'}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500 truncate max-w-[140px]">
                      {inf.industry || '—'}
                    </td>
                    <td className="px-3 py-2 text-xs text-gray-500">{inf.status}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Footer: pagination + confirm */}
        <div className="px-6 py-3 border-t border-gray-100 flex items-center justify-between bg-gray-50 rounded-b-xl">
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="px-2 py-1 border border-gray-200 rounded disabled:opacity-40 hover:bg-white"
            >
              ‹
            </button>
            <span>{t('influencerPicker.pageOf', { current: page, total: totalPages, count: total })}</span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="px-2 py-1 border border-gray-200 rounded disabled:opacity-40 hover:bg-white"
            >
              ›
            </button>
          </div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5"
            >
              {t('influencerPicker.cancel')}
            </button>
            <button
              onClick={() => onConfirm(Array.from(selectedIds))}
              disabled={selectedIds.size === 0}
              className="text-sm bg-gray-900 text-white px-4 py-1.5 rounded-lg hover:bg-gray-800 disabled:opacity-40"
            >
              {t('influencerPicker.confirm', { count: selectedIds.size })}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Send Panel ────────────────────────────────────────────────────────────────
// Extracted from EmailsPage so it can be mounted anywhere — currently used in
// EmailsPage's "batch send" tab AND MailboxesPage's "send" tab. Behaviour is
// identical regardless of mount point. Recipients can come from three places,
// in priority order:
//   1. Explicit prop `selectedInfluencerIds` (parent supplies)
//   2. URL query string ?influencer_ids=1,2,3 (legacy CRM jump-in route)
//   3. Internal state populated by InfluencerPicker (in-page selection)
// The last route is the only one accessible without leaving the email module.

type Phase = 'setup' | 'sending' | 'done'

interface ProgressState {
  sent: number
  success: number
  failed: number
  total: number
  current_email: string
}

interface SendPanelProps {
  /** Optional caller-supplied ids. Overrides URL + picker state when set. */
  selectedInfluencerIds?: number[]
}

export default function SendPanel({ selectedInfluencerIds }: SendPanelProps = {}) {
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
  // In-page selected ids (set by InfluencerPicker). Sticks across renders so
  // toggling the picker doesn't lose what the user already chose.
  const [pickedIds, setPickedIds]       = useState<number[]>([])
  const [pickerOpen, setPickerOpen]     = useState(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Resolve the active recipient list. Prop > URL > picker state.
  const influencerIds: number[] = useMemo(() => {
    if (selectedInfluencerIds && selectedInfluencerIds.length > 0) {
      return selectedInfluencerIds
    }
    const raw = searchParams.get('influencer_ids')
    if (raw) {
      return raw.split(',').map(Number).filter(n => !isNaN(n) && n > 0)
    }
    return pickedIds
  }, [selectedInfluencerIds, searchParams, pickedIds])

  useEffect(() => {
    templatesApi.list()
      .then(setTemplates)
      .catch(() => setError(t('emails.batch.loadTemplatesFailed')))
      .finally(() => setLoadingTemplates(false))
    draftsApi.listAngles().then(setAngles).catch(() => { /* non-blocking */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      setError(t('drafts.creationFailed'))
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
    setPickedIds([])
    // setSearchParams({}) clears any ?influencer_ids= the user landed
    // with — no-op if the URL already has no params, harmless.
    setSearchParams({})
  }

  const handlePickerConfirm = (ids: number[]) => {
    // React 18 batches the three setters below into one render, so the
    // memo for `influencerIds` (which depends on both pickedIds and
    // searchParams) sees a consistent post-confirm state. Pre-batch
    // React would have fired three renders with intermediate states,
    // briefly flashing the empty-recipients placeholder when URL ids
    // were cleared before pickedIds populated.
    setPickedIds(ids)
    setPickerOpen(false)
    // Clear URL ?influencer_ids= so the in-page picker takes precedence
    // even on routes the user originally entered with a CRM-style jump.
    if (searchParams.get('influencer_ids')) {
      const next = new URLSearchParams(searchParams)
      next.delete('influencer_ids')
      setSearchParams(next)
    }
  }

  const progressPct = progress.total > 0 ? Math.round((progress.sent / progress.total) * 100) : 0

  // ── No influencers selected — show selector entry point ─────────────────
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
          <p className="text-sm text-gray-700 font-medium mb-1">{t('emails.batch.noInfluencers')}</p>
          <p className="text-xs text-gray-400 mb-5">
            {t('sendPanel.pickHint')}
          </p>
          <button
            onClick={() => setPickerOpen(true)}
            className="inline-flex items-center gap-1.5 px-4 py-2 bg-gray-900 text-white text-sm font-medium rounded-lg hover:bg-gray-800 transition-colors"
          >
            {t('sendPanel.openPicker')}
          </button>
        </div>
        {pickerOpen && (
          <InfluencerPicker
            initiallySelected={pickedIds}
            onClose={() => setPickerOpen(false)}
            onConfirm={handlePickerConfirm}
          />
        )}
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
          <span className="text-sm text-blue-700 flex-1">
            {t('emails.batch.influencersSelected', { count: influencerIds.length })}
          </span>
          <button
            onClick={() => setPickerOpen(true)}
            className="text-xs text-blue-700 hover:text-blue-900 underline"
          >
            {t('sendPanel.changeRecipients')}
          </button>
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
                {t('drafts.panelTitle')}
              </div>
              <div className="text-xs text-emerald-700 mt-0.5">
                {t('drafts.panelHint')}
              </div>
            </div>
          </div>

          <div className="mb-3">
            <label className="block text-xs font-medium text-emerald-800 mb-1 uppercase tracking-wide">
              {t('drafts.angleLabel')}
            </label>
            <select
              value={selectedAngle}
              onChange={e => setSelectedAngle(e.target.value)}
              disabled={angles.length === 0}
              className="w-full border border-emerald-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              {angles.length === 0 && <option>{t('drafts.review.loading')}</option>}
              {angles.map(a => (
                <option key={a.key} value={a.key}>
                  {a.key} — {a.description.slice(0, 60)}
                </option>
              ))}
            </select>
          </div>

          <div className="mb-3">
            <label className="block text-xs font-medium text-emerald-800 mb-1 uppercase tracking-wide">
              {t('drafts.extraNotesLabel')}{' '}
              <span className="text-emerald-500 font-normal normal-case">{t('drafts.extraNotesOptional')}</span>
            </label>
            <input
              value={extraNotes}
              onChange={e => setExtraNotes(e.target.value)}
              placeholder={t('drafts.extraNotesPlaceholder')}
              className="w-full border border-emerald-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <button
            onClick={handleCreateDraft}
            disabled={!selectedTemplateId || creatingDraft || influencerIds.length === 0}
            className="w-full bg-emerald-600 text-white text-sm font-medium py-2.5 rounded-lg hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {creatingDraft
              ? t('drafts.creating')
              : t('drafts.createButton', { count: influencerIds.length })}
          </button>
          <p className="text-xs text-emerald-600 mt-2 text-center">
            {t('drafts.costEstimate', { cost: (influencerIds.length * 0.0001).toFixed(4) })}
          </p>
        </div>

        {/* ── Plain Jinja2 batch send (legacy, still available) ──────────── */}
        <details className="mb-4">
          <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-600">
            {t('drafts.directSendDetails')}
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

        {pickerOpen && (
          <InfluencerPicker
            initiallySelected={influencerIds}
            onClose={() => setPickerOpen(false)}
            onConfirm={handlePickerConfirm}
          />
        )}
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
