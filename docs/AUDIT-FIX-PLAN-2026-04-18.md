# Audit Fix Plan — 2026-04-18

> **Opus 4.7 max 出方案，Sonnet 4.6 max 执行，Opus review。**
> 起点：`ralph/admin-panel` branch，16/16 stories PASSED 后发现 3 类共 9 项未修问题。
> Phase 0 已完成：清理 Ralph 运行垃圾 + 冻结 WIP（i18n / 端口迁移 / LLM 抓取字段）为一个 `chore:` commit。HEAD = `6e856e1`。

---

## 执行批次

### Batch A（并行，互不依赖，P0 + 最小 P1）

| # | 任务 | 代理文件数 | 预计产出 |
|---|------|----------|---------|
| A1 | `security.py` password_hash → hashed_password + 验证 | 1 | 1 行修复 + commit |
| A2 | Frontend 9 个 Typecheck 错误 | 4 | 4 文件修复 + tsc 通过 |
| A3 | `overview.py` 死代码删除 + 30+ SQL 合并（P0-3 + P1-5 合并，同文件） | 1 | 重写 get_metrics |
| A4 | `classifier.py` 收敛到 `llm_client.py` | 1 + 可能改 llm_client | 重写 + 保留 structured output |

### Batch B（并行，与 A 独立）

| # | 任务 | 文件 | 产出 |
|---|------|----------|---------|
| B1 | AGENTS.md 架构描述对齐 | `AGENTS.md` | 改掉 LangGraph Supervisor 描述 |
| B2 | Alembic 替代 lifespan ALTER TABLE | `server/alembic/`、`main.py`、`requirements.txt` | migrations 目录 + lifespan 精简 |

### Batch C（依赖 A 全通过）

| # | 任务 | 产出 |
|---|------|------|
| C1 | 集成测试 4 条安全敏感路径 | `server/tests/test_admin_*.py` |
| C2 | Audit Gate 加固 tsc + curl | `scripts/ralph/ralph.py` |

---

## A1 — security.py password_hash fix

**根因**：`server/app/api/admin/security.py:248` 写成 `admin_user.password_hash`，但 User 模型字段是 `hashed_password`（见 `server/app/models/user.py:21`）。`/api/admin/security/rotate-keys` 一调用必炸 AttributeError → 500。US-015 Validator 漏网因为浏览器只能测 GET /alerts 等无密码路径，没测 rotate-keys。

**修复 diff**：

```python
# server/app/api/admin/security.py:248
-    if not admin_user or not verify_password(body.admin_password, admin_user.password_hash):
+    if not admin_user or not verify_password(body.admin_password, admin_user.hashed_password):
```

**验收**：grep `password_hash\b` on `server/app/` 应该 0 结果（当前仅此一处）。`python -c "from app.api.admin.security import rotate_keys"` 无错。

**Commit msg**: `fix: [security] correct User field name password_hash → hashed_password`

---

## A2 — Frontend 9 Typecheck errors

### 类型 1：Recharts Tooltip formatter 签名（3 处，5 errors）

Recharts 3.x 的 `Tooltip.formatter` 签名变成 `(value: ValueType | undefined, name, item, index, payload) => ReactNode | [string, string]`。项目里窄化成 `(value: number, name: string)` 不兼容。

**修复**（每处同样 pattern）：

**HolidaysAdminPage.tsx:198**
```tsx
-  formatter={(value: number, name: string) => [
-    name === 'total' ? value : `${value}%`,
+  formatter={(value, name) => [
+    name === 'total' ? Number(value) : `${Number(value)}%`,
     name === 'total' ? 'Sent' : name === 'open_rate' ? 'Open Rate' : 'Reply Rate',
   ]}
```

**UsagePage.tsx:219 & :259**
```tsx
-  formatter={(v: number) => [`$${v.toFixed(4)}`, 'Cost']}
+  formatter={(v) => [`$${Number(v).toFixed(4)}`, 'Cost']}
```

### 类型 2：HolidaysPage onSave union mismatch（1 error）

`HolidayModal.onSave: (data: HolidayCreate | HolidayUpdate) => Promise<void>`，但 `handleAdd: (data: HolidayCreate)` 窄于 union。

**修复 HolidaysPage.tsx:456/461**：
```tsx
-  const handleAdd = async (data: Parameters<typeof holidaysApi.create>[0]) => {
+  const handleAdd = async (data: HolidayCreate | HolidayUpdate) => {
     try {
-      await holidaysApi.create(data)
+      await holidaysApi.create(data as HolidayCreate)
       ...
-  const handleEdit = async (data: Parameters<typeof holidaysApi.update>[1]) => {
+  const handleEdit = async (data: HolidayCreate | HolidayUpdate) => {
     if (!editTarget) return
     try {
-      await holidaysApi.update(editTarget.id, data)
+      await holidaysApi.update(editTarget.id, data as HolidayUpdate)
```

### 类型 3：TemplatesPage 迭代变量 `t` shadow 翻译函数（4 errors）

`const { t } = useTranslation()` 之后又 `results.map((t, i) => ...)` / `templates.map((t) => ...)`，内层 `t('key')` 把模板数据当函数调用。

**修复 TemplatesPage.tsx**：
- 394 行：`results.map((t, i)` → `results.map((tpl, i)`，内部所有 `t.style / t.name / t.subject / t.body_html` → `tpl.xxx`。行 414/418/430 的 `t('templates.ai.xxx')` 留原样（那是外层翻译函数）。
- 588 行：`templates.map((t)` → `templates.map((tpl)`，内部所有 `t.style / t.name / t.id / t.created_at / t.industry` → `tpl.xxx`。行 609/617 的 `t('common.edit/delete')` 留原样。
- 503 行 `templates.map((t) => t.industry)` 是一次性函数无 shadow 问题，但为一致性也改 `tpl`。

**验收**：
```bash
cd client && npx tsc -b --noEmit 2>&1 | grep -c "error TS"
# 应该返回 0
```

**Commit msg**：
- `fix: [frontend] typecheck errors in holidays/usage/templates pages`

---

## A3 — overview.py 死代码 + SQL 合并（P0-3 + P1-5）

**根因**：
- 行 22-24 `_get_db()` 死代码（`async with` 退出后返回已关闭 session），删除。
- 行 49-209 `get_metrics` 一次请求 30+ 个串行 SQL（7 天 × 2 聚合 + today/week/month × 6 实体）。SQLite 本地无感，PostgreSQL 破 p95<1s 的 SM-4。

**合并策略**：
1. **Emails metric** 一次 SQL：按 `CASE WHEN sent_at >= today_start AND status IN (...) THEN 1 ELSE 0 END AS sent_today`，三窗口 × 2 (sent/replied) = 6 个 SUM 一起算。
2. **Influencers / ScrapeTasks** 一次 SQL 同理。
3. **7 天 email_trend** 用 `GROUP BY DATE(sent_at)` 一次查 7 天。SQLite 用 `strftime('%Y-%m-%d', sent_at)`。
4. **7 天 scrape_trend** 同理。
5. **platform_dist** 已经是 `GROUP BY`，保留。
6. **Users total/active** 两个查询合成一个 `SUM(CASE WHEN is_active THEN 1 ELSE 0 END)`。

目标：20+ round trips → **5 个查询**（emails / influencers / scrape / email_trend / scrape_trend）+ 2 个保留（users / platform_dist）= **7 个查询**。

关键点：SQLite 对 `>= today_start AND <= today_end` 的 between 可以是 `DATE(sent_at) = :today_str`；但为了兼容 PostgreSQL，用 `>= today_start AND < tomorrow_start`（half-open），不用 `<= today_end`（避免毫秒精度坑）。

**示例 emails 合并查询**：
```python
emails_query = select(
    func.sum(case(
        (and_(
            Email.status.in_(sent_statuses),
            Email.sent_at >= today_start,
            Email.sent_at < tomorrow_start,
        ), 1), else_=0
    )).label("sent_today"),
    func.sum(case(
        (and_(
            Email.status.in_(sent_statuses),
            Email.sent_at >= week_start,
        ), 1), else_=0
    )).label("sent_week"),
    func.sum(case(
        (and_(
            Email.status.in_(sent_statuses),
            Email.sent_at >= month_start,
        ), 1), else_=0
    )).label("sent_month"),
    func.sum(case(
        (and_(
            Email.status == EmailStatus.replied,
            Email.replied_at >= today_start,
            Email.replied_at < tomorrow_start,
        ), 1), else_=0
    )).label("replied_today"),
    func.sum(case(
        (and_(
            Email.status == EmailStatus.replied,
            Email.replied_at >= week_start,
        ), 1), else_=0
    )).label("replied_week"),
    func.sum(case(
        (and_(
            Email.status == EmailStatus.replied,
            Email.replied_at >= month_start,
        ), 1), else_=0
    )).label("replied_month"),
)
row = (await db.execute(emails_query)).one()
```

**7 天 trend 用 GROUP BY 日期**：
```python
from sqlalchemy import cast, Date
trend_start = today - timedelta(days=6)
trend_query = select(
    cast(Email.sent_at, Date).label("d"),
    func.sum(case((Email.status.in_(sent_statuses), 1), else_=0)).label("sent"),
    func.sum(case((Email.status == EmailStatus.replied, 1), else_=0)).label("replied"),
).where(
    Email.sent_at >= datetime.combine(trend_start, datetime.min.time())
).group_by(cast(Email.sent_at, Date))
# then fill missing days with zero in Python
```

**验收**：
- Response schema 与改前 100% 一致（用 curl + jq 对比改前改后 JSON key 树）
- 实测查询数 `SET echo` 看日志，SQL 数应 ≤ 10（原 30+）
- 死代码 `_get_db` 不再出现在文件中

**Commit msg**：`perf: [admin/overview] remove dead code and consolidate 30+ queries into 7`

---

## A4 — classifier.py 收敛到 llm_client.py

**根因**：
- `server/app/agents/classifier.py:90` 直接用 `ChatOpenAI` + LangGraph；
- D-16 locked decision：所有 LLM 调用必须走 `server/app/tools/llm_client.py`；
- 跳过后，admin `/api/admin/usage` 拿不到 classifier 的 token cost，成本监控失真。

**选项评估**：
- **选项 A（推荐）**：保留 LangGraph 状态机骨架，把 `ChatOpenAI(...).with_structured_output(...)` 换成 `llm_client.chat(...)` + 手工 JSON parse + Pydantic 校验。失去 structured_output 便利但换来 D-16 合规和 token 追踪。
- **选项 B**：给 `llm_client` 加 `structured_chat(schema, ...)` 方法，classifier 调新方法。更干净但改 llm_client API。

**走选项 A**，改动最小：

```python
# classifier.py — 删除 from langchain_openai import ChatOpenAI
# 在 classify_node 内改为：

async def classify_node(state: ClassifierState) -> dict:
    from app.tools.llm_client import chat as llm_chat
    try:
        settings = get_settings()
        raw = await llm_chat(
            model=settings.openai_classifier_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"reply_content:\n{state['reply_content'][:2000]}"},
            ],
            temperature=0,
            response_format={"type": "json_object"},
            agent_name="classifier",
        )
        import json
        data = json.loads(raw)
        result = ClassifyResult(**data)
        if result.intent not in _VALID_INTENTS:
            result.intent = "irrelevant"
        result.confidence = max(0.0, min(1.0, result.confidence))
        ...
```

**前置**：`llm_client.chat` 需要支持 `response_format` 透传。看当前代码可能已支持（kwargs 透传），Sonnet 需要确认。

**验收**：
- `grep -rn "langchain_openai\|ChatOpenAI" server/app/agents/` → 0 结果
- `grep -rn "from openai import\|AsyncOpenAI" server/app/agents/` → 0 结果（只能出现在 llm_client.py）
- classifier 集成测试（如可跑）返回 `ClassifyResult` 不抛异常

**Commit msg**：`refactor: [classifier] route LLM calls through unified llm_client per D-16`

---

## B1 — AGENTS.md 架构描述对齐实现

**根因**：AGENTS.md 行 28-50 画了"Supervisor (LangGraph)"框 + 5 Executor；实际 `supervisor.py` 只有 54 行 tracking wrapper，真正编排走 APScheduler + asyncio.create_task + IMAP 轮询。

**判断**：不补 Supervisor。tracking wrapper + APScheduler 是合理选择，装 LangGraph 只是 classifier 单个 agent 用到。**改文档对齐代码。**

**修改 AGENTS.md**：
- 行 16：`| Agent 编排 | LangGraph | Supervisor 模式，状态机驱动 |` → `| Agent 编排 | APScheduler + asyncio + tracking wrapper | 分布式 Agent 通过 agent_runs 表追踪，非集中式状态机 |`
- 行 28-50 整个 "Agent 架构" 图改为：

```
  ┌──────────────────────────────────────────────────────┐
  │  orchestration layer                                  │
  │  ─ APScheduler cron jobs (holiday, daily reset,       │
  │    monthly follow-up)                                 │
  │  ─ asyncio.create_task (Monitor Agent lifespan task)  │
  │  ─ supervisor.py: tracked wrappers (agent_runs 表)    │
  │  ─ Classifier: LangGraph StateGraph（单 agent 内部用） │
  └──────────────────────────────────────────────────────┘
             │       │        │        │        │
             ▼       ▼        ▼        ▼        ▼
          Scraper  Sender  Monitor  Responder  Classifier
          (一次)  (一次)  (长驻)   (触发)    (触发+LG)
```

- 行 54 "Agent 职责定义" 表里 Supervisor 行改为描述 "追踪封装层，非状态机"。

**验收**：AGENTS.md 里不再出现 "LangGraph Supervisor" 字样；"LangGraph" 仅出现在 classifier 描述里。

**Commit msg**：`docs: [agents] align architecture description with actual APScheduler-based orchestration`

---

## B2 — Alembic 替代 lifespan ALTER TABLE

**根因**：`main.py` 行 79-112 有 27 条 `ALTER TABLE / CREATE TABLE` + 总括 try/except。每次启动全跑一遍，SQLite 能忍，PostgreSQL 会满屏 "column already exists" 错误日志。

**方案**：
1. 安装 alembic：`requirements.txt` 加 `alembic==1.13.3`
2. `server/alembic.ini` + `server/alembic/env.py`（用 `app.database.Base.metadata`）
3. 为现存 schema 生成 **baseline** migration `0001_baseline.py`（完全匹配当前所有 model 的 Create Table）
4. 为 lifespan 里那 27 条 ALTER 改写成 **增量 migration**，按时间序列逻辑分 3-5 个 revision（audit_log / agent_runs / usage / feature_flag / security_alert）
5. `main.py` lifespan 改为：`alembic upgrade head` 通过子进程或 alembic programmatic API 跑
6. 删除 lifespan 里的 27 条 ALTER 代码块
7. 文档：`server/alembic/README.md` 写"新增字段流程：alembic revision --autogenerate -m ... && alembic upgrade head"

**风险**：
- SQLite 现有数据库有这些表/列，baseline 直接 `upgrade head` 会冲突。需要 `alembic stamp head` 标记"当前状态已是 head"，然后新增 model 时走 autogenerate。
- Sonnet 要在干净 SQLite 和已有数据库两种场景都通。

**验收**：
- `cd server && alembic upgrade head` 干净库成功
- `cd server && alembic stamp head && alembic check` 已有库成功
- `main.py` lifespan 不再含 27 条 ALTER
- `python -c "from app.main import app"` 无报错

**注意**：SQLite ALTER TABLE 有诸多限制（不支持 DROP COLUMN、不支持改约束）。baseline 以后新增列仍可用。降低 Alembic 使用门槛：提供一个 `scripts/migrate.sh` 包装命令。

**Commit msg**：`chore: [migrations] replace lifespan ALTER TABLE with Alembic migrations`

---

## C1 — 集成测试 4 条安全敏感路径

**目标路径**：
1. `POST /api/admin/security/rotate-keys` 密码正确 200 / 密码错误 403（A1 修复后才能真过）
2. `POST /api/admin/users/{id}/force-logout` 老 token 在此之后被拒 401
3. Audit middleware 对写操作 100% 写入 audit_log（用 TestClient POST 并检查 DB）
4. `GET /api/admin/overview/metrics` 返回的 schema 与规格一致（key 完整性）

**框架**：
- `pytest` + `pytest-asyncio` + `httpx.AsyncClient(app=app)` + 临时 SQLite 库（`server/tests/conftest.py` 给每个测试独立 DB）
- 先补好 `conftest.py`：fixture `async_client`, `admin_token`, `operator_token`

**文件新增**：
- `server/tests/conftest.py` (新)
- `server/tests/test_admin_security.py`
- `server/tests/test_admin_users.py`
- `server/tests/test_audit_middleware_integration.py`（扩展现有 test_audit_middleware.py）
- `server/tests/test_admin_overview.py`

**验收**：
```bash
cd server && python -m pytest tests/ -v
# 全部通过
```

**Commit msg**：`test: [admin] integration tests for security/users/audit/overview critical paths`

---

## C2 — ralph.py Audit Gate 加固

**根因**：Opus 纸面审 + Validator 浏览器点 = 漏掉 "代码写错字段名但 runtime 才炸" / "TS error 存在但开发过程没跑 tsc"。

**加固点**：在 `ralph.py` 写 `audit-gate.json(pending)` 之前，**自动跑 3 个强制检查**：
1. **tsc**: `cd client && npx tsc -b --noEmit` 必须 0 错误
2. **python import**: 跑 `cd server && python -c "from app.main import app"`
3. **可选 curl 探测**（若 story notes 里 JSON 标注 `sanity_endpoints: ["POST /api/admin/security/rotate-keys"]`，启动 test server 并 curl 确认 HTTP 码在允许集合）

不通过 → Audit Gate 自动 reject 并把错误写进 notes，Ralph 下一轮自己修。

**验收**：
- 故意在某 story 注入一个 TS 错误，Ralph 流程自动被 reject 而非跑到 Opus 面前
- `grep "tsc -b" scripts/ralph/ralph.py` 有结果

**Commit msg**：`feat: [ralph] enforce tsc + python import checks in audit gate`

---

## 回退策略

每批 commit 独立，出事直接 `git revert <sha>`。Alembic 那批改动较大，出事 revert + 恢复到 lifespan ALTER 方案。

---

## 执行顺序（Opus 调度）

```
Phase 0 DONE (6e856e1 chore commit)
  │
  ├─ Batch A 并行（4 agents）
  │   ├─ A1: security.py (sonnet, 2 min)
  │   ├─ A2: Frontend TS (sonnet, 10 min)
  │   ├─ A3: overview.py (sonnet, 15 min)
  │   └─ A4: classifier.py (sonnet, 10 min)
  │
  ├─ Batch B 并行（2 agents，与 A 并行）
  │   ├─ B1: AGENTS.md (sonnet, 5 min)
  │   └─ B2: Alembic (sonnet, 30 min)
  │
  │ Opus review 所有 A + B commit，跑 tsc + pytest 验证
  │
  └─ Batch C（依赖 A 全通）
      ├─ C1: 集成测试 (sonnet, 30 min)
      └─ C2: Audit Gate 加固 (sonnet, 15 min)

  │ Opus 最终 review + push
```

---

**PLAN END**
