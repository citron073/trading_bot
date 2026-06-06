#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="${APP_DIR}/keiba_public_wrapper.sh"

LABEL="com.ouroboros.keiba.public"
RESTART_DELAY_SEC=5
MAX_RESTARTS=0
ONESHOT=0
PUBLIC_PROVIDER="auto"
ENABLE_CAFFEINATE=1
CAFFEINATE_ARGS="-dimsu"
LAUNCH_DIR="${HOME}/Library/LaunchAgents"

usage() {
  cat <<'USAGE'
Usage:
  ./install_public_launchagent.sh [options]

Options:
  --label NAME            LaunchAgent label (default: com.ouroboros.keiba.public)
  --restart-delay-sec N   Restart delay seconds (default: 5)
  --max-restarts N        0=infinite (default: 0)
  --oneshot               Run once then stop
  --provider NAME         auto|cloudflared|cloudflared_named|ngrok (default: auto)
  --keep-awake            Enable caffeinate while public app is running (default)
  --no-keep-awake         Disable caffeinate
  --caffeinate-args ARG   caffeinate flags (default: -dimsu)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --label)
      LABEL="$2"
      shift 2
      ;;
    --restart-delay-sec)
      RESTART_DELAY_SEC="$2"
      shift 2
      ;;
    --max-restarts)
      MAX_RESTARTS="$2"
      shift 2
      ;;
    --oneshot)
      ONESHOT=1
      shift
      ;;
    --provider)
      PUBLIC_PROVIDER="$2"
      shift 2
      ;;
    --keep-awake)
      ENABLE_CAFFEINATE=1
      shift
      ;;
    --no-keep-awake)
      ENABLE_CAFFEINATE=0
      shift
      ;;
    --caffeinate-args)
      CAFFEINATE_ARGS="$2"
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

python3 - <<'PY' "${RESTART_DELAY_SEC}" "${MAX_RESTARTS}"
import sys
r = int(sys.argv[1])
m = int(sys.argv[2])
if r < 1:
    raise SystemExit("[FAIL] --restart-delay-sec must be >= 1")
if m < 0:
    raise SystemExit("[FAIL] --max-restarts must be >= 0")
PY

if [[ ! -x "${WRAPPER}" ]]; then
  echo "[FAIL] wrapper not executable: ${WRAPPER}" >&2
  exit 2
fi

mkdir -p "${LAUNCH_DIR}" "${APP_DIR}/ci_logs"
PLIST_PATH="${LAUNCH_DIR}/${LABEL}.plist"
UID_NUM="$(id -u)"
PY_BIN="$(command -v python3 || true)"
CLOUDFLARED_BIN="$(command -v cloudflared || true)"
NGROK_BIN="$(command -v ngrok || true)"
CAFFEINATE_BIN="$(command -v caffeinate || true)"
PATH_VAL="${PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

if [[ -z "${PY_BIN}" ]]; then
  PY_BIN="/usr/bin/python3"
fi
if [[ -z "${CLOUDFLARED_BIN}" && -x "/opt/homebrew/bin/cloudflared" ]]; then
  CLOUDFLARED_BIN="/opt/homebrew/bin/cloudflared"
fi
if [[ -z "${NGROK_BIN}" && -x "/opt/homebrew/bin/ngrok" ]]; then
  NGROK_BIN="/opt/homebrew/bin/ngrok"
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
      <string>${WRAPPER}</string>
    </array>

    <key>WorkingDirectory</key>
    <string>${APP_DIR}</string>

    <key>EnvironmentVariables</key>
    <dict>
      <key>RESTART_DELAY_SEC</key><string>${RESTART_DELAY_SEC}</string>
      <key>MAX_RESTARTS</key><string>${MAX_RESTARTS}</string>
      <key>ONESHOT</key><string>${ONESHOT}</string>
      <key>PUBLIC_PROVIDER</key><string>${PUBLIC_PROVIDER}</string>
      <key>ENABLE_CAFFEINATE</key><string>${ENABLE_CAFFEINATE}</string>
      <key>CAFFEINATE_ARGS</key><string>${CAFFEINATE_ARGS}</string>
      <key>PY_BIN</key><string>${PY_BIN}</string>
      <key>PATH</key><string>${PATH_VAL}</string>
PLIST

if [[ -n "${CLOUDFLARED_BIN}" ]]; then
  cat >> "${PLIST_PATH}" <<PLIST
      <key>CLOUDFLARED_BIN</key><string>${CLOUDFLARED_BIN}</string>
PLIST
fi
if [[ -n "${NGROK_BIN}" ]]; then
  cat >> "${PLIST_PATH}" <<PLIST
      <key>NGROK_BIN</key><string>${NGROK_BIN}</string>
PLIST
fi
if [[ -n "${CAFFEINATE_BIN}" ]]; then
  cat >> "${PLIST_PATH}" <<PLIST
      <key>CAFFEINATE_BIN</key><string>${CAFFEINATE_BIN}</string>
PLIST
fi

cat >> "${PLIST_PATH}" <<PLIST
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>${APP_DIR}/ci_logs/launchd_keiba_public_out.log</string>
    <key>StandardErrorPath</key>
    <string>${APP_DIR}/ci_logs/launchd_keiba_public_err.log</string>
  </dict>
</plist>
PLIST

chmod 644 "${PLIST_PATH}"

launchctl bootstrap "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl load "${PLIST_PATH}"
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" >/dev/null 2>&1 || true

echo "[OK] KEIBA public launch agent installed"
echo "[INFO] label=${LABEL}"
echo "[INFO] plist=${PLIST_PATH}"
echo "[INFO] wrapper=${WRAPPER}"
echo "[INFO] keep_awake=${ENABLE_CAFFEINATE} (${CAFFEINATE_ARGS})"
echo "[INFO] note: MacBook の lid close sleep は caffeinate でも回避できません"
echo "[INFO] inspect: launchctl print gui/${UID_NUM}/${LABEL}"
echo "[INFO] remove: ${APP_DIR}/uninstall_public_launchagent.sh --label ${LABEL}"
