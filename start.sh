#!/usr/bin/env bash
# ============================================================
# Influencer Trigger — One-click startup (Linux/macOS)
# Usage: ./start.sh
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$SCRIPT_DIR/server"
CLIENT_DIR="$SCRIPT_DIR/client"

echo "=============================="
echo " Influencer Trigger  startup"
echo "=============================="

# ---- 1. Check .env ----
if [ ! -f "$SERVER_DIR/.env" ]; then
  echo "[WARN] server/.env not found. Copying from .env.example..."
  cp "$SERVER_DIR/.env.example" "$SERVER_DIR/.env"
  echo "[WARN] Please edit server/.env before production use."
fi

# ---- 2. Ensure data directory ----
mkdir -p "$SERVER_DIR/data"

# ---- 3. Python virtualenv & dependencies ----
if [ ! -d "$SERVER_DIR/.venv" ]; then
  echo "[INFO] Creating Python virtualenv..."
  python3 -m venv "$SERVER_DIR/.venv"
fi

source "$SERVER_DIR/.venv/bin/activate"
echo "[INFO] Installing Python dependencies..."
pip install -q -r "$SERVER_DIR/requirements.txt"

# ---- 4. Start Redis (if not running) ----
if command -v redis-cli &>/dev/null && ! redis-cli ping &>/dev/null 2>&1; then
  echo "[INFO] Starting Redis..."
  redis-server --daemonize yes --logfile /tmp/redis-influencer.log
  sleep 1
else
  echo "[INFO] Redis already running or not installed (optional)."
fi

# ---- 5. Start FastAPI backend ----
echo "[INFO] Starting FastAPI backend on port 6002..."
cd "$SERVER_DIR"
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 6002 \
  > /tmp/influencer-backend.log 2>&1 &
BACKEND_PID=$!
echo "[INFO] Backend PID: $BACKEND_PID"

# Wait for backend to be ready
echo -n "[INFO] Waiting for backend..."
for i in $(seq 1 30); do
  if curl -sf http://localhost:6002/api/health &>/dev/null; then
    echo " ready!"
    break
  fi
  sleep 1
  echo -n "."
done

# ---- 6. Build & serve frontend (if nginx is not used) ----
if command -v nginx &>/dev/null; then
  echo "[INFO] Building frontend for nginx..."
  cd "$CLIENT_DIR"
  npm ci -q
  npm run build
  echo "[INFO] Frontend built. Configure nginx with nginx.conf in project root."
else
  echo "[INFO] Starting frontend dev server on port 6001..."
  cd "$CLIENT_DIR"
  npm ci -q
  nohup npm run dev > /tmp/influencer-frontend.log 2>&1 &
  FRONTEND_PID=$!
  echo "[INFO] Frontend PID: $FRONTEND_PID"
fi

echo ""
echo "=============================="
echo " Services started:"
echo "  Backend:  http://localhost:6002"
echo "  API docs: http://localhost:6002/docs"
if ! command -v nginx &>/dev/null; then
  echo "  Frontend: http://localhost:6001"
fi
echo ""
echo " Logs:"
echo "  Backend:  /tmp/influencer-backend.log"
echo "  Redis:    /tmp/redis-influencer.log"
echo "=============================="
