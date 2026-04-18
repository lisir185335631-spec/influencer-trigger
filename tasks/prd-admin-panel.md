# PRD: Admin 管理后台

> **Scope**: 为 influencer-trigger 项目新增管理员专属 Admin 管理界面。
> **Context**: 基于现有 FastAPI + React 18 项目扩展，复用 `client/` 工程与 `server/` API 基础设施。
> **Execution Path**: Opus 4.7 max（规划/审查） + Sonnet 4.6 max（Ralph 执行循环） · 16 stories / 4 waves。

---

## 0. Assumptions（基于代码库分析，已与用户确认）

### 技术假设（已确认正确）
- **A1** ✅ 前端：复用 `client/` 工程，React 18 + TypeScript + TailwindCSS + React Router v6 + Zustand store + axios client
- **A2** ✅ 后端：FastAPI + SQLAlchemy 2.0 async + Pydantic v2，所有 router 挂 `/api` 前缀
- **A3** ✅ 鉴权：现有 `deps.py` 已有 `require_admin` / `require_manager_or_above` / `get_current_user` 依赖，直接复用
- **A4** ✅ User 模型已有 `role: admin/manager/operator`（`server/app/models/user.py:10`）
- **A5** ✅ 审计日志通过 FastAPI Middleware 实现，写入用 BackgroundTask 异步落库，不阻塞响应
- **A6** ✅ WebSocket 复用现有 `/ws` 连接，Admin 事件通过新增 `channel=admin` 区分
- **A7** ✅ 单租户架构，不引入 tenant_id
- **A8** ✅ 数据库 SQLite（开发）/ PostgreSQL（生产），已有 `create_tables()` 机制，新表通过 SQLAlchemy 模型自动创建
- **A9** ✅ 前端路由守卫：新增 `<RequireAdmin>` 组件包裹所有 `/admin/*` 路由
- **A10** ✅ 后端 Admin API 全部挂 `/api/admin` 前缀，不改现有 `/api/*`

### 范围假设
- **A11** ✅ 不重写前台 TeamPage/SettingsPage，但 Admin 版本功能更强（后续可选逐步隐藏前台入口，本 PRD 不处理）
- **A12** ✅ Feature Flag 仅用于 Admin 侧开关，不强制接入到现有业务代码

---

## 1. 介绍/概述

当前 influencer-trigger 系统所有角色（admin/manager/operator）共用同一套 UI 和 API，管理员缺少：

1. **上帝视角**：看不到全系统 Agent 运行健康度、邮箱池状态、LLM 成本、异常事件流
2. **操作审计**：无法追溯"谁何时做了什么"（关键合规与安全需求）
3. **全局干预**：无法批量撤销邮件、强制终止异常任务、回收失控邮箱、冻结用户
4. **成本可见**：LLM Token / 邮件量 / 存储没有聚合视图，无法做预算控制

本 PRD 定义一套**独立于业务前台的 Admin 管理后台**，通过 `/admin/*` 子路由 + `/api/admin/**` API 命名空间实现，给 `role=admin` 用户提供完整的平台治理能力。

**定位公式**：
```
Admin 后台 = 前台 11 个业务模块的"上帝视角镜像" + 5 个平台治理新模块
```

---

## 2. Goals

- **G1** 100% 覆盖前台 11 个业务模块的管理员视角
- **G2** 新增 5 个平台治理模块（Agent 监控、审计日志、成本用量、安全合规、系统诊断）
- **G3** 零侵入：现有 `/api/**` 和前台 UI 不做任何破坏性修改
- **G4** 权限硬隔离：后端 `require_admin` 强制校验，前端路由守卫防误入
- **G5** 写操作 100% 审计 + 读操作 10% 采样，全量可追溯
- **G6** 视觉明确：深色侧栏 `slate-900` 让管理员立刻识别"我在后台"
- **G7** 16 stories 分 4 wave 交付，每 wave 独立可上线

---

## 3. User Stories

### Wave 1 · 地基（5 stories）

---

#### A01: Admin 路由地基 + AdminLayout + 权限守卫（前后端基础）

**描述**：作为管理员，我需要一个独立的 Admin 路由体系，以便访问管理员专属页面而不与业务前台混淆。

**depends_on**: 无

**Acceptance Criteria**:
- [ ] 后端新增 `server/app/api/admin/` 目录，创建 `__init__.py` 和 `deps.py`
- [ ] 新增 `server/app/api/admin/overview.py` 占位 router，注册一个 `GET /api/admin/overview/ping` 测试端点，使用 `Depends(require_admin)`
- [ ] `server/app/main.py` 注册 admin router，前缀 `/api/admin`
- [ ] 非 admin 用户访问 `/api/admin/overview/ping` 返回 403
- [ ] 前端新增 `client/src/components/admin/AdminLayout.tsx`（深色侧栏 `bg-slate-900` + 白色主内容区 + 顶部 "ADMIN CONSOLE" 标识）
- [ ] 前端新增 `client/src/components/admin/AdminSidebar.tsx`（先列 16 个菜单项占位，点击切换路由）
- [ ] 前端新增 `client/src/components/admin/RequireAdmin.tsx` 路由守卫（非 admin 角色重定向到 `/dashboard`）
- [ ] `client/src/App.tsx` 新增 `/admin/*` 路由，默认子路由 `/admin/overview`
- [ ] 登录成功后：role=admin 自动跳转 `/admin/overview`；其他角色仍跳转 `/dashboard`
- [ ] 新增 `client/src/api/admin/client.ts`：axios 实例，baseURL=`/api/admin`，共享 JWT token 拦截器
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：admin 账号登录 → 自动进入 `/admin/overview`；operator 账号访问 `/admin/overview` → 跳转回 `/dashboard`

---

#### A02: 用户与权限中心 `/admin/users`

**描述**：作为管理员，我需要管理全平台用户账号、角色、冻结状态，并能查看登录历史。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] 后端新增 `server/app/api/admin/users_admin.py`，提供：
  - `GET /api/admin/users` 列表（分页 + 搜索用户名/邮箱 + 按角色筛选）
  - `POST /api/admin/users` 创建用户（username/email/password/role）
  - `PATCH /api/admin/users/{id}` 修改角色/激活状态
  - `POST /api/admin/users/{id}/reset-password` 重置密码（管理员填写新密码）
  - `POST /api/admin/users/{id}/force-logout` 强制下线（使 JWT 失效，通过 `token_version` 字段累加实现）
  - `GET /api/admin/users/{id}/login-history` 最近 50 条登录记录
- [ ] User 模型新增 `token_version: int = 0` 字段；JWT payload 携带 `token_version`，`get_current_user` 校验不匹配则 401
- [ ] 新增 `server/app/models/login_history.py`：`id, user_id, ip, user_agent, success, failed_reason, created_at`
- [ ] **在 `server/app/models/__init__.py` 中 import `login_history`**（否则 `create_tables()` 不会建表）
- [ ] `/api/auth/login` 每次登录写 login_history（成功/失败都写）
- [ ] 前端新增 `client/src/pages/admin/UsersAdminPage.tsx`：
  - 表格显示所有用户（用户名/邮箱/角色/激活状态/创建时间/最后登录时间）
  - 顶部搜索框 + 角色筛选下拉
  - 每行操作：编辑、重置密码、冻结/解冻、强制下线、查看登录历史（modal）
  - 新建用户按钮（modal 表单）
- [ ] 所有破坏性操作（重置密码/强制下线/删除）必须弹 confirm modal，且需管理员再次输入自己密码
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：登录 admin → 进入 `/admin/users` → 能看到所有用户 → 创建新用户 → 修改角色 → 强制下线测试账号

---

#### A03: 平台总览大屏 `/admin/overview`

**描述**：作为管理员，我需要一个首屏看到的全系统仪表盘，快速了解当前平台整体健康度和关键指标。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] 后端新增 `server/app/api/admin/overview.py`，提供：
  - `GET /api/admin/overview/metrics` 返回核心指标聚合（用户总数/活跃用户/今日/本周/本月：抓取任务数、邮件发送数、邮件回复数、网红数量、Agent 运行任务数、异常数）
  - `GET /api/admin/overview/health` 返回系统健康状态（DB 连接/Scheduler 运行/Monitor Agent 运行/WebSocket 活跃连接数）
  - `GET /api/admin/overview/recent-events` 返回最近 20 条系统事件（登录/发送异常/抓取完成/Agent 错误）
- [ ] 前端新增 `client/src/pages/admin/OverviewPage.tsx`：
  - 顶部 4 个大数字 Metric Card（今日邮件发送/今日新增网红/今日回复数/活跃 Agent 数）
  - 中部 3 个图表（邮件发送 7 天趋势折线图、抓取任务 7 天堆叠柱状图、各平台网红数量环形图）
  - 底部系统健康面板（5 个指示灯：DB/Scheduler/Monitor/WebSocket/邮箱池）
  - 右侧 Recent Events 事件流时间轴（最近 20 条）
- [ ] 邮箱池健康指示灯算法：**至少 1 个 mailbox 健康评分 > 70 → 绿；全部 ≤ 70 但有 > 30 → 黄；全部 ≤ 30 或无可用 mailbox → 红**
- [ ] 图表使用 `recharts`（已在现有前台使用的，复用）。若未使用，需加入 `package.json`
- [ ] 30 秒自动刷新（轮询），可手动刷新
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：admin 进入 `/admin/overview` → 所有数字和图表正常渲染 → 事件流显示最近操作

---

#### A04: 审计日志系统（模型 + 中间件 + API）

**描述**：作为管理员，我需要系统自动记录所有关键操作，以便合规审计和问题追溯。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] 新增 `server/app/models/audit_log.py`：
  - 字段：`id, user_id, username, role, action, resource_type, resource_id, request_method, request_path, ip, user_agent, status_code, request_body_snippet (max 2KB), response_snippet (max 2KB), duration_ms, created_at`
  - 索引：`user_id + created_at`、`resource_type + resource_id`、`created_at`
- [ ] **在 `server/app/models/__init__.py` 中 import `audit_log`**
- [ ] 新增 `server/app/middleware/audit_middleware.py`：
  - 写操作（POST/PUT/PATCH/DELETE）：100% 写审计
  - 读操作（GET）：10% 采样写审计
  - 写入走 `BackgroundTask`，不阻塞响应
  - 敏感字段（password、token、api_key）在写入前打码为 `***`
  - **异常容错：中间件内部任何异常都必须 try/except 静默吞掉，绝不阻塞业务请求**
- [ ] `server/app/main.py` 注册 audit middleware，放在 CORS 之后
- [ ] 新增 `server/app/api/admin/audit.py`：
  - `GET /api/admin/audit/logs` 支持筛选（user_id / username / action / resource_type / method / status_code / created_at 区间）+ 分页 + 按时间倒序
  - `GET /api/admin/audit/export` 导出 CSV（限制最多 10000 条）
  - `GET /api/admin/audit/stats` 返回 7 天操作趋势（按 action 分组）
- [ ] 单元测试（≥3 条）：验证中间件能正确写入 log、敏感字段打码、读操作采样
- [ ] Typecheck + lint 通过

---

#### A05: 审计日志 UI + 多维过滤 + 导出 `/admin/audit`

**描述**：作为管理员，我需要一个可视化的审计日志查询界面，能按用户/操作/资源过滤并导出证据。

**depends_on**: A04

**Acceptance Criteria**:
- [ ] 前端新增 `client/src/pages/admin/AuditLogPage.tsx`：
  - 顶部过滤器面板（用户下拉、action 下拉、resource_type 下拉、method 下拉、日期范围选择器、关键字搜索）
  - 表格列：时间/用户/角色/方法/路径/资源/状态码/IP/耗时，支持点击行展开看完整 request/response snippet
  - 分页 + 每页 50 条
  - 右上角"导出 CSV"按钮（调用 `/api/admin/audit/export`）
  - 顶部小图表：7 天操作趋势（调用 `/api/admin/audit/stats`）
- [ ] 请求体/响应体 snippet 用等宽字体 `font-mono`，并做 JSON 高亮（`react-syntax-highlighter` 或原生 pre）
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：admin 在平台操作几次 → 进入 `/admin/audit` → 能看到自己的操作 → 按用户筛选能过滤 → 导出 CSV 能下载

---

### Wave 2 · 业务治理（5 stories）

---

#### A06: 邮件全局流 `/admin/emails`（批量撤销 + 黑名单）

**描述**：作为管理员，我需要看到全量邮件流水，能批量撤销异常发送并管理收件人黑名单。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] 后端新增 `server/app/api/admin/emails_admin.py`：
  - `GET /api/admin/emails` 全量邮件列表（筛选：状态/发送者邮箱/收件人/时间段/模板）+ 分页
  - `POST /api/admin/emails/batch-cancel` 批量撤销（仅 status=pending/queued 的可撤销）
  - `GET /api/admin/emails/stats` 退信率、打开率、回复率按时间/按邮箱维度
  - 黑名单：新增 `server/app/models/email_blacklist.py`（id, email, reason, added_by_user_id, created_at）
  - **在 `server/app/models/__init__.py` 中 import `email_blacklist`**
  - `GET/POST/DELETE /api/admin/emails/blacklist`
  - 在 `server/app/services/sender_service.py` **发送前**调用 `is_blacklisted(email)` 函数，命中则跳过该条并记录为 `status=blocked`（仅新增一次函数调用，不改现有发送逻辑）
- [ ] 前端新增 `client/src/pages/admin/EmailsAdminPage.tsx`：
  - Tab 切换：邮件流水 / 黑名单管理
  - 流水 Tab：表格（时间/收件人/发件邮箱/状态/模板/打开/回复），行可多选，顶部按钮"批量撤销选中"
  - 顶部 4 个指标卡（今日发送/退信率/打开率/回复率）
  - 黑名单 Tab：列表 + 新增黑名单表单（邮箱 + 原因）+ 删除
- [ ] 批量撤销前弹 confirm modal，显示撤销条数和影响的收件人
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：admin 进入 `/admin/emails` → 能看到全量邮件 → 多选 → 批量撤销 → 新增黑名单项 → 发送邮件时该地址被拦截

---

#### A07: 邮箱池管理 `/admin/mailboxes`

**描述**：作为管理员，我需要监控全平台所有 SMTP 发送邮箱的健康度和 IMAP 监控状态，能强制踢出异常邮箱。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] 后端新增 `server/app/api/admin/mailboxes_admin.py`：
  - `GET /api/admin/mailboxes` 全邮箱列表（展示：地址/SMTP 连接状态/IMAP 连接状态/今日已发/今日额度/最后成功时间/最后失败时间/失败率/健康评分）
  - `POST /api/admin/mailboxes/{id}/test-smtp` 实时测试 SMTP 连接
  - `POST /api/admin/mailboxes/{id}/test-imap` 实时测试 IMAP 连接
  - `POST /api/admin/mailboxes/{id}/disable` 强制停用
  - `POST /api/admin/mailboxes/{id}/reset-quota` 重置今日额度
  - `GET /api/admin/mailboxes/{id}/send-history` 该邮箱最近 100 条发送记录
- [ ] 健康评分算法：基于失败率（<1% 健康/1-5% 预警/>5% 异常）、额度使用率、最后失败时间
- [ ] 前端新增 `client/src/pages/admin/MailboxesAdminPage.tsx`：
  - 表格每行左侧显示 3 色健康指示灯（绿/黄/红）+ 文字评分
  - 行操作：测试 SMTP / 测试 IMAP / 强制停用 / 重置额度 / 查看发送历史（drawer）
  - 顶部卡片：总邮箱数 / 健康数 / 预警数 / 异常数
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：admin 进入 `/admin/mailboxes` → 看到健康灯 → 测试 SMTP → 强制停用 → 查看发送历史

---

#### A08: 网红库治理 `/admin/influencers`（合并去重 + 数据质量）

**描述**：作为管理员，我需要清理重复网红数据、查看数据质量报告、批量回刷邮箱验证。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] 后端新增 `server/app/api/admin/influencers_admin.py`：
  - `GET /api/admin/influencers/duplicates` 查询疑似重复（按 email 精确匹配 + 按 name+platform 相似度 > 0.9）
  - `POST /api/admin/influencers/merge` 合并多条记录到一条（保留主记录 ID，其他记录的外键关系迁移到主 ID 后删除）
  - `GET /api/admin/influencers/quality-report` 数据质量报告（空邮箱比例/无效邮箱比例/粉丝数缺失比例/bio 缺失比例）
  - `POST /api/admin/influencers/batch-verify-email` 批量 MX 验证（后台任务，返回 task_id）
  - `GET /api/admin/influencers/batch-verify-email/{task_id}` 查询验证进度
  - `GET /api/admin/influencers` 管理员视角的全量列表（比前台多显示：创建者、创建时间、所有关联 task_id、邮件发送次数）
- [ ] 前端新增 `client/src/pages/admin/InfluencersAdminPage.tsx`：
  - Tab 切换：全量列表 / 重复数据 / 质量报告
  - 重复数据 Tab：分组展示疑似重复，每组可选主记录后点"合并"
  - 质量报告 Tab：4 个饼图 + 一键"批量 MX 验证"按钮，启动后显示进度条
- [ ] 合并操作前弹 confirm modal 并显示影响的所有外键数据（邮件记录、标签等）
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：admin 进入 `/admin/influencers` → 看到重复列表 → 合并一组 → 查看质量报告

---

#### A09: 抓取任务治理 `/admin/scrape`

**描述**：作为管理员，我需要监控所有抓取任务、强制终止异常任务、查看 Playwright 资源占用。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] 后端新增 `server/app/api/admin/scrape_admin.py`：
  - `GET /api/admin/scrape/tasks` 全量抓取任务（含所有用户创建的，显示创建者）
  - `POST /api/admin/scrape/tasks/{id}/force-terminate` 强制终止（释放 Playwright 资源）
  - `POST /api/admin/scrape/tasks/{id}/retry` 失败重试
  - `GET /api/admin/scrape/platform-quota` 各平台今日抓取配额使用情况
  - `PATCH /api/admin/scrape/platform-quota` 调整配额（admin 可调）
  - 新增 `server/app/models/platform_quota.py`：`platform (unique), daily_limit, today_used, last_reset_at`
  - **在 `server/app/models/__init__.py` 中 import `platform_quota`**
- [ ] 前端新增 `client/src/pages/admin/ScrapeAdminPage.tsx`：
  - Tab 切换：任务列表 / 平台配额
  - 任务列表：全量任务（含创建者列），运行中行高亮，支持强制终止/重试
  - 平台配额 Tab：5 个平台进度条（已用/上限），可点击进度条修改上限
- [ ] 强制终止前弹 confirm modal
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：admin 进入 `/admin/scrape` → 看到全量任务 → 强制终止一个 → 修改 TikTok 配额

---

#### A10: 模板审核库 `/admin/templates`

**描述**：作为管理员，我需要审核所有邮件模板，执行上下架、合规关键词扫描、查看使用排行。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] Template 模型新增字段：`is_published: bool = true`、`compliance_flags: str = ""`（逗号分隔的违规关键词命中）
- [ ] 后端新增 `server/app/api/admin/templates_admin.py`：
  - `GET /api/admin/templates` 全量（显示创建者、使用次数、发送成功率、is_published 状态）
  - `POST /api/admin/templates/{id}/publish` 上架
  - `POST /api/admin/templates/{id}/unpublish` 下架（下架后前台用户无法选用）
  - `POST /api/admin/templates/{id}/compliance-scan` 运行合规扫描（关键词库命中）
  - `GET /api/admin/templates/ranking` 使用次数排行 top 20
  - 新增 `server/app/models/compliance_keywords.py`（管理员维护的敏感词库）：`id, keyword, category, severity, created_at`
  - **在 `server/app/models/__init__.py` 中 import `compliance_keywords`**
  - `GET/POST/DELETE /api/admin/templates/keywords` CRUD 关键词库
- [ ] **前台兼容改造（显式文件清单）**：
  - `server/app/api/templates.py` GET 端点添加可选参数 `include_unpublished: bool = False`（仅 admin 生效）
  - `server/app/services/template_service.py` list 函数接受 `include_unpublished` 参数，默认过滤 `is_published=true`
  - `client/src/api/templates.ts` **不变**（默认行为：只拿 published）
  - 前台使用模板的页面（EmailsPage / TemplatesPage / FollowUpPage）**不需修改**
- [ ] 回归测试：operator 用户在前台创建邮件时能选模板，且只能选 `is_published=true` 的模板
- [ ] 前端新增 `client/src/pages/admin/TemplatesAdminPage.tsx`：
  - Tab 切换：模板审核 / 使用排行 / 关键词库
  - 模板审核：表格（标题/创建者/使用次数/成功率/合规标志/状态），行操作：上架/下架/合规扫描/查看内容
  - 使用排行：top 20 柱状图 + 表格
  - 关键词库：增删改敏感词（字段：keyword/category: 政治/暴力/色情/其他/severity: low/medium/high）
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：admin 进入 `/admin/templates` → 下架一个模板 → 前台 operator 用户创建邮件时看不到该模板 → 扫描合规

---

### Wave 3 · Agent 监控与成本（4 stories）

---

#### A11: Agent 运行监控 `/admin/agents`

**描述**：作为管理员，我需要实时监控 5 个 Agent 的运行状态、历史任务、错误日志。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] 新增 `server/app/models/agent_run.py`：
  - 字段：`id, agent_name, task_id, state (pending/running/success/failed/cancelled), input_snapshot, output_snapshot, error_message, error_stack, started_at, finished_at, duration_ms, token_cost_usd, llm_calls_count`
  - 索引：`agent_name + started_at`、`state + started_at`
- [ ] **在 `server/app/models/__init__.py` 中 import `agent_run`**
- [ ] 新增 `server/app/agents/_tracking.py` 提供一个 **async context manager** `track_agent_run(agent_name, task_id, input_data)`，在 with 块内部执行 Agent 逻辑，自动记录 run 的 started_at / finished_at / state / error / duration
- [ ] **最小侵入改造**：仅修改 `server/app/agents/supervisor.py` 一个文件——在 Supervisor 调用各 Executor Agent 的地方用 `async with track_agent_run(...)` 包裹
- [ ] **5 个 Executor Agent 文件保持不变**（scraper.py / sender.py / monitor.py / responder.py / classifier.py 零修改）
- [ ] 若 Supervisor 未覆盖某个 Agent 调用路径（如 monitor 是独立 lifespan task），单独在 monitor 启动处手动调用 track_agent_run 包裹 loop body
- [ ] 后端新增 `server/app/api/admin/agents_monitor.py`：
  - `GET /api/admin/agents/status` 6 个 Agent 当前状态（最近 N 个 run 的 success/failed 比例 + 平均耗时 + 当前运行中的任务数）
  - `GET /api/admin/agents/runs` 历史运行记录（按 agent/状态/时间段筛选）
  - `GET /api/admin/agents/runs/{id}` 单次运行详情（含完整 input/output/error）
  - `POST /api/admin/agents/runs/{id}/retry` 手动重试失败的 run（构造同样 input 重新调用）
- [ ] 前端新增 `client/src/pages/admin/AgentsMonitorPage.tsx`：
  - 顶部 6 个 Agent 卡片（名称/状态灯/最近成功率/平均耗时/运行中任务数）
  - 中部表格：历史 run 列表（筛选 agent + 状态 + 日期），展开看 input/output/error
  - 失败 run 行提供"重试"按钮
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：admin 进入 `/admin/agents` → 看到 6 个 Agent 卡片 → 触发一次抓取 → 能看到新 run 出现

---

#### A12: 成本与用量 `/admin/usage`

**描述**：作为管理员，我需要聚合查看 LLM Token 消耗、邮件发送量、Playwright 运行时长、存储占用，按日/周/月趋势分析。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] 新增 `server/app/models/usage_metric.py`：
  - 字段：`id, metric_date (date), metric_type (llm_token/email_sent/scrape_run/storage_mb), sub_key (model_name/user_id/agent_name/nullable), value (float), cost_usd (float, nullable), created_at`
  - 复合唯一索引：`metric_date + metric_type + sub_key`
- [ ] **在 `server/app/models/__init__.py` 中 import `usage_metric`**
- [ ] 新增 `server/app/services/admin/usage_service.py`：
  - `record_llm_usage(model, prompt_tokens, completion_tokens, user_id)` 原子累加当天记录（UPSERT），cost 自动按模型单价计算
  - `record_email_sent(user_id, count)` 同上
- [ ] **新增统一 LLM 客户端入口 `server/app/tools/llm_client.py`**（本 story 的核心架构收敛）：
  - 封装 `async def chat(model, messages, user_id=None, agent_name=None, **kwargs) -> str` 统一调用 OpenAI
  - 所有 LLM 调用必须走此入口，客户端内部自动调用 `record_llm_usage` 打点
  - 提供 `async def embed(...)` 等其他调用入口（如现有代码使用）
- [ ] **重构现有 LLM 调用点**（收敛到 llm_client）：
  - `server/app/services/scraper_service.py`、`classifier_service.py`、`responder_service.py`、`template_service.py` 中所有 `openai.*` / `AsyncOpenAI(...)` 原生调用改为走 `llm_client.chat(...)`
  - **Validator 校验标准**：`grep -rn "AsyncOpenAI\|openai\.ChatCompletion\|client\.chat\.completions" server/app --include="*.py"` 的结果只允许出现在 `server/app/tools/llm_client.py` 内部
- [ ] 在 `server/app/services/sender_service.py` 成功发送后调用 `record_email_sent`（仅新增 1 处调用）
- [ ] 后端新增 `server/app/api/admin/usage.py`：
  - `GET /api/admin/usage/summary?period=day|week|month` 总成本 + 4 个指标
  - `GET /api/admin/usage/trend?metric=llm_token&period=30d` 时间序列（按天）
  - `GET /api/admin/usage/breakdown?metric=llm_token&dimension=model|user` 分组汇总
  - `GET /api/admin/usage/alerts` 当前成本预警（当日成本 > 阈值）
  - `POST /api/admin/usage/budget` 设置月度预算阈值
- [ ] 新增 `server/app/models/usage_budget.py`：`id, month (YYYY-MM), budget_usd, alert_threshold_pct, created_at`
- [ ] **在 `server/app/models/__init__.py` 中 import `usage_budget`**
- [ ] 前端新增 `client/src/pages/admin/UsagePage.tsx`：
  - 顶部 4 个指标卡（当月总成本/今日 Token/本月邮件量/存储）
  - 中部 2 个图表（30 天成本趋势折线图、模型分布环形图）
  - 底部表格：按用户 Top 10 成本排行
  - 右侧预算预警面板 + 设置预算按钮
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：触发一次 LLM 调用 → admin 进入 `/admin/usage` → 看到数字累加 → 设置月度预算

---

#### A13: 追发策略中心 + 节假日治理 `/admin/followup` + `/admin/holidays`

**描述**：作为管理员，我需要配置全局追发策略、查看 Responder Agent 行为审计、管理节假日邮件规则。

**depends_on**: A01

**Acceptance Criteria**:

**★ 追发部分**
- [ ] 后端新增 `server/app/api/admin/followup_admin.py`：
  - `GET/PATCH /api/admin/followup/settings` 管理员级策略（最大追发次数、时间间隔、启用/禁用）
  - `GET /api/admin/followup/responder-logs` Responder Agent 回复生成历史（原始回复 → 意图分类 → 生成的跟进邮件）
  - `POST /api/admin/followup/pause-all` 紧急暂停全部追发
  - `POST /api/admin/followup/resume-all` 恢复
- [ ] 前端新增 `client/src/pages/admin/FollowupAdminPage.tsx`：
  - 策略配置表单（最大次数/间隔天数/总开关）
  - 紧急暂停按钮（红色 danger 按钮 + confirm modal）
  - 下方 Responder 行为审计表格
- [ ] agent-browser 验证：admin 配置策略 → 紧急暂停 → 策略立即生效（Scheduler 的 follow_up job 停运）

**★ 节假日部分**
- [ ] 后端新增 `server/app/api/admin/holidays_admin.py`：
  - `GET /api/admin/holidays` 管理员视角（全量节日 + 每个节日历史投放统计）
  - `POST/PATCH/DELETE /api/admin/holidays` CRUD
  - `GET /api/admin/holidays/{id}/investment-report` 该节日历年发送报告（发送数/打开率/回复率）
  - `POST /api/admin/holidays/sensitive-regions` 敏感地区名单（该地区用户不发该节日）
- [ ] Holiday 模型新增 `sensitive_regions: str = ""` 字段（逗号分隔 region code）
- [ ] 前端新增 `client/src/pages/admin/HolidaysAdminPage.tsx`：
  - 日历视图 + 列表切换
  - 每个节日行可展开查看历年投放报告（柱状图）
  - 敏感地区配置
- [ ] agent-browser 验证：admin 新增节日 → 配置敏感地区 → 查看投放报告

**★ 通用**
- [ ] Typecheck + lint 通过

---

#### A14: 系统配置中心 + Feature Flag `/admin/settings`

**描述**：作为管理员，我需要管理平台级参数（LLM Key、Webhook、分级配额）和 Feature Flag（控制新功能灰度发布）。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] 新增 `server/app/models/feature_flag.py`：
  - 字段：`id, flag_key (unique), enabled (bool), description, rollout_percentage (0-100), target_roles (逗号分隔), updated_by_user_id, created_at, updated_at`
- [ ] **在 `server/app/models/__init__.py` 中 import `feature_flag`**
- [ ] 后端新增 `server/app/api/admin/settings_admin.py`：
  - `GET /api/admin/settings/system` 系统级参数（LLM Key **只读状态**：configured/not_configured + 最后 4 位 / Webhook URL / 默认分级配额）
  - `PATCH /api/admin/settings/system` 更新 Webhook 和 默认配额（**不包含 LLM Key**）
  - `GET /api/admin/settings/flags` 所有 feature flag
  - `POST/PATCH/DELETE /api/admin/settings/flags` CRUD
  - `GET /api/admin/settings/flags/{key}/check?user_id=X` 查询某用户某 flag 是否开启（用于业务调用）
- [ ] System Settings 扩展：现有 `system_settings` 表新增 `webhook_default_url`、`default_daily_quota` 字段（**不加 LLM Key 字段**）
- [ ] **LLM Key 保持走环境变量 `OPENAI_API_KEY`，不入库**。Admin UI 仅**只读展示**：
  - 从 `os.environ` 读 Key，返回 `{"configured": true/false, "last_4": "...xxxx"}`，**绝不返回真值**
  - DB 存储 + Fernet 加密功能列入 Open Questions，后续 story 处理
- [ ] 前端新增 `client/src/pages/admin/SettingsAdminPage.tsx`：
  - Tab 切换：系统参数 / Feature Flag
  - 系统参数：
    - LLM Key 区域：**只读** badge 显示 `Configured: sk-...xxxx` 或 `Not Configured`，下方灰色提示文字"LLM Key 通过环境变量 OPENAI_API_KEY 配置，UI 修改功能待后续 story"
    - Webhook URL / 默认配额：普通表单（可编辑）
  - Feature Flag：表格（key/enabled/rollout/目标角色），行可编辑
  - 新建 Flag：key、desc、rollout_percentage 滑块、角色多选
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：admin 进入 `/admin/settings` → 看到 LLM Key 状态为 Configured → 更新 Webhook → 创建一个 feature flag → 调整 rollout percentage

---

### Wave 4 · 安全与诊断（2 stories）

---

#### A15: 安全与合规 `/admin/security`

**描述**：作为管理员，我需要查看异常登录告警、启用敏感操作二次认证、轮换系统密钥。

**depends_on**: A02（依赖 login_history 表）

**Acceptance Criteria**:
- [ ] 后端新增 `server/app/api/admin/security.py`：
  - `GET /api/admin/security/alerts` 异常登录事件（新 IP/新设备/10 分钟内失败 > 5 次）
  - `POST /api/admin/security/alerts/{id}/acknowledge` 标记已处理
  - `GET /api/admin/security/2fa-config` 二次认证配置（目前支持：敏感操作要求再次输入密码 + TOTP 可选）
  - `PATCH /api/admin/security/2fa-config` 修改
  - `POST /api/admin/security/rotate-keys` 轮换系统加密密钥（JWT SECRET + Fernet KEY），自动使所有 JWT 失效
  - `GET /api/admin/security/key-rotation-history` 密钥轮换历史
- [ ] 异常登录检测规则（在 `login_history` 写入后触发）：
  - 新 IP：该用户过去 30 天未出现过的 IP
  - 10 分钟内同一用户 ≥5 次失败 → 触发告警
  - 不同地区（基于 IP 地理信息，可用 `ip2location` 或简单按 IP 段判断，MVP 可省略地理信息仅检测新 IP）
- [ ] 新增 `server/app/models/security_alert.py`：`id, alert_type, user_id, details_json, acknowledged, acknowledged_by, acknowledged_at, created_at`
- [ ] **在 `server/app/models/__init__.py` 中 import `security_alert`**
- [ ] 前端新增 `client/src/pages/admin/SecurityPage.tsx`：
  - Tab：告警 / 2FA 配置 / 密钥轮换
  - 告警：时间轴（红色 = 未处理，灰色 = 已处理），点击可展开详情
  - 2FA：开关 + 配置说明
  - 密钥轮换：当前密钥年龄（>90 天显示警告）+ 轮换按钮（confirm modal + 管理员密码二次确认）
- [ ] 密钥轮换操作必须写入 audit_log
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：5 次错误登录 → admin 进入 `/admin/security` → 看到告警 → 标记已处理 → 查看密钥轮换历史

---

#### A16: 系统诊断 `/admin/diagnostics`

**描述**：作为管理员，我需要一键检查系统各组件的健康状态（DB/Redis/WS/Scheduler/磁盘/内存），定位异常。

**depends_on**: A01

**Acceptance Criteria**:
- [ ] 后端新增 `server/app/api/admin/diagnostics.py`：
  - `GET /api/admin/diagnostics/db` DB 健康（连接池用量、当前活动连接、最近慢查询 top 10）
  - `GET /api/admin/diagnostics/redis` Redis 健康（连接、队列深度、key 数量）—— 如未使用 Redis 则返回 `not_configured`
  - `GET /api/admin/diagnostics/websocket` WS 活跃连接数、分通道统计
  - `GET /api/admin/diagnostics/scheduler` APScheduler 所有 job 状态（id/下次执行时间/最近执行结果）
  - `GET /api/admin/diagnostics/system` 磁盘使用率、内存使用率、Python 进程信息（使用 `psutil`）
  - `POST /api/admin/diagnostics/healthcheck` 一键全量自检（并行调用上述 5 个端点，返回汇总报告）
- [ ] 将 `psutil` 加入 `requirements.txt`
- [ ] **psutil 降级处理**：`diagnostics.py` 中 `import psutil` 用 `try/except ImportError` 包裹；失败时 `GET /api/admin/diagnostics/system` 返回 `{"status": "not_available", "reason": "psutil not installed"}`
- [ ] 前端 System 卡片检测到 `status=not_available` 时显示灰色提示："系统指标不可用（请联系运维安装 psutil）"，其他卡片正常工作
- [ ] 前端新增 `client/src/pages/admin/DiagnosticsPage.tsx`：
  - 顶部"运行完整自检"大按钮，点击后并行检查 5 项，每项用卡片显示结果（绿/黄/红）
  - 5 个诊断卡片：DB / Redis / WebSocket / Scheduler / System
  - 每个卡片可展开看详情
  - Scheduler 卡片列出所有 job
  - System 卡片显示磁盘/内存进度条
- [ ] Typecheck + lint 通过
- [ ] 使用 agent-browser 验证：admin 进入 `/admin/diagnostics` → 点击一键自检 → 所有卡片显示状态 → 展开 Scheduler 卡片能看到 job

---

## 4. Functional Requirements

- **FR-1**：所有 `/api/admin/**` 端点必须使用 `Depends(require_admin)`，非 admin 角色返回 403
- **FR-2**：所有 `/admin/*` 前端路由必须包裹 `<RequireAdmin>` 组件，非 admin 重定向到 `/dashboard`
- **FR-3**：审计中间件写入 100% 写操作 + 10% 读操作，敏感字段（password/token/api_key）自动打码
- **FR-4**：审计日志写入走 BackgroundTask，不阻塞响应
- **FR-5**：Admin 侧栏使用深色 `bg-slate-900`，与业务前台白色背景形成视觉区分
- **FR-6**：所有破坏性操作（删除/撤销/强制终止/密钥轮换/重置密码）必须弹 confirm modal
- **FR-7**：极度敏感操作（密钥轮换、用户权限变更、LLM Key 修改）必须二次输入管理员密码
- **FR-8**：所有 Admin API 遵循现有 FastAPI + Pydantic v2 + SQLAlchemy 2.0 async 范式
- **FR-9**：新增 4 张表（audit_log / usage_metric / feature_flag / agent_run）通过 SQLAlchemy 模型自动创建，不破坏现有 migration 流程
- **FR-10**：Feature Flag 仅作为 Admin 侧开关框架，本 PRD 不强制接入现有业务代码
- **FR-11**：登录成功后 role=admin 自动跳转 `/admin/overview`，其他角色仍跳转 `/dashboard`

---

## 5. Non-Goals（超出范围）

- **NG-1**：不引入 tenant_id 多租户架构（项目仍为单租户）
- **NG-2**：不重写前台 TeamPage / SettingsPage（本 PRD 不隐藏前台入口）
- **NG-3**：不引入新的鉴权系统（复用现有 JWT）
- **NG-4**：Feature Flag 不强制接入业务代码（后续 story 可选）
- **NG-5**：不做基于地理 IP 的异常登录检测（MVP 仅检测"新 IP"，后续可加 `ip2location`）
- **NG-6**：不做 TOTP 真正实现（A15 仅提供配置框架，TOTP 代码生成/校验不实现）
- **NG-7**：不做邮件内容的 AI 合规审查（A10 仅做关键词库匹配）
- **NG-8**：不做 Admin 后台的国际化（复用现有 i18n 基础设施，英文优先，后续可补中文）
- **NG-9**：不引入 Redis（如项目未使用则 A16 的 Redis 卡片显示 not_configured）
- **NG-10**：不做 LangGraph 状态机可视化图（A11 仅做 run 历史表格，可视化图后续 story 处理）

---

## 6. Design Considerations

### 视觉规范
- **侧栏**：`bg-slate-900 text-slate-100`，宽度 240px，顶部红字 "ADMIN CONSOLE"
- **主内容区**：`bg-white`，延续现有业务前台风格
- **强调色**：rose-500（破坏性操作）、amber-500（警告）、emerald-500（成功）、slate-500（中性）
- **反 AI 模板要求**：按现有 `refined-ui-design` 原则，卡片 hover 顶部强调线动画、不用渐变、克制品牌感

### 可复用组件
- Modal / Dialog / Table / Form 组件复用现有前台 `components/` 下的基础组件
- 新增 `components/admin/` 下的专属组件：`AdminLayout`、`AdminSidebar`、`AdminHeader`、`MetricCard`、`AlertPanel`、`AuditTable`、`HealthIndicator`

### 路由规划
```
/login                          登录
/dashboard                      业务前台首页（role != admin）
/admin/                         重定向到 /admin/overview
/admin/overview                 平台总览大屏
/admin/users                    用户与权限
/admin/audit                    审计日志
/admin/emails                   邮件全局流
/admin/mailboxes                邮箱池
/admin/influencers              网红库治理
/admin/scrape                   抓取治理
/admin/templates                模板审核
/admin/agents                   Agent 监控
/admin/usage                    成本用量
/admin/followup                 追发策略
/admin/holidays                 节假日治理
/admin/settings                 系统配置
/admin/security                 安全合规
/admin/diagnostics              系统诊断
```

---

## 7. Technical Considerations

### 后端目录扩展
```
server/app/
├── api/
│   └── admin/                  # 全部 admin API（16 个文件）
├── models/
│   ├── audit_log.py            # A04
│   ├── usage_metric.py         # A12
│   ├── feature_flag.py         # A14
│   ├── agent_run.py            # A11
│   ├── login_history.py        # A02
│   ├── email_blacklist.py      # A06
│   ├── platform_quota.py       # A09
│   ├── compliance_keywords.py  # A10
│   ├── usage_budget.py         # A12
│   └── security_alert.py       # A15
├── services/
│   └── admin/
│       ├── audit_service.py
│       ├── usage_service.py
│       ├── agent_monitor_service.py
│       ├── security_service.py
│       └── diagnostics_service.py
├── middleware/
│   └── audit_middleware.py     # A04
└── agents/
    └── _tracking.py             # A11: @track_agent_run 装饰器
```

### 前端目录扩展
```
client/src/
├── pages/admin/                # 16 个页面
├── components/admin/           # Admin 专属组件
└── api/admin/                  # Admin API 客户端
```

### 性能约束
- 审计中间件写入必须异步（BackgroundTask），不阻塞响应
- 读操作仅 10% 采样以防 log 爆炸
- 审计日志表需建复合索引 `(user_id, created_at)` 和 `(resource_type, resource_id)`
- Overview 数据聚合若性能不够，允许预计算（daily job）到缓存表

### 安全约束
- 所有破坏性操作必须写 audit_log
- LLM Key 存储使用 Fernet 对称加密（env 注入 `SYSTEM_ENCRYPTION_KEY`）
- JWT token_version 机制支持强制下线
- Admin API 限流比业务 API 更严（slowapi 限流规则待定，MVP 可省略）

### 与现有系统集成
- 现有 `/api/**` 完全不改（只修改 `/api/templates` GET 添加 `include_unpublished` 参数，默认行为不变）
- 现有前端 `client/` 只新增文件和修改 `App.tsx`，不破坏现有路由
- 现有 WebSocket 复用，新增 admin 通道用频道字段区分

---

## 8. Success Metrics

- **SM-1**：16 个 stories 全部通过 Validator 验证（PASSED）
- **SM-2**：前台业务功能零回归（手动回归测试 14 个前台页面无异常）
- **SM-3**：审计日志覆盖率 100%（写操作）+ 10%（读操作采样）
- **SM-4**：Admin 接口响应时间 p95 < 500ms（overview 聚合类 < 1s）
- **SM-5**：非 admin 用户无法通过任何途径访问 `/admin/*` 前端路由和 `/api/admin/**` API
- **SM-6**：所有破坏性操作必须留下可追溯审计日志

---

## 9. Open Questions

- **OQ-1**：审计日志保留策略（目前 PRD 未定：建议 90 天热存储 + 归档到冷存储，但 MVP 可省略归档）
- **OQ-2**：是否需要向 webhook 推送 admin 关键告警（本 PRD 不做，后续 story 可加）
- **OQ-3**：LangGraph 可视化状态机图（A11 仅做表格，可视化后续 story 处理）
- **OQ-4**：LLM Key DB 存储 + Fernet 加密（本 PRD A14 暂走 env 变量只读展示，UI 修改功能待后续 story 引入 SYSTEM_ENCRYPTION_KEY 机制后实现）
- **OQ-5**：前台 TeamPage / SettingsPage 权限收敛（本 PRD 保留前台入口，后续 story 决定是否对 non-admin 隐藏）

---

## 10. Locked Decisions

- **D-01**：前端复用 `client/` 工程，子路由 `/admin/*`，不新建工程
- **D-02**：共用 `/login`，按 role 自动跳转
- **D-03**：后端 API 前缀 `/api/admin/**`，现有 `/api/**` 零破坏
- **D-04**：审计颗粒度：写操作 100% + 读操作 10% 采样
- **D-05**：单租户架构不变，不引入 tenant_id
- **D-06**：复用现有 `require_admin` 依赖
- **D-07**：深色侧栏 `slate-900` + 白色主内容区做视觉分离
- **D-08**：破坏性操作强制 confirm modal，极度敏感操作二次输入密码
- **D-09**：新增 4+6 张表（audit_log/usage_metric/feature_flag/agent_run + login_history/email_blacklist/platform_quota/compliance_keywords/usage_budget/security_alert），均通过 SQLAlchemy 自动创建
- **D-10**：LLM Key 本 PRD **不入库**，继续走环境变量 `OPENAI_API_KEY`，Admin UI 仅只读展示状态；DB 存储+加密留给后续 story
- **D-11**：JWT 携带 `token_version` 支持强制下线
- **D-12**：审计中间件使用 BackgroundTask 异步写入，中间件内部异常必须 try/except 静默
- **D-13**：模型选择：Opus 4.7 max 负责规划/审查；Sonnet 4.6 max 负责执行（Ralph + Validator）
- **D-14**：Feature Flag 作为 Admin 侧框架，本 PRD 不接入现有业务代码
- **D-15**：A11 Agent tracking 用 async context manager，**仅修改 supervisor.py + monitor 启动处**，5 个 Executor Agent 文件零修改
- **D-16**：A12 所有 LLM 调用必须收敛到 `server/app/tools/llm_client.py` 统一入口，原生 OpenAI 调用只能出现在此文件内部
- **D-17**：Overview 性能问题 MVP 直接聚合查询，性能不够单独开 story 处理（不在本 PRD 范围）

---

## 11. 依赖关系（Ralph prd.json 参考）

```
A01 (基础)
├── A02 → A15 (异常登录依赖 login_history)
├── A03
├── A04 → A05
├── A06
├── A07
├── A08
├── A09
├── A10
├── A11
├── A12
├── A13
├── A14
└── A16

Waves:
Wave 1: A01 → [A02, A03, A04]  // A02/A03/A04 可并行
Wave 1 末: A05 (依赖 A04)
Wave 2: [A06, A07, A08, A09, A10]  // 全部并行
Wave 3: [A11, A12, A13, A14]  // 全部并行
Wave 4: [A15 (依赖 A02), A16]  // 并行
```

---

## 12. 执行协议

- **模型分配**：Opus 4.7 max 写 PRD/prd.json/审查；Sonnet 4.6 max 写代码/跑 Validator
- **启用 max**：通过环境变量 `CLAUDE_CODE_EFFORT_LEVEL=max` 局部启用，不改全局 settings
- **Ralph 启动（Git Bash / Linux / macOS）**：
  ```bash
  export CLAUDE_CODE_EFFORT_LEVEL=max && python scripts/ralph/ralph.py --model sonnet --daemon
  ```
- **Ralph 启动（Windows 原生 cmd）**：
  ```cmd
  set CLAUDE_CODE_EFFORT_LEVEL=max && python scripts/ralph/ralph.py --model sonnet --daemon
  ```
- **Audit Gate**：每个 story 完成后 Opus 做 4 维度审查（AC 合规 / AGENTS.md 约束 / 安全 / PRD 一致性）→ approve/reject
- **最终验证**：所有 story 通过后 `/goal-verify` 对比 PRD 与实际实现

---

**PRD END**
