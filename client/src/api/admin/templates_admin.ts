import adminClient from './client'

export interface TemplateAdminItem {
  id: number
  name: string
  subject: string
  body_html: string
  industry: string | null
  style: string | null
  language: string
  is_published: boolean
  compliance_flags: string
  created_by: number | null
  creator_username: string | null
  usage_count: number
  send_success_rate: number
  created_at: string
}

export interface TemplateRankingItem {
  id: number
  name: string
  industry: string | null
  is_published: boolean
  usage_count: number
}

export interface ComplianceKeyword {
  id: number
  keyword: string
  category: string
  severity: string
  created_at: string
}

export async function listAdminTemplates(): Promise<{ total: number; items: TemplateAdminItem[] }> {
  const res = await adminClient.get('/templates')
  return res.data
}

export async function publishTemplate(id: number): Promise<{ ok: boolean }> {
  const res = await adminClient.post(`/templates/${id}/publish`)
  return res.data
}

export async function unpublishTemplate(id: number): Promise<{ ok: boolean }> {
  const res = await adminClient.post(`/templates/${id}/unpublish`)
  return res.data
}

export async function complianceScan(id: number): Promise<{ ok: boolean; compliance_flags: string; hits: string[] }> {
  const res = await adminClient.post(`/templates/${id}/compliance-scan`)
  return res.data
}

export async function getTemplatesRanking(): Promise<{ items: TemplateRankingItem[] }> {
  const res = await adminClient.get('/templates/ranking')
  return res.data
}

export async function listKeywords(): Promise<{ total: number; items: ComplianceKeyword[] }> {
  const res = await adminClient.get('/templates/keywords')
  return res.data
}

export async function createKeyword(
  keyword: string,
  category: string,
  severity: string,
): Promise<ComplianceKeyword> {
  const res = await adminClient.post('/templates/keywords', { keyword, category, severity })
  return res.data
}

export async function deleteKeyword(id: number): Promise<{ ok: boolean }> {
  const res = await adminClient.delete(`/templates/keywords/${id}`)
  return res.data
}
