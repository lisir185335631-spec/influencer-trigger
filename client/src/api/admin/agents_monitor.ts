import adminClient from './client'

export interface AgentStatus {
  agent_name: string
  running_count: number
  recent_total: number
  recent_success: number
  success_rate: number | null
  avg_duration_ms: number | null
  last_run_at: string | null
}

export interface AgentsStatusResponse {
  agents: Record<string, AgentStatus>
}

export interface AgentRunItem {
  id: number
  agent_name: string
  task_id: string | null
  state: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  error_message: string | null
}

export interface AgentRunDetail extends AgentRunItem {
  input_snapshot: string | null
  output_snapshot: string | null
  error_stack: string | null
  token_cost_usd: number | null
  llm_calls_count: number | null
}

export interface AgentRunsResponse {
  total: number
  page: number
  page_size: number
  items: AgentRunItem[]
}

export async function getAgentsStatus(): Promise<AgentsStatusResponse> {
  const res = await adminClient.get('/agents/status')
  return res.data
}

export async function listAgentRuns(params: {
  agent?: string
  state?: string
  from_date?: string
  to_date?: string
  page?: number
  page_size?: number
}): Promise<AgentRunsResponse> {
  const res = await adminClient.get('/agents/runs', { params })
  return res.data
}

export async function getAgentRun(runId: number): Promise<AgentRunDetail> {
  const res = await adminClient.get(`/agents/runs/${runId}`)
  return res.data
}

export async function retryAgentRun(runId: number): Promise<{ ok: boolean; agent: string; retried_from: number }> {
  const res = await adminClient.post(`/agents/runs/${runId}/retry`)
  return res.data
}
