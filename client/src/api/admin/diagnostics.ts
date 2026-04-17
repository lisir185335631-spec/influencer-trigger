import adminClient from './client'

export interface DbHealth {
  status: string
  latency_ms?: number
  pool?: { size: number | null; checked_out: number | null; overflow: number | null }
  slow_queries_top10?: unknown[]
  reason?: string
}

export interface RedisHealth {
  status: string
  latency_ms?: number
  connected_clients?: number
  used_memory_human?: string
  key_count?: number
  queue_depth?: number
  reason?: string
}

export interface WsHealth {
  status: string
  active_connections?: number
  channels?: Record<string, number>
  reason?: string
}

export interface SchedulerJob {
  id: string
  name: string
  next_run_time: string | null
  trigger: string
}

export interface SchedulerHealth {
  status: string
  running?: boolean
  job_count?: number
  jobs?: SchedulerJob[]
  reason?: string
}

export interface SystemHealth {
  status: string
  disk?: { total_gb: number; used_gb: number; free_gb: number; percent: number }
  memory?: { total_gb: number; used_gb: number; available_gb: number; percent: number }
  process?: {
    pid: number | null
    name: string | null
    cpu_percent: number | null
    memory_rss_mb: number | null
    num_threads: number | null
    uptime_s: number | null
  }
  reason?: string
}

export interface HealthcheckResult {
  overall: string
  checked_at: string
  components: {
    db: DbHealth
    redis: RedisHealth
    websocket: WsHealth
    scheduler: SchedulerHealth
    system: SystemHealth
  }
}

export async function checkDb(): Promise<DbHealth> {
  const res = await adminClient.get<DbHealth>('/diagnostics/db')
  return res.data
}

export async function checkRedis(): Promise<RedisHealth> {
  const res = await adminClient.get<RedisHealth>('/diagnostics/redis')
  return res.data
}

export async function checkWs(): Promise<WsHealth> {
  const res = await adminClient.get<WsHealth>('/diagnostics/websocket')
  return res.data
}

export async function checkScheduler(): Promise<SchedulerHealth> {
  const res = await adminClient.get<SchedulerHealth>('/diagnostics/scheduler')
  return res.data
}

export async function checkSystem(): Promise<SystemHealth> {
  const res = await adminClient.get<SystemHealth>('/diagnostics/system')
  return res.data
}

export async function runHealthcheck(): Promise<HealthcheckResult> {
  const res = await adminClient.post<HealthcheckResult>('/diagnostics/healthcheck')
  return res.data
}
