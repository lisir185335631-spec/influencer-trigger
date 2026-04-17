import adminClient from './client'

export interface SecurityAlertOut {
  id: number
  alert_type: string
  user_id: number | null
  details_json: string | null
  acknowledged: boolean
  acknowledged_by: number | null
  acknowledged_at: string | null
  created_at: string
}

export interface TwoFAConfig {
  require_password_for_sensitive: boolean
  totp_enabled: boolean
}

export interface TwoFAConfigPatch {
  require_password_for_sensitive?: boolean
  totp_enabled?: boolean
}

export interface KeyRotationHistoryOut {
  id: number
  rotated_by_user_id: number
  rotated_by_username: string
  note: string | null
  created_at: string
}

export interface KeyRotationHistoryResponse {
  key_age_days: number | null
  items: KeyRotationHistoryOut[]
}

export async function listAlerts(): Promise<{ items: SecurityAlertOut[] }> {
  const res = await adminClient.get<{ items: SecurityAlertOut[] }>('/security/alerts')
  return res.data
}

export async function acknowledgeAlert(id: number): Promise<void> {
  await adminClient.post(`/security/alerts/${id}/acknowledge`)
}

export async function get2FAConfig(): Promise<TwoFAConfig> {
  const res = await adminClient.get<TwoFAConfig>('/security/2fa-config')
  return res.data
}

export async function patch2FAConfig(data: TwoFAConfigPatch): Promise<TwoFAConfig> {
  const res = await adminClient.patch<TwoFAConfig>('/security/2fa-config', data)
  return res.data
}

export async function rotateKeys(admin_password: string): Promise<{ ok: boolean; message: string }> {
  const res = await adminClient.post<{ ok: boolean; message: string }>('/security/rotate-keys', {
    admin_password,
  })
  return res.data
}

export async function getKeyRotationHistory(): Promise<KeyRotationHistoryResponse> {
  const res = await adminClient.get<KeyRotationHistoryResponse>('/security/key-rotation-history')
  return res.data
}
