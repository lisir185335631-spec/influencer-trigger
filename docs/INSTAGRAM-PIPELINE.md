# Instagram 网红邮箱抓取流水线（当前稳定方案）

> 快照日期：2026-04-26（梳理时点）
> 主流上线：2026-04-25（commit `6216266` full-stack rebuild）
> 上一版总览：[`SCRAPER-STATUS.md`](./SCRAPER-STATUS.md)（2026-04-25 时点 4 平台总览）+ [`YOUTUBE-PIPELINE.md`](./YOUTUBE-PIPELINE.md)（YouTube 详版）
> 本文聚焦 Instagram 单平台的**完整抓取链路**。

---

## 1. 一句话定位

Instagram 是 5 平台里**唯一双路径自动切换**的平台：
有 Apify token → **Path A**（Brave SERP → Apify `instagram-profile-scraper` 批量抓 businessEmail → Linktree fallback），命中率 40-60%，单任务 $0.30-0.80
无 Apify token → **Path B**（Brave SERP → Playwright SSR per profile → Linktree fallback），命中率 5-10%，单任务 $0（仅 Brave 配额）

**为什么不能纯 Playwright SSR**：IG 自 2024 起把 `contact_email` / `business_email` / `external_url` 三个关键字段藏在 require_login 墙后面。即使是 Dave2D（248k 粉）/ Unbox Therapy（3M 粉）/ iJustine 这种头部 KOL，匿名 SSR `og:description` 都返 `"X Followers, Y Following, Z Posts"` 模板，bio 段几乎全空。Apify 用私 API / 移动端模拟拿这些字段，是绕开登录墙的唯一稳定路径（task #34-#37 Power Bank niche 全员 emails=0 是历史血证）。

---

## 2. 总流程图（双路径切换）

```
POST /api/scrape/tasks { platforms: ["instagram"], industry, target_count, target_market, ... }
  ↓ BackgroundTasks → supervisor.run_scraper_with_tracking
  ↓ run_scraper_agent → run_platform("instagram") → _scrape_instagram

Phase 1-6 (0-15%)  启动 + LLM 出 query + browser 起好

Phase 7 (15-29%)   _discover_ig_profiles
    expected_lang = _expected_query_lang(industry, target_market)
    templates = _ig_dork_templates(expected_lang)  # 5 语种
    for q in seeds: for tpl in templates: dorks.append(tpl.format(q=q))
    for dork in dorks:
        urls = await _search_brave(dork, limit=20, ...)   # 1.1-1.6s 节流
        seen.update(urls); all_profiles.extend(unique)
        if quota_errors_out: break  # 配额耗尽早停剩余 dorks
    if len(all_profiles) < max(target_urls // 3, 5):
        retry with universal dorks: `"{ind}" "gmail.com"` / `"{ind}" email "@"`

Phase 8 (30%)      候选池 dedup + shuffle
    profile_urls 过滤 excluded_profiles → shuffle → 推 30%

Phase 9 决策路径：
    apify_token, apify_actor = await resolve_apify_credentials(db, "instagram")
    if apify_token: → Path A
    else:           → Path B

─── Path A (Apify, 30-79%) ─────────────────────────────────────────
    max_to_scrape = min(len(profile_urls), 200)
    usernames = [_IG_PROFILE_URL_RE.match(u).group(1).lower() for u in batch]
    POST https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items
        json={"usernames": usernames}
        timeout=Timeout(connect=15, read=300, write=30, pool=10)
    HTTP 401/402/403/429 → 写 quota_errors_out → UI 弹 modal
    by_username = {data["username"].lower(): data for data in resp.json()}

    for profile_url in batch:
        data = by_username.get(username_from_url)
        emails = []
        if data["businessEmail"]:        emails.extend(_extract_emails(business_email))
        elif data["publicEmail"]:        emails.extend(_extract_emails(public_email))
        elif data["biography"]:          emails = await asyncio.to_thread(_extract_emails, biography)
        elif data["externalUrl"] is aggregator (Linktree/beacons/etc.):
            fallback_ctx = lazy_init Playwright context
            emails = await _scrape_aggregator_emails(fallback_ctx, external_url)

        for email in emails:
            is_junk_email() + _mx_valid() → on_found(email, name, profile_url, ...)
            if is_new and new_counter >= target_count: break

─── Path B (Playwright SSR fallback, 30-79%) ────────────────────────
    max_to_visit = min(len(profile_urls), 200)
    sem = Semaphore(_IG_CONCURRENCY=3)
    for profile_url in profile_urls[:max_to_visit] (并发 3):
        async with asyncio.timeout(_IG_PROFILE_BUDGET=18.0):
            page.goto(profile_url, wait_until="domcontentloaded", timeout=15000)
            if page.url contains "/accounts/login": return  # 登录墙快速跳过
            content = await page.content()
            emails = await asyncio.to_thread(_extract_emails, content)
            meta = await asyncio.to_thread(_extract_instagram_profile_metadata, content, username)
            if not emails:
                aggregator_url = _extract_linktree_url(content)
                if aggregator_url: emails = await _scrape_aggregator_emails(ctx, aggregator_url)
            for email in emails:
                is_junk_email() + _mx_valid() → on_found
        await _random_delay()  # 2-5s

Phase 10 (80-99%)  enriching → 4D scoring (LLM)
Phase 11 (100%)    completing
```

代码入口：`server/app/agents/scraper.py:_scrape_instagram`（行 1881-2104）。

---

## 3. 核心架构决策（5 条，每条对应踩坑回溯）

### 3.1 Brave SERP 是唯一可用的搜索入口

实测过的：
- DuckDuckGo HTTP scraping：返 `status=418`（明确拒绝服务器 IP）
- Bing scraping：返 200 但 captcha wall（Playwright 跑也一样）
- Google scraping：小 HTML 残页

**根因**：服务器 IP 被各家反爬列黑名单，**不是 bot 特征问题**（Playwright + stealth 也照样拦）。

**Brave Search API 是唯一正规军路径**：
- FREE tier 2000 query/月，单任务 ~12 query，够日常 ~150 任务
- 1 QPS 硬限 → 代码里强制 `1.1-1.6s` 随机间隔
- 配置：`server/.env.BRAVE_SEARCH_API_KEY`

### 3.2 Apify Path A 解决 IG 登录墙

历史血证（task #34-#37 Power Bank niche）：Playwright SSR 的 `og:description` 在 IG 2024+ 是登录墙下的截断模板：
```
"248k Followers, 524 Following, 1,234 Posts - See Instagram photos and videos from Dave2D (@dave2d)"
```
没 bio、没 email、没 external_url。3M 粉的 Unbox Therapy 也一样。**纯 SSR 命中率 5-10%**，且都是已经把邮箱直接放在显示名/handle 里的极少数特例。

Apify `apify~instagram-profile-scraper` 用私 API + 移动端模拟，返完整字段：
```json
{
  "username": "dave2d",
  "fullName": "Dave Lee",
  "biography": "...",
  "followersCount": 248000,
  "profilePicUrlHD": "https://...",
  "externalUrl": "https://daveleereviews.com",
  "businessEmail": "biz@daveleereviews.com",
  "publicEmail": "...",
  "businessPhoneNumber": "...",
  "businessCategoryName": "...",
  "isBusinessAccount": true
}
```
**命中率 40-60%**。代价：$0.05 / 50-profile batch（FREE plan $5/mo 覆盖 ~100 任务）。

**必须 `usernames` 不是 `directUrls`**：actor 接受 `{"usernames": [...]}`，传 `directUrls` 返 404。代码里在 POST 前做 `_IG_PROFILE_URL_RE.match(url).group(1).lower()` 提取 handle。

### 3.3 4 层 email source 漏斗（Path A 的精髓）

每个 profile 按优先级走：
1. `businessEmail`（Apify 直字段，IG "Email" 联系按钮的明文值）
2. `publicEmail`（个人账号 opt-in）
3. `biography` 内 plain-text email（regex 抽）
4. `externalUrl` 是 Linktree/beacons/bio.link 等 → Playwright 访问该 URL → `_scrape_aggregator_emails`

**4 层是有意排序**：直字段最快最准，Linktree 最慢但兜底强。前 3 层都失败才启 Playwright（lazy init `fallback_ctx`，没人用 Linktree 这次的 task 不付 browser 启动成本）。

### 3.4 Language alignment（task #27 fix）

**症状**：task #27 us market + ai tools 跑 32 dork × 0 hit。
**根因**：LLM 用中文 query 去搜英文 IG bio（`"AI 工具" "business inquiries"` 在英文 bio 上当然 0 命中）。
**修复**：
1. `_CJK_RE` / `_is_cjk_text` / `_expected_query_lang(industry, target_market)` 推断目标语言
2. system prompt 注入 `Expected query language: en|cn|tw|jp|kr` 强约束
3. LLM 输出 post-validate（CJK-vs-Latin 脚本检查），不符 query 丢弃
4. `_ig_dork_templates(lang)` 按语言出不同 dork 限定词（en `"business inquiries"`、cn `"合作"`、jp `"お仕事"`、kr `"협업"`）
5. fallback 也分 5 语种（`_IG_FALLBACK_SUFFIXES_BY_LANG`），不再压缩空格（旧 bug：`"ai tools" → "aitools"` 0 命中）

### 3.5 Linktree/aggregator fallback（创作者经济通用模式）

IG 创作者把多链接放在外站是普遍做法，**16 种 aggregator 都识别**：
```
linktr.ee, beacons.ai, linkin.bio, campsite.bio, bio.link, carrd.co,
lnk.bio, allmylinks.com, many.link, flowcode.com, link.me, linkpop.com,
snipfeed.co, contactin.bio, direct.me, magic.ly, milkshake.app,
stan.store, komi.io, withkoji.com, tap.bio, pop.bio, popl.co, toneden.io
```

`link.me` 是 2026-04-25 加的（Apify 揭示 Unbox Therapy 等大 KOL 用这个，原黑名单漏过）。

`_scrape_aggregator_emails` 是 Path A / Path B 共用的，也被 Twitter / Facebook 的 cascade 复用（4 平台共享基础设施）。

---

## 4. 关键参数表（出问题先调这些）

| # | 参数 | 当前值 | 用途 |
|---|---|---|---|
| 1 | `target_urls` | `target_count × 15` | Brave 候选池上限 |
| 2 | Apify `max_to_scrape` cap | **200** | 单批 Apify 调用最大 profile 数 |
| 3 | Apify HTTP timeout | `connect=15s, read=300s, write=30s, pool=10s` | actor 跑 50 profile 需 60-180s |
| 4 | `_IG_PROFILE_BUDGET`（Path B）| **18.0s** | 单 profile 硬超时（比 YouTube 多 3s，IG SSR Meta edge 偶尔卡）|
| 5 | `_IG_CONCURRENCY`（Path B）| **3** | Path B 并发；同 YouTube 稳定值 |
| 6 | Brave QPS 节流 | **1.1-1.6s** 随机 | Brave 免费 1 QPS 硬限 |
| 7 | low-hit retry threshold | `max(target_urls // 3, 5)` | < 此数触发 universal dorks 兜底 |
| 8 | `_random_delay`（Path B）| **2-5s** | 每 profile 处理后 |
| 9 | goto timeout（Path B） | **15s** | profile SSR |
| 10 | avatar URL 截断 | **1024 字符** | 比 YouTube 的 512 翻倍（IG CDN URL 带长 auth 签名）|
| 11 | Brave dork 模板数（5 语种） | en/cn/tw/jp/kr 各 2-3 条 | 总 15 dork 上限 |
| 12 | LLM cache TTL | 5 min | 同 (industry,market,brands,...) 复用 |
| 13 | Cross-task dedup window | 30 天 | 已抓 profile_url 不再访问 |

---

## 5. Apify 错误处理（quota_errors_out 机制）

**HTTP 错误码 → UI modal 文案**（`_scrape_via_apify` 行 1693-1720）：

| HTTP | 含义 | 文案要点 |
|---|---|---|
| **401** | token 无效/未找到 | 引导到 https://console.apify.com/account/integrations 重新签发 |
| **402** | payment required（FREE plan $5 月度耗尽 / 付费 plan 卡拒）| 提示升级 plan 或等月度 1 号重置 |
| **403** | token scope 不足 | 检查 token scope 或换 actor |
| **429** | rate limit / 并发上限 | FREE plan 25 并发 actor run 上限，等几分钟重试 |

机制：`quota_errors_out` 是任务协调器传下来的共享 list，scraper 写错误进去 → `run_platform` 收尾时 broadcast 给前端 → UI 弹 modal。**早停优化**：discovery 段任一 dork 触发 quota → break 剩余 dorks（避免 24 个连续 warning + 浪费时间）。

---

## 6. avatar 处理（IG 特有 3 件套）

IG avatar URL 有 3 个独立坑（4 平台里 IG 最难搞）：

### 6.1 HTML entity 必须 unescape
`og:image` content 属性的 `&` 按 W3C 必须 escape 成 `&amp;` → 抓取时不 unescape 直存 → DB URL 长这样：`?stp=xxx&amp;_nc_cat=107&amp;...&amp;oh=...`，浏览器加载 403。
修复：`html_module.unescape(m.group(1))[:1024]`。

### 6.2 截断长度从 512 → 1024
IG CDN URL 末尾的 `oh=...&oe=...` 是 auth 签名，512 字符截断会切掉签名 → 永久 403。
修复：放宽到 1024。

### 6.3 IG CDN 反盗链 → 后端图片代理
IG `scontent-*.cdninstagram.com` 拒所有无 Referer / 错 Referer 的请求。前端 `<img src="...cdninstagram.com/...">` 必 403。
修复：后端 `/api/image-proxy` 服务带 Referer=`https://www.instagram.com/` 转发；前端 `AvatarBadge` 仅对 IG/FB/Twitter/TikTok CDN 套代理（YouTube `yt3.*` 接受 no-referrer，继续直连）。
SSRF 防护：白名单 `*.cdninstagram.com / *.fbcdn.net / yt3.* / pbs.twimg.com / *.tiktokcdn.com`，per-host Referer 映射。

### 6.4 avatar 坏值回填
修好 scraper 后重跑，新 profile 头像正常但旧 profile 头像还坏（DB 保留 `&amp;` 老 URL）。
修复：`make_on_found` else 分支检测 `'&amp;' in existing.avatar_url` → 覆盖更新。

---

## 7. 4D scoring（task #35 fix）

**症状**：task #35 4 个 valid contact 全 0% 评分，理由 "内容与 PremLogin 无关"。
**根因**：scoring prompt 把 PremLogin 的业务上下文当成评分轴，不是 user 输入的 industry。
**修复**：`enrich_results.system.md` prompt 改 4 维度评分：
1. 内容与 industry 主题契合度
2. 受众人群与 industry 目标匹配度
3. 商业化倾向（business-intent 信号）
4. 粉丝量级合理性

PremLogin 业务背景**只作为示例参考**，不再当评分基准。

---

## 8. 出问题先查的 5 件事

1. **Apify token 配置**：`/api/settings` 的 `apify_ig_token` 字段 / `server/.env.APIFY_API_TOKEN` 任一有值。日志看 `[Instagram] using Apify path` 还是 `[Instagram] APIFY_API_TOKEN not set — falling back to Playwright SSR`，区分走 Path A 还是 B
2. **Brave 是否生效**：`server/.env.BRAVE_SEARCH_API_KEY` 必须有；日志看 `[Instagram] search #1/N dork=...` 后跟 `brave=N` 不为 0；如果 Brave 0 hits 持续 N 个 dork → low-hit retry 会触发 universal dorks
3. **language mismatch**：日志看 `[Instagram] discovery done: ... lang=en`；如果 lang 推断错（CJK industry 推成 en 或反之）→ 检查 `target_market` 字段和 `_expected_query_lang` 逻辑
4. **Path A 0 hit**：`[Instagram/Apify] HTTP X — ...` 看 401/402/403/429，对应处理；`[Instagram/Apify] scraped 0/N profiles` 通常是 actor 挂了或 username 提取失败
5. **avatar 头像不显示**：浏览器 Network 看 `/api/image-proxy?url=...` 响应；502 = DB URL 坏（含 `&amp;` 或被 512 截断）→ 触发 avatar 坏值回填或手动重抓该 profile

---

## 9. 回滚路径（按严重度）

| 症状 | 降级动作 |
|---|---|
| Apify quota 耗尽 (402) | UI 显示 modal 引导用户升级；可临时清空 token 走 Path B |
| Apify token 失效 (401/403) | UI 显示 modal；用户在 SettingsPage 重新填 token |
| Apify 429（并发限）| `target_count` 暂调小；FREE plan 25 并发上限 |
| Brave 429（QPS 超）| 节流间隔 `1.1-1.6s` → `2-3s` |
| Brave 月度配额用完 | 切 Serper.dev（2500/月免费）或升级 Brave Pro（$3/1000）|
| Path B 被 IG 反爬 | `_IG_CONCURRENCY` 3 → 1，`_random_delay` 放宽回 5-15s |
| 头像还是不显示 | 看 `/api/image-proxy` 502 → DB URL 坏 → 触发 avatar 回填或手动重抓 |
| LLM 出 query 全语言错 | `_fallback_queries` 兜底（base + 5 后缀变体）|

---

## 10. 关键代码指针

| 模块 | 位置 |
|---|---|
| 主入口（双路径切换） | `server/app/agents/scraper.py:_scrape_instagram`（行 1881-2104） |
| Path A Apify 流水线 | `server/app/agents/scraper.py:_scrape_instagram_via_apify`（行 1745-1879） |
| Apify HTTP 调用 | `server/app/agents/scraper.py:_scrape_via_apify`（行 1620-1742） |
| Path B Playwright SSR | `server/app/agents/scraper.py:_scrape_instagram` 行 1972-2104 |
| Brave 发现 + dork 生成 | `server/app/agents/scraper.py:_discover_ig_profiles`（行 1326-1443） |
| 多语种 dork 模板 | `server/app/agents/scraper.py:_IG_DORK_TEMPLATES_*`（行 1048-1082） |
| Profile metadata 抽取 | `server/app/agents/scraper.py:_extract_instagram_profile_metadata`（行 1446） |
| Linktree URL 检测 | `server/app/agents/scraper.py:_extract_linktree_url` + `_LINK_AGGREGATOR_RE`（行 1097, 1508） |
| Aggregator email 抽取 | `server/app/agents/scraper.py:_scrape_aggregator_emails`（行 1513，4 平台共用） |
| Brave 搜索 | `server/app/agents/scraper.py:_search_brave`（4 平台共用，含 `url_filter` 参数） |
| Settings UI 后端 | `server/app/api/settings.py`（含 Apify 4 平台 token+actor） |
| Settings UI 前端 | `client/src/pages/SettingsPage.tsx`（4 平台卡片，IG 第 2 张） |
| 图片代理 | `server/app/api/image_proxy.py` + 前端 `AvatarBadge._needsProxy` |
| 4D scoring prompt | `server/app/prompts/scraper/enrich_results.system.md` |

---

## 11. 实测命中率参考

| niche | target | wall time | 实际 valid | 路径 |
|---|---|---|---|---|
| ai tools | 5 | ~3 min | 6/5 | Path A |
| ai developer | 10 | ~4 min | 9/10 | Path A |
| Canva / ChatGPT 类 | 5 | 2-4 min | 5+/5 | Path A |
| 旧版 hashtag explore（已废）| 5 | 失败 | **0/5** | 旧 SSR |
| Path B 任意 niche | 10 | 4-5 min | 1-3/10 | Path B（5-10% hit）|

**Apify Path A 的命中率上限取决于 Brave SERP 给出多少 high-quality profile URL**：商业化关键词（`<brand> review/tutorial`）70%+，纯 niche 名（`Power Bank`）30-40%，超长尾 niche 可能不够候选池触发 universal dork retry。

---

## 12. 与其他 4 平台共享的基础设施

- `_search_brave`（含 `url_filter` 参数，IG 默认 `_ig_profile_url_from_href`）
- `_scrape_aggregator_emails`（Linktree 等 16 种 aggregator 抽 email，Twitter / Facebook 也用）
- `is_junk_email`（domain + local-part 黑名单）
- `_mx_valid`（DNS MX，module-level cache）
- `_normalize_actor_id`（Apify URL `/` → `~` 防呆）
- `[INFO]/[WARN]/[ERROR]` 严重度警告前缀
- `StatusPill` 派生 partial（new < target × 0.7）
- 警告阈值 `< target × 0.7`（4 平台公共，2026-04-26 改）
- 图片代理 + per-host Referer 映射

---

## 13. 没做的事（积压）

- **登录 cookie opt-in**（对称 YouTube 那条路径）：用 IG 小号 cookies 解锁 SSR 私密字段。⚠ IG 对登录号反爬远严于 YouTube，先上住宅代理再说
- **Apify 多 actor fallback**：当前单 actor `apify~instagram-profile-scraper`，挂了直接 Path B。可加 `dtrungtin/instagram-scraper`、`zuzka/instagram-scraper` 等候补
- **Path A 命中率诊断**：Apify 返 0 profile 时区分"actor 挂了"vs"username 提取错"vs"profile 真的不存在"，目前都返空
- **Path B 加 Apify 走过但 0 商务联系的 profile cascade**：当前如果 Apify 返了 profile 但 emails=0 + externalUrl 不是 aggregator，就直接放弃。可考虑 Playwright 访问 SSR 当兜底（命中可能仍低，要测 ROI）

---

## 附录 A：双路径决策树

```
入口：_scrape_instagram(industry, target_count, target_market, ...)
    ↓
discovery：_discover_ig_profiles → all_profiles
    ↓
cross-task DB dedup + shuffle → profile_urls
    ↓
resolve_apify_credentials(db, "instagram") → (apify_token, apify_actor)
    ↓
    ┌─────────────────────────────┬─────────────────────────────┐
    ↓                             ↓                             ↓
  token 有                      token 无                      profile_urls 空
    ↓                             ↓                             ↓
Path A：                       Path B：                       直接返回
_scrape_instagram_via_apify    Playwright SSR per profile     warning 写日志
batch HTTP POST                concurrency=3, budget=18s
   ↓                              ↓
4 层 email source              2 层 email source
(biz/pub/bio/Linktree)         (bio regex / Linktree)
   ↓                              ↓
on_found → DB                  on_found → DB
```

---

## 附录 B：Apify Plan & 成本估算

| Plan | 月费 | 月度 credit | 单 IG 任务成本 | 月度任务上限 |
|---|---|---|---|---|
| **FREE** | $0 | $5 | ~$0.05 / 50 profile batch | ~100 任务 |
| **Personal** | $49 | $49 | 同 FREE | ~980 任务 |
| **Team** | $499 | $500 | 同 FREE | ~10000 任务 |

实测：单任务 target=10 通常 ~$0.05-0.15（候选池 50-150 profile，跑两批 Apify 调用平均 $0.10）。

**FREE plan 25 个并发 actor run 上限**：单用户多任务并发 → 触发 429 → quota_errors_out 报告 → 等几分钟重试。

---

## 附录 C：dork 模板示例（5 语种）

```python
# en
'site:instagram.com "{q}" email "@"'
'site:instagram.com "{q}"'

# cn / tw（共享中文限定词）
'site:instagram.com "{q}" email "@"'
'site:instagram.com "{q}"'
'site:instagram.com "{q}" "合作"'

# jp
'site:instagram.com "{q}" email "@"'
'site:instagram.com "{q}"'
'site:instagram.com "{q}" "お仕事"'

# kr
'site:instagram.com "{q}" email "@"'
'site:instagram.com "{q}"'
'site:instagram.com "{q}" "협업"'
```

**为什么 en 没有专属"business inquiries"限定词**：2026-04-25 5-expert review 实测发现 `"Power Bank" "business inquiries"` dork 全候选池 0 命中、`"Power Bank" email "@"` 返 13 个 — `business inquiries` 是营销话术不是 IG bio 高频词。slimmer set 把 75% 浪费的 Brave quota 还给真有效的两条。
