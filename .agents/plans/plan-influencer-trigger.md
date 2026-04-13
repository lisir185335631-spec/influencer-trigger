# 深度技术规划：Influencer Trigger System

> 日期：2026-04-13
> 基于 PRD v1.0 + 知识库架构模式

---

## 1. 整体架构

### 1.1 四层架构

```
┌─────────────────────────────────────────────────────────────┐
│                     表现层 (Presentation)                     │
│  React 18 + TypeScript + TailwindCSS + WebSocket Client      │
│  9 页面：Dashboard / Scrape / Emails / CRM / Templates ...   │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API (JSON) + WebSocket
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                     应用层 (Application)                      │
│  FastAPI + LangGraph Supervisor + APScheduler                │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ API 路由  │ │ Services │ │ Agents   │ │ Scheduler│       │
│  │ (12 模块) │ │ (业务层) │ │ (6 个)   │ │ (定时)   │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────┐
│                     工具层 (Tools)                            │
│  Playwright │ SMTP Client │ IMAP Client │ OpenAI API         │
│  CSV Parser │ MX Validator│ Fernet Crypto│ Jinja2 Templates  │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────┼──────────────────────────────────┐
│                     数据层 (Data)                             │
│  SQLite/PostgreSQL (持久化) │ Redis (队列+缓存+锁)           │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 服务组件

| 组件 | 职责 | 端口 | 进程模型 |
|------|------|------|---------|
| FastAPI Server | API + WebSocket + Agent 编排 | 8000 | uvicorn (async) |
| IMAP Monitor | 24/7 邮件回复检测 | - | 后台 asyncio task |
| APScheduler | 月度追发 + 节假日触发 | - | 嵌入 FastAPI 进程 |
| Redis | 任务队列 + 分布式锁 | 6379 | 独立进程 |
| React Dev Server | 前端开发 | 3000 | vite dev (开发) |

**关键决策：IMAP Monitor 不独立部署，作为 FastAPI 的后台 asyncio task 运行**
- 理由：规模小（监控 ≤10 个邮箱），无需独立进程
- 实现：`asyncio.create_task()` 在 FastAPI startup 事件中启动
- 心跳：每 5 分钟轮询一次所有活跃邮箱的收件箱
- 断线重连：IMAP 连接异常时指数退避重试（5s → 10s → 30s → 60s）

---

## 2. Agent 编排设计

### 2.1 LangGraph 状态机

```python
class InfluencerState(TypedDict):
    # 任务控制
    task_type: str          # scrape / send / monitor / classify
    task_id: str
    
    # 抓取
    platform: str
    industry: str
    target_count: int
    scraped_results: list[dict]
    
    # 发送
    influencer_ids: list[str]
    template_id: str
    send_progress: dict     # {total, sent, failed}
    
    # 监控
    new_replies: list[dict]
    
    # 分类
    reply_content: str
    classification: dict    # {intent, confidence}
    
    # 全局
    errors: list[str]
    current_agent: str
```

### 2.2 Agent 路由逻辑

```
Supervisor 入口
  │
  ├─ task_type == "scrape"
  │   └→ Scraper Agent
  │       ├→ 启动 Playwright 浏览器实例
  │       ├→ 按平台并行抓取（最多 3 并发）
  │       ├→ 邮箱提取 + 反混淆 + MX 验证
  │       └→ 去重 → 写入 influencers 表
  │
  ├─ task_type == "send"
  │   └→ Sender Agent
  │       ├→ 加载网红列表 + 模板
  │       ├→ 选择可用邮箱（轮换策略）
  │       ├→ 渲染模板变量 → SMTP 发送
  │       ├→ 写入 emails 表 (status=sent)
  │       └→ WebSocket 推送进度
  │
  ├─ task_type == "classify"
  │   └→ Classifier Agent
  │       ├→ 收到回复内容
  │       ├→ GPT-4o-mini 意图分类（5 类）
  │       ├→ 更新 influencer.reply_intent
  │       └→ 触发通知（非 auto_reply 时）
  │
  └─ task_type == "follow_up"
      └→ Responder Agent
          ├→ 查询未回复 + 满足追发条件的网红
          ├→ GPT-4o 生成差异化追发内容
          ├→ 调用 Sender Agent 发送
          └→ 更新追发计数
```

### 2.3 Agent 不做的事

| 不做 | 原因 | 替代方案 |
|------|------|---------|
| Scraper 不做邮件发送 | 职责分离 | 抓取完毕后由 Supervisor 调度 Sender |
| Classifier 不做自动回复 | 用户要求回复即转人工 | 仅分类 + 通知 |
| Monitor 不用 LLM | 纯状态检测不需要 AI | IMAP 轮询 + 正则匹配 |

---

## 3. 核心技术方案

### 3.1 网红邮箱抓取（Scraper Agent）

**技术选型：Playwright（Python async）**

```
抓取流程（单平台）：
1. 启动 Playwright Chromium（headless，stealth 模式）
2. 导航到平台搜索页 → 输入行业关键词
3. 滚动加载网红列表 → 提取主页链接
4. 逐一访问网红主页 → 提取 bio/about/contact 中的邮箱
5. 反混淆处理 → MX 验证 → 写入数据库
```

**各平台邮箱位置**：

| 平台 | 邮箱位置 | 抓取难度 |
|------|---------|---------|
| Instagram | bio 区域 / "Contact" 按钮 | 中（需登录态才能看部分 bio） |
| YouTube | About 页 → "View email address" | 低（公开可见） |
| TikTok | bio 区域 | 低 |
| Twitter(X) | bio / pinned tweet | 低 |
| Facebook | Page → About → Contact | 中（部分需登录） |

**反检测措施**：
- `playwright-stealth` 插件：伪装浏览器指纹
- 随机化操作间隔：每次页面操作间隔 2-5 秒随机
- User-Agent 轮换
- 代理 IP 池（可选，MVP 阶段不强制）
- 单平台并发限制：同时最多 1 个浏览器实例

**邮箱提取正则**：
```python
EMAIL_PATTERNS = [
    r'[\w.+-]+@[\w-]+\.[\w.]+',           # 标准格式
    r'[\w.+-]\s*\[at\]\s*[\w-]+\s*\[dot\]\s*[\w.]+',  # 反混淆
    r'[\w.+-]\s*\(at\)\s*[\w-]+\s*\(dot\)\s*[\w.]+',  # 另一种反混淆
]
```

### 3.2 邮件发送引擎（Sender Agent）

**多邮箱轮换策略**：

```python
class MailboxRotator:
    """均匀分配 + 自动跳过已满邮箱"""
    
    async def get_next_mailbox(self) -> Mailbox:
        # 1. 查询所有 status=active 且 today_sent < daily_limit 的邮箱
        # 2. 按 today_sent 升序排列（用得最少的优先）
        # 3. 返回第一个
        # 4. 如果没有可用邮箱，raise NoAvailableMailboxError
```

**发送节流**：
- 每封邮件间隔：30-60 秒随机（`random.uniform(30, 60)`）
- 单邮箱每小时上限：默认 20 封（防触发 ESP 限流）
- 单邮箱每日上限：默认 50 封（用户可配置）
- 每日 0:00 UTC 重置 `today_sent` 计数

**SMTP 发送流程**：
```
1. 从 MailboxRotator 获取可用邮箱
2. 解密 SMTP 密码（Fernet）
3. 建立 SMTP 连接（aiosmtplib，TLS）
4. 渲染 Jinja2 模板 → 生成 MIME 邮件
5. 发送 → 记录 message_id
6. 写入 emails 表 (status=sent, mailbox_id=...)
7. 更新 mailbox.today_sent += 1
8. WebSocket 推送发送进度
9. asyncio.sleep(random.uniform(30, 60))
```

### 3.3 邮件监控（Monitor — 后台 asyncio task）

**IMAP 轮询架构**：

```python
async def imap_monitor_loop():
    """FastAPI startup 事件启动，24/7 运行"""
    while True:
        try:
            mailboxes = await get_active_mailboxes()
            for mb in mailboxes:
                new_replies = await check_inbox(mb)
                for reply in new_replies:
                    # 匹配 In-Reply-To / References 关联原始邮件
                    original = await match_original_email(reply)
                    if original:
                        await update_email_status(original, "replied", reply)
                        await trigger_classification(original, reply)
                        await notify_via_websocket(original, reply)
            await asyncio.sleep(300)  # 5 分钟轮询
        except Exception as e:
            logger.error(f"IMAP monitor error: {e}")
            await asyncio.sleep(60)  # 异常后 1 分钟重试
```

**回复匹配逻辑**：
1. 优先匹配 `In-Reply-To` header → 与 `emails.message_id` 关联
2. 回退：匹配发件人邮箱 → 与 `influencers.email` 关联
3. 再回退：匹配邮件主题（去掉 Re:/Fwd: 前缀后模糊匹配）

**退信检测**：
- 解析 `Content-Type: multipart/report` 类型的退信通知
- 提取 DSN (Delivery Status Notification) 中的状态码
- 5.x.x 永久失败 → 标记退信 + 更新 mailbox.bounce_rate

### 3.4 意图分类（Classifier Agent）

**Prompt 设计**：
```
You are an email reply classifier for influencer outreach campaigns.
Classify the following email reply into ONE of these categories:

1. interested - Wants to know more, asks about collaboration details
2. pricing - Directly asks about pricing, commission, or compensation
3. declined - Politely refuses or says not interested
4. auto_reply - Out of office, automatic reply, vacation notice
5. irrelevant - Spam, unrelated content, wrong person

Reply with JSON: {"intent": "...", "confidence": 0.0-1.0, "summary": "..."}
```

**模型选择**：GPT-4o-mini（足够准确，成本低，~$0.001/次分类）

### 3.5 自动追发引擎（Responder Agent + APScheduler）

**调度策略**：

```python
# APScheduler 定时任务配置
scheduler.add_job(
    monthly_follow_up_check,
    trigger=CronTrigger(hour=10, minute=0),  # 每天 10:00 UTC 检查
    id="monthly_follow_up"
)

scheduler.add_job(
    holiday_greeting_check,
    trigger=CronTrigger(hour=8, minute=0),   # 每天 8:00 UTC 检查
    id="holiday_greeting"
)
```

**月度追发逻辑**：
```
每日 10:00 UTC 执行：
1. 查询 influencers WHERE status='contacted' 
   AND last_email_sent_at < now() - 30 days
   AND follow_up_count < max_follow_up (默认 6)
   AND this_month_sent = false
2. 对每个网红：
   a. GPT-4o 生成差异化追发内容（不同角度/价值主张）
   b. 调用 Sender Agent 发送
   c. follow_up_count += 1
   d. 如果 follow_up_count >= max → status='archived'
```

**节假日祝福逻辑**：
```
每日 8:00 UTC 执行：
1. 查询 holidays 表 WHERE date = today
2. 如果今天是节假日：
   a. 查询所有 status != 'archived' 的网红
   b. 排除本月已收到追发/祝福的网红
   c. GPT-4o 生成节日祝福（结合行业）
   d. 批量发送（不计入 follow_up_count）
```

### 3.6 CSV/Excel 导入

**技术方案**：
- CSV：Python `csv` 模块
- Excel：`openpyxl` 库
- 列名映射：预定义中英文映射表 + fuzzy match

```python
COLUMN_MAPPING = {
    "email": ["email", "邮箱", "e-mail", "email address"],
    "nickname": ["nickname", "昵称", "name", "username", "账号名"],
    "platform": ["platform", "平台", "social media"],
    "followers": ["followers", "粉丝数", "粉丝", "subscriber"],
    "profile_url": ["profile_url", "主页链接", "url", "link", "profile"],
    "industry": ["industry", "行业", "category", "niche"],
}
```

---

## 4. 数据库设计

### 4.1 完整 Schema

```sql
-- 网红档案
CREATE TABLE influencers (
    id TEXT PRIMARY KEY,           -- UUID
    nickname VARCHAR(200),
    platform VARCHAR(20) NOT NULL, -- tiktok/instagram/youtube/twitter/facebook
    email VARCHAR(200) NOT NULL,
    profile_url TEXT,
    followers INTEGER DEFAULT 0,
    bio TEXT,
    region VARCHAR(100),
    industry VARCHAR(100),
    status VARCHAR(20) DEFAULT 'scraped',  -- scraped/contacted/replied/cooperating/archived
    reply_intent VARCHAR(20),      -- interested/pricing/declined/auto_reply/irrelevant
    priority VARCHAR(10),          -- high/medium/low
    follow_up_count INTEGER DEFAULT 0,
    last_email_sent_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(email)
);

-- 邮件记录
CREATE TABLE emails (
    id TEXT PRIMARY KEY,
    influencer_id TEXT NOT NULL REFERENCES influencers(id),
    campaign_id TEXT REFERENCES campaigns(id),
    mailbox_id TEXT REFERENCES mailboxes(id),
    type VARCHAR(20) NOT NULL,     -- outreach/follow_up/holiday
    subject TEXT,
    body TEXT,
    message_id VARCHAR(200),       -- SMTP Message-ID header
    status VARCHAR(20) DEFAULT 'pending',  -- pending/sent/delivered/opened/replied/bounced
    sent_at TIMESTAMP,
    replied_at TIMESTAMP,
    reply_content TEXT,
    reply_subject TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 发送邮箱
CREATE TABLE mailboxes (
    id TEXT PRIMARY KEY,
    email VARCHAR(200) NOT NULL UNIQUE,
    display_name VARCHAR(200),
    smtp_host VARCHAR(200) NOT NULL,
    smtp_port INTEGER DEFAULT 587,
    imap_host VARCHAR(200),
    imap_port INTEGER DEFAULT 993,
    password_encrypted TEXT NOT NULL,  -- Fernet 加密
    daily_limit INTEGER DEFAULT 50,
    hourly_limit INTEGER DEFAULT 20,
    today_sent INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active', -- active/limited/error/disabled
    bounce_rate FLOAT DEFAULT 0.0,
    last_reset_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 发送批次
CREATE TABLE campaigns (
    id TEXT PRIMARY KEY,
    name VARCHAR(200),
    industry VARCHAR(100),
    template_id TEXT REFERENCES templates(id),
    total_count INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    replied_count INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'draft', -- draft/sending/completed/paused
    created_by TEXT REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- 邮件模板
CREATE TABLE templates (
    id TEXT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    industry VARCHAR(100),
    style VARCHAR(20),             -- formal/casual/direct
    subject TEXT NOT NULL,
    body TEXT NOT NULL,             -- HTML，含 Jinja2 变量
    is_system BOOLEAN DEFAULT FALSE,
    created_by TEXT REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 标签
CREATE TABLE tags (
    id TEXT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    color VARCHAR(7) DEFAULT '#6B7280',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 网红-标签关联
CREATE TABLE influencer_tags (
    influencer_id TEXT REFERENCES influencers(id) ON DELETE CASCADE,
    tag_id TEXT REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (influencer_id, tag_id)
);

-- 备注
CREATE TABLE notes (
    id TEXT PRIMARY KEY,
    influencer_id TEXT NOT NULL REFERENCES influencers(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_by TEXT REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 合作历史
CREATE TABLE collaborations (
    id TEXT PRIMARY KEY,
    influencer_id TEXT NOT NULL REFERENCES influencers(id),
    title VARCHAR(200),
    description TEXT,
    amount DECIMAL(10,2),
    currency VARCHAR(3) DEFAULT 'USD',
    status VARCHAR(20) DEFAULT 'pending', -- pending/active/completed/cancelled
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 节假日日历
CREATE TABLE holidays (
    id TEXT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    date DATE NOT NULL,
    template_hint TEXT,            -- 节日关键词，LLM 生成祝福时参考
    is_system BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 抓取任务
CREATE TABLE scrape_tasks (
    id TEXT PRIMARY KEY,
    platforms TEXT NOT NULL,        -- JSON array: ["tiktok","instagram"]
    industry VARCHAR(100) NOT NULL,
    target_count INTEGER DEFAULT 100,
    scraped_count INTEGER DEFAULT 0,
    valid_count INTEGER DEFAULT 0,  -- 有效邮箱数
    status VARCHAR(20) DEFAULT 'pending', -- pending/running/completed/failed
    error_message TEXT,
    created_by TEXT REFERENCES users(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

-- 团队成员
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name VARCHAR(200),
    role VARCHAR(20) DEFAULT 'operator', -- admin/manager/operator
    email VARCHAR(200),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 邮件状态事件（审计日志）
CREATE TABLE email_events (
    id TEXT PRIMARY KEY,
    email_id TEXT NOT NULL REFERENCES emails(id),
    event_type VARCHAR(20) NOT NULL, -- sent/delivered/opened/replied/bounced
    event_data TEXT,                  -- JSON，存储额外信息
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 通知记录
CREATE TABLE notifications (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id),
    type VARCHAR(20) NOT NULL,     -- reply/bounce/system
    title TEXT NOT NULL,
    content TEXT,
    influencer_id TEXT REFERENCES influencers(id),
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.2 关键索引

```sql
-- 高频查询索引
CREATE INDEX idx_influencers_email ON influencers(email);
CREATE INDEX idx_influencers_status ON influencers(status);
CREATE INDEX idx_influencers_platform_industry ON influencers(platform, industry);
CREATE INDEX idx_influencers_reply_intent ON influencers(reply_intent) WHERE reply_intent IS NOT NULL;

CREATE INDEX idx_emails_influencer_status ON emails(influencer_id, status);
CREATE INDEX idx_emails_status_sent ON emails(status, sent_at DESC);
CREATE INDEX idx_emails_message_id ON emails(message_id) WHERE message_id IS NOT NULL;
CREATE INDEX idx_emails_campaign ON emails(campaign_id);

CREATE INDEX idx_mailboxes_status ON mailboxes(status) WHERE status = 'active';

CREATE INDEX idx_holidays_date ON holidays(date);
CREATE INDEX idx_notifications_user_read ON notifications(user_id, is_read);
CREATE INDEX idx_email_events_email ON email_events(email_id, created_at DESC);
```

---

## 5. API 设计

### 5.1 路由模块

| 路由前缀 | 模块 | 核心端点 |
|----------|------|---------|
| `/api/auth` | 认证 | POST /login, POST /register |
| `/api/scrape` | 抓取 | POST /tasks, GET /tasks, GET /tasks/{id} |
| `/api/influencers` | CRM | GET /, GET /{id}, PATCH /{id}, POST /import, POST /export |
| `/api/emails` | 邮件 | GET /, POST /send-batch, GET /stats |
| `/api/campaigns` | 批次 | GET /, POST /, GET /{id}, PATCH /{id} |
| `/api/templates` | 模板 | GET /, POST /, PUT /{id}, DELETE /{id}, POST /generate |
| `/api/mailboxes` | 邮箱 | GET /, POST /, PUT /{id}, DELETE /{id}, POST /{id}/test |
| `/api/tags` | 标签 | GET /, POST /, DELETE /{id} |
| `/api/holidays` | 节假日 | GET /, POST /, PUT /{id}, DELETE /{id} |
| `/api/notifications` | 通知 | GET /, PATCH /{id}/read, POST /read-all |
| `/api/dashboard` | 仪表盘 | GET /stats, GET /trends, GET /mailbox-health |
| `/api/users` | 团队 | GET /, POST /, PUT /{id}, DELETE /{id} |
| `/api/settings` | 设置 | GET /, PUT / |
| `/ws` | WebSocket | 实时推送 |

### 5.2 WebSocket 事件

```typescript
// 前端监听的事件类型
type WSEvent = 
  | { type: "scrape_progress", data: { task_id, scraped, total } }
  | { type: "send_progress", data: { campaign_id, sent, total, failed } }
  | { type: "email_status_change", data: { email_id, influencer_name, old_status, new_status } }
  | { type: "new_reply", data: { influencer_id, name, platform, intent, summary } }
  | { type: "notification", data: { id, type, title, content } }
```

---

## 6. 安全设计

| 安全项 | 方案 |
|--------|------|
| SMTP 密码存储 | Fernet 对称加密，密钥从环境变量加载 |
| 用户密码 | bcrypt 哈希（不可逆） |
| API 认证 | JWT（access token 30min + refresh token 7d） |
| HTTPS | Nginx 反向代理 + Let's Encrypt |
| CSRF | SameSite Cookie + CORS 白名单 |
| 输入校验 | Pydantic v2 全字段校验 |
| 邮箱密码传输 | 仅 HTTPS，前端不缓存 |
| 日志脱敏 | 邮箱密码、token 等敏感字段不写入日志 |

---

## 7. 部署方案

### 7.1 原生进程部署（不使用 Docker）

**进程管理**：PM2（Node 生态，跨平台）或 systemd（Linux 原生）

```bash
# PM2 部署方案
pm2 start server/run.py --name influencer-api --interpreter python3
pm2 start "redis-server" --name influencer-redis
pm2 start "nginx" --name influencer-nginx
pm2 save && pm2 startup
```

**Nginx 反向代理**：直接安装 nginx，配置反向代理 + 静态文件托管

```nginx
server {
    listen 80;
    location /api/ { proxy_pass http://127.0.0.1:8000; }
    location /ws   { proxy_pass http://127.0.0.1:8000; proxy_http_version 1.1; proxy_set_header Upgrade $http_upgrade; proxy_set_header Connection "upgrade"; }
    location /     { root /path/to/client/dist; try_files $uri /index.html; }
}
```

**Windows 开发环境**：直接用 `start.bat` 脚本启动各进程

### 7.2 环境变量

```env
# Database
DATABASE_URL=sqlite+aiosqlite:///./data/influencer.db
# DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/influencer

# Redis
REDIS_URL=redis://localhost:6379/0

# Encryption
FERNET_KEY=your-fernet-key-here

# LLM
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1

# JWT
JWT_SECRET=your-jwt-secret
JWT_EXPIRE_MINUTES=30

# App
APP_ENV=production
LOG_LEVEL=INFO
```

---

## 8. 实现优先级与依赖

```
Phase 1 (MVP 核心) — 13 个 User Stories
═══════════════════════════════════════
  Wave 1: 基础设施 (无外部依赖)
    ├─ 项目脚手架（FastAPI + React + DB）
    ├─ 用户认证（JWT）
    └─ 数据库 Schema + Migration
    
  Wave 2: 邮箱管理 + 模板 (依赖 Wave 1)
    ├─ US-2.1 发送邮箱 CRUD + SMTP 测试
    └─ US-2.2 邮件模板 CRUD + LLM 生成
    
  Wave 3: 抓取引擎 (依赖 Wave 1)
    ├─ US-1.1 创建抓取任务
    ├─ US-1.2 网红信息提取 (Playwright)
    ├─ US-1.3 抓取结果预览
    └��� US-1.4 CSV/Excel 导入
    
  Wave 4: 发送引擎 (依赖 Wave 2 + Wave 3)
    └─ US-2.3 批量发送 + 多邮箱轮换
    
  Wave 5: 监控 + 分流 (依赖 Wave 4)
    ├─ US-3.1 IMAP 监控 (24/7)
    ├─ US-3.2 邮件状态看板
    ├─ US-4.1 回复意图分类
    └─ US-4.2 人工介入通知

Phase 2 (增强功能) — 8 个 User Stories
═══════════════════════════════════════
  Wave 6: CRM (依赖 Wave 1)
    ├─ US-6.1 网红档案
    ├─ US-6.2 网红列表与筛选
    └─ US-6.3 回复网红筛选
    
  Wave 7: 追发 + 仪表盘 (依赖 Wave 4 + Wave 5)
    ├─ US-5.1 月度自动追发
    ├─ US-5.2 节假日祝福
    └─ US-7.1 数据仪表盘

Phase 3 (完善) — 后续
═══════════════════════
  Wave 8: 系统管理
    ├─ US-8.1 邮箱健康度监控
    ├─ US-8.2 团队管理
    └─ US-8.3 系统设置
```
