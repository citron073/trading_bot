#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATUS_PATH="${STATUS_PATH:-$APP_DIR/data/public_tunnel_status.json}"
HEALTH_PATH="${HEALTH_PATH:-$APP_DIR/data/public_health_status.json}"
LABEL="${LABEL:-com.ouroboros.keiba.public}"
TIMEOUT_SEC="${TIMEOUT_SEC:-8}"

usage() {
  cat <<'USAGE'
Usage:
  ./keiba_public_healthcheck.sh [--label NAME]
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)
      LABEL="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[FAIL] unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

python3 - "$STATUS_PATH" "$HEALTH_PATH" "$LABEL" "$TIMEOUT_SEC" <<'PY'
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

status_path = Path(sys.argv[1])
health_path = Path(sys.argv[2])
label = sys.argv[3]
timeout_sec = float(sys.argv[4])

payload = {
    "checked_at": datetime.now().isoformat(timespec="seconds"),
    "label": label,
    "status_file_exists": status_path.exists(),
    "launchagent_loaded": None,
    "provider": "",
    "public_url": "",
    "local_url": "",
    "local_ok": None,
    "public_ok": None,
    "public_http_status": None,
    "message": "",
}

status_data = {}
if status_path.exists():
    try:
        status_data = json.loads(status_path.read_text(encoding="utf-8"))
    except Exception as exc:
        payload["message"] = f"status json parse failed: {exc}"

if isinstance(status_data, dict):
    payload["provider"] = str(status_data.get("provider", "") or "")
    payload["public_url"] = str(status_data.get("public_url", "") or "")
    payload["local_url"] = str(status_data.get("local_url", "") or "")

try:
    uid = subprocess.run(["id", "-u"], capture_output=True, text=True, timeout=1, check=True).stdout.strip()
    result = subprocess.run(
        ["launchctl", "print", f"gui/{uid}/{label}"],
        capture_output=True,
        text=True,
        timeout=2,
    )
    payload["launchagent_loaded"] = result.returncode == 0
except Exception:
    payload["launchagent_loaded"] = None

def check_url(url: str):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        return getattr(resp, "status", 200)

local_url = payload["local_url"].strip()
if local_url:
    parsed = urlparse(local_url)
    local_health = f"{parsed.scheme}://{parsed.netloc}/_stcore/health"
    try:
        payload["local_ok"] = check_url(local_health) == 200
    except Exception as exc:
        payload["local_ok"] = False
        if not payload["message"]:
            payload["message"] = f"local health failed: {exc}"

public_url = payload["public_url"].strip()
if public_url:
    try:
        status = check_url(public_url)
        payload["public_ok"] = 200 <= int(status) < 400
        payload["public_http_status"] = int(status)
    except urllib.error.HTTPError as exc:
        payload["public_ok"] = False
        payload["public_http_status"] = int(exc.code)
        if not payload["message"]:
            payload["message"] = f"public http error: {exc.code}"
    except Exception as exc:
        payload["public_ok"] = False
        if not payload["message"]:
            payload["message"] = f"public health failed: {exc}"

if not payload["message"]:
    payload["message"] = "ok"

health_path.parent.mkdir(parents=True, exist_ok=True)
health_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

print(f"checked_at={payload['checked_at']}")
print(f"provider={payload['provider'] or '-'}")
print(f"launchagent_loaded={payload['launchagent_loaded']}")
print(f"local_ok={payload['local_ok']}")
print(f"public_ok={payload['public_ok']}")
print(f"public_http_status={payload['public_http_status']}")
print(f"message={payload['message']}")
PY
