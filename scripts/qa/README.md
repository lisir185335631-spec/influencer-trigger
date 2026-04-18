# QA Scripts

手动/半自动化 QA 脚本。CI 可调用。

## smoke-frontend.sh

对应 PRD SM-2 —— **前台 11 个页面回归冒烟测试**。

每个页面验证 3 件事：
1. 路由存在（HTTP 200）
2. console 无 error 级别输出（JS runtime error）
3. React root 挂载（不是白屏）

### 前置

1. 后端跑着（默认 6002）
2. 前端 dev server 跑着（默认 6001）
3. 装 gstack/browse（项目已用，路径默认 `~/.claude/skills/gstack/browse/dist/browse-win.sh`）
4. 有一个 admin 账号

### 跑

```bash
# 默认 admin/admin123
./scripts/qa/smoke-frontend.sh

# 指定账号
ADMIN_USER=me ADMIN_PASS=mypw ./scripts/qa/smoke-frontend.sh

# 自定义端口
BACKEND_PORT=8000 FRONTEND_PORT=3000 ./scripts/qa/smoke-frontend.sh
```

### 产出

- 控制台：每条路由 PASS/FAIL 汇总
- `scripts/qa/smoke-results-YYYYMMDD-HHMMSS/`：每页截图 + chain log

### 退出码

- 0: 全通过
- 1: 登录失败
- 2: 有页面 runtime error 或 React root 未挂
- 3: 依赖工具缺失（gstack/browse 没装）

### 触发时机

- PR 合并 main 前跑一次（手动或 CI）
- 前端大改动后（路由、登录流、全局组件）
- 升级依赖（React/Vite/react-router）后
- 部署到 staging 前

### 不覆盖什么

- **业务功能**（创建任务、发邮件、合并网红等）—— 需要真实数据 + 长流程自动化，这个脚本是冒烟级别
- **Admin 后台页面**（/admin/*）—— 已有 pytest 集成测试覆盖 API 层；前端后台页面在 PR #1 里都通过了 Validator 浏览器测试
- **移动端适配** —— 只测 desktop viewport
- **性能** —— 用 scripts/benchmark/admin-overview.k6.js

### 局限

- 只检测"能加载 + React root 挂着"，不保证业务按钮点下去真能用
- gstack/browse 的 console 日志抓取可能因浏览器版本差异误判
- `/influencers`、`/follow-up` 等路由名可能和 App.tsx 实际定义不一致（前台路由用动态 path 构建，脚本硬编码的路径表需要偶尔对照 App.tsx 更新）
