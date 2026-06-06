#!/usr/bin/env bash
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STARTER="${APP_DIR}/start_public.sh"

RESTART_DELAY_SEC="${RESTART_DELAY_SEC:-5}"
MAX_RESTARTS="${MAX_RESTARTS:-0}"
ONESHOT="${ONESHOT:-0}"
PUBLIC_PROVIDER="${PUBLIC_PROVIDER:-auto}"

LOG_DIR="${APP_DIR}/ci_logs"
WRAP_LOG="${WRAP_LOG:-${LOG_DIR}/keiba_public_wrapper.log}"
ENABLE_CAFFEINATE="${ENABLE_CAFFEINATE:-1}"
CAFFEINATE_BIN="${CAFFEINATE_BIN:-$(command -v caffeinate || true)}"
CAFFEINATE_ARGS="${CAFFEINATE_ARGS:--dimsu}"

mkdir -p "${LOG_DIR}"

if [[ ! -x "${STARTER}" ]]; then
  echo "[FAIL] starter not executable: ${STARTER}" >&2
  exit 2
fi

CHILD_PID=""
CAFFEINATE_PID=""

cleanup() {
  local code=$?
  if [[ -n "${CHILD_PID}" ]]; then
    kill "${CHILD_PID}" >/dev/null 2>&1 || true
    wait "${CHILD_PID}" >/dev/null 2>&1 || true
  fi
  if [[ -n "${CAFFEINATE_PID}" ]]; then
    kill "${CAFFEINATE_PID}" >/dev/null 2>&1 || true
    wait "${CAFFEINATE_PID}" >/dev/null 2>&1 || true
  fi
  exit "${code}"
}
trap cleanup INT TERM EXIT

restart_count=0

echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] wrapper start provider=${PUBLIC_PROVIDER}" | tee -a "${WRAP_LOG}"
if [[ "${ENABLE_CAFFEINATE}" == "1" ]]; then
  if [[ -n "${CAFFEINATE_BIN}" && -x "${CAFFEINATE_BIN}" ]]; then
    # Prevent idle sleep while the public wrapper is active. Lid-close sleep on MacBook is not bypassed.
    read -r -a CAFFEINATE_ARGV <<< "${CAFFEINATE_ARGS}"
    "${CAFFEINATE_BIN}" "${CAFFEINATE_ARGV[@]}" -w $$ >/dev/null 2>&1 &
    CAFFEINATE_PID=$!
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] caffeinate enabled args=${CAFFEINATE_ARGS}" | tee -a "${WRAP_LOG}"
  else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] caffeinate requested but not found" | tee -a "${WRAP_LOG}"
  fi
fi

while true; do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] launching start_public.sh" | tee -a "${WRAP_LOG}"

  PUBLIC_PROVIDER="${PUBLIC_PROVIDER}" "${STARTER}" >>"${WRAP_LOG}" 2>&1 &
  CHILD_PID=$!
  wait "${CHILD_PID}"
  rc=$?
  CHILD_PID=""

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] starter exited rc=${rc}" | tee -a "${WRAP_LOG}"

  if [[ "${ONESHOT}" == "1" ]]; then
    exit "${rc}"
  fi

  restart_count=$((restart_count + 1))
  if [[ "${MAX_RESTARTS}" != "0" && ${restart_count} -ge ${MAX_RESTARTS} ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] reached MAX_RESTARTS=${MAX_RESTARTS}" | tee -a "${WRAP_LOG}"
    exit 0
  fi

  sleep "${RESTART_DELAY_SEC}"
done
