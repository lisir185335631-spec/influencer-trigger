# influencer-trigger Scraper 现状与方案（2026-04-18 快照）

## 项目位置
- 代码：`C:\Users\Administrator\Desktop\Ai_Agent\influencer-trigger`
- 远程：https://github.com/lisir185335631-spec/influencer-trigger
- 分支：main
- 最新 commit（截至本文）：`2972cd9`

## 业务背景
PremLogin 商务开发 BD Agent。Playwright + LLM 混合架构，从 YouTube/Instagram 抓 KOL 公开联系邮箱 → 批量发合作邮件 → Monitor 监控回复。当前 scraper 主要调通 YouTube，Instagram 代码在但未单独验证命中率。

## 当前 scraper 架构（YouTube 为例）

```
POST /api/scrape/tasks
  ↓
BackgroundTasks → run_scraper_agent(task_id)
  ↓
Phase 1 (0%)   启动
Phase 2 (5%)   LLM 生成搜索 queries（llm_client + PremLogin business.md）
Phase 3 (15-79%) Playwright 循环：
  每条 query 搜索 → regex 抓 canonicalBaseUrl → /@handle 列表
  每个 channel → /about 页
    - og:description / og:image / "X subscribers" 抓 bio/avatar/followers
    - view_email_btn locator（登录才显示）
    - _extract_emails 正则 + MX 验证
  【Fallback】about 0 邮箱 → 访问 channel 首个视频 /watch → Show more → 再 extract
  命中 → INSERT influencers + scrape_task_influencers
Phase 4 (85%)  LLM enrich：relevance_score + match_reason
Phase 5 (100%) completed
```

## 命中率实测（2026-04-18）

| 关键词类型 | 命中率 | 代表 | 抓到的 |
|---|---|---|---|
| 商业化教程频道 | ~35% | `Canva`, `AI tools` | edureka! / Apna College / Think School / Howfinity / Cutting Edge School |
| 生产力个人号 | ~15% | `Notion productivity` | Fayefilms / urmomsushi（前 6 channel 抓 3 个） |
| 纯娱乐/游戏 | <10% | Vlog / gaming | 未测但推断 |

**核心规律**：商业化频道在公开 bio 写 BD 邮箱；个人博主普遍把邮箱藏在 YouTube 的"View email address"登录按钮后面（未登录不显示）。

**给 PremLogin BD 用的高命中率关键词建议**：
- `Canva Pro tutorial` / `Canva review` ★
- `ChatGPT Plus review` / `ChatGPT tips` ★
- `Netflix Premium` / `Netflix subscription deals` ★
- `NordVPN review` / `ExpressVPN compare`
- `AI productivity tools` / `AI software stack`

**低命中率关键词（不推荐）**：
- `Notion productivity` / `Roam` / `Obsidian`（个人知识博主隐私强）
- 任何 vlog / daily life 频道

## 已实现的改进（时间线）

### 2026-04-18 早段
- `938c02b` 每个 channel 抓 bio + followers（从 og:description / 正文 regex）
- `c7f380d` Instagram 也抓 bio/followers/avatar；playwright-stealth；延迟 5-15s；concurrency 1
- `9da61d5` `scripts/backfill_influencer_metadata.py` 回填老数据

### 2026-04-18 晚段
- `e60fe05` **关键修复**：YouTube selector 问题。原因是 YouTube SPA，channel 链接在 `ytInitialData` JS 变量里不在 DOM。改 regex 从 HTML 抓 `"canonicalBaseUrl":"/@xxx"` → 0 命中变成 100% 达标
- `0fd88eb` 进度 5 阶段 + silent 轮询（修进度条一闪一闪 / 0% 停很久）
- `2972cd9` 命中率三件套：
  1. Video description fallback（about 0 → 访问视频 desc 再找）
  2. `_load_youtube_cookies()` 读 `server/data/youtube-cookies.json`（opt-in）
  3. 候选池 2× → 3×；scroll 1200→1800px；间隔 1.5→2s

## 待办（需要用户配合）

### ⭐ 高价值待办：配 YouTube 登录 cookie

**不配**：命中率就停在 ~35%（商业化关键词）~15%（个人号）
**配完**：预估 70-85%（解锁"View email address"按钮）

**配置方法**：
1. 按 `server/data/README-youtube-cookies.md` 操作
2. 用 YouTube **小号**登录（主号有被标风险）
3. 用 Chrome "Cookie Editor" 插件导出 JSON
4. 保存到 `server/data/youtube-cookies.json`
5. 重启 backend

scraper 启动时自动检测：
- 有 → log "[YouTube] loaded N cookies"
- 无 → log "[YouTube] no cookies.json — running anonymous"

Cookie 文件已 gitignore（`data/` 被忽略，只 README-*.md 例外允许）。

### 其他潜在优化（未做，有需求再做）
- Instagram 的命中率专项测试 + stealth 加强
- TikTok/Twitter/Facebook 现在是 CSV stub，未来上 Playwright 方案
- Proxy 池（现在只有 stealth + UA 轮换，高频抓会被 detect）
- 对"受欢迎关键词"的结果去重 cache（同一 creator 反复抓浪费时间）

## LLM 代理配置（重要）

`.env`：
```
OPENAI_API_KEY=sk-8kTk...  (用户提供的 kk666 代理 key)
OPENAI_BASE_URL=https://api.kk666.online/v1
```

重要陷阱：**llm_client.py 用 httpx 原生发请求，不用 openai SDK**。因为 kk666 代理黑名单 OpenAI SDK 的 `X-Stainless-*` 诊断 header（会返回 403）。

## DB 当前数据（2026-04-18 17:xx）

```
scrape_tasks: #1-9（#2 被 admin 取消 / 其他 completed）
influencers: 35+ 条（#25-35 是本日真抓的，其余是测试 seed）
scrape_task_influencers 关联齐全
```

验证命令：
```bash
cd C:/Users/Administrator/Desktop/Ai_Agent/influencer-trigger/server
.venv/Scripts/python -c "
import sqlite3
conn = sqlite3.connect('data/influencer.db')
for r in conn.execute('SELECT id, nickname, email, followers FROM influencers WHERE id>=25 ORDER BY id DESC'):
    print(r)
"
```

## 服务启动命令（Windows Git Bash）

```bash
cd C:/Users/Administrator/Desktop/Ai_Agent/influencer-trigger/server
.venv/Scripts/python -m uvicorn app.main:app --host 0.0.0.0 --port 6002 > /tmp/backend.log 2>&1 &

cd C:/Users/Administrator/Desktop/Ai_Agent/influencer-trigger/client
npm run dev > /tmp/vite.log 2>&1 &
```

访问 http://localhost:6001，账号 admin / admin123。

## 未解决问题 / 注意事项

1. **backend JWT 30 分钟过期**。前端一段时间不操作再刷新会看到 401，需要重新登录。
2. **React StrictMode "WebSocket closed before established"** 是 dev 模式下双 mount 的正常现象，不是 bug，生产 build 无此问题。
3. **alembic check 暴露过 3 个小 schema 不一致**，已在 `b33e85e` 修复。新 migration 走 `alembic revision + upgrade head` 标准流程。

## 下次继续工作的起点

1. 读这个文件 + MEMORY.md 里对应索引
2. `git log --oneline -10` 看最近 commit
3. `cd server && .venv/Scripts/python -c "import sqlite3; conn=sqlite3.connect('data/influencer.db'); print(list(conn.execute('SELECT COUNT(*) FROM influencers'))[0])"` 看 DB 状态
4. 如果用户已配 cookies.json，跑一次新 scrape 任务看命中率变化
