import apiClient from './client'

export interface TagOut {
  id: number
  name: string
  color: string
  created_at: string
}

export interface NoteOut {
  id: number
  influencer_id: number
  content: string
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface CollaborationOut {
  id: number
  influencer_id: number
  title: string
  status: string
  description: string | null
  budget: string | null
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface EmailTimelineItem {
  id: number
  email_type: string
  subject: string
  status: string
  reply_content: string | null
  reply_from: string | null
  sent_at: string | null
  delivered_at: string | null
  opened_at: string | null
  replied_at: string | null
  bounced_at: string | null
  created_at: string
}

export interface InfluencerDetail {
  id: number
  nickname: string | null
  email: string
  platform: string | null
  profile_url: string | null
  followers: number | null
  industry: string | null
  bio: string | null
  status: string
  priority: string
  reply_intent: string | null
  follow_up_count: number
  last_email_sent_at: string | null
  created_at: string
  updated_at: string
  tags: TagOut[]
  notes: NoteOut[]
  collaborations: CollaborationOut[]
  emails: EmailTimelineItem[]
}

export interface InfluencerListItem {
  id: number
  nickname: string | null
  email: string
  platform: string | null
  avatar_url?: string | null
  followers: number | null
  industry: string | null
  status: string
  priority: string
  reply_intent: string | null
  reply_summary: string | null
  follow_up_count: number
  last_email_sent_at: string | null
  created_at: string
  tags: TagOut[]
}

export interface InfluencerListResponse {
  items: InfluencerListItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export interface InfluencerUpdate {
  nickname?: string
  platform?: string
  profile_url?: string
  followers?: number
  industry?: string
  bio?: string
  status?: string
  priority?: string
}

export async function listInfluencers(params?: {
  page?: number
  page_size?: number
  status?: string
  platform?: string
  priority?: string
  search?: string
  tag_ids?: number[]
  followers_min?: number
  followers_max?: number
  industry?: string
  reply_intent?: string
  sort_by?: string
}): Promise<InfluencerListResponse> {
  const { tag_ids, sort_by, ...rest } = params ?? {}
  const queryParams: Record<string, unknown> = { ...rest }
  // axios serializes arrays as tag_ids[]=1 by default; use paramsSerializer to send tag_ids=1&tag_ids=2
  const res = await apiClient.get('/influencers', {
    params: queryParams,
    paramsSerializer: (p) => {
      const sp = new URLSearchParams()
      for (const [k, v] of Object.entries(p)) {
        if (v !== undefined && v !== null && v !== '') sp.append(k, String(v))
      }
      if (tag_ids?.length) tag_ids.forEach((id) => sp.append('tag_ids', String(id)))
      if (sort_by) sp.append('sort_by', sort_by)
      return sp.toString()
    },
  })
  return res.data
}

export async function batchUpdateInfluencers(payload: {
  influencer_ids: number[]
  action: 'archive' | 'assign_tags'
  tag_ids?: number[]
}): Promise<{ affected: number }> {
  const res = await apiClient.patch('/influencers/batch', payload)
  return res.data
}

export async function exportInfluencers(params?: {
  status?: string
  platform?: string
  priority?: string
  search?: string
  tag_ids?: number[]
  followers_min?: number
  followers_max?: number
  industry?: string
  reply_intent?: string
}): Promise<Blob> {
  const res = await apiClient.post('/influencers/export', params ?? {}, {
    responseType: 'blob',
  })
  return res.data
}

export async function getInfluencerDetail(id: number): Promise<InfluencerDetail> {
  const res = await apiClient.get(`/influencers/${id}`)
  return res.data
}

export async function updateInfluencer(id: number, data: InfluencerUpdate): Promise<InfluencerDetail> {
  const res = await apiClient.patch(`/influencers/${id}`, data)
  return res.data
}

export async function getInfluencerEmails(id: number): Promise<EmailTimelineItem[]> {
  const res = await apiClient.get(`/influencers/${id}/emails`)
  return res.data
}

export async function addNote(id: number, content: string): Promise<NoteOut> {
  const res = await apiClient.post(`/influencers/${id}/notes`, { content })
  return res.data
}

export async function listTags(): Promise<TagOut[]> {
  const res = await apiClient.get('/tags')
  return res.data
}

export async function createTag(name: string, color?: string): Promise<TagOut> {
  const res = await apiClient.post('/tags', { name, color: color ?? '#6366f1' })
  return res.data
}

export async function deleteTag(tagId: number): Promise<void> {
  await apiClient.delete(`/tags/${tagId}`)
}

export async function assignTags(influencerId: number, tagIds: number[]): Promise<TagOut[]> {
  const res = await apiClient.post(`/influencers/${influencerId}/tags`, { tag_ids: tagIds })
  return res.data
}
