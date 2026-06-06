#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

PY_BIN="${PY_BIN:-python3}"
NGROK_BIN="${NGROK_BIN:-ngrok}"
LOCAL_HOST="${LOCAL_HOST:-127.0.0.1}"
PORT="${PORT:-8511}"
MAX_PORT="${MAX_PORT:-8520}"
STREAMLIT_LOG="${STREAMLIT_LOG:-$APP_DIR/run_keiba_public_streamlit.log}"
NGROK_LOG="${NGROK_LOG:-$APP_DIR/run_keiba_public_ngrok.log}"
STATUS_PATH="${STATUS_PATH:-$APP_DIR/data/public_tunnel_status.json}"

STREAMLIT_STARTED_BY_SCRIPT=0
NGROK_STARTED_BY_SCRIPT=0
STREAMLIT_PID=""
NGROK_PID=""
ACTIVE_PORT=""

usage() {
  cat <<'USAGE'
Usage:
  ./start_public_ngrok.sh

Environment variables:
  NGROK_BIN      ngrok command path (default: ngrok)
  LOCAL_HOST     local bind host (default: 127.0.0.1)
  PORT           preferred local port (default: 8511)
  MAX_PORT       fallback port upper bound (default: 8520)
  STREAMLIT_LOG  streamlit log path
  NGROK_LOG      ngrok log path
  STATUS_PATH    public url status json path
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

get_matching_public_url() {
  local target_addr="$1"
  "$PY_BIN" - "$target_addr" <<'PY'
import json
import sys
import urllib.request

target = sys.argv[1].strip()

def variants(addr: str) -> set[str]:
    value = addr.strip()
    out = {value}
    if value.startswith("http://"):
        out.add(value[len("http://"):])
    elif value.startswith("https://"):
        out.add(value[len("https://"):])
    else:
        out.add(f"http://{value}")
        out.add(f"https://{value}")
    return out

target_set = variants(target)
url = "http://127.0.0.1:4040/api/tunnels"
try:
    with urllib.request.urlopen(url, timeout=0.8) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    for tunnel in payload.get("tunnels", []):
        public_url = str(tunnel.get("public_url", "")).strip()
        config = tunnel.get("config") or {}
        addr = str(config.get("addr", "")).strip()
        if public_url.startswith("https://") and (variants(addr) & target_set):
            print(public_url)
            break
except Exception:
    pass
PY
}

get_any_tunnel_info() {
  "$PY_BIN" - <<'PY'
import json
import urllib.request

url = "http://127.0.0.1:4040/api/tunnels"
try:
    with urllib.request.urlopen(url, timeout=0.8) as resp:
        payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    for tunnel in payload.get("tunnels", []):
        public_url = str(tunnel.get("public_url", "")).strip()
        config = tunnel.get("config") or {}
        addr = str(config.get("addr", "")).strip()
        if public_url.startswith("https://"):
            print(f"{public_url}\t{addr}")
            break
except Exception:
    pass
PY
}

write_status() {
  local public_url="$1"
  local local_url="$2"
  mkdir -p "$(dirname "$STATUS_PATH")"
  "$PY_BIN" - "$STATUS_PATH" "$public_url" "$local_url" "$NGROK_PID" "$STREAMLIT_PID" "$ACTIVE_PORT" <<'PY'
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
    "provider": "ngrok",
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
  if [[ "$NGROK_STARTED_BY_SCRIPT" == "1" && -n "${NGROK_PID:-}" ]]; then
    kill "$NGROK_PID" >/dev/null 2>&1 || true
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

if ! command -v "$NGROK_BIN" >/dev/null 2>&1; then
  echo "[ERROR] ngrok not found."
  echo "[HINT] brew install ngrok"
  echo "[HINT] ngrok config add-authtoken <YOUR_TOKEN>"
  exit 1
fi

echo "[INFO] KEIBA root: $APP_DIR"
echo "[INFO] preferred local target: http://${LOCAL_HOST}:${PORT}"
echo "[INFO] logs:"
echo "  - $STREAMLIT_LOG"
echo "  - $NGROK_LOG"

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
PUBLIC_URL="$(get_matching_public_url "$TARGET_ADDR")"
if [[ -n "$PUBLIC_URL" ]]; then
  echo "[INFO] reusing existing ngrok tunnel for ${TARGET_ADDR}: ${PUBLIC_URL}"
else
  EXISTING_TUNNEL_INFO="$(get_any_tunnel_info)"
  if [[ -n "$EXISTING_TUNNEL_INFO" ]]; then
    IFS=$'\t' read -r EXISTING_PUBLIC_URL EXISTING_ADDR <<< "$EXISTING_TUNNEL_INFO"
    echo "[WARN] existing ngrok tunnel points to ${EXISTING_ADDR:-unknown} (${EXISTING_PUBLIC_URL:-unknown})"
    echo "[HINT] if tunnel creation fails, stop it first: pkill -f ngrok"
  fi

  echo "[INFO] starting ngrok tunnel..."
  "$NGROK_BIN" http "$TARGET_ADDR" >"$NGROK_LOG" 2>&1 &
  NGROK_PID=$!
  NGROK_STARTED_BY_SCRIPT=1
  echo "[INFO] ngrok pid=$NGROK_PID"

  for _ in $(seq 1 120); do
    PUBLIC_URL="$(get_matching_public_url "$TARGET_ADDR")"
    if [[ -n "$PUBLIC_URL" ]]; then
      break
    fi
    sleep 0.25
  done
fi

if [[ -z "$PUBLIC_URL" ]]; then
  echo "[ERROR] ngrok public URL not found."
  echo "[HINT] open inspector: http://127.0.0.1:4040"
  echo "[HINT] tail -n 120 $NGROK_LOG"
  tail -n 120 "$NGROK_LOG" || true
  exit 4
fi

write_status "$PUBLIC_URL" "$LOCAL_URL"

echo "[OK] local url:   ${LOCAL_URL}"
echo "[OK] public url:  ${PUBLIC_URL}"
echo "[INFO] free ngrok has browser warning page and small usage limits."
echo "[INFO] app sidebar also shows this URL while the tunnel is running."
echo "[INFO] press Ctrl+C to stop streamlit and ngrok."

if [[ "$NGROK_STARTED_BY_SCRIPT" == "1" ]]; then
  wait "$NGROK_PID"
else
  while true; do
    if [[ -z "$(get_matching_public_url "$TARGET_ADDR")" ]]; then
      echo "[WARN] ngrok tunnel for ${TARGET_ADDR} is gone."
      exit 5
    fi
    sleep 2
  done
fi
