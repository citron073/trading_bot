#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
STATUS_PATH="${APP_DIR}/data/public_tunnel_status.json"
HEALTH_PATH="${APP_DIR}/data/public_health_status.json"
WATCH_PATH="${APP_DIR}/data/public_watch_state.json"
LOCAL_STATUS_PATH="${APP_DIR}/data/local_runtime_status.json"
PY_BIN="${PY_BIN:-}"

if [[ -z "$PY_BIN" ]]; then
  if [[ -x "${HOME}/.pyenv/versions/3.10.13/bin/python3" ]]; then
    PY_BIN="${HOME}/.pyenv/versions/3.10.13/bin/python3"
  else
    PY_BIN="$(command -v python3)"
  fi
fi

cd "$APP_DIR"

"$APP_DIR/uninstall_public_watch_launchagent.sh" >/dev/null 2>&1 || true
"$APP_DIR/uninstall_public_launchagent.sh" >/dev/null 2>&1 || true

"$PY_BIN" - "$STATUS_PATH" "$APP_DIR" <<'PY'
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

status_path = Path(sys.argv[1])
app_dir = sys.argv[2]
if not status_path.exists():
    payload = {}
else:
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}

def safe_kill(pid_value: object, expected_tokens: tuple[str, ...]) -> None:
    try:
        pid = int(pid_value)
    except Exception:
        return
    try:
        cmd = subprocess.check_output(["ps", "-p", str(pid), "-o", "command="], text=True).strip()
    except Exception:
        return
    if not cmd:
        return
    if not any(token in cmd for token in expected_tokens):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        return

safe_kill(payload.get("tunnel_pid"), ("cloudflared", "ngrok"))
safe_kill(payload.get("streamlit_pid"), ("KEIBA/app.py", "streamlit run"))

try:
    ps_text = subprocess.check_output(["ps", "aux"], text=True)
except Exception:
    raise SystemExit(0)

for line in ps_text.splitlines():
    if app_dir not in line:
        continue
    if "streamlit run" not in line:
        continue
    parts = line.split(None, 10)
    if len(parts) < 2:
        continue
    safe_kill(parts[1], ("KEIBA/app.py", "streamlit run"))
PY

"$PY_BIN" - "$STATUS_PATH" "$HEALTH_PATH" "$WATCH_PATH" "$LOCAL_STATUS_PATH" <<'PY'
import json
import sys
from datetime import datetime
from pathlib import Path

public_paths = [Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])]
local_status_path = Path(sys.argv[4])

for path in public_paths:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")

payload = {
    "mode": "local_ready",
    "profile": "hot",
    "run_on_save": True,
    "file_watcher_type": "auto",
    "local_url": "http://127.0.0.1:8511",
    "updated_at": datetime.now().isoformat(timespec="seconds"),
}
local_status_path.parent.mkdir(parents=True, exist_ok=True)
local_status_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

echo "[OK] KEIBA をローカル確認モードに切り替えました"
echo "[INFO] 次のコマンドで起動してください"
echo "cd ~/trading_bot/trading_bot/KEIBA && ./run_keiba.sh"
