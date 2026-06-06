#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
PROFILE="hot"
PY_BIN="${PY_BIN:-}"

if [[ "${1:-}" == "--stable" ]]; then
  PROFILE="stable"
  shift
fi

PORT="${1:-8511}"
MAX_PORT="${2:-8520}"
STATUS_PATH="${STATUS_PATH:-$APP_DIR/data/local_runtime_status.json}"

if [[ -z "$PY_BIN" ]]; then
  if [[ -x "${HOME}/.pyenv/versions/3.10.13/bin/python3" ]]; then
    PY_BIN="${HOME}/.pyenv/versions/3.10.13/bin/python3"
  else
    PY_BIN="$(command -v python3)"
  fi
fi

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

cd "$APP_DIR"
if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  ALT_PORT="$(find_free_port "$PORT" "$MAX_PORT" || true)"
  if [[ -z "${ALT_PORT:-}" ]]; then
    echo "ERROR: ${PORT}-${MAX_PORT} の範囲で空きポートが見つかりません。"
    exit 1
  fi
  if [[ "$ALT_PORT" != "$PORT" ]]; then
    echo "INFO: ポート $PORT は使用中のため $ALT_PORT に切り替えます。"
    PORT="$ALT_PORT"
  fi
fi

if [[ "$PROFILE" == "stable" ]]; then
  exec "$APP_DIR/run_keiba_stable.sh" "$PORT" "$MAX_PORT"
fi

"$PY_BIN" - "$STATUS_PATH" "$PORT" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path

status_path = Path(sys.argv[1])
port = sys.argv[2]
payload = {
    "mode": "local_hot_reload",
    "profile": "hot",
    "run_on_save": True,
    "file_watcher_type": "auto",
    "local_url": f"http://127.0.0.1:{port}",
    "updated_at": datetime.now().isoformat(timespec="seconds"),
}
status_path.parent.mkdir(parents=True, exist_ok=True)
status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

echo "INFO: 起動URL -> http://127.0.0.1:${PORT}"
exec "$PY_BIN" -m streamlit run "$APP_DIR/app.py" \
  --server.port "$PORT" \
  --server.address 127.0.0.1 \
  --server.headless true \
  --server.runOnSave true \
  --server.fileWatcherType auto \
  --browser.gatherUsageStats false
