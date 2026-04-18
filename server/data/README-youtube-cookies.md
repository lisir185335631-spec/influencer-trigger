# YouTube 登录 Cookie 配置（可选）

未登录访问 YouTube 时，频道 "View email address" 按钮**不会显示**，导致 scraper
拿不到该按钮后面的邮箱（创作者专门设置的商务联系方式）。

加载登录 cookie 后，scraper 以登录用户身份访问频道 About 页，"View email
address" 按钮点击后能拿到真实邮箱 → **命中率能显著提高**。

## 配置步骤

### 1. 导出 cookie

**方法 A：Chrome 插件（推荐）**

1. Chrome / Edge 登录你的 YouTube 账号（**建议用小号**，避免主号被标风险）
2. 安装插件 **"Cookie Editor"** 或 **"EditThisCookie"**
3. 打开 `https://www.youtube.com`，点插件图标
4. 选 "Export" → "Export as JSON"
5. 复制 JSON 内容

**方法 B：Playwright 手动登录**

```python
# server 目录下跑一次：
.venv/Scripts/python -c "
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=False)  # 有界面
        ctx = await b.new_context()
        page = await ctx.new_page()
        await page.goto('https://accounts.google.com/signin')
        print('请在弹出的浏览器里登录 YouTube，完成后按 Enter...')
        input()
        state = await ctx.storage_state()
        import json
        with open('data/youtube-cookies.json', 'w') as f:
            json.dump(state, f, indent=2)
        print('已保存 cookies 到 data/youtube-cookies.json')
        await b.close()

asyncio.run(main())
"
```

### 2. 保存为 `server/data/youtube-cookies.json`

两种格式都支持：

**格式 1：Playwright storage_state**
```json
{
  "cookies": [
    {"name": "SAPISID", "value": "...", "domain": ".youtube.com", "path": "/"},
    ...
  ],
  "origins": [...]
}
```

**格式 2：原生 cookie 数组**
```json
[
  {"name": "SAPISID", "value": "...", "domain": ".youtube.com", "path": "/"},
  ...
]
```

关键字段：`name / value / domain / path` 必须有；`expires / httpOnly / secure / sameSite` 可选。

### 3. 重启 backend

```
pkill 掉 uvicorn ; 再启
```

新抓取任务的 scraper log 会打：

```
[YouTube] loaded 42 cookies for authenticated scraping
```

未配 cookie 时会打：

```
[YouTube] no cookies.json — running anonymous (some emails hidden)
```

## 安全提示

- `youtube-cookies.json` **会被 `.gitignore` 忽略**（`server/data/*.json` 已在 ignore 里）—— 不会进 git
- 包含登录态，**泄漏等于账号被盗**。不要分享这个文件，不要截图里暴露
- 建议用**小号**登录，不要用主号
- Cookie 每 30-60 天会过期；过期后 scraper 会 fallback 到匿名模式，重新导入一份即可

## 不想配置？

不配也能用，只是命中率低一些。配完一次能让 scraper 额外多抓 30-50% 的频道联系方式。

---

scraper 会自动检测文件存在与否；安全 fallback；无需改代码。
