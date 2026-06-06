#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="${APP_DIR}/keiba_auto_cycle.py"
LABEL="com.ouroboros.keiba.localauto"
INTERVAL_SEC=1800
MONTHS_BACK=24
WEEKLY_DAYS_AHEAD=7
HISTORY_BACKFILL_DAYS=2
ENTRIES_CACHE_HOURS=4
WEATHER_CACHE_HOURS=6
ENABLE_TUNING=0
SKIP_ENTRIES=1
LLM_TIMEOUT_SEC=20
LLM_MODEL="qwen2.5:1.5b"
LLM_REVIEW_MODEL="qwen2.5:0.5b"
LLM_REVIEW_TIMEOUT_SEC=45
MAX_LLM_RACES=4
WEEKLY_SIMULATIONS=1200
WEEKLY_REFRESH_MINUTES=180
LAUNCH_DIR="${HOME}/Library/LaunchAgents"
CONFIG_PATH="${APP_DIR}/data/auto_cycle_config.json"

usage() {
  cat <<'USAGE'
Usage:
  ./install_local_auto_launchagent.sh [options]

Options:
  --label NAME                 LaunchAgent label
  --interval-sec N             Run interval seconds (default: 1800)
  --months-back N              History months back (default: 24)
  --weekly-days-ahead N        Weekly days ahead (default: 7)
  --history-backfill-days N    Backfill days for results (default: 2)
  --entries-cache-hours N      Weekly entries cache hours (default: 4)
  --weather-cache-hours N      Weather cache hours (default: 6)
  --llm-model NAME             Local LLM model for race picks (default: qwen2.5:1.5b)
  --llm-review-model NAME      Local LLM model for review text (default: qwen2.5:0.5b)
  --llm-timeout-sec N          Local LLM timeout seconds (default: 20)
  --llm-review-timeout-sec N   Local LLM review timeout seconds (default: 45)
  --max-llm-races N            Max races sent to local LLM per cycle (default: 4)
  --weekly-simulations N       Weekly prediction simulations per race (default: 1200)
  --weekly-refresh-minutes N   Skip weekly prediction rebuild while fresh (default: 180)
  --no-tuning                  Disable tuning in scheduled runs
  --skip-entries               Skip weekly entries refresh in scheduled runs
  既定: no-tuning + skip-entries
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
    --months-back)
      MONTHS_BACK="$2"
      shift 2
      ;;
    --weekly-days-ahead)
      WEEKLY_DAYS_AHEAD="$2"
      shift 2
      ;;
    --history-backfill-days)
      HISTORY_BACKFILL_DAYS="$2"
      shift 2
      ;;
    --entries-cache-hours)
      ENTRIES_CACHE_HOURS="$2"
      shift 2
      ;;
    --weather-cache-hours)
      WEATHER_CACHE_HOURS="$2"
      shift 2
      ;;
    --llm-timeout-sec)
      LLM_TIMEOUT_SEC="$2"
      shift 2
      ;;
    --llm-model)
      LLM_MODEL="$2"
      shift 2
      ;;
    --llm-review-model)
      LLM_REVIEW_MODEL="$2"
      shift 2
      ;;
    --llm-review-timeout-sec)
      LLM_REVIEW_TIMEOUT_SEC="$2"
      shift 2
      ;;
    --max-llm-races)
      MAX_LLM_RACES="$2"
      shift 2
      ;;
    --weekly-simulations)
      WEEKLY_SIMULATIONS="$2"
      shift 2
      ;;
    --weekly-refresh-minutes)
      WEEKLY_REFRESH_MINUTES="$2"
      shift 2
      ;;
    --no-tuning)
      ENABLE_TUNING=0
      shift
      ;;
    --skip-entries)
      SKIP_ENTRIES=1
      shift
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

if [[ ! -f "${SCRIPT_PATH}" ]]; then
  echo "[FAIL] missing script: ${SCRIPT_PATH}" >&2
  exit 2
fi

PY_BIN="${PY_BIN:-}"
if [[ -z "${PY_BIN}" ]]; then
  if [[ -x "${HOME}/.pyenv/versions/3.10.13/bin/python3" ]]; then
    PY_BIN="${HOME}/.pyenv/versions/3.10.13/bin/python3"
  else
    PY_BIN="$(command -v python3)"
  fi
fi

mkdir -p "${LAUNCH_DIR}" "${APP_DIR}/ci_logs" "${APP_DIR}/data"
PLIST_PATH="${LAUNCH_DIR}/${LABEL}.plist"
UID_NUM="$(id -u)"
PATH_VAL="${PATH:-/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin}"

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
      <string>${SCRIPT_PATH}</string>
      <string>--months-back</string>
      <string>${MONTHS_BACK}</string>
      <string>--weekly-days-ahead</string>
      <string>${WEEKLY_DAYS_AHEAD}</string>
      <string>--history-backfill-days</string>
      <string>${HISTORY_BACKFILL_DAYS}</string>
      <string>--entries-cache-hours</string>
      <string>${ENTRIES_CACHE_HOURS}</string>
      <string>--weather-cache-hours</string>
      <string>${WEATHER_CACHE_HOURS}</string>
      <string>--llm-model</string>
      <string>${LLM_MODEL}</string>
      <string>--llm-review-model</string>
      <string>${LLM_REVIEW_MODEL}</string>
      <string>--llm-timeout-sec</string>
      <string>${LLM_TIMEOUT_SEC}</string>
      <string>--llm-review-timeout-sec</string>
      <string>${LLM_REVIEW_TIMEOUT_SEC}</string>
      <string>--max-llm-races</string>
      <string>${MAX_LLM_RACES}</string>
      <string>--weekly-simulations</string>
      <string>${WEEKLY_SIMULATIONS}</string>
      <string>--weekly-refresh-minutes</string>
      <string>${WEEKLY_REFRESH_MINUTES}</string>
PLIST

if [[ "${ENABLE_TUNING}" == "0" ]]; then
  cat >> "${PLIST_PATH}" <<PLIST
      <string>--no-tuning</string>
PLIST
fi
if [[ "${SKIP_ENTRIES}" == "1" ]]; then
  cat >> "${PLIST_PATH}" <<PLIST
      <string>--skip-entries</string>
PLIST
fi

cat >> "${PLIST_PATH}" <<PLIST
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
    <string>${APP_DIR}/ci_logs/launchd_keiba_local_auto_out.log</string>
    <key>StandardErrorPath</key>
    <string>${APP_DIR}/ci_logs/launchd_keiba_local_auto_err.log</string>
  </dict>
</plist>
PLIST

chmod 644 "${PLIST_PATH}"

"${PY_BIN}" - <<'PY' "${CONFIG_PATH}" "${LABEL}" "${INTERVAL_SEC}" "${ENABLE_TUNING}" "${SKIP_ENTRIES}" "${LLM_TIMEOUT_SEC}" "${MAX_LLM_RACES}" "${WEEKLY_SIMULATIONS}" "${WEEKLY_REFRESH_MINUTES}" "${LLM_MODEL}" "${LLM_REVIEW_MODEL}" "${LLM_REVIEW_TIMEOUT_SEC}"
import json
import sys
from datetime import datetime
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "label": sys.argv[2],
    "interval_sec": int(sys.argv[3]),
    "run_tuning": bool(int(sys.argv[4])),
    "skip_entries": bool(int(sys.argv[5])),
    "llm_timeout_sec": int(sys.argv[6]),
    "max_llm_races": int(sys.argv[7]),
    "weekly_simulations": int(sys.argv[8]),
    "weekly_refresh_minutes": int(sys.argv[9]),
    "llm_model": sys.argv[10],
    "llm_review_model": sys.argv[11],
    "llm_review_timeout_sec": int(sys.argv[12]),
    "installed_at": datetime.now().isoformat(timespec="seconds"),
}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
PY

launchctl bootstrap "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl load "${PLIST_PATH}"
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}" >/dev/null 2>&1 || true

echo "[OK] KEIBA local auto launch agent installed"
echo "[INFO] label=${LABEL}"
echo "[INFO] interval_sec=${INTERVAL_SEC}"
echo "[INFO] plist=${PLIST_PATH}"
echo "[INFO] inspect: launchctl print gui/${UID_NUM}/${LABEL}"
echo "[INFO] remove: ${APP_DIR}/uninstall_local_auto_launchagent.sh --label ${LABEL}"
