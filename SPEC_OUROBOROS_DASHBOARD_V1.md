# Project Ouroboros v1 — DASHBOARD SPEC v1.1 (Complete)

============================================================
dashboard.py の表示・CONTROL・JSON連携 契約仕様
============================================================

------------------------------------------------------------
1. Dashboardの役割（責務境界）
------------------------------------------------------------

Dashboardは表示・実行UIのみを担当する。

- CONTROL.csv 編集UI
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

============================================================
END OF SPEC
============================================================
