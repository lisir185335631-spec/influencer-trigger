import apiClient from './client'

export interface ColumnMappingItem {
  csv_column: string
  field: string | null
}

export interface ImportPreviewResponse {
  rows: Record<string, string>[]
  columns: string[]
  suggested_mapping: ColumnMappingItem[]
  total_rows: number
}

export interface ImportConfirmResponse {
  imported: number
  duplicates: number
  invalid: number
  total: number
  errors: string[]
}

export const FIELD_OPTIONS = [
  { value: 'email',       label: 'Email (required)' },
  { value: 'nickname',    label: 'Nickname' },
  { value: 'platform',    label: 'Platform' },
  { value: 'followers',   label: 'Followers' },
  { value: 'profile_url', label: 'Profile URL' },
  { value: 'industry',    label: 'Industry' },
]

export const importApi = {
  preview: (file: File): Promise<ImportPreviewResponse> => {
    const form = new FormData()
    form.append('file', file)
    return apiClient.post<ImportPreviewResponse>('/influencers/import/preview', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },

  confirm: (
    file: File,
    mapping: ColumnMappingItem[],
    overwrite: boolean,
  ): Promise<ImportConfirmResponse> => {
    const form = new FormData()
    form.append('file', file)
    form.append('mapping', JSON.stringify(mapping))
    form.append('overwrite_duplicates', String(overwrite))
    return apiClient.post<ImportConfirmResponse>('/influencers/import/confirm', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },
}
