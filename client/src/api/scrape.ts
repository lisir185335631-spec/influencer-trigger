import apiClient from './client'

export type ScrapeTaskStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface ScrapeTask {
  id: number
  platforms: string        // JSON string e.g. '["instagram","youtube"]'
  industry: string
  target_count: number
  status: ScrapeTaskStatus
  progress: number
  found_count: number
  valid_count: number
  error_message: string | null
  created_by: number | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  target_market?: string | null
  search_keywords?: string | null
  competitor_brands?: string | null
}

export interface ScrapeTaskCreate {
  platforms: string[]
  industry: string
  target_count: number
  target_market?: string
  competitor_brands?: string
}

export interface ScrapeInfluencerResult {
  id: number
  nickname: string | null
  email: string
  platform: string | null
  profile_url: string | null
  followers: number | null
  industry: string | null
  bio: string | null
  status: string
  relevance_score?: number | null
  match_reason?: string | null
}

export const scrapeApi = {
  createTask: (data: ScrapeTaskCreate) =>
    apiClient.post<ScrapeTask>('/scrape/tasks', data).then(r => r.data),

  listTasks: () =>
    apiClient.get<ScrapeTask[]>('/scrape/tasks').then(r => r.data),

  getTask: (id: number) =>
    apiClient.get<ScrapeTask>(`/scrape/tasks/${id}`).then(r => r.data),

  getTaskResults: (id: number, sort: 'followers' | 'default' = 'followers') =>
    apiClient
      .get<ScrapeInfluencerResult[]>(`/scrape/tasks/${id}/results`, { params: { sort } })
      .then(r => r.data),
}

export function parsePlatforms(raw: string): string[] {
  try {
    return JSON.parse(raw)
  } catch {
    return [raw]
  }
}
