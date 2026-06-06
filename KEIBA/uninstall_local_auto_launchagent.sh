#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.ouroboros.keiba.localauto"
LAUNCH_DIR="${HOME}/Library/LaunchAgents"
CONFIG_PATH="${APP_DIR}/data/auto_cycle_config.json"

usage() {
  cat <<'USAGE'
Usage:
  ./uninstall_local_auto_launchagent.sh [--label NAME]
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

PLIST_PATH="${LAUNCH_DIR}/${LABEL}.plist"
UID_NUM="$(id -u)"

if [[ -f "${PLIST_PATH}" ]]; then
  launchctl bootout "gui/${UID_NUM}" "${PLIST_PATH}" >/dev/null 2>&1 || launchctl unload "${PLIST_PATH}" >/dev/null 2>&1 || true
  rm -f "${PLIST_PATH}"
fi

rm -f "${CONFIG_PATH}"

echo "[OK] KEIBA local auto launch agent removed"
echo "[INFO] label=${LABEL}"
