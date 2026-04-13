# Influencer Trigger System

国外社交媒体平台网红自动触发系统。

## 项目定位
从 TikTok/Instagram/YouTube/Twitter/Facebook 抓取网红邮箱，全量发送合作邮件，实时监控邮件状态，智能跟进，人工介入。

## 架构锚点
- 完整架构定义见 AGENTS.md
- Agent 编排：LangGraph Supervisor + 5 Executor
- 后端：FastAPI + SQLAlchemy async + SQLite/PostgreSQL
- 前端：React 18 + TypeScript + TailwindCSS
- 邮件：SendGrid/Mailgun API（发送）+ IMAP（监控）
- 浏览器自动化：Playwright（邮箱抓取）
- 实时推送：WebSocket

## 开发规范
- 不复用 DianShang 代码，独立设计
- 所有 Agent 在 server/app/agents/ 下，一个文件一个 Agent
- 配置走环境变量，禁止硬编码密钥
- 异步优先，async/await 全链路
- 前端 UI 克制高级，纯白背景 #ffffff，反 AI 模板风格

## Coding 3.0 模型分配

| 步骤 | 处理方式 | 说明 |
|---|---|---|
| `/prime` 项目上下文 | Opus 主对话 | 判断项目现状，识别关键架构 |
| `/create-rules` AGENTS.md | Opus 主对话 | 提取架构模式、做技术判断 |
| `prd` PRD 生成 | Opus 主对话 | 自动选择 Questions/Assumptions 模式 |
| `/plan-feature` 深度规划 | Opus 主对话 | 高判断密度，方案选型、风险评估 |
| `ralph` 转 prd.json | Opus 主对话 | story 拆分 + depends_on 依赖分析 |
| `/plan-check` 质量门禁 | Opus 主对话 | 验证 prd.json 结构和语义 |
| Ralph v2 执行循环 | Sonnet（ralph.py 自动） | 崩溃恢复 + 上下文注入 + 成本追踪 |
| Validator 验证 | Sonnet（ralph.py 自动） | 显式接收 story ID + criteria |
| **Audit Gate 审计门禁** | **ralph.py 自动等待** | **Validator 通过后写 audit-gate.json(pending)，Ralph 轮询等待 Opus 审查** |
| Step 5.5 Opus 质量审查 | Opus 主对话 | 检测 audit-gate.json(pending) → 4 维度审查 → approve/reject |
| `/goal-verify` 最终验证 | Opus 主对话 | 对比 PRD 与实际实现 |

### Audit Gate 操作命令

```bash
python scripts/ralph/ralph-tools.py approve          # Opus 审查通过，Ralph 继续
python scripts/ralph/ralph-tools.py reject "反馈"    # Opus 驳回，Ralph 重做
python scripts/ralph/ralph-tools.py audit-status     # 查看当前门禁状态
```

## 知识库参考
写技术文档或做架构决策前，先检索 `../knowledge-base/`。
