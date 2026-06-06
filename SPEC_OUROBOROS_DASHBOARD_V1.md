# Project Ouroboros v1 — DASHBOARD SPEC v1.2 (Complete)

============================================================
dashboard.py の表示・CONTROL・JSON連携 契約仕様
============================================================

------------------------------------------------------------
1. Dashboardの役割（責務境界）
------------------------------------------------------------

Dashboardは表示・実行UIのみを担当する。

- CONTROL.csv 編集UI
- LIVE設定編集（market_type/product_code/fx_leverage/fx_collateral_use_ratio）
- daily_report 実行ボタン
- audit 実行ボタン
- daily_report_out JSON 可視化
- priceライン + ENTRY/EXITマーカー可視化（ログ推定）
- 損益内訳（総利益/総損失/Payoff/ProfitFactor）表示（推定）
- pos_id 単位表示
- issues表示
- AI自動学習ステータス表示（state._ai_auto_train）

禁止事項：
- エントリー判断ロジックを持たない
- 公式集計（daily_report / audit の正値）を上書きしない
- 監査JSONがある場合に pos_id状態を再判定しない

許容事項（表示専用の推定）：
- ログ由来の推定 ret_pct / 推定PnL の計算と可視化
- 監査JSONが無い場合のログフォールバック表示

bot.py が唯一の判断主体である。

------------------------------------------------------------
2. CONTROL 契約
------------------------------------------------------------

形式:
- key,value の2列
- 未知キーを削除しない
- DEFAULTS外キーは extra として保持

保存時:
- atomic write 推奨
- 保存前にバックアップ作成（.bak）
- 変更履歴（`dashboard_change_log.jsonl`）への追記に失敗した場合は保存を失敗扱いにし、CONTROLを書き戻す（未記録保存を禁止）

------------------------------------------------------------
3. daily_report JSON 優先順位
------------------------------------------------------------

表示データ優先順位:

1) daily_report_out/daily_report_YYYYMMDD.json
2) 無ければ trade_log_YYYYMMDD.csv から推定表示

JSONが破損している場合:
- エラー表示
- ログ推定へフォールバック

------------------------------------------------------------
4. daily_report JSON 構造契約（固定キー）
------------------------------------------------------------

必須キー:

meta:
- spec
- generated_at_jst
- target_day8
- rows_total
- rows_used

daily:
- paper_n
- observe_n
- skip_n
- hold_n
- exit_n
- error_n
- paper_rate_pct

by_side:
- BUY / SELL / UNKNOWN
  - paper_n
  - observe_n
  - skip_n
  - hold_n
  - exit_n
  - paper_rate_pct
  - tp_n
  - sl_n
  - timeout_n
  - partial_tp_n
  - eod_n

by_hour:
- 0-23 (string key)
  - paper_n
  - observe_n
  - hold_n
  - exit_n
  - paper_rate_pct
  - spread_avg_pct

spread:
- avg_pct
- p90_pct
- max_pct
- over_limit_n

exit_integrity:
- paper_pos_ids
- exit_pos_ids
- open_pos_ids
- missing_exit_pos_ids

mae_mfe:
- per_pos
- summary

issues:
- list of {severity, code, pos_id, message}

------------------------------------------------------------
5. pos_id 表示契約
------------------------------------------------------------

status:
- OPEN
- CLOSED
- UNKNOWN
- ERROR

Dashboardは再判定しない。
JSON値をそのまま表示。

------------------------------------------------------------
6. 損益表示契約
------------------------------------------------------------

ret_pct = (exit - entry) / entry

SELL の場合は符号反転。
fee未加味。
必ず「推定」と明示。

------------------------------------------------------------
7. 売買ポイント可視化契約
------------------------------------------------------------

- `成績・分析` タブで以下を表示する：
  - 価格ライン（LTP）
  - ENTRY BUY（緑▲）
  - ENTRY SELL（赤▼）
  - EXIT（黄✕）
- 表示元は trade_log の `PAPER` / `PAPER_EXIT_*` 行
- 推定表示であることを明示する

------------------------------------------------------------
8. by_side / by_hour 表示契約
------------------------------------------------------------

- テーブル表示
- bar_chart（paper_n / exit_n）
- line_chart（paper_rate_pct / spread_avg_pct）
- 欠損は0扱い

------------------------------------------------------------
9. issues 表示契約
------------------------------------------------------------

- severity色分け
- pos_idリンク化
- 検索フィルタ連動

------------------------------------------------------------
10. エラー耐性
------------------------------------------------------------

- JSON欠落キーは default値で補完
- ファイル不存在は st.warning 表示
- 実行失敗は stderr表示

------------------------------------------------------------
11. 変更ルール
------------------------------------------------------------

- JSONキー変更時 → DAILY_REPORT_SPEC 更新必須
- CONTROL仕様変更時 → MAIN_SPEC 更新必須
- 表示構造変更時 → 本SPEC更新必須

------------------------------------------------------------
12. 認証・セキュリティ契約（OIDC主体）
------------------------------------------------------------

- 認証モードは `LOCAL / OIDC / AUTO` をサポートする
- 通常運用は OIDC（Google/Apple）主体
- `AUTO` 時のローカル認証は breakglass（緊急時）用途
- breakglass制御キー（`dashboard_auth.json`）:
  - `allow_breakglass_in_auto`（bool）
  - `breakglass_daily_limit`（int, 1以上）
- ローカル認証失敗はロック制御（`max_failures`, `lock_minutes`）を適用
- 通知（`dashboard_security`）:
  - `login_notify_enabled`
  - `auth_fail_notify_enabled`
  - `ntfy_topic_url` / `login_notify_webhook_url`

------------------------------------------------------------
13. 運用自動復旧契約（dashboard + ngrok）
------------------------------------------------------------

- launchdスクリプト:
  - `MAIN/tools/install_dashboard_launchagent.sh`
  - `MAIN/tools/uninstall_dashboard_launchagent.sh`
  - `MAIN/tools/dashboard_ngrok_wrapper.sh`
- `install` 後は RunAtLoad + KeepAlive で常駐再起動
- ログ出力:
  - `MAIN/ci_logs/launchd_dashboard_out.log`
  - `MAIN/ci_logs/launchd_dashboard_err.log`
  - `MAIN/ci_logs/dashboard_ngrok_wrapper.log`

------------------------------------------------------------
14. 取引通知契約（イベント通知）
------------------------------------------------------------

- 通知スクリプト: `MAIN/tools/trade_event_notifier.py`
- 常駐化スクリプト:
  - `MAIN/tools/install_trade_notifier_launchagent.sh`
  - `MAIN/tools/uninstall_trade_notifier_launchagent.sh`
- 通知対象:
  - `PAPER`（ENTRY）
  - `PAPER_EXIT_*`（EXIT）
  - `_risk_stop` 状態変化
  - `.run_lock` の runner 稼働状態変化
- 設定は `secrets.toml` の `[dashboard_security]` を使用
- 初回通知抑制（履歴洪水防止）を既定とし、`--bootstrap-send` で既存行通知を許可

------------------------------------------------------------
15. 成績分析KPI契約（推定）
------------------------------------------------------------

- `成績・分析` タブに以下を表示（推定・fee未加味）
  - Expectancy
  - Max Drawdown（PnL / ret_pct）
  - 最大連敗
  - テクニカルEXIT集計（`note` の `exit_tech=...` を理由別に集計）
  - 時間帯サマリー（hourly: trades/win_rate/ret_sum/pnl_sum/avg_pnl）
- すべてログ由来推定であり、正値は daily_report / audit を優先する

------------------------------------------------------------
16. 起動前セーフティゲート契約（LIVE）
------------------------------------------------------------

- `ホーム > bot 起動/停止` に `起動前セーフティゲート` を表示する
- `LIVE売買条件`（`today_on=1 && trade_enabled=1 && paper_mode=0 && live_enabled=1 && observe_only=0 && safety_hard_block=0`）の時のみ、追加のLIVEガードを適用する
- LIVEガードの必須条件:
  - `live_preflight` の直近成功履歴があること（既定: 12時間以内）
  - `run_check.sh` の直近成功履歴があること（既定: 12時間以内）
  - `limit_order_timeout_sec` が 10〜180 秒
  - `canary_lot <= lot`
  - FX/CFD/LIGHTNING時に `fx_leverage <= 2.0`
  - `daily_loss_limit_pct` が過度に緩くない（-5.0%未満はNG）
- ガード違反時は `bot起動` / `CANARY起動` をブロックする
- ガード結果は画面上に理由を列挙し、`live_preflight` / `run_check.sh` 実行ボタンで再判定できる
- 実行履歴は `MAIN/.ops_checks.json` に保存し、Dashboardセッション再起動後も参照可能とする

------------------------------------------------------------
17. 週次AI提案の反映前後比較契約
------------------------------------------------------------

- `成績・分析` タブで `weekly_report` の `ai_feedback.suggested_control_updates` を反映した際、比較用スナップショットを `state.json` に保存する
- 保存キー:
  - `_weekly_ai_feedback_compare`
- 保存内容（最低限）:
  - `applied_at`
  - `range_start8` / `range_end8`
  - `summary`
  - `suggested_control_updates`
  - `before_last_day`
  - `before_ai_auto`（`_ai_auto_train` の比較対象サブセット）
- 画面表示:
  - `status` は `比較待機中` / `更新済み` を表示
  - `before/after/delta` をテーブル表示
  - `status` 列に `UP / DOWN / SAME / REF / CHANGED` を表示
- 改善判定対象（正方向ほど良い）:
  - `current_metric`
  - `best_metric`
  - `improve`
  - `backtest_gate_eval_pf`
  - `backtest_gate_eval_expectancy`
- `比較スナップショットをクリア` 操作で `_weekly_ai_feedback_compare` を削除できる
- この比較は運用補助表示であり、売買判断の正値は bot / report 契約を優先する

============================================================
END OF SPEC
============================================================
