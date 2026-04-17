import adminClient from './client'

export interface LLMKeyStatus {
  status: 'configured' | 'not_configured'
  last_four: string | null
}

export interface SystemSettingsOut {
  scrape_concurrency: number
  webhook_feishu: string
  webhook_slack: string
  webhook_default_url: string
  default_daily_quota: number
  llm_key: LLMKeyStatus
}

export interface SystemSettingsPatch {
  webhook_default_url?: string
  default_daily_quota?: number
  webhook_feishu?: string
  webhook_slack?: string
}

export interface FeatureFlagOut {
  id: number
  flag_key: string
  enabled: boolean
  description: string
  rollout_percentage: number
  target_roles: string
  updated_by_user_id: number | null
  created_at: string
  updated_at: string
}

export interface FeatureFlagCreate {
  flag_key: string
  enabled?: boolean
  description?: string
  rollout_percentage?: number
  target_roles?: string
}

export interface FeatureFlagPatch {
  enabled?: boolean
  description?: string
  rollout_percentage?: number
  target_roles?: string
}

export async function getSystemSettings(): Promise<SystemSettingsOut> {
  const res = await adminClient.get<SystemSettingsOut>('/settings/system')
  return res.data
}

export async function patchSystemSettings(data: SystemSettingsPatch): Promise<SystemSettingsOut> {
  const res = await adminClient.patch<SystemSettingsOut>('/settings/system', data)
  return res.data
}

export async function listFeatureFlags(): Promise<FeatureFlagOut[]> {
  const res = await adminClient.get<FeatureFlagOut[]>('/settings/flags')
  return res.data
}

export async function createFeatureFlag(data: FeatureFlagCreate): Promise<FeatureFlagOut> {
  const res = await adminClient.post<FeatureFlagOut>('/settings/flags', data)
  return res.data
}

export async function updateFeatureFlag(flagKey: string, data: FeatureFlagPatch): Promise<FeatureFlagOut> {
  const res = await adminClient.patch<FeatureFlagOut>(`/settings/flags/${flagKey}`, data)
  return res.data
}

export async function deleteFeatureFlag(flagKey: string): Promise<void> {
  await adminClient.delete(`/settings/flags/${flagKey}`)
}
