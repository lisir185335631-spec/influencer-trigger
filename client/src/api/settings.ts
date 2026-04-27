import apiClient from './client'

export interface SystemSettings {
  follow_up_enabled: boolean
  interval_days: number
  max_count: number
  hour_utc: number
  scrape_concurrency: number
  webhook_feishu: string
  webhook_slack: string
  // Masked SendKey on output (e.g. "****abcd"). Use webhook_serverchan_set
  // to know whether DB has a real value — the masked string itself is not
  // suitable for "configured?" checks.
  webhook_serverchan: string
  webhook_serverchan_set: boolean
  // Apify per-platform configuration. Tokens come back masked (e.g.
  // "****abcd"); use *_token_set to know if a value exists in DB.
  apify_tiktok_token: string
  apify_tiktok_token_set: boolean
  apify_tiktok_actor: string
  apify_ig_token: string
  apify_ig_token_set: boolean
  apify_ig_actor: string
  apify_twitter_token: string
  apify_twitter_token_set: boolean
  apify_twitter_actor: string
  apify_facebook_token: string
  apify_facebook_token_set: boolean
  apify_facebook_actor: string
}

export interface SystemSettingsUpdate {
  follow_up_enabled?: boolean
  interval_days?: number
  max_count?: number
  hour_utc?: number
  scrape_concurrency?: number
  webhook_feishu?: string
  webhook_slack?: string
  webhook_serverchan?: string
  // For Apify: omit (undefined) to leave unchanged; "" to clear.
  apify_tiktok_token?: string
  apify_tiktok_actor?: string
  apify_ig_token?: string
  apify_ig_actor?: string
  apify_twitter_token?: string
  apify_twitter_actor?: string
  apify_facebook_token?: string
  apify_facebook_actor?: string
}

export type ApifyPlatform = 'tiktok' | 'instagram' | 'twitter' | 'facebook'

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

export const testWebhook = (
  platform: 'feishu' | 'slack' | 'serverchan',
  url: string,
) =>
  apiClient
    .post<{ success: boolean; platform: string }>('/settings/test-webhook', {
      platform,
      // Server 酱 sends the SendKey here; backend re-uses the `url` param name
      // for both URL-based webhooks and the SendKey to keep the payload shape
      // identical across channels.
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

// Manager+ only — fetches the saved YouTube cookies file as raw JSON to
// power the SettingsPage eye-toggle reveal. Returns "" if no file exists.
export const getYouTubeCookiesRaw = () =>
  apiClient
    .get<{ raw: string }>('/settings/youtube-cookies/raw')
    .then((r) => r.data.raw)

export const saveYouTubeCookies = (raw: string) =>
  apiClient
    .post<YouTubeCookiesStatus>('/settings/youtube-cookies', { raw })
    .then((r) => r.data)

export const deleteYouTubeCookies = () =>
  apiClient
    .delete<YouTubeCookiesStatus>('/settings/youtube-cookies')
    .then((r) => r.data)
