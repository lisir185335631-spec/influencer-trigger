import axios from 'axios'

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const { data } = await axios.post<LoginResponse>('/api/auth/login', { username, password })
  return data
}
