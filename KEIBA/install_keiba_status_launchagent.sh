#!/bin/bash
# install_keiba_status_launchagent.sh
# KEIBA ステータスサーバー (port 8789) を macOS LaunchAgent として登録する

set -e

LABEL="com.ouroboros.keiba.status-server"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3)"
SERVER_SCRIPT="${SCRIPT_DIR}/keiba_status_server.py"
LOG_DIR="${SCRIPT_DIR}/ci_logs"
STATUS_HOST="${KEIBA_STATUS_HOST:-0.0.0.0}"
ACTION_TOKEN="${KEIBA_DASHBOARD_ACTION_TOKEN:-}"
ACTION_DISABLED="${KEIBA_ACTIONS_DISABLED:-0}"

mkdir -p "$LOG_DIR"

if [ ! -f "$SERVER_SCRIPT" ]; then
  echo "ERROR: ${SERVER_SCRIPT} が見つかりません"
  exit 1
fi

# 既存の agent を停止
if launchctl list | grep -q "$LABEL"; then
  echo "既存の LaunchAgent を停止中..."
  launchctl unload "$PLIST" 2>/dev/null || true
fi

cat > "$PLIST" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON}</string>
    <string>${SERVER_SCRIPT}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/keiba_status_server.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/keiba_status_server_err.log</string>
  <key>WorkingDirectory</key>
  <string>${SCRIPT_DIR}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>KEIBA_STATUS_HOST</key>
    <string>${STATUS_HOST}</string>
    <key>KEIBA_DASHBOARD_ACTION_TOKEN</key>
    <string>${ACTION_TOKEN}</string>
    <key>KEIBA_ACTIONS_DISABLED</key>
    <string>${ACTION_DISABLED}</string>
  </dict>
  <key>ThrottleInterval</key>
  <integer>10</integer>
</dict>
</plist>
PLIST_EOF

launchctl load "$PLIST"
echo "✅ LaunchAgent インストール完了: ${LABEL}"
echo "   bind:    ${STATUS_HOST}:8789"
echo "   local:   http://127.0.0.1:8789/keiba-status.json"
echo "   ログ:     ${LOG_DIR}/keiba_status_server.log"
echo ""
echo "停止するには:"
echo "   launchctl unload ${PLIST}"
