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
  followers: number | null
  status: string
  priority: string
  reply_intent: string | null
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
}): Promise<InfluencerListResponse> {
  const res = await apiClient.get('/influencers', { params })
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
