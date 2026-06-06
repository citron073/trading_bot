#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

ENV_FILE_DEFAULT="$APP_DIR/.cloudflared/keiba_named_tunnel.env"
ENV_FILE="${ENV_FILE:-$ENV_FILE_DEFAULT}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

PY_BIN="${PY_BIN:-python3}"
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-cloudflared}"
LOCAL_HOST="${CF_LOCAL_HOST:-127.0.0.1}"
PORT="${CF_LOCAL_PORT:-8511}"
MAX_PORT="${CF_LOCAL_MAX_PORT:-8520}"
TUNNEL_NAME="${CF_TUNNEL_NAME:-}"
TUNNEL_UUID="${CF_TUNNEL_UUID:-}"
TUNNEL_HOSTNAME="${CF_TUNNEL_HOSTNAME:-}"
TUNNEL_CREDENTIALS_FILE="${CF_TUNNEL_CREDENTIALS_FILE:-}"
STREAMLIT_LOG="${STREAMLIT_LOG:-$APP_DIR/run_keiba_public_streamlit.log}"
CLOUDFLARED_LOG="${CLOUDFLARED_LOG:-$APP_DIR/run_keiba_public_cloudflared_named.log}"
STATUS_PATH="${STATUS_PATH:-$APP_DIR/data/public_tunnel_status.json}"
CONFIG_DIR="${CONFIG_DIR:-$APP_DIR/.cloudflared}"
GENERATED_CONFIG_PATH="${GENERATED_CONFIG_PATH:-$CONFIG_DIR/generated_keiba_named_tunnel.yml}"

STREAMLIT_STARTED_BY_SCRIPT=0
CLOUDFLARED_STARTED_BY_SCRIPT=0
STREAMLIT_PID=""
CLOUDFLARED_PID=""
ACTIVE_PORT=""

usage() {
  cat <<'USAGE'
Usage:
  ./start_public_cloudflared_named.sh

Required env vars:
  CF_TUNNEL_NAME
  CF_TUNNEL_UUID
  CF_TUNNEL_HOSTNAME
  CF_TUNNEL_CREDENTIALS_FILE

Optional env file:
  KEIBA/.cloudflared/keiba_named_tunnel.env
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

write_status() {
  local public_url="$1"
  local local_url="$2"
  mkdir -p "$(dirname "$STATUS_PATH")"
  "$PY_BIN" - "$STATUS_PATH" "$public_url" "$local_url" "$TUNNEL_HOSTNAME" "$CLOUDFLARED_PID" "$STREAMLIT_PID" "$ACTIVE_PORT" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path

status_path = Path(sys.argv[1])
public_url = sys.argv[2]
local_url = sys.argv[3]
hostname = sys.argv[4]
tunnel_pid = sys.argv[5]
streamlit_pid = sys.argv[6]
active_port = sys.argv[7]
now = datetime.now().isoformat(timespec="seconds")
payload = {
    "provider": "cloudflared_named",
    "public_url": public_url,
    "local_url": local_url,
    "hostname": hostname,
    "started_at": now,
    "updated_at": now,
    "tunnel_pid": tunnel_pid,
    "streamlit_pid": streamlit_pid,
    "port": active_port,
}
status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY
}

render_config() {
  mkdir -p "$CONFIG_DIR"
  cat >"$GENERATED_CONFIG_PATH" <<EOF
tunnel: $TUNNEL_UUID
credentials-file: $TUNNEL_CREDENTIALS_FILE

ingress:
  - hostname: $TUNNEL_HOSTNAME
    service: http://$LOCAL_HOST:$ACTIVE_PORT
  - service: http_status:404
EOF
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

for name in TUNNEL_NAME TUNNEL_UUID TUNNEL_HOSTNAME TUNNEL_CREDENTIALS_FILE; do
  if [[ -z "${!name:-}" ]]; then
    echo "[ERROR] missing required setting: $name"
    echo "[HINT] run ./setup_named_tunnel.sh and fill $ENV_FILE"
    exit 2
  fi
done

if [[ ! -f "$TUNNEL_CREDENTIALS_FILE" ]]; then
  echo "[ERROR] credentials file not found: $TUNNEL_CREDENTIALS_FILE"
  exit 3
fi

echo "[INFO] KEIBA root: $APP_DIR"
echo "[INFO] tunnel name: $TUNNEL_NAME"
echo "[INFO] hostname: https://$TUNNEL_HOSTNAME"
echo "[INFO] env file: $ENV_FILE"
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
    exit 4
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
  exit 5
fi

render_config
TARGET_ADDR="http://${LOCAL_HOST}:${ACTIVE_PORT}"
LOCAL_URL="${TARGET_ADDR}"
rm -f "$CLOUDFLARED_LOG"

echo "[INFO] starting named cloudflared tunnel..."
"$CLOUDFLARED_BIN" tunnel --config "$GENERATED_CONFIG_PATH" run "$TUNNEL_NAME" >"$CLOUDFLARED_LOG" 2>&1 &
CLOUDFLARED_PID=$!
CLOUDFLARED_STARTED_BY_SCRIPT=1
echo "[INFO] cloudflared pid=$CLOUDFLARED_PID"

for _ in $(seq 1 80); do
  if ! kill -0 "$CLOUDFLARED_PID" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

if ! kill -0 "$CLOUDFLARED_PID" >/dev/null 2>&1; then
  echo "[ERROR] named tunnel exited early."
  echo "[HINT] tail -n 120 $CLOUDFLARED_LOG"
  tail -n 120 "$CLOUDFLARED_LOG" || true
  exit 6
fi

write_status "https://$TUNNEL_HOSTNAME" "$LOCAL_URL"

echo "[OK] local url:   ${LOCAL_URL}"
echo "[OK] public url:  https://${TUNNEL_HOSTNAME}"
echo "[INFO] mode: Cloudflare named tunnel (fixed URL)"
echo "[INFO] keep this terminal open while sharing the app."

wait "$CLOUDFLARED_PID"
