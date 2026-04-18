# Benchmark Scripts

对应 PRD SM-4：Admin 接口响应时间 p95 < 500ms（overview 聚合类 < 1s）。

**本地 SQLite 测不出差异**（单请求 <50ms），必须在 staging + PostgreSQL 远程才有意义。
pytest 里的 `test_overview_metrics_perf_regression` 只是"防回归"，不是 SM-4 benchmark。

## admin-overview.k6.js

k6 压测脚本，覆盖 7 个 admin GET 端点（overview 3 个 + users/audit/mailboxes/agents）。

### 前置

1. 部署 influencer-trigger 到 staging，后端用 PostgreSQL
2. 在 staging 上建一个 admin 账号，用它登录拿 JWT
3. 本地装 k6：https://k6.io/docs/getting-started/installation/

### 跑

```bash
export BASE_URL=https://staging.example.com
export ADMIN_TOKEN=eyJhbGciOi...  # staging 上 admin 登录返回的 JWT

k6 run scripts/benchmark/admin-overview.k6.js
```

### 压测策略

渐进加压：
- 0-10s 预热到 5 VU
- 10-40s 到 20 VU
- 40-70s 到 50 VU（峰值）
- 70-80s 降到 0

随机选端点 + 0.5-2s 随机思考时间，模拟 admin 真实使用模式（dashboard 轮询 + 偶尔深入某模块）。

### 阈值（k6 会自动判 PASS/FAIL）

| 端点 | p95 bound |
|---|---|
| `/api/admin/overview/metrics` | 1000ms（聚合类） |
| `/api/admin/overview/health` | 500ms |
| `/api/admin/overview/recent-events` | 500ms |
| `/api/admin/users` | 500ms |
| `/api/admin/audit/logs` | 500ms |
| `/api/admin/mailboxes` | 500ms |
| `/api/admin/agents/status` | 500ms |
| 全局 http_req_failed rate | <1% |

失败任一阈值 k6 退出码非 0，可接 CI pass/fail gate。

### 产出

- stdout：按端点的 p50/p95/p99 + PASS/FAIL
- `benchmark-result.json`：完整 k6 metrics 原始数据

## 未来可扩展

- 加 POST 写操作场景（batch-cancel 邮件、create user）
- 加 WebSocket 压测（目前只测 HTTP）
- 加长时间浸泡测试（1h 持续中等负载，看内存泄漏）

目前只做只读端点的 SM-4 验证，够用。
