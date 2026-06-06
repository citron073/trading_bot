# Project Ouroboros v1 — WEEKLY_REPORT SPEC v1

対象: `MAIN/weekly_report.py`  
目的: `trade_log_YYYYMMDD.csv` から週次集計JSONを生成し、週単位の成績/品質/異常を俯瞰し、AI学習へ反映する。

## 1. Input Contract
- 主要ログ: `../logs/trade_log_YYYYMMDD.csv`
- ログ探索: `MAIN/logs` または `MAIN/../logs`（`--logs-dir` 指定時は固定）
- 必須カラム:
  - `time,result,side,price,size,ltp,best_bid,best_ask,spread_pct,limit_pct,ma_fast,ma_slow,trend,signal,note,pos_id`
- 文字コード: `UTF-8 / UTF-8-SIG / CP932`
- `time` 解析不能行は `WARN` として除外可

## 2. Output Contract
- 出力: `weekly_report_out/weekly_report_YYYYMMDD_YYYYMMDD.json`
- WRITEログ: 生成成功時は必ず
  - 例: `[WRITE] weekly_report_out/weekly_report_20260303_20260309.json`

## 3. CLI Contract
- positional:
  - `day8` (`YYYYMMDD`) または `range` (`YYYYMMDD-YYYYMMDD`)
- options:
  - `--start YYYYMMDD`
  - `--end YYYYMMDD`
  - `--out-dir path`（default: `weekly_report_out`）
  - `--logs-dir path`
  - `--week-start MON|TUE|WED|THU|FRI|SAT|SUN`（default: `MON`）
  - `--strict`（`WARN` も失敗扱い）

優先順位:
1. `range`
2. `--start/--end`
3. `day8`（週開始曜日に基づき自動で7日範囲を決定）

終了コード:
- `0`: ERRORなし（`--strict` で WARN も無し）
- `1`: ERRORあり、または `--strict` で WARNあり
- `2`: 引数不正/致命エラー

## 4. Metrics Contract
### 4.1 `weekly`
最低限以下を含む:
- `rows_total`, `rows_used`, `day_count`
- `paper_n`, `exit_n`, `observe_n`, `skip_n`, `hold_n`, `error_n`
- `paper_rate_pct`, `exit_rate_pct`
- `spread_avg_pct`, `spread_p90_pct`, `spread_max_pct`
- `spread_over_limit_n`

### 4.2 `by_day`
- キー: `YYYYMMDD`
- 値: 週次と同等の構造（`rows_total/rows_used/...`）

### 4.3 `by_side`
- キー: `BUY / SELL / UNKNOWN`
- 値: `paper_n/exit_n/observe_n/skip_n/paper_rate_pct`
- 任意で `exit_breakdown` を追加可

### 4.4 `by_hour`
- キー: `"0"〜"23"`
- 値: `paper_n/observe_n/exit_n/hold_n/paper_rate_pct/spread_avg_pct`

### 4.5 `weekly_exit_integrity`
- `paper_pos_ids`
- `exit_pos_ids`
- `missing_exit_pos_ids`
- `exit_without_paper_pos_ids`

`pos_id` リストは巨大化回避のため上限を設けてよい（推奨: 2000）。超過時は `WARN`。

### 4.6 `weekly_review`
- `closed_n`, `win_n`, `loss_n`, `win_rate_pct`
- `ret_sum_pct`, `avg_ret_pct`, `gross_profit_pct`, `gross_loss_pct`, `profit_factor`
- `avg_hold_min`
- `exit_reason_breakdown`
- `by_weekday`（`MON..SUN`）
- `by_hour`（`0..23`）

`weekly_review` は `PAPER` ENTRY と `PAPER_EXIT_*` を `pos_id` で突合して推定する（fee未加味）。

### 4.7 `ai_feedback`
- `min_hour_samples`
- `good_hours` / `bad_hours`
- `good_hours_reason` / `bad_hours_reason`
- `suggested_control_updates`
- `summary`

`suggested_control_updates` は Dashboard の Bot設定に反映可能な key/value（文字列）を返す。
想定キー:
- `ai_train_weekly_feedback_enabled`
- `ai_train_weekly_good_hours`
- `ai_train_weekly_bad_hours`
- `ai_train_weekly_good_hour_boost`
- `ai_train_weekly_bad_hour_penalty`

## 5. Issues Contract
`issues` は list。各要素は以下キーを持つ:
- `code`
- `severity` (`INFO|WARN|ERROR|FATAL`)
- `message`
- `context`

代表例:
- `E_LOG_NOT_FOUND`
- `E_LOG_MISSING_COLUMNS`
- `W_TIME_PARSE`
- `W_NON_NUMERIC`
- `W_POS_ID_MISSING`
- `W_RESULT_UNKNOWN`

## 6. JSON Top-Level Contract
トップレベル必須キー:
- `meta`
- `range`
- `weekly`
- `by_day`
- `by_side`
- `by_hour`
- `weekly_review`
- `ai_feedback`
- `weekly_exit_integrity`
- `issues`

## 7. CI/Spec 連携
- `weekly_report` は `daily_report` / `audit` 非依存で単独生成可能
- 週次契約の定義は `MAIN/SPEC_CONTRACTS_V1.json` の `weekly_report_json` を正とする

## 8. Dashboard連携契約（運用）
- Dashboard は `ai_feedback.suggested_control_updates` を `CONTROL.csv` へ反映できる
- 反映時に Dashboard は `state.json._weekly_ai_feedback_compare` へ比較スナップショットを保存し、次回AI学習後の before/after/delta を可視化する
- 本契約は表示・運用導線のみであり、`weekly_report` JSONの必須キー自体は変更しない

## 9. Non-breaking Rule
- 既存キー削除禁止
- 型変更禁止
- 拡張は追加のみ
- 変更時はコードとSPECを同時更新すること
