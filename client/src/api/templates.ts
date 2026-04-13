import apiClient from './client'

export interface Template {
  id: number
  name: string
  subject: string
  body_html: string
  industry: string | null
  style: string | null
  language: string
  created_by: number | null
  created_at: string
  updated_at: string
}

export interface TemplateCreate {
  name: string
  subject: string
  body_html: string
  industry?: string
  style?: string
  language?: string
}

export interface TemplateUpdate {
  name?: string
  subject?: string
  body_html?: string
  industry?: string
  style?: string
  language?: string
}

export interface GeneratedTemplate {
  name: string
  style: string
  subject: string
  body_html: string
}

export const templatesApi = {
  list: (industry?: string) => {
    const params = industry ? { industry } : {}
    return apiClient.get<Template[]>('/templates/', { params }).then((r) => r.data)
  },

  create: (data: TemplateCreate) =>
    apiClient.post<Template>('/templates/', data).then((r) => r.data),

  update: (id: number, data: TemplateUpdate) =>
    apiClient.put<Template>(`/templates/${id}`, data).then((r) => r.data),

  delete: (id: number) => apiClient.delete(`/templates/${id}`),

  generate: (industry: string) =>
    apiClient
      .post<GeneratedTemplate[]>('/templates/generate', { industry })
      .then((r) => r.data),
}
