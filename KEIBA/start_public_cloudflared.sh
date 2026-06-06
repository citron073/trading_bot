#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

PY_BIN="${PY_BIN:-python3}"
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-cloudflared}"
LOCAL_HOST="${LOCAL_HOST:-127.0.0.1}"
PORT="${PORT:-8511}"
MAX_PORT="${MAX_PORT:-8520}"
CLOUDFLARED_PROTOCOL="${CLOUDFLARED_PROTOCOL:-http2}"
STREAMLIT_LOG="${STREAMLIT_LOG:-$APP_DIR/run_keiba_public_streamlit.log}"
CLOUDFLARED_LOG="${CLOUDFLARED_LOG:-$APP_DIR/run_keiba_public_cloudflared.log}"
STATUS_PATH="${STATUS_PATH:-$APP_DIR/data/public_tunnel_status.json}"

STREAMLIT_STARTED_BY_SCRIPT=0
CLOUDFLARED_STARTED_BY_SCRIPT=0
STREAMLIT_PID=""
CLOUDFLARED_PID=""
ACTIVE_PORT=""

usage() {
  cat <<'USAGE'
Usage:
  ./start_public_cloudflared.sh

Environment variables:
  CLOUDFLARED_BIN  cloudflared command path (default: cloudflared)
  LOCAL_HOST       local bind host (default: 127.0.0.1)
  PORT             preferred local port (default: 8511)
  MAX_PORT         fallback port upper bound (default: 8520)
  CLOUDFLARED_PROTOCOL protocol for quick tunnel (default: http2)
  STREAMLIT_LOG    streamlit log path
  CLOUDFLARED_LOG  cloudflared log path
  STATUS_PATH      public url status json path
USAGE
}

find_free_port() {
  local start="$1"
  local last="$2"
  local p
  for ((p=start; p<=last; p++)); do
    if ! lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
      echo "$p"
      return 0
    fi
  done
  return 1
}

find_listener_pid() {
  local port="$1"
  lsof -t -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1
}

is_keiba_streamlit_pid() {
  local pid="${1:-}"
  local cmd=""
  if [[ -z "$pid" ]]; then
    return 1
  fi
  cmd="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$cmd" == *"streamlit run ${APP_DIR}/app.py"* ]]
}

health_check() {
  local port="$1"
  curl -fsS "http://${LOCAL_HOST}:${port}/_stcore/health" >/dev/null 2>&1
}

find_existing_streamlit_port() {
  local p
  local pid
  for ((p=PORT; p<=MAX_PORT; p++)); do
    if health_check "$p"; then
      pid="$(find_listener_pid "$p" || true)"
      if is_keiba_streamlit_pid "$pid"; then
        echo "$p"
        return 0
      fi
    fi
  done
  return 1
}

find_existing_cloudflared_pid() {
  local target_addr="$1"
  ps ax -o pid= -o command= | awk -v target="$target_addr" '
    $0 ~ /cloudflared tunnel --url/ && index($0, target) > 0 {print $1; exit}
  '
}

extract_public_url() {
  "$PY_BIN" - "$CLOUDFLARED_LOG" <<'PY'
import re
import sys
from pathlib import Path

log_path = Path(sys.argv[1])
if not log_path.exists():
    raise SystemExit(0)
text = log_path.read_text(encoding="utf-8", errors="replace")
matches = re.findall(r"https://[-a-z0-9]+\.trycloudflare\.com", text, flags=re.IGNORECASE)
if matches:
    print(matches[-1])
PY
}

write_status() {
  local public_url="$1"
  local local_url="$2"
  mkdir -p "$(dirname "$STATUS_PATH")"
  "$PY_BIN" - "$STATUS_PATH" "$public_url" "$local_url" "$CLOUDFLARED_PID" "$STREAMLIT_PID" "$ACTIVE_PORT" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path

status_path = Path(sys.argv[1])
public_url = sys.argv[2]
local_url = sys.argv[3]
tunnel_pid = sys.argv[4]
streamlit_pid = sys.argv[5]
active_port = sys.argv[6]
now = datetime.now().isoformat(timespec="seconds")
payload = {
    "provider": "cloudflared",
    "public_url": public_url,
    "local_url": local_url,
    "started_at": now,
    "updated_at": now,
    "tunnel_pid": tunnel_pid,
    "streamlit_pid": streamlit_pid,
    "port": active_port,
}
status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

cleanup() {
  local code=$?
  rm -f "$STATUS_PATH" >/dev/null 2>&1 || true
  if [[ "$CLOUDFLARED_STARTED_BY_SCRIPT" == "1" && -n "${CLOUDFLARED_PID:-}" ]]; then
    kill "$CLOUDFLARED_PID" >/dev/null 2>&1 || true
  fi
  if [[ "$STREAMLIT_STARTED_BY_SCRIPT" == "1" && -n "${STREAMLIT_PID:-}" ]]; then
    kill "$STREAMLIT_PID" >/dev/null 2>&1 || true
  fi
  exit "$code"
}
trap cleanup INT TERM EXIT

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v "$CLOUDFLARED_BIN" >/dev/null 2>&1; then
  echo "[ERROR] cloudflared not found."
  echo "[HINT] brew install cloudflared"
  exit 1
fi

echo "[INFO] KEIBA root: $APP_DIR"
echo "[INFO] preferred local target: http://${LOCAL_HOST}:${PORT}"
echo "[INFO] logs:"
echo "  - $STREAMLIT_LOG"
echo "  - $CLOUDFLARED_LOG"

if ACTIVE_PORT="$(find_existing_streamlit_port)"; then
  STREAMLIT_PID="$(find_listener_pid "$ACTIVE_PORT" || true)"
  echo "[INFO] reusing existing streamlit on ${LOCAL_HOST}:${ACTIVE_PORT}"
else
  ACTIVE_PORT="$(find_free_port "$PORT" "$MAX_PORT" || true)"
  if [[ -z "$ACTIVE_PORT" ]]; then
    echo "[ERROR] ${PORT}-${MAX_PORT} の範囲で空きポートが見つかりません。"
    exit 2
  fi
  echo "[INFO] starting streamlit on ${LOCAL_HOST}:${ACTIVE_PORT}..."
  "$PY_BIN" -m streamlit run "$APP_DIR/app.py" \
    --server.address "$LOCAL_HOST" \
    --server.port "$ACTIVE_PORT" \
    --server.headless true \
    --server.runOnSave false \
    --server.fileWatcherType none \
    --browser.gatherUsageStats false >"$STREAMLIT_LOG" 2>&1 &
  STREAMLIT_PID=$!
  STREAMLIT_STARTED_BY_SCRIPT=1
  echo "[INFO] streamlit pid=$STREAMLIT_PID"

  for _ in $(seq 1 120); do
    if health_check "$ACTIVE_PORT"; then
      break
    fi
    sleep 0.25
  done
fi

if ! health_check "$ACTIVE_PORT"; then
  echo "[ERROR] streamlit health check failed at ${LOCAL_HOST}:${ACTIVE_PORT}"
  echo "[HINT] tail -n 80 $STREAMLIT_LOG"
  tail -n 80 "$STREAMLIT_LOG" || true
  exit 3
fi

TARGET_ADDR="http://${LOCAL_HOST}:${ACTIVE_PORT}"
LOCAL_URL="${TARGET_ADDR}"
PUBLIC_URL=""
EXISTING_CLOUDFLARED_PID="$(find_existing_cloudflared_pid "$TARGET_ADDR" || true)"
if [[ -n "$EXISTING_CLOUDFLARED_PID" ]]; then
  CLOUDFLARED_PID="$EXISTING_CLOUDFLARED_PID"
  PUBLIC_URL="$(extract_public_url)"
  if [[ -n "$PUBLIC_URL" ]]; then
    echo "[INFO] reusing existing cloudflared pid=$CLOUDFLARED_PID"
  fi
fi

if [[ -z "$PUBLIC_URL" ]]; then
  rm -f "$CLOUDFLARED_LOG"
  echo "[INFO] starting cloudflared quick tunnel (protocol=${CLOUDFLARED_PROTOCOL})..."
  "$CLOUDFLARED_BIN" tunnel --protocol "$CLOUDFLARED_PROTOCOL" --url "$TARGET_ADDR" >"$CLOUDFLARED_LOG" 2>&1 &
  CLOUDFLARED_PID=$!
  CLOUDFLARED_STARTED_BY_SCRIPT=1
  echo "[INFO] cloudflared pid=$CLOUDFLARED_PID"

  for _ in $(seq 1 160); do
    if ! kill -0 "$CLOUDFLARED_PID" >/dev/null 2>&1; then
      break
    fi
    PUBLIC_URL="$(extract_public_url)"
    if [[ -n "$PUBLIC_URL" ]]; then
      break
    fi
    sleep 0.25
  done
fi

if [[ -z "$PUBLIC_URL" ]]; then
  echo "[ERROR] Cloudflare public URL not found."
  echo "[HINT] tail -n 120 $CLOUDFLARED_LOG"
  tail -n 120 "$CLOUDFLARED_LOG" || true
  exit 4
fi

write_status "$PUBLIC_URL" "$LOCAL_URL"

echo "[OK] local url:   ${LOCAL_URL}"
echo "[OK] public url:  ${PUBLIC_URL}"
echo "[INFO] mode: Cloudflare Quick Tunnel"
echo "[INFO] URL is random and changes each time you start it."
echo "[INFO] keep this terminal open while sharing the app."

if [[ "$CLOUDFLARED_STARTED_BY_SCRIPT" == "1" ]]; then
  wait "$CLOUDFLARED_PID"
else
  while kill -0 "$CLOUDFLARED_PID" >/dev/null 2>&1; do
    sleep 2
  done
fi
