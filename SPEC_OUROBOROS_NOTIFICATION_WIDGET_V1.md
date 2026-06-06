# Project Ouroboros v1 — NOTIFICATION / WIDGET SPEC v1

============================================================
Project Ouroboros v1 における通知・ウィジェット表示の運用ルール
============================================================

------------------------------------------------------------
1. 目的
------------------------------------------------------------

Project Ouroboros v1 における通知・ウィジェット表示の責務、通知経路、運用境界を明文化する。

この SPEC は以下を目的とする。

- 通知元の見える化
- ウィジェット責務の明文化
- ntfy / macOS通知 / webhook の運用整理
- 将来の PWA / Swift アプリ化に備えた土台の固定

本 SPEC は売買ロジックや API 認証情報の仕様を定義しない。

------------------------------------------------------------
2. 対象ファイル
------------------------------------------------------------

ウィジェット系:

- `MAIN/tools/widget_status.py`
- `MAIN/widget/scriptable/OuroborosWidget.local.js`
- `MAIN/widget/scriptable/OuroborosWidget.js`
- `MAIN/WIDGETS.md`

通知系:

- `MAIN/ibkr_bot.py`
- `MAIN/tools/send_weekly_summary_ntfy.py`
- `MAIN/tools/smart_exit_report.py`
- `MAIN/tools/trade_event_notifier.py`
- `MAIN/dashboard.py`
- `MAIN/stock_shadow_weekly.py`
- `MAIN/stock_shadow_bot.py`
- `KEIBA/keiba_auto_cycle.py`
- `KEIBA/keiba_public_watch.py`

設定:

- `MAIN/.streamlit/secrets.toml`
- `KEIBA/.streamlit/keiba_public_notify.json`
- `KEIBA/data/auto_cycle_config.json`

------------------------------------------------------------
3. 通知経路
------------------------------------------------------------

現状の通知経路は以下。

| 経路 | 現状 | 用途 |
|---|---|---|
| ntfy | 実装済み | 日次/週次レポート、Bot異常、状態変化、KEIBA完了/異常、shadow通知 |
| macOS通知 | 実装済み | `KEIBA/keiba_public_watch.py` のローカル通知 |
| webhook | 部分実装 | `KEIBA/keiba_public_watch.py`、`MAIN/stock_shadow_weekly.py` |
| 将来拡張用 | 未実装 | Slack / Teams / Push / Mail など |

補足:

- `ntfy` は最優先の汎用通知経路とする
- `macOS通知` はローカル監視補助とする
- `webhook` は外部連携補助とする
- 複数経路に送る場合でも、同一イベントの意味を変えない

------------------------------------------------------------
4. 通知レベル
------------------------------------------------------------

通知レベルは以下の3段階に整理する。

| レベル | 意味 | 例 |
|---|---|---|
| INFO | 通常完了、状態共有、日次/週次サマリ | 週次サマリ、KEIBA予想完了、scanner outcome |
| WARN | API遅延、ログ更新遅延、軽微異常、確認推奨 | stale成果物、接続遅延、repeat unhealthy |
| CRITICAL | Bot停止、API接続不能、OPEN異常残存、損失上限接近、手動確認必須 | drift停止、取引自動再開、重大接続断、日次DD悪化 |

タグや Priority は transport ごとに持ってもよいが、意味上のレベルはこの3段階に揃える。

------------------------------------------------------------
5. 通知抑制ルール
------------------------------------------------------------

将来ルール:

- INFO: 原則1回
- WARN: 同一コードは30分抑制
- CRITICAL: 同一コードは10分抑制。ただし復旧通知は送る

現状:

- `trade_event_notifier.py` には既存の cooldown 制御がある
- `MAIN/tools/notification_policy.py` を共通ヘルパーとして追加し、INFO/WARN/CRITICAL の正規化、priority/tags、基本 cooldown を共通化した
- 現時点でこのヘルパーを使う通知元:
  - `MAIN/tools/send_weekly_summary_ntfy.py`
  - `MAIN/tools/smart_exit_report.py`
  - `MAIN/signal_scanner_outcome.py`
  - `MAIN/stock_shadow_weekly.py`
  - `MAIN/stock_shadow_bot.py`
  - `MAIN/ibkr_bot.py`
  - `KEIBA/keiba_auto_cycle.py`
- `KEIBA/keiba_public_watch.py` のような複数チャネル通知は独自抑制ロジックを維持している
- `KEIBA/keiba_public_watch.py` は複数チャネル通知を維持しつつ、ntfy 部分だけ `notification_policy.py` を使う段階へ進めた

したがって、現状は「共通ヘルパー導入済みだが全通知元への完全統一は段階移行中」とする。

------------------------------------------------------------
6. ウィジェット責務
------------------------------------------------------------

`widget_status.py` の責務は以下。

- `state.json` を読む
- `CONTROL.csv` を読む
- `secrets.toml` を読む
- `/widget-status.json` を返す
- `/widget-status.txt` を返す
- 軽量 Web 表示を返す
- `/widget-app` を返す
- `manifest / service worker` を返す
- Scriptable 用の表示データを整形する
- daily reflection / balance / version / freshness を軽量表示する
- `widget-app` の下部固定ナビと Reflection Snapshot を返す
- PWA オフライン時に最後の取得結果または簡易 offline 状態を返し、真っ白表示を避ける

`widget_status.py` にやらせないこと:

- 取引判断
- 注文実行
- API キーの露出
- 複雑な通知判定の乱立
- Bot本体ロジックの上書き

補足:

- PWA 導線は `/widget-app` を正面入口とする
- 既存の Scriptable ウィジェットと `/widget-status.json` は後方互換を維持する
- native app ではなく、まずはホーム画面追加できる軽量 Web App として統合する
- iPhone では `Overview / Reflection / Dashboard` の固定ナビで主要画面へ移動できるようにする
- native 化する場合は、既存の `/widget-app` / `/daily-reflection` / `unified_dashboard` を包む薄い shell を優先し、売買ロジックや token 保護は Web 側に残す

------------------------------------------------------------
7. Scriptable 側の責務
------------------------------------------------------------

対象:

- `OuroborosWidget.local.js`
- `OuroborosWidget.js`

責務:

- `/widget-status.json` を取得する
- 表示用に整形する
- 小/中/大ウィジェットへ描画する
- 異常時に視認性を上げる
- 必要に応じて `/daily-reflection` へ遷移する

やらせないこと:

- secrets の保持
- 取引判断
- 注文実行
- 通知本文生成の主体化

------------------------------------------------------------
8. secrets.toml 管理
------------------------------------------------------------

原則:

- `ntfy_topic_url` は secrets で管理する
- `ntfy_bearer_token` は必要時のみ使う
- token / API key を JS 側へ直書きしない
- 通知 URL をログや画面へ露出しない
- public topic 利用時は bearer token 不要

KEIBA 側補足:

- `KEIBA/data/auto_cycle_config.json` に `ntfy_url` がある場合はそちらを優先してよい
- `KEIBA/.streamlit/keiba_public_notify.json` は公開監視通知用の別設定とする

------------------------------------------------------------
9. 通知元一覧（正）
------------------------------------------------------------

| 区分 | ファイル | 関数/処理 | 通知先 | 通知タイミング | レベル | 備考 |
|---|---|---|---|---|---|---|
| IBKR | `MAIN/ibkr_bot.py` | `_send_ntfy()` | ntfy | Paper bot 状態通知 | WARN/CRITICAL | 読み取り専用 bot 監視とは別 |
| REPORT | `MAIN/tools/send_weekly_summary_ntfy.py` | `main()` | ntfy | 週次サマリ | INFO | 週次自動学習後 |
| REPORT | `MAIN/tools/smart_exit_report.py` | `--ntfy` | ntfy | smart exit レポート | INFO/WARN | 手動または自動 |
| EVENT | `MAIN/tools/trade_event_notifier.py` | `_send_event()` 系 | ntfy/webhook | drift 変更、再開、DD悪化など | WARN/CRITICAL | cooldown 一部あり |
| DASHBOARD | `MAIN/dashboard.py` | `_notify_control_change_ntfy()` | ntfy | CONTROL 変更後 | INFO | 差分通知 |
| SHADOW | `MAIN/stock_shadow_weekly.py` | `send_notification()` | ntfy/webhook | 週次 shadow summary | INFO | notifier 未設定ならファイル保存 |
| SHADOW | `MAIN/stock_shadow_weekly.py` | `_send_readiness_achieved_notify()` | ntfy | 実弾準備完了 | CRITICAL | readiness 到達時 |
| SHADOW | `MAIN/stock_shadow_bot.py` | `_send_trade_notify()` | ntfy | BUY/SELL/SHORT/COVER | INFO | 取引イベント |
| KEIBA | `KEIBA/keiba_auto_cycle.py` | `_send_keiba_ntfy()` | ntfy | 自動サイクル完了/失敗/WR変化 | INFO/WARN/CRITICAL | `ntfy_url` 優先 |
| KEIBA | `KEIBA/keiba_public_watch.py` | `_notify_macos()` | macOS通知 | 公開監視変化 | WARN | ローカル補助 |
| KEIBA | `KEIBA/keiba_public_watch.py` | `_notify_remote()` | ntfy/webhook | 公開監視変化 | WARN/CRITICAL | recovery/unhealthy, webhook payload に `event_level` を含む |

------------------------------------------------------------
10. 既存 SPEC との整合
------------------------------------------------------------

本 SPEC は以下と矛盾してはならない。

- `SPEC_OUROBOROS_DASHBOARD_V1.md`
- `SPEC_OUROBOROS_REPORT_OUT_DIR_V1.md`
- `SPEC_OUROBOROS_V1.md`
- `MAIN/docs/OUROBOROS_TRADING_SPEC_TABLE.md`
- `MAIN/docs/IBKR_AGENT_SPEC.md`
- `KEIBA/docs/KEIBA_SPEC_TABLE.md`
- `MAIN/WIDGETS.md`

整合ルール:

- `state.json / CONTROL.csv` の読み方は既存仕様に従う
- `review_out / daily_report_out` の出力責務を壊さない
- KEIBA / IBKR / Ouroboros の通知を混同しない
- widget は表示専用であり、Bot判断主体ではない

------------------------------------------------------------
11. 変更ルール
------------------------------------------------------------

- 通知経路を追加したら、本 SPEC と `MAIN/docs/notification_routes.md` を更新する
- widget の入出力を変えたら `MAIN/WIDGETS.md` を更新する
- secrets の扱いを変えたら URL/Token の露出有無を再点検する
- 通知抑制ルールを統一実装した場合は、本 SPEC の第5節を更新する

============================================================
END OF SPEC
============================================================
