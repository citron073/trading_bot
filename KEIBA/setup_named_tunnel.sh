#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

TEMPLATE_PATH="$APP_DIR/cloudflared_templates/keiba_named_tunnel.env.example"
TARGET_DIR="$APP_DIR/.cloudflared"
TARGET_PATH="$TARGET_DIR/keiba_named_tunnel.env"

mkdir -p "$TARGET_DIR"

if [[ ! -f "$TARGET_PATH" ]]; then
  cp "$TEMPLATE_PATH" "$TARGET_PATH"
  echo "[OK] created: $TARGET_PATH"
else
  echo "[INFO] already exists: $TARGET_PATH"
fi

cat <<EOF

次の順で一度だけ設定してください。

1. Cloudflare にログイン
   cloudflared tunnel login

2. トンネル作成
   cloudflared tunnel create keiba

3. 固定URLをDNSへ紐付け
   cloudflared tunnel route dns keiba keiba.example.com

4. 生成された UUID と credentials file のパスを
   $TARGET_PATH
   に記入

5. 起動
   cd ~/trading_bot/trading_bot/KEIBA
   PUBLIC_PROVIDER=cloudflared_named ./start_public.sh

補足:
- CF_TUNNEL_HOSTNAME には実際に使いたい固定URLを入れてください
- credentials file は通常 ~/.cloudflared/<UUID>.json です
- この env ファイルは .gitignore 済みです
EOF
