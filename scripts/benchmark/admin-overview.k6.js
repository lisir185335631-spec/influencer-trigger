// Admin Overview 性能压测脚本 (k6)
//
// 用途：
//   验证 SM-4 —— Admin 接口响应时间 p95 < 500ms（overview 聚合类 < 1s）
//   本地 SQLite 测不出差异，必须在 staging + PostgreSQL 远程才有意义。
//
// 前置：
//   1. 部署 influencer-trigger 到 staging，后端用 PostgreSQL
//   2. 生成 admin JWT，导出为环境变量 ADMIN_TOKEN
//   3. 后端 URL 导出为环境变量 BASE_URL
//   4. 本地装 k6：https://k6.io/docs/getting-started/installation/
//
// 跑：
//   BASE_URL=https://staging.example.com ADMIN_TOKEN=eyJ... k6 run admin-overview.k6.js
//
// 阈值（SM-4 要求）：
//   - /api/admin/overview/metrics    p95 < 1000ms（聚合类）
//   - /api/admin/overview/health     p95 < 500ms
//   - /api/admin/overview/recent-events p95 < 500ms
//   - 其他 admin GET 端点            p95 < 500ms

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:6002';
const ADMIN_TOKEN = __ENV.ADMIN_TOKEN;

if (!ADMIN_TOKEN) {
  throw new Error('ADMIN_TOKEN env var is required');
}

// 自定义指标（分端点跟踪）
const overviewMetrics = new Trend('overview_metrics_duration', true);
const overviewHealth = new Trend('overview_health_duration', true);
const overviewRecent = new Trend('overview_recent_duration', true);
const usersList = new Trend('users_list_duration', true);
const auditLogs = new Trend('audit_logs_duration', true);
const mailboxesList = new Trend('mailboxes_list_duration', true);
const agentsStatus = new Trend('agents_status_duration', true);

export const options = {
  // 渐进加压：5 VU -> 20 VU -> 50 VU，每阶段 30s
  stages: [
    { duration: '10s', target: 5 },
    { duration: '30s', target: 20 },
    { duration: '30s', target: 50 },
    { duration: '10s', target: 0 },
  ],
  thresholds: {
    // SM-4 约束
    'overview_metrics_duration': ['p(95)<1000'],  // 聚合类
    'overview_health_duration': ['p(95)<500'],
    'overview_recent_duration': ['p(95)<500'],
    'users_list_duration': ['p(95)<500'],
    'audit_logs_duration': ['p(95)<500'],
    'mailboxes_list_duration': ['p(95)<500'],
    'agents_status_duration': ['p(95)<500'],
    // 全局成功率
    'http_req_failed': ['rate<0.01'],
    'http_req_duration{status:200}': ['p(95)<1000'],
  },
};

const headers = {
  Authorization: `Bearer ${ADMIN_TOKEN}`,
  'Content-Type': 'application/json',
};

const endpoints = [
  { name: 'overview_metrics', path: '/api/admin/overview/metrics', trend: overviewMetrics },
  { name: 'overview_health', path: '/api/admin/overview/health', trend: overviewHealth },
  { name: 'overview_recent', path: '/api/admin/overview/recent-events', trend: overviewRecent },
  { name: 'users_list', path: '/api/admin/users?page=1&page_size=20', trend: usersList },
  { name: 'audit_logs', path: '/api/admin/audit/logs?page=1&page_size=50', trend: auditLogs },
  { name: 'mailboxes_list', path: '/api/admin/mailboxes', trend: mailboxesList },
  { name: 'agents_status', path: '/api/admin/agents/status', trend: agentsStatus },
];

export default function () {
  // 随机挑一个端点，模拟真实 admin 使用场景（dashboard 刷新 + 偶尔深入某模块）
  const ep = endpoints[Math.floor(Math.random() * endpoints.length)];

  const res = http.get(`${BASE_URL}${ep.path}`, { headers, tags: { endpoint: ep.name } });

  check(res, {
    [`${ep.name} status 200`]: (r) => r.status === 200,
  });

  ep.trend.add(res.timings.duration);

  // 思考时间：admin 不是压测机器人，加 0.5-2s 随机
  sleep(0.5 + Math.random() * 1.5);
}

export function handleSummary(data) {
  // 按端点打印 p50/p95/p99
  const lines = ['', '=== SM-4 Benchmark Summary ==='];
  for (const ep of endpoints) {
    const t = data.metrics[`${ep.name}_duration`];
    if (!t) continue;
    const p50 = t.values['p(50)'];
    const p95 = t.values['p(95)'];
    const p99 = t.values['p(99)'];
    const bound = ep.name === 'overview_metrics' ? 1000 : 500;
    const pass = p95 < bound ? 'PASS' : 'FAIL';
    lines.push(
      `  ${ep.name.padEnd(22)} p50=${p50.toFixed(0).padStart(4)}ms  p95=${p95.toFixed(0).padStart(4)}ms  p99=${p99.toFixed(0).padStart(4)}ms  bound<${bound}ms  ${pass}`
    );
  }
  lines.push('');

  return {
    'stdout': lines.join('\n'),
    'benchmark-result.json': JSON.stringify(data, null, 2),
  };
}
