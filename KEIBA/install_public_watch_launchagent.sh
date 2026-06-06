#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCHER="${APP_DIR}/keiba_public_watch.py"

LABEL="com.ouroboros.keiba.public.watch"
INTERVAL_SEC=60
LAUNCH_DIR="${HOME}/Library/LaunchAgents"

usage() {
  cat <<'USAGE'
Usage:
  ./install_public_watch_launchagent.sh [options]

Options:
  --label NAME          LaunchAgent label (default: com.ouroboros.keiba.public.watch)
  --interval-sec N      Watch interval in seconds (default: 60)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)
      LABEL="$2"
      shift 2
      ;;
    --interval-sec)
      INTERVAL_SEC="$2"
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

python3 - <<'PY' "${INTERVAL_SEC}"
import sys
v = int(sys.argv[1])
if v < 60:
    raise SystemExit("[FAIL] --interval-sec must be >= 60")
PY

if [[ ! -f "${WATCHER}" ]]; then
  echo "[FAIL] watcher not found: ${WATCHER}" >&2
  exit 2
fi

mkdir -p "${LAUNCH_DIR}" "${APP_DIR}/ci_logs"
PLIST_PATH="${LAUNCH_DIR}/${LABEL}.plist"
UID_NUM="$(id -u)"
PY_BIN="$(command -v python3 || true)"
PATH_VAL="${PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

if [[ -z "${PY_BIN}" ]]; then
  PY_BIN="/usr/bin/python3"
fi

if [[ -f "${PLIST_PATH}" ]]; then
  launchctl bootout "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl unload "${PLIST_PATH}" >/dev/null 2>&1 || true
  rm -f "${PLIST_PATH}"
fi

cat > "${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>${LABEL}</string>

    <key>ProgramArguments</key>
    <array>
      <string>${PY_BIN}</string>
      <string>${WATCHER}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${APP_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key><string>${PATH_VAL}</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>StartInterval</key>
    <integer>${INTERVAL_SEC}</integer>

    <key>StandardOutPath</key>
    <string>${APP_DIR}/ci_logs/launchd_keiba_public_watch_out.log</string>
    <key>StandardErrorPath</key>
    <string>${APP_DIR}/ci_logs/launchd_keiba_public_watch_err.log</string>
  </dict>
</plist>
PLIST

chmod 644 "${PLIST_PATH}"

launchctl bootstrap "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl load "${PLIST_PATH}"
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" >/dev/null 2>&1 || true

echo "[OK] KEIBA public watch launch agent installed"
echo "[INFO] label=${LABEL}"
echo "[INFO] plist=${PLIST_PATH}"
echo "[INFO] inspect: launchctl print gui/${UID_NUM}/${LABEL}"
echo "[INFO] logs: ${APP_DIR}/ci_logs/launchd_keiba_public_watch_out.log"
echo "[INFO] remove: ${APP_DIR}/uninstall_public_watch_launchagent.sh --label ${LABEL}"
