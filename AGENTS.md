# AGENTS.md — Influencer Trigger System

> 国外社交媒体平台网红自动触发系统
> 自动抓取网红邮箱 → 批量发送邮件 → 实时监控状态 → 智能跟进 → 人工介入

---

## 项目概述

从 TikTok / Instagram / YouTube / Twitter / Facebook 五大平台抓取网红公开邮箱，全量发送合作邮件，实时追踪邮件生命周期，根据回复状态智能分流：有回复自动跟进后转人工，无回复持续监控并自动追发。

## 技术栈

| 层级 | 技术选型 | 说明 |
|------|---------|------|
| 后端框架 | FastAPI | 异步高性能，WebSocket 原生支持 |
| Agent 编排 | APScheduler + asyncio + agent_runs 表 | 分布式调度（cron/lifespan/endpoint 触发），supervisor.py 做统一 tracking 封装；Classifier Agent 内部单独使用 LangGraph StateGraph |
| ORM | SQLAlchemy 2.0 async | 异步数据库操作 |
| 数据库 | SQLite（开发）→ PostgreSQL（生产） | 轻量启动，平滑迁移 |
| 缓存/队列 | Redis | 邮件发送队列 + 状态事件流 |
| 浏览器自动化 | Playwright | 网红主页邮箱抓取 |
| 邮件发送 | SendGrid / Mailgun API | 批量发送 + Webhook 状态回调 |
| 邮件监控 | IMAP 轮询 + SendGrid Webhooks | 双通道状态追踪 |
| LLM | OpenAI GPT-4o（分析）+ GPT-4o-mini（分类） | 大小模型分层 |
| 前端 | React 18 + TypeScript + TailwindCSS | 实时仪表盘 |
| 实时通信 | WebSocket | 邮件状态实时推送到前端 |

## Agent 架构（分布式调度 + 统一 tracking）

```
  ┌───────────────────────────────────────────────────────────┐
  │  编排层（orchestration）                                   │
  │                                                            │
  │   APScheduler cron jobs             asyncio lifespan task  │
  │   ├─ daily reset_today_sent         └─ Monitor Agent 长驻 │
  │   ├─ monthly follow_up_check                               │
  │   └─ daily holiday_greeting_check                          │
  │                                                            │
  │   HTTP 端点触发（FastAPI /api/scrape 等）                   │
  │                                                            │
  │   supervisor.py：tracking 包装层                            │
  │   所有 Agent 入口经 track_agent_run() 统一写 agent_runs 表 │
  └───────────────────────────────────────────────────────────┘
             │        │         │          │           │
             ▼        ▼         ▼          ▼           ▼
        ┌────────┬────────┬────────┬───────────┬───────────────┐
        │Scraper │Sender  │Monitor │ Responder │ Classifier    │
        │(触发)  │(触发)  │(长驻)  │  (触发)   │ (触发+LangGraph│
        │        │        │        │           │   StateGraph) │
        └────────┴────────┴────────┴───────────┴───────────────┘
```

### Agent 职责定义

| Agent | 职责 | 输入 | 输出 | 触发条件 |
|-------|------|------|------|---------|
| **Supervisor** | 统一 tracking 封装层（非集中编排器） | Agent 函数调用 | 包装后的 Agent 调用 + agent_runs 写入 | 所有 Agent 入口 |
| **Scraper Agent** | 从 5 大平台抓取网红主页公开邮箱 | 平台 + 关键词/分类 | `{influencer_name, platform, email, profile_url, followers, bio}` | 用户发起抓取任务 |
| **Sender Agent** | 批量发送合作邮件，控制发送速率 | 网红列表 + 邮件模板 | `{email_id, sent_at, status}` | 抓取完成后 |
| **Monitor Agent** | 实时监控邮件状态（送达/打开/回复/退信） | 邮件 ID 列表 | 状态变更事件 | 持续运行（轮询 + Webhook） |
| **Responder Agent** | 分析回复内容，生成自动跟进邮件 | 回复邮件内容 | 跟进邮件草稿 | Monitor 检测到回复 |
| **Classifier Agent** | 对回复邮件进行意图分类和网红质量评估 | 回复内容 + 网红画像 | `{intent, interest_score, priority}` | 收到回复时 |

> **注**：Supervisor 不是集中式编排器，只是 tracking wrapper。实际的跨 Agent 流程由 APScheduler cron、asyncio lifespan task、FastAPI endpoint 直接触发驱动。这是有意的设计选择：业务流程里 Agent 之间无需共享 StateGraph，独立触发更简单。

### 邮件状态机

```
[已抓取] → [待发送] → [已发送] → [已送达] → [已打开] → [已回复] → [自动跟进中] → [人工介入]
                                    │           │           │
                                    ▼           ▼           ▼
                                 [退信]     [未回复]    [拒绝/无意向]
                                             │
                                             ▼
                                    [自动追发1] → [自动追发2] → [自动追发3] → [归档]
```

## 核心业务流程

### 阶段 1：邮箱抓取
- Playwright 无头浏览器访问网红主页
- 解析 bio / about / contact 区域提取邮箱
- 正则 + 反混淆处理（`[at]` → `@`，图片 OCR 等）
- 邮箱 MX 记录验证，过滤无效地址
- 去重（同一网红跨平台只保留一条）

### 阶段 2：批量发送
- 全量发送，不做前置筛选
- SendGrid/Mailgun API 批量投递
- 速率控制：避免触发 ESP 限流（每小时上限可配置）
- 邮件模板变量替换（网红名、平台、粉丝数等）
- 发送日志写入数据库

### 阶段 3：实时监控
- **主动通道**：IMAP 轮询收件箱（指数退避：60s → 5min）
- **被动通道**：SendGrid/Mailgun Webhook 回调（送达/打开/点击/退信）
- 状态变更实时写入数据库 + WebSocket 推送前端
- 异常处理：退信自动标记、软退信重试

### 阶段 4：智能分流
- **有回复路径**：
  1. Classifier Agent 分析回复意图（感兴趣/拒绝/询价/犹豫/无关）
  2. Responder Agent 根据意图生成跟进邮件
  3. 自动发送跟进邮件（最多 N 轮自动跟进）
  4. 标记为"人工介入"，推送通知给运营人员
- **无回复路径**：
  1. 按时间策略自动追发（第3天/第7天/第14天）
  2. 每轮追发内容差异化（不同角度、不同价值主张）
  3. 超过最大追发次数 → 归档

### 阶段 5：回复网红筛选
- 对已回复网红按维度评分：合作意向、粉丝量级、互动率、内容匹配度
- 生成优先级排序列表，辅助人工决策

## 目录结构规范

```
influencer-trigger/
├── AGENTS.md                    # 本文件
├── CLAUDE.md                    # 项目级 Claude 指令
├── tasks/                       # PRD 文档
├── scripts/ralph/               # Ralph 执行引擎
├── server/                      # FastAPI 后端
│   ├── app/
│   │   ├── main.py              # 应用入口
│   │   ├── config.py            # 配置管理
│   │   ├── agents/              # Agent 实现
│   │   │   ├── supervisor.py    # Supervisor 编排
│   │   │   ├── scraper.py       # 邮箱抓取 Agent
│   │   │   ├── sender.py        # 邮件发送 Agent
│   │   │   ├── monitor.py       # 状态监控 Agent
│   │   │   ├── responder.py     # 自动跟进 Agent
│   │   │   └── classifier.py    # 意图分类 Agent
│   │   ├── models/              # SQLAlchemy ORM 模型
│   │   ├── api/                 # API 路由
│   │   ├── services/            # 业务逻辑层
│   │   ├── tools/               # 外部工具集成
│   │   │   ├── email_client.py  # SendGrid/Mailgun 封装
│   │   │   ├── imap_client.py   # IMAP 监控客户端
│   │   │   └── browser.py       # Playwright 浏览器工具
│   │   ├── schemas/             # Pydantic 数据校验
│   │   └── websocket/           # WebSocket 管理
│   ├── requirements.txt
│   └── .env.example
├── client/                      # React 前端
│   ├── src/
│   │   ├── pages/               # 页面组件
│   │   ├── components/          # 通用组件
│   │   ├── api/                 # API 客户端
│   │   ├── hooks/               # 自定义 Hooks
│   │   └── stores/              # 状态管理
│   └── package.json
└── docs/                        # 补充文档
```

## 编码规范

### Python（后端）
- Python 3.11+，全量 type hints
- async/await 异步优先
- Pydantic v2 做数据校验
- Agent 之间独立触发，不共享 StateGraph；跨 Agent 协调通过 APScheduler/asyncio/FastAPI 驱动，统一经 supervisor.py tracking wrapper 调用
- 每个 Agent 单独文件，职责单一
- 日志用 structlog，JSON 格式

### TypeScript（前端）
- React 18 + TypeScript strict mode
- TailwindCSS utility-first
- WebSocket 连接状态自动重连
- 表格组件支持虚拟滚动（网红列表可能很长）

### 通用
- 所有配置走环境变量，禁止硬编码
- API 密钥、邮箱密码等敏感信息只存 .env，.gitignore 必须包含
- 提交信息用英文，格式 `type(scope): description`
