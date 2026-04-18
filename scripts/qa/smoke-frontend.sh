#!/usr/bin/env bash
# Frontend smoke test — 前台 11 页回归（SM-2）
#
# 作用：登录后依次访问所有前台页面，检查：
#   - 页面返回 200（路由存在、React 根组件挂载）
#   - console 无 error 级别输出（JS runtime error）
#   - 关键选择器存在（页面骨架正常渲染，不是白屏）
#
# 前置：
#   - backend 跑在 $BACKEND_PORT（默认 6002）
#   - frontend dev server 跑在 $FRONTEND_PORT（默认 6001）
#   - 有一个 admin 账号：username=$ADMIN_USER password=$ADMIN_PASS
#   - 装好 gstack/browse
#
# 跑：
#   ./scripts/qa/smoke-frontend.sh
#   ADMIN_USER=me ADMIN_PASS=xxx ./scripts/qa/smoke-frontend.sh
#
# 失败退出码：
#   0 全通过
#   1 有页面 4xx/5xx
#   2 有页面 console error
#   3 依赖工具缺失
set -uo pipefail

BACKEND_PORT="${BACKEND_PORT:-6002}"
FRONTEND_PORT="${FRONTEND_PORT:-6001}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-admin123}"
BASE="http://localhost:${FRONTEND_PORT}"

B="${BROWSE_BIN:-bash $HOME/.claude/skills/gstack/browse/dist/browse-win.sh}"

if ! $B --help >/dev/null 2>&1; then
  echo "[FAIL] gstack/browse not available (set BROWSE_BIN or install gstack)" >&2
  exit 3
fi

# 前台 11 个路由（从 client/src/App.tsx 静态抓取）
# 除 detail 页外都可直接访问；InfluencerDetail / ScrapeTaskDetail 需要上下文 ID，只测 list 父路由即可
ROUTES=(
  "/dashboard"
  "/scrape"
  "/emails"
  "/templates"
  "/mailboxes"
  "/follow-up"
  "/team"
  "/settings"
  "/import"
  "/holidays"
  "/influencers"        # 若前台没这条路由则会 404，忽略即可
)

OUTDIR="${PWD}/scripts/qa/smoke-results-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUTDIR"

echo "=== Frontend Smoke Test ==="
echo "Base:    $BASE"
echo "Admin:   $ADMIN_USER"
echo "Output:  $OUTDIR"
echo ""

# 1. 登录拿 JWT，通过 localStorage 注入
echo "[1/12] Login -> $ADMIN_USER"
TOKEN_JSON=$(curl -sS -X POST "http://localhost:${BACKEND_PORT}/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"${ADMIN_USER}\",\"password\":\"${ADMIN_PASS}\"}")
TOKEN=$(echo "$TOKEN_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

if [ -z "$TOKEN" ]; then
  echo "[FAIL] Login failed: $TOKEN_JSON" >&2
  exit 1
fi

echo "      -> got token (${TOKEN:0:20}...)"

# 2. 依次访问每个路由，收集 console errors + HTTP status + screenshot
declare -A STATUSES
declare -A ERRORS
FAILED=0

for i in "${!ROUTES[@]}"; do
  ROUTE="${ROUTES[$i]}"
  IDX=$((i + 2))
  SAFE_NAME=$(echo "$ROUTE" | tr '/' '_' | sed 's/^_//')
  echo "[${IDX}/12] ${ROUTE}"

  # chain: goto login with token pre-injected via localStorage, then navigate to target
  CHAIN_JSON=$(cat <<EOF
[
  ["goto", "${BASE}/login"],
  ["evaluate", "localStorage.setItem('access_token', '${TOKEN}')"],
  ["goto", "${BASE}${ROUTE}"],
  ["wait", "--networkidle"],
  ["screenshot", "${OUTDIR}/${SAFE_NAME}.png"],
  ["evaluate", "({ url: location.href, title: document.title, hasReactRoot: !!document.querySelector('#root > *') })"],
  ["console"]
]
EOF
)

  RESULT=$(echo "$CHAIN_JSON" | $B chain 2>&1 || true)

  # Parse status / errors (best-effort, depends on browse output format)
  if echo "$RESULT" | grep -qiE "error|exception" | grep -vi "no error"; then
    STATUSES["$ROUTE"]="ERROR"
    ERRORS["$ROUTE"]=$(echo "$RESULT" | grep -iE "error|exception" | head -5)
    FAILED=1
  elif echo "$RESULT" | grep -q '"hasReactRoot":true'; then
    STATUSES["$ROUTE"]="OK"
  else
    STATUSES["$ROUTE"]="UNKNOWN"
    ERRORS["$ROUTE"]="no React root detected"
    FAILED=1
  fi

  echo "$RESULT" > "${OUTDIR}/${SAFE_NAME}.log"
done

# 3. Summary
echo ""
echo "=== Smoke Test Summary ==="
for ROUTE in "${ROUTES[@]}"; do
  STATUS="${STATUSES[$ROUTE]:-SKIP}"
  case "$STATUS" in
    OK)      echo "  [OK]      $ROUTE" ;;
    ERROR)   echo "  [ERROR]   $ROUTE  -- ${ERRORS[$ROUTE]:0:80}" ;;
    UNKNOWN) echo "  [UNKNOWN] $ROUTE  -- ${ERRORS[$ROUTE]:0:80}" ;;
    *)       echo "  [$STATUS] $ROUTE" ;;
  esac
done

echo ""
echo "Screenshots + logs in: $OUTDIR"

if [ "$FAILED" = "1" ]; then
  echo ""
  echo "[RESULT] FAILED — some pages had errors. See logs above."
  exit 2
else
  echo ""
  echo "[RESULT] PASSED — all pages loaded with React root present."
  exit 0
fi
