# YouTube 网红邮箱抓取流水线（当前稳定方案）

> 快照日期：2026-04-26
> 适用 commit：`4d880fb` 及之后
> 上一版总览：[`SCRAPER-STATUS.md`](./SCRAPER-STATUS.md)（2026-04-25 时点的 4 平台总览）
> 本文聚焦 YouTube 单平台的**完整抓取链路**。

---

## 1. 一句话定位

YouTube 是当前 4 平台里**唯一不依赖第三方付费 actor、纯本地 Playwright 直抓**的平台：
直接 GET YouTube 公开 SERP HTML → 正则抽 `/@handle` 频道路径 → 并发 3 线程进每个频道 `/about` 页 → 提 email + bio + follower + avatar → MX 校验 + 黑名单过滤 → 入库。

**单任务零外部 API 成本**（Brave 不参与、Apify 不参与、LLM 仅用于生成 search query 1-2 次调用 ~$0.001），**端到端单任务成本 < $0.005**。代价是慢一些（target=10 大约 3-5 min）+ 命中率受 YouTube SERP 排序波动影响。

---

## 2. 总流程图（9 phase 进度映射）

```
POST /api/scrape/tasks { platforms: ["youtube"], industry, target_count, ... }
  ↓ BackgroundTasks.add_task(_launch_scraper, task_id)
  ↓ supervisor.run_scraper_with_tracking()  # 写 agent_runs 表 tracking
  ↓ run_scraper_agent() → run_platform("youtube") → _scrape_youtube()

Phase 1 (0%)   starting             task=running, WS broadcast
Phase 2 (0%)   querying_history     并行：DB 查 30 天 same-industry already-scraped channel URL
                                    + 后台 _start_browser() 启 Playwright Chromium
Phase 3 (0%)   llm_thinking         excluded ≥ 100 → broadcast scrape:saturation 警告
Phase 4 (0%)   LLM 出 search_queries(gpt-4o-mini, max_tokens=500)
                                    5min 内同 (industry,market,brands,platforms,excluded_count) 缓存命中跳过
                                    语言不符 query 丢；命中已抓 KOL 名的 query 丢
                                    剩 < 3 条 → _fallback_queries 补
Phase 5 (5%)   strategy_ready       search_keywords 落库
Phase 6 (7%)   browser_starting     await playwright_task
Phase 7 (15-29%) SERP 阶段
                                    对每 query：GET https://www.youtube.com/results?search_query=...
                                    regex "canonicalBaseUrl":"/@[A-Za-z0-9_.\-]+" 从 HTML 抽
                                    ⚠ 不用 DOM selector — SPA 把链接放 ytInitialData JS blob
                                    滚动 ≤ 8 次；连续 3 次 0 新 → 跳下一个 query
                                    excluded ≥ 20 → 前 4 个 query 加跑 date-desc 变体（&sp=CAI%253D）
Phase 8 (30-79%) /about 抓取阶段
                                    候选池过滤已 excluded URL → shuffle 去 ranking bias
                                    并发 3 个 channel，每个 15s 硬 budget
                                    /about → og:title/og:description/og:image/subscriberCount → name/bio/avatar/followers
                                    点 "View email address" 按钮（need cookies） → page.content() → regex 抽 email
                                    relevance prefilter（行业 token 不命中且 < 5K 粉丝直接丢）
                                    junk filter（黑名单 + placeholder） + MX 校验
                                    on_found(email, name, ch_url, ...) — 仅 NEW 计入 target
                                    达 target_count 或 hit-rate gate 触发 → stop_event.set()
Phase 9 (80-100%) enriching → completing
                                    LLM enrich：relevance_score + match_reason
                                    进度平滑 80→99→100
                                    warning 汇总写 task.error_message（[INFO]/[WARN]/[ERROR] 前缀）
```

代码入口：`server/app/agents/scraper.py:_scrape_youtube`（行 513-1013）。

---

## 3. 核心架构决策（5 条，每条都有踩坑回溯）

### 3.1 用 regex 抽 ytInitialData，不用 DOM selector

YouTube 是 SPA，搜索结果以 JSON blob `ytInitialData` 注入到 HTML 头部，渲染后才挂 DOM。`page.locator("a[href^='/@']")` 总返 0 — DOM 中根本没有那批 `<a>`。

**当前实现**：
```python
_YT_CHANNEL_PATH_RE = re.compile(r'"(?:canonicalBaseUrl|url)":"(/@[A-Za-z0-9_.\-]+)"')
matches = await asyncio.to_thread(_YT_CHANNEL_PATH_RE.findall, html)
```

`asyncio.to_thread` 是必须的：1-2MB HTML 上 regex 扫 100-1000ms，同步占 event loop 会让 `/api/health` 都 10s 超时。**这是当前并发能稳定到 3 的关键之一**。

### 3.2 subresource block：CDP 事件量减 5×

Windows Python 3.13 ProactorEventLoop 下，Playwright CDP WebSocket + uvicorn HTTP 共用 IOCP。每打开一个 YouTube 页 100+ 子资源（image/font/css/track/media）通过 IOCP 事件涌入 → 几分钟后 `accept_coro()` 报 `WinError 64`，uvicorn accept 队列死掉。

**当前实现**：
```python
_BLOCK_RESOURCE_TYPES = frozenset({"image", "stylesheet", "font", "media"})

async def _block_non_essential(route):
    if route.request.resource_type in _BLOCK_RESOURCE_TYPES:
        await route.abort()
    else:
        await route.continue_()

# 在 navigation 之前
await ctx.route("**/*", _block_non_essential)
```

`ytInitialData` 是 inline 在主 HTML 里的，所以 block 子资源**不损失任何抽取字段**。CDP 事件量降 80%，让 IOCP 有余量同时服务 HTTP，并发才能从 1 重新放回 3。

### 3.3 并发 3 + per-channel 15s budget + finally 释放

```python
_CHANNEL_CONCURRENCY = 3
_CHANNEL_BUDGET = 15.0  # 单频道硬上限（asyncio.timeout 包整段）
sem = asyncio.Semaphore(_CHANNEL_CONCURRENCY)

async def _process_channel(ch_idx, ch_url):
    async with sem:
        try:
            async with asyncio.timeout(_CHANNEL_BUDGET):
                ch_page = await ctx.new_page()
                await stealth_async(ch_page)
                await ch_page.goto(about_url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(1.2)  # hydration: 等 "View email address" 按钮渲染
                # ... 点按钮 → page.content() → regex 抽
        finally:
            if ch_page is not None:
                await ch_page.close()  # 防 Chromium tab 泄漏
```

历史曲线：3 → 2 → 1（IOCP 崩）→ 3（加了 subresource block 之后才稳）。再大不行 — Windows 测过 5 必崩 backend。

### 3.4 cookies 解锁 "View email address" 按钮

未登录时 YouTube 频道 About 页**不显示** `<button>View email address</button>`。登录态下点按钮 → 弹 captcha → 通过后 HTML 回填明文邮箱。

**两种导入路径**：
- **UI 内粘贴**：`SettingsPage` → "YouTube Cookies" 卡片 → 粘 DevTools Network tab 的 cookie 字符串或 Cookie Editor 导出的 JSON → POST `/api/settings/youtube-cookies` → 校验有 `SAPISID/__Secure-3PSID/LOGIN_INFO` 之一 → 写 `server/data/youtube-cookies.json`
- **CLI 脚本**：`server/scripts/import_youtube_cookies.py`（Playwright 弹有头浏览器手登录后 dump）

**配 cookies 命中率提高 30-50%**（实测 dog training niche 35% → 70%）。

**重要 bug 回顾**：曾经 `_load_youtube_cookies` 用 `parents[3]` 拼路径（项目根目录），但 UI 与 CLI 都写到 `parents[2]`（server/data/）→ 写了等于没写，UI 显示"已配置"但 scraper 永远 anonymous，hit rate 卡 35% 半个月没人发现。已修为 `parents[2]`。

### 3.5 锁定 about 页字段，删除 video fallback

历史方案：about 页找不到邮箱时 fallback 抓首个视频描述。问题：
- subresource block 下视频页 hydration 不全，`page.content()` 几乎拿不到完整 HTML
- 单次 fallback 浪费 20-30s 并发槽
- 即使偶尔抽到邮箱，nickname/avatar/bio/followers 全是视频级（错误归因）

**当前**：only about 页，fallback 整段删除。代偿方式：候选池 `target_count × 15` + `_MAX_VISIT_CAP=200` 放大候选池，多走几个频道总比走死胡同强。

---

## 4. 关键参数表（出问题先调这些）

| # | 参数 | 当前值 | 说明 |
|---|---|---|---|
| 1 | `_CHANNEL_CONCURRENCY` | **3** | 频道并发；Windows IOCP 上限 |
| 2 | `_CHANNEL_BUDGET` | **15.0s** | 单频道硬超时（asyncio.timeout 包整段）|
| 3 | `_MAX_SCROLLS` | **8** | 每 query SERP 滚动上限 |
| 4 | `_SCROLL_STALL_THRESHOLD` | **3** | 连续 N 次 0 新 channel 提前结束滚动（2 → 3 改于 2026-04-25）|
| 5 | `_MAX_VISIT_CAP` | **200** | 候选池访问硬上限（旧 target × 15 不够用）|
| 6 | `_LOW_HIT_VISITS_THRESHOLD` | `max(80, target × 8)` | 命中率 gate 触发条件 |
| 7 | `_LOW_HIT_NEW_THRESHOLD` | `max(1, target // 2)` | 命中率 gate 阈值 |
| 8 | `_SERP_SATURATION_THRESHOLD` | **20** | excluded ≥ 此数则前 4 query 加跑 date-desc 变体 |
| 9 | `_DATE_VARIANT_QUERY_COUNT` | **4** | date-desc 变体只跑前 4 个 query（控时长）|
| 10 | `_random_delay` | `2-5s` | 每 channel 处理后的 sleep |
| 11 | hydration sleep | **1.2s** | goto 后给 "View email address" 按钮渲染 |
| 12 | goto timeout | **20s/30s** | about 页 20s / SERP 页 30s |
| 13 | follower_bypass（prefilter）| **5_000** | ≥ 5K 粉丝直接放行 |
| 14 | URL pool buffer | `target × 15` | 三处都改（pool/visit/cap）|
| 15 | LLM cache TTL | **5 min** | 同 (industry,market,brands,platforms,excluded_count) 5min 内复用 |
| 16 | Cross-task dedup window | **30 天** | 30 天内已抓 channel_url 不再访问 |

---

## 5. 进度推进规则（前端不卡 28% 的核心）

| Phase | 进度区间 | 推进规则 |
|---|---|---|
| 1-6 启动 | 0-15% | LLM 完成、browser 起好 → 跳 7-15 |
| 7 SERP | 15-29% | 每 scroll 完成 → `int(cumulative_scrolls / estimated_total_scrolls × 30)`，整数变化才 broadcast；scroll 提前 stall 用 walk 50ms/digit 平滑补到 30 |
| 8 about | 30-79% | 每 channel 完成（无论命中与否）→ `min(79, 30 + max(visit_ratio, new_ratio) × 49)`，monotonic gate 防回退 |
| 9 enrich | 80-99% | LLM enrich 完 → walk 80→99 |
| done | 100% | task.status = completed |

**关键设计**：visit_counter 是真完成数（finally 段 `nonlocal` 自增），不是 ch_idx（候选池位置）。在并发=3 下两者不一致，UI 用 visit_counter 才能保证"看到的数字单调递增"。

---

## 6. SERP 饱和度自适应（2026-04-25 加的）

冷启动一个 niche（excluded < 20）：候选池本来就足够，第一轮 default-sort SERP 通常给 60-100 unique channel。
长期跑同一个 niche（excluded ≥ 20）：default sort 永远给同一批"头部老熟人"——前 5 个候选都是 J3M_AI / lichangzhanglaile 这种已抓过的。

**对策**：excluded ≥ 20 时，前 4 query 跑两次：
- 第 1 次：`?search_query={q}` —— 默认排序
- 第 2 次：`?search_query={q}&sp=CAI%253D` —— upload date desc

date-desc 切片倾向"近期上传"，自然偏向中小尾部 channel。两次结果合并 dedup → 候选池扩到 80-150。

控时：只前 4 query 加跑（不是全部 12 query）→ 额外 ~30s。

---

## 7. Hit-rate gate（提前结束的兜底）

低命中率 niche 的典型表现：候选池 200 个、走完 100+ 个还只 5 个新人、剩下都是和当前 industry 不沾边的随机创作者（LLM 生成的 query 太宽泛 / 用了虚构 KOL 名）。

**门禁逻辑**：
```python
if visited_counter >= max(80, target × 8) and new_counter < max(1, target // 2):
    stop_event.set()  # 早停，触发 "部分完成"
```

target=10 时 → 走 80 个还不到 5 新人 → 停。比再走 80 个赌另外 1 个新人划算（这步省 80 × 5s = 400s）。

---

## 8. 多语言 fallback（避免 LLM 失败导致 0 hit）

LLM 给的 search query 偶尔会塌（速率限、生成失败、被语言策略全部拒掉）。`_fallback_queries` 兜底产 8 条变体：

```python
_YT_FALLBACK_SUFFIXES_BY_LANG = {
    "en": ("creator contact email", "review", "tutorial", "best 2026", "guide", "tips", "comparison", "for creators"),
    "cn": ("创作者 邮箱", "评测", "教程", "推荐", "商务合作", "懒人包", "排行 2026", "使用指南"),
    "tw": ("創作者 信箱", "評測", "教學", "推薦", "商務合作", "懶人包", "排行 2026", "使用指南"),
    "jp": ("クリエイター メール", "レビュー", "使い方", "おすすめ", "お仕事", "ガイド", "比較", "2026 ランキング"),
    "kr": ("크리에이터 이메일", "리뷰", "사용법", "추천", "협업 문의", "가이드", "비교", "2026 순위"),
}
```

语言由 `_expected_query_lang(industry, target_market)` 推断 — 历史 task #27 用过 IG 抓中国 niche 但 fallback 给的英文 suffix → 0 命中，这个 5-语种字典是 fix。

---

## 9. 邮箱过滤层（与 4 平台共享）

落库前邮箱过 3 道：

1. **`_industry_relevance_prefilter`**（only YouTube 当下用）：bio + nickname + business-intent regex（包含 collab/合作/お仕事/협업 等多语种）任一命中 OR followers ≥ 5K 才放行
2. **`is_junk_email`**（4 平台共用）：domain 黑名单（clickbank/digistore24/jvzoo/tempmail/mailinator/apple/facebook/instagram/tiktok）+ local-part 黑名单（johnappleseed/test/demo/noreply）
3. **`_mx_valid`**（4 平台共用）：DNS MX 记录查询（带 module-level cache 避免重复查 gmail.com）

---

## 10. 并发安全（一条都不能省）

- 每 channel task 自己 `ctx.new_page()` + `stealth_async()` + UA 轮换；context 共享（cookies/storage 复用）但 page 独立
- `found_lock = asyncio.Lock()` 包 `nonlocal new_counter` 自增（防并发少算）
- DB 写入走 `asyncio.Lock()` 序列化（防 SQLite write race）
- `stop_event` 早停（达 target 后剩余 channel 不再 spawn）
- `page.close()` 必须在 `finally`（防 Chromium tab 泄漏）
- 字段锁定：name/bio/follower/avatar 只在主 about 页抽（曾经 fallback 抽视频页 → nickname 变成视频标题）

---

## 11. 实测命中率参考

| niche | target | wall time | 实际 valid | 备注 |
|---|---|---|---|---|
| Canva Pro tutorial | 10 | 2-3 min | **10/10** | 商业化关键词 hit rate ~35% |
| ChatGPT Plus review | 10 | 2-3 min | **10/10** | 同上 |
| AI tools | 10 | 4-5 min | 5-8/10 | 中等垂直度 ~25% |
| Notion productivity | 10 | 4-5 min | 6-8/10 | ~25% |
| 任意低商业化 niche | 10 | 5+ min | 3-6/10 | hit-rate gate 早停 |

**target=10 的成功率主要由关键词商业化程度决定**，不是 scraper 本身的问题。引导用户填 `<品牌名> review/tutorial` 类关键词命中率 ≥ 70%。

---

## 12. 出问题先查的 5 件事

1. **uvicorn 没 --reload**：改完代码必须 `taskkill //F` + 重启，否则跑老代码（ecosystem.config.js 没启 reload 是有意的——避免开发期文件 touch 触发重启把跑到一半的 task 干掉）
2. **cookies 路径**：`server/data/youtube-cookies.json` 必须存在且含 SAPISID/__Secure-3PSID/LOGIN_INFO 之一；scraper 启动 log 看 `[YouTube] loaded N cookies`，没看到就是没生效
3. **看 SERP 阶段日志**：`[YouTube] q1/default scroll #1: html_len=X regex_hits=Y new_channels=Z`。html_len < 50KB 通常是被反爬返了空页 / 验证页；regex_hits=0 且 html_len 正常 = canonicalBaseUrl 正则失效（YouTube 改 schema 了，需改 regex）
4. **看 about 阶段日志**：`[YouTube] [N] html_len=X view_email_btn=Y emails_found=Z`。view_email_btn=0 通常是 cookies 失效；emails_found=0 但 view_email_btn=1 是点击/captcha 失败
5. **Windows IOCP 崩了**：backend 突然全卡（health 也卡）→ `_CHANNEL_CONCURRENCY` 暂降到 1 → 看是不是因为 task 数太多 / 别的进程占满 IOCP

---

## 13. 回滚路径（按严重度）

| 症状 | 降级动作 |
|---|---|
| backend accept 错 / 健康检查 timeout | `_CHANNEL_CONCURRENCY` 3 → 2 → 1 |
| 命中率正常但 UI 卡顿 | `_CHANNEL_BUDGET` 15s → 10s（早杀慢频道）|
| 出现 captcha / 429 | `_random_delay` 2-5s → 5-15s，concurrency=1，等 30 min |
| target 长期不达 | 切商业化关键词（`<brand> review/tutorial`）；候选池 `target × 15` → 20 |
| YouTube SERP 改 schema | regex `_YT_CHANNEL_PATH_RE` 失效 → grep canonicalBaseUrl 看新字段名 |
| cookies 月度过期 | UI 重新粘 cookie 字符串（每 30-60 天）|

---

## 14. 关键代码指针

| 模块 | 位置 |
|---|---|
| 主流水线 | `server/app/agents/scraper.py:_scrape_youtube`（行 513-1013）|
| Cookies 加载 | `server/app/agents/scraper.py:_load_youtube_cookies`（行 330）|
| Subresource block | `server/app/agents/scraper.py:_block_non_essential`（行 370）|
| Context 创建 | `server/app/agents/scraper.py:_new_context`（行 382）|
| About 页元数据抽取 | `server/app/agents/scraper.py:_extract_youtube_channel_metadata`（行 450）|
| Channel 处理 worker | `server/app/agents/scraper.py:_process_channel`（行 802）|
| Prefilter | `server/app/agents/scraper.py:_industry_relevance_prefilter`（行 247）|
| Fallback queries | `server/app/agents/scraper.py:_YT_FALLBACK_SUFFIXES_BY_LANG`（行 3517）|
| Cookies UI 后端 | `server/app/api/settings.py`（行 35-451）|
| Cookies 配置文档 | `server/data/README-youtube-cookies.md` |
| Cookies CLI 导入 | `server/scripts/import_youtube_cookies.py` |

---

## 15. 没做的事（积压）

- **登录池轮换**：单 cookies 长期使用风险（账号被风控）。可加多账号 cookies 轮换 + 失效自动剔除。当前仅单账号，30-60 天 expired 就重导。
- **代理池**：单 IP 在 N > 100 任务规模会触发反爬。Linux 部署 + 住宅代理是规模化方案，本地测试还碰不到。
- **YouTube Data API v3 兜底**：API quota 10000 unit/day 够辅助补 channel metadata。当前仅用 Playwright + SERP，API 集成是积压。
- **video desc fallback 重启**：要让 video URL 绕过 subresource block + budget 调到 60s。当前 ROI 不值。
- **per-language 命中率档案**：现在每次都按 niche 通用估，可加 niche 命中率历史做更准的 cap 估算。

---

## 附录 A：单一职责原则在本流水线的体现

- `_scrape_youtube`：只做编排（context 起 + 收集 SERP + 派发 workers + 收尾）
- `_process_channel`：只做单频道（goto + 抽 + 落库）
- `_extract_youtube_channel_metadata`：只 regex（zero IO，可 to_thread）
- `_load_youtube_cookies`：只读文件（None-fallback 安全）
- `_block_non_essential`：只 abort/continue（zero state）
- `_industry_relevance_prefilter`：只 bool 判断（pure function，可单测）

测试覆盖：`server/tests/test_scraper_prefilter.py` 仅覆盖 prefilter；`_scrape_youtube` 主流水线无 unit test（Playwright 难 mock，靠 e2e 任务实测）。
