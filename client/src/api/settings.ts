import apiClient from './client'

export interface SystemSettings {
  follow_up_enabled: boolean
  interval_days: number
  max_count: number
  hour_utc: number
  scrape_concurrency: number
  webhook_feishu: string
  webhook_slack: string
  // Apify per-platform configuration. Tokens come back masked (e.g.
  // "****abcd"); use *_token_set to know if a value exists in DB.
  apify_tiktok_token: string
  apify_tiktok_token_set: boolean
  apify_tiktok_actor: string
  apify_ig_token: string
  apify_ig_token_set: boolean
  apify_ig_actor: string
}

export interface SystemSettingsUpdate {
  follow_up_enabled?: boolean
  interval_days?: number
  max_count?: number
  hour_utc?: number
  scrape_concurrency?: number
  webhook_feishu?: string
  webhook_slack?: string
  // For Apify: omit (undefined) to leave unchanged; "" to clear.
  apify_tiktok_token?: string
  apify_tiktok_actor?: string
  apify_ig_token?: string
  apify_ig_actor?: string
}

export type ApifyPlatform = 'tiktok' | 'instagram'

export interface TestApifyActorResponse {
  success: boolean
  platform: string
  actor: string
  message: string
  actor_title?: string | null
  actor_username?: string | null
}

export const getSettings = () =>
  apiClient.get<SystemSettings>('/settings').then((r) => r.data)

export const updateSettings = (body: SystemSettingsUpdate) =>
  apiClient.put<SystemSettings>('/settings', body).then((r) => r.data)

export const testWebhook = (platform: 'feishu' | 'slack', url: string) =>
  apiClient
    .post<{ success: boolean; platform: string }>('/settings/test-webhook', {
      platform,
      url,
    })
    .then((r) => r.data)

// Verify Apify token + actor against Apify's /v2/acts/{actor} metadata
// endpoint (cheap — no actor run). Pass token/actor to test pending unsaved
// values; omit to test the currently saved DB config (with env fallback).
export const testApifyActor = (
  platform: ApifyPlatform,
  token?: string,
  actor?: string,
) =>
  apiClient
    .post<TestApifyActorResponse>('/settings/test-apify-actor', {
      platform,
      token,
      actor,
    })
    .then((r) => r.data)

export interface YouTubeCookiesStatus {
  configured: boolean
  count: number
  auth_complete: boolean
  updated_at: string | null
  file_size: number
}

export const getYouTubeCookiesStatus = () =>
  apiClient
    .get<YouTubeCookiesStatus>('/settings/youtube-cookies/status')
    .then((r) => r.data)

export const saveYouTubeCookies = (raw: string) =>
  apiClient
    .post<YouTubeCookiesStatus>('/settings/youtube-cookies', { raw })
    .then((r) => r.data)

export const deleteYouTubeCookies = () =>
  apiClient
    .delete<YouTubeCookiesStatus>('/settings/youtube-cookies')
    .then((r) => r.data)
