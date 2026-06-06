#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_PROVIDER="auto"
WATCH_INTERVAL_SEC=60
RESTART_DELAY_SEC=5
ENABLE_CAFFEINATE=1
CAFFEINATE_ARGS="-dimsu"

usage() {
  cat <<'USAGE'
Usage:
  ./install_public_resilient_mode.sh [options]

Options:
  --provider NAME         auto|cloudflared|cloudflared_named|ngrok (default: auto)
  --watch-interval-sec N  Health watch interval seconds (default: 60)
  --restart-delay-sec N   Restart delay seconds for wrapper (default: 5)
  --no-keep-awake         Disable caffeinate
  --caffeinate-args ARG   caffeinate flags (default: -dimsu)
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider)
      PUBLIC_PROVIDER="$2"
      shift 2
      ;;
    --watch-interval-sec)
      WATCH_INTERVAL_SEC="$2"
      shift 2
      ;;
    --restart-delay-sec)
      RESTART_DELAY_SEC="$2"
      shift 2
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

cd "$APP_DIR"

PUBLIC_ARGS=(
  --provider "$PUBLIC_PROVIDER"
  --restart-delay-sec "$RESTART_DELAY_SEC"
)
if [[ "$ENABLE_CAFFEINATE" == "1" ]]; then
  PUBLIC_ARGS+=(--keep-awake --caffeinate-args "$CAFFEINATE_ARGS")
else
  PUBLIC_ARGS+=(--no-keep-awake)
fi

"$APP_DIR/install_public_launchagent.sh" "${PUBLIC_ARGS[@]}"
"$APP_DIR/install_public_watch_launchagent.sh" --interval-sec "$WATCH_INTERVAL_SEC"

echo "[OK] KEIBA resilient public mode installed"
echo "[INFO] provider=${PUBLIC_PROVIDER}"
echo "[INFO] watch_interval_sec=${WATCH_INTERVAL_SEC}"
echo "[INFO] keep_awake=${ENABLE_CAFFEINATE}"
echo "[INFO] healthcheck: ${APP_DIR}/keiba_public_healthcheck.sh"
echo "[INFO] note: MacBook を閉じると通常はスリープします。lid close を避けるか、固定運用は常時起動マシン/VPSへ移してください。"
