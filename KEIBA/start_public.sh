#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

PUBLIC_PROVIDER="${PUBLIC_PROVIDER:-auto}"
NAMED_ENV_FILE="${ENV_FILE:-$APP_DIR/.cloudflared/keiba_named_tunnel.env}"

is_named_tunnel_value_valid() {
  local value="${1:-}"
  case "$value" in
    ""|replace-with-your-*|*.example.com|/Users/yourname/*)
      return 1
      ;;
    *)
      return 0
      ;;
  esac
}

has_named_tunnel_config() {
  if is_named_tunnel_value_valid "${CF_TUNNEL_NAME:-}" \
    && is_named_tunnel_value_valid "${CF_TUNNEL_UUID:-}" \
    && is_named_tunnel_value_valid "${CF_TUNNEL_HOSTNAME:-}" \
    && is_named_tunnel_value_valid "${CF_TUNNEL_CREDENTIALS_FILE:-}"; then
    return 0
  fi

  if [[ -f "$NAMED_ENV_FILE" ]]; then
    (
      set -a
      # shellcheck disable=SC1090
      source "$NAMED_ENV_FILE"
      set +a
      is_named_tunnel_value_valid "${CF_TUNNEL_NAME:-}" \
        && is_named_tunnel_value_valid "${CF_TUNNEL_UUID:-}" \
        && is_named_tunnel_value_valid "${CF_TUNNEL_HOSTNAME:-}" \
        && is_named_tunnel_value_valid "${CF_TUNNEL_CREDENTIALS_FILE:-}"
    )
    return $?
  fi

  return 1
}

case "$PUBLIC_PROVIDER" in
  auto)
    if command -v cloudflared >/dev/null 2>&1 && has_named_tunnel_config; then
      exec "$APP_DIR/start_public_cloudflared_named.sh" "$@"
    fi
    if command -v cloudflared >/dev/null 2>&1; then
      exec "$APP_DIR/start_public_cloudflared.sh" "$@"
    fi
    if command -v ngrok >/dev/null 2>&1; then
      exec "$APP_DIR/start_public_ngrok.sh" "$@"
    fi
    echo "[ERROR] neither cloudflared nor ngrok was found."
    echo "[HINT] stable/free first choice: brew install cloudflared"
    echo "[HINT] fallback: brew install ngrok"
    exit 1
    ;;
  cloudflared)
    exec "$APP_DIR/start_public_cloudflared.sh" "$@"
    ;;
  cloudflared_named)
    exec "$APP_DIR/start_public_cloudflared_named.sh" "$@"
    ;;
  ngrok)
    exec "$APP_DIR/start_public_ngrok.sh" "$@"
    ;;
  *)
    echo "[ERROR] unsupported PUBLIC_PROVIDER: $PUBLIC_PROVIDER"
    echo "[HINT] use PUBLIC_PROVIDER=cloudflared_named, PUBLIC_PROVIDER=cloudflared, PUBLIC_PROVIDER=ngrok, or omit it."
    exit 2
    ;;
esac
