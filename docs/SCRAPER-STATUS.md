# influencer-trigger Scraper 当前稳定方案（2026-04-25 快照）

> 上一版本：2026-04-18 快照（commit `22fd4a1`）。本次大改 7 天，覆盖。

## 项目坐标
- 代码：`C:\Users\Administrator\Desktop\Ai_Agent\influencer-trigger`
- 远程：https://github.com/lisir185335631-spec/influencer-trigger
- 分支：`main`
- 截至本文最新 commit：`2c26b6a` — fix: scraper Windows asyncio policy + outer-except diagnostics + #65 follow-up

## 业务用途
PremLogin BD Agent。Playwright + Brave Search + LLM 混合，从 YouTube/Instagram 公开主页抓 KOL 联系邮箱 → 批量发合作邮件 → Monitor 监听回复。本文档聚焦 YouTube（已稳定）；Instagram 走另一条 Brave Search + Apify pipeline，独立调优中。

## YouTube 抓取流程（9 phase）

```
POST /api/scrape/tasks
  ↓ BackgroundTasks.add_task(_launch_scraper, task_id)
  ↓ supervisor.run_scraper_with_tracking → run_scraper_agent

Phase 1 (0%)  starting              新任务标 running，broadcast WS
Phase 2 (0%)  querying_history      并行：DB 查 30 天内同 industry 已抓 channel
              + 后台 _start_browser 起 Playwright Chromium
Phase 3 (0%)  llm_thinking          ⚠ 饱和早警告：excluded ≥ 100 时 broadcast
                                    scrape:saturation，error_message 持久化
Phase 4 (0%)  LLM 生成 search_queries（gpt-4o-mini, max_tokens=500）
              5 分钟内同 (industry, market, brands, platforms, excluded_count)
              缓存命中 → 跳过 LLM；语言不符 query 丢弃；命中已抓 KOL 名的
              query 也丢弃；剩 < 3 条则用 fallback 补
Phase 5 (5%)  strategy_ready        search_keywords 落库
Phase 6 (7%)  browser_starting      await playwright_task（一般已就绪）
Phase 7 (15-29%) searching SERP loop
              对每个 query 调 https://www.youtube.com/results?search_query=...
              regex `"canonicalBaseUrl":"/@[A-Za-z0-9_.\-]+"` 从 HTML 抓
              ⚠ 不用 DOM selector — YouTube SPA 把链接放在 ytInitialData JS 变量里
              滚动至多 8 次；连续 3 次 0 新 channel 就跳下一个 query
              candidate 池 ≥ 20 时前 4 个 query 加跑 date-desc 变体
              （&sp=CAI%253D）拿不同的 SERP 切片
Phase 8 (30-79%) crawling /about
              候选池过滤：去掉 30 天内已抓的 profile_url
              访问 channel /about → og:description / og:image / "X subscribers"
              → bio + follower + avatar
              提取 email：about 0 邮箱时 fallback 访问首个视频 desc 再找
              prefilter relax 决定是否进 DB（见下文"参数"段）
              新 KOL → INSERT influencers + scrape_task_influencers
              已存在 → 仅 back-fill avatar，**不计入 valid_count**（fresh-only）
Phase 9 (80-100%) enriching → completing
              LLM enrich：relevance_score + match_reason
              进度条平滑爬 80→85→99→100
              warning 汇总：saturation / quota / fallback / 部分完成 / 0 新人
```

## 关键设计决策

### 1. target_count 只算"新增"
`target_count` = 期望抓到 N 个**全新** KOL（不包括 30 天内已抓的复链接）。原本算 valid_count（含复链接）会出现 target=10 实际 5 新+5 旧的"虚假完成"（task #52）。

### 2. visit cap = 200
`_MAX_VISIT_CAP = 200` 硬上限。即便候选池有 500 个 channel，也只访问头 200 个。配合 `_LOW_HIT_VISITS_THRESHOLD = max(80, target_count*8)` 提前退出（命中率持续低就停）。

### 3. SERP 抓取 = JSON regex，不用 DOM
YouTube 是 SPA，channel 链接在 `ytInitialData` JS blob 里，`<a>` 标签全靠运行时渲染。`page.querySelector` 永远 0 命中（task #23 的根因）。改成 regex `"(canonicalBaseUrl|url)":"(/@xxx)"` 从原始 HTML 抓。

### 4. SERP scroll：8 次上限 + 3 次 stall 早退
- `_MAX_SCROLLS = 8` 硬上限
- `_SCROLL_STALL_THRESHOLD = 3` —— 连续 3 次滚 0 新 channel 就跳下一个 query。原值 2 偏激进（YouTube lazy-load 偶尔第 2 次返 0、第 3 次又出来），#65 抓偏少促使放宽到 3。

### 5. 饱和场景双 SERP 变体
`_SERP_SATURATION_THRESHOLD = 20`：当本 industry 已抓过 ≥ 20 个 channel 时，前 4 个 query（`_DATE_VARIANT_QUERY_COUNT = 4`）加跑 `&sp=CAI%253D`（按上传日期降序），换一个 SERP 切片避免再吃同一头部 KOL。

### 6. LLM 搜索策略缓存
`_LLM_CACHE_TTL = 300.0`（5 分钟）。缓存键 = `(industry.strip, market.lower, competitor_brands, sorted(platforms), excluded_count)`。`excluded_count` 入键是因为新增已抓 channel 后 LLM 应当避开，旧 cache 不能用。

### 7. LLM-query 后过滤：黑名单匹配 + 语言对齐
LLM 返回的 query 里：
- 整条匹配某个已抓 KOL nickname → 丢（normalize: lower + 去全/半角空格），#65 实测 4/15 query 是这种
- 语言不符（en 任务返中文 query / 反过来）→ 丢，但**短拉丁专名（≤ 3 词）放过**（KOL handle 像 `Matt Wolfe` 是合法的跨语言 query）
- 剩 < 3 条 → fallback 多语言模板补到 ≥ 3

### 8. prefilter relax（task #65 大改）
`_industry_relevance_prefilter` 只 reject **同时**满足以下 ALL 才拒：
- industry 非空且能拆出 ≥ 1 个有意义 token
- bio + nickname 非空
- followers < `follower_bypass = 5_000`（之前 50K，太严）
- bio **不**含商务意图词（`_BUSINESS_INTENT_RE`：collab / business / sponsor / partner / contact / inquir / brand deal / 合作 / 商务 / 联系 / 邮箱 / 信箱 / 协作 / お仕事 / 협업 / 문의）
- bio 和 nickname 都不含任何 industry token

任何一条不满足就放过，让 LLM enrichment 后续打分。task #65 实测：71% kill rate（7 个有邮箱的 channel 砍掉 5 个）→ relax 后只砍掉真·跑题英文 vlog。

### 9. excluded channels = 30 天 + 同 industry（normalized）
`_norm_industry`：lower + 去 ASCII/全角空格。所以 `AI 工具` / `AI　工具` / `AI工具` / `ai工具` / `AI TOOLS` / `AI tools` 都视为同一 industry，excluded 集合共用。回退到 30 天窗口（task #53 短暂尝试过 all-time + all-industry，候选池缩太狠，net new=0+reused=39，回退）。

### 10. cookies opt-in（命中率倍增）
`server/data/youtube-cookies.json` 存在 → 加载到 Playwright context，命中率 ~35% → 70-85%（解锁 "View email address" 登录按钮）。
不存在 → 匿名，scraper log `[YouTube] no cookies.json — running anonymous`。
脚本 `server/scripts/import_youtube_cookies.py` 交互式导入；cookies 30-60 天过期，过期重跑。

### 11. Windows asyncio 事件循环兜底（task #66/#67/#68 修复）
`app/main.py` 模块顶部硬设 `WindowsProactorEventLoopPolicy`（仅 Windows）。原因：uvicorn ≤ 0.30 + `--reload` 子进程默认用 SelectorEventLoop，Playwright `chromium.launch()` 内部 `asyncio.create_subprocess_exec` 在 Selector 上抛 `NotImplementedError()`（**str 是空的**），整个任务 3 秒内 fail，UI 显示"失败 + 0% + 无错误信息"。

### 12. 异常诊断兜底
`run_scraper_agent` 外层 except：`error_message` 永远带异常类名。`str(exc)=""` 时（如 `NotImplementedError`、`asyncio.CancelledError`）至少出 `"NotImplementedError"`。WS broadcast 同步用这个 message。

## 关键参数清单（一览）

| 参数 | 值 | 在哪 | 为什么 |
|------|---|------|--------|
| `_MAX_VISIT_CAP` | 200 | scraper.py:737 | 单任务最多访问 200 个 channel，避免无限拉 |
| `_LOW_HIT_VISITS_THRESHOLD` | `max(80, target*8)` | scraper.py:791 | 命中率持续低就停 |
| `_MAX_SCROLLS` | 8 | scraper.py:540 | 每个 query 最多滚 8 次 |
| `_SCROLL_STALL_THRESHOLD` | 3 | scraper.py:551 | 连续 3 次 0 新就跳 query |
| `_DATE_VARIANT_QUERY_COUNT` | 4 | scraper.py:562 | 饱和时前 4 query 加 date-desc 二刷 |
| `_SERP_SATURATION_THRESHOLD` | 20 | scraper.py:572 | candidate ≥ 20 才启用 date variant |
| `_AVG_SCROLLS_PER_QUERY` | 3 | scraper.py:587 | 进度条估算用（实测均值） |
| `_SATURATION_THRESHOLD` | 100 | scraper.py:2796 | excluded ≥ 100 早警告 |
| `follower_bypass` | 5_000 | scraper.py:252 | prefilter 粉丝放过线 |
| `_LLM_CACHE_TTL` | 300s | scraper.py:2041 | LLM 搜索策略缓存 5 分钟 |
| `scrape_concurrency` | 系统设置默认 1 | system_settings 表 | 平台并发数 |
| `target_per_platform` | `target_count // len(platforms)` | scraper.py:2638 | 多平台均分 |

## 命中率（2026-04-25 实测）

带 cookies + 商业化关键词，target=10 任务典型用时 5-8 分钟，结果分两类：
- **首次抓取该 industry**：候选池干净，10 个 target 大概率 7-10 个新人 + 0-3 复链接
- **饱和 industry**（excluded ≥ 100）：触发早警告，仍跑但 new/target 通常 < 30%（#65 实测 144 excluded → 2/10 新）

无 cookies 命中率减半。

## 失败模式 & 防御

| 失败模式 | 原因 | 防御 |
|---------|------|------|
| 任务 3s 内 fail，error_message 空 | Windows Selector loop 上 Playwright 抛空消息 NotImplementedError | main.py 顶 ProactorEventLoopPolicy + outer-except 加 type 名前缀 |
| Brave/Apify 配额耗尽 | 第三方 API 429/401 | quota_errors 收集，broadcast `scrape:saturation` 等 modal 弹窗 |
| LLM 不可用 | API key 失效 / 网络 / 模板缺失 | fallback_queries 多语言模板，error_message 标 "LLM 搜索策略不可用" |
| 候选池被历史任务穷尽 | 同 industry 已抓 ≥ 100 channel | 任务开头 `scrape:saturation` 早警告，operator 可取消 |
| YouTube DOM 变更 | YouTube 改 SPA 结构 | 用 ytInitialData JSON regex（比 selector 抗变） |
| `agent_runs` 状态与 `scrape_tasks` 不一致 | scraper 内部消化异常未 re-raise | **已知遗留**，影响 admin 页面而非业务，未来如需可让 supervisor 反查 task 状态 |
| Windows 日志 GBK 编码 emoji 报 UnicodeEncodeError | sqlalchemy INFO log 含 ☑ 等 emoji | **已知遗留**，仅日志显示问题，不影响业务；需要可设 `PYTHONIOENCODING=utf-8` |

## 调优时间线

| 日期 | commit | 改动 |
|------|--------|------|
| 2026-04-18 | `e60fe05` | YouTube selector → ytInitialData JSON regex |
| 2026-04-18 | `0fd88eb` | 进度条 5 阶段 + silent 轮询 |
| 2026-04-18 | `2972cd9` | 视频 desc fallback + cookies opt-in + 候选池 2x→3x |
| 2026-04-19 | `541f63d` | YouTube crawl 稳定性 + CRM 重做 |
| 2026-04-22 | `ffcf6a8` | Instagram 接 Brave Search + Linktree fallback + avatar proxy |
| 2026-04-23 | `6216266` | Instagram 全栈重建 — Apify + 语言对齐 + 4D scoring |
| 2026-04-23 | `f5709c4` | Brave/Apify 配额错误 modal + reenrich 历史任务脚本 |
| 2026-04-23 | `5ccb633` | quota modal 刷新可见 + failed 任务也 broadcast |
| 2026-04-23 | `892d1c5` | 短拉丁专名查询不被 CJK 期望误判语言 |
| 2026-04-23 | `c4500d3` | 57 unit test for query language validator |
| 2026-04-23 | `279381a` | CI 加 pytest + tsc on push/PR |
| 2026-04-24 | `8de388b` | Playwright 启动并行化 + 4 新进度阶段 |
| 2026-04-24 | `36c9fde` | live phase_detail + LLM cache + DB/LLM 并行 |
| 2026-04-24 | `51ec4af` | target 只算 NEW + visit cap 200 + 部分完成 warning |
| 2026-04-24 | `a89f5a7` | excluded 短暂改成 all-time/all-industry（之后回退） |
| 2026-04-25 | `c4c2647` | 精度+稳定性+work-aligned progress overhaul |
| 2026-04-25 | `2c26b6a` | Windows asyncio policy + outer-except 诊断 + #65 follow-up |

## 服务启动（Windows）

```powershell
# Backend（detached，避免父进程退出连带杀子进程）
Start-Process -FilePath "C:\Users\Administrator\Desktop\Ai_Agent\influencer-trigger\server\.venv\Scripts\python.exe" `
  -ArgumentList "-m","uvicorn","app.main:app","--host","0.0.0.0","--port","6002" `
  -WorkingDirectory "C:\Users\Administrator\Desktop\Ai_Agent\influencer-trigger\server" `
  -RedirectStandardOutput "C:\...\server\uvicorn.log" `
  -RedirectStandardError "C:\...\server\uvicorn.log.err" `
  -WindowStyle Hidden
```

```bash
# Frontend
cd C:/Users/Administrator/Desktop/Ai_Agent/influencer-trigger/client
npm run dev > /tmp/vite.log 2>&1 &
```

访问 http://localhost:6001，账号 admin / admin123（或 .env 配置的）。

## 健康检查 & 调试

```bash
# Backend health
curl -sf http://localhost:6002/api/health

# 看真实 listening 进程（Windows netstat 会留 PID 残影；用 PowerShell）
powershell "Get-NetTCPConnection -LocalPort 6002 -State Listen | Select-Object OwningProcess"

# 抓最近失败任务的 traceback（agent_runs.error_stack）
.venv/Scripts/python -c "
import sqlite3
c = sqlite3.connect('data/influencer.db').cursor()
for r in c.execute('SELECT id,task_id,state,error_message FROM agent_runs WHERE state=\"failed\" ORDER BY id DESC LIMIT 5'):
    print(r)
"

# 看最近 scrape_tasks
.venv/Scripts/python -c "
import sqlite3
c = sqlite3.connect('data/influencer.db').cursor()
for r in c.execute('SELECT id,industry,target_market,status,progress,new_count,reused_count,error_message FROM scrape_tasks ORDER BY id DESC LIMIT 8'):
    print(r)
"
```

## 下次接手起点

1. 读本文 + `git log --oneline -10`
2. 看 `docs/AUDIT-FIX-PLAN-2026-04-18.md` 里的历史架构决策
3. `curl http://localhost:6002/api/health` 确认服务在跑
4. 如要新功能：参考 `AGENTS.md` 流程；调 scraper 参数：直接改 scraper.py 顶部常量
