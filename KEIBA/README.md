# KEIBA (独立版)

このフォルダは競馬予想アプリ専用です。`MAIN` のトレード機能とは分離されています。

## 起動
```bash
cd ~/trading_bot/trading_bot/KEIBA
./run_keiba.sh
```

開くURL:
- `http://127.0.0.1:8511`
- もし `8511` が使用中なら、`run_keiba.sh` が空きポートへ自動切替し、起動ログにURLを表示します。
- 既定は `Hot Reload ON` です。保存後にローカル画面で反映確認しやすい設定になっています。

ポート変更:
```bash
./run_keiba.sh 8512
```

安定優先で自動反映を切る:
```bash
./run_keiba.sh --stable
```

外部公開を止めてローカル確認へ戻す:
```bash
cd ~/trading_bot/trading_bot/KEIBA
./switch_to_local_mode.sh
./run_keiba.sh
```

## 外部公開（無料）
安定重視なら `cloudflared` を優先してください。`start_public.sh` は `cloudflared` が入っていればそちらを使い、なければ `ngrok` にフォールバックします。

```bash
brew install cloudflared
cd ~/trading_bot/trading_bot/KEIBA
./start_public.sh
```

公開URLはターミナルに表示され、アプリのサイドバーにも表示されます。
`cloudflared` の Quick Tunnel は無料で警告ページもなく安定寄りですが、URLは起動ごとに変わります。
`ngrok` を使いたい場合は次です。

```bash
brew install ngrok
ngrok config add-authtoken <YOUR_TOKEN>
cd ~/trading_bot/trading_bot/KEIBA
PUBLIC_PROVIDER=ngrok ./start_public.sh
```

## 常駐化（止めずに使う）
macOS の `launchd` で公開プロセスを自動復旧させられます。

```bash
cd ~/trading_bot/trading_bot/KEIBA
./install_public_launchagent.sh
```

推奨の安定運用:

```bash
cd ~/trading_bot/trading_bot/KEIBA
./install_public_resilient_mode.sh
```

このモードは次をまとめて入れます。
- 公開LaunchAgent
- 60秒ごとの公開監視
- `caffeinate` によるアイドルスリープ抑止

重要:
- `caffeinate` は `MacBook を閉じたときのスリープ` までは防げません
- 外から安定して見せたいなら、`lid close` を避けるか、常時起動PC/VPSへ移す必要があります

状態確認:

```bash
cd ~/trading_bot/trading_bot/KEIBA
launchctl print gui/$(id -u)/com.ouroboros.keiba.public
./keiba_public_healthcheck.sh
```

停止/解除:

```bash
cd ~/trading_bot/trading_bot/KEIBA
./uninstall_public_launchagent.sh
./uninstall_public_watch_launchagent.sh
```

## 異常時通知
公開URLの異常だけでなく、Quick Tunnel の URL 変更も監視できます。
不健康になったときは、既定でトンネルPIDを落として自動再起動を試みます。

監視開始:

```bash
cd ~/trading_bot/trading_bot/KEIBA
./install_public_watch_launchagent.sh
```

既定では `60秒ごと` に監視します。

既定では macOS 通知を使います。`ntfy` / `webhook` を使いたい場合は、次のファイルを作成して設定してください。

```bash
cp .streamlit/keiba_public_notify.example.json .streamlit/keiba_public_notify.json
```

停止:

```bash
cd ~/trading_bot/trading_bot/KEIBA
./uninstall_public_watch_launchagent.sh
```

### 固定URLで安定運用（Cloudflare named tunnel）
Cloudflare 側に自分のドメインがあるなら、この方法が一番実用的です。

```bash
brew install cloudflared
cd ~/trading_bot/trading_bot/KEIBA
./setup_named_tunnel.sh
```

その後、一度だけ次を実行します。

```bash
cloudflared tunnel login
cloudflared tunnel create keiba
cloudflared tunnel route dns keiba keiba.example.com
```

`KEIBA/.cloudflared/keiba_named_tunnel.env` に `UUID / hostname / credentials file` を記入したら、起動はこれです。

```bash
cd ~/trading_bot/trading_bot/KEIBA
PUBLIC_PROVIDER=cloudflared_named ./start_public.sh
```

`PUBLIC_PROVIDER` を省略しても、名前付きトンネル設定ファイルがあれば自動で固定URLモードを優先します。

## データ整形
```bash
python3 tools/normalize_csv.py --mode history --in ./data/jra_history_raw.csv --out ./data/jra_history_normalized.csv
python3 tools/normalize_csv.py --mode entries --in ./data/jra_entries_raw.csv --out ./data/jra_entries_normalized.csv --default-weather 晴 --default-track 良 --default-distance 1600
```

## 自動取得 + 自動学習
まず一度:
```bash
pip install keibascraper
```

CLI一発更新（最新追記の高速運用）:
```bash
python3 tools/auto_update_data.py --months-back 24 --weekly-days-ahead 7 --incremental --append-only --history-backfill-days 0 --entries-cache-hours 4
```

## 定時自動運用
結果取得と再学習を定時で回したい場合は、ローカルの `launchd` を使います。

まず1回だけ確認実行:
```bash
cd ~/trading_bot/trading_bot/KEIBA
python3 keiba_auto_cycle.py
```

30分ごとに自動実行:
```bash
cd ~/trading_bot/trading_bot/KEIBA
./install_local_auto_launchagent.sh
```

既定は軽量運用です:
- `--skip-entries`
- `--no-tuning`

必要なときだけ重い処理を足してください:
```bash
python3 keiba_auto_cycle.py --run-tuning
python3 keiba_auto_cycle.py --refresh-entries
python3 keiba_auto_cycle.py --refresh-entries --run-tuning
```

間隔変更の例:
```bash
./install_local_auto_launchagent.sh --interval-sec 900
```

停止:
```bash
cd ~/trading_bot/trading_bot/KEIBA
./uninstall_local_auto_launchagent.sh
```

状態確認:
- サイドバー `定時自動運用`
- `data/auto_cycle_status.json`

## 統合ダッシュボード連携
`MAIN/tools/unified_dashboard.html` の `KEIBA 競馬` タブは、次のローカルAPIを参照します。

```bash
cd ~/trading_bot/trading_bot
python3 KEIBA/keiba_status_server.py
```

参照URL:
- `http://127.0.0.1:8789/keiba-status.json`

常駐化:

```bash
cd ~/trading_bot/trading_bot/KEIBA
./install_keiba_status_launchagent.sh
```

KEIBA側の運用SPECは `KEIBA/docs/KEIBA_SPEC_TABLE.md` を正とします。
統合ダッシュボードに出す項目を増やす場合は、先に `keiba_status_server.py` のJSONへ後方互換で追加してください。

アプリ側では、サイドバーの `最新だけ更新` が最速導線です。
過去データは `data/history_auto.csv` に蓄積され、以後は新規データだけ追記できます。
必要時だけ `学習だけ実行` または `取得→学習→予想を一括実行` を使ってください。
初回フル取得は時間がかかりますが、2回目以降は最新追記で短縮されます。
`天気予報を自動取得して反映` をONにすると、今週レースの天気を自動更新します（開催地が判定できるレースのみ）。
`更新後に今週AI予想を自動作成` をONにすると、今週全レースの本命馬一覧を自動で作成します。
Yahoo経由のレース一覧取得に失敗した場合は、netkeiba日次ページからの代替取得へ自動フォールバックします。
`ページ起動時に自動更新（1セッション1回）` をONにすると、画面を開いた時点で自動取得を走らせられます。
今週AI予想と単レース予想には `データ本命 / 大穴 / スピリチュアル` の3スタイル表示があります。

## 重み最適化
```bash
python3 tools/tune_feature_weights.py --history ./data/jra_history_normalized.csv --out ./data/keiba_best_weights.json --trials 40 --val-races 30 --simulations 1500
```

生成した `keiba_best_weights.json` はアプリのサイドバー `重みJSON（任意）` から読み込みます。

## 注意
- 起動ログに `Local URL` が出たら起動成功です。
- 終了は起動中ターミナルで `Ctrl+C`。
