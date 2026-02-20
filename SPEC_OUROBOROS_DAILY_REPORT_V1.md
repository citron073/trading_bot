# Project Ouroboros v1 — DAILY_REPORT SPEC v1（実装完全準拠）

============================================================
対象：MAIN/daily_report.py
生成物：daily_report_out/daily_report_YYYYMMDD.json（必須）
============================================================

このSPECは bot.py が生成する logs/trade_log_YYYYMMDD.csv を一次情報とする。
state.json は参照してよいが、無くても daily JSON を生成できること（必須）。

------------------------------------------------------------
A. 入力（Input Contract）
------------------------------------------------------------

| 項目 | 契約 | 備考 |
|---|---|---|
| ログ | logs/trade_log_YYYYMMDD.csv | 指定日 |
| 必須カラム | time,result,ltp,best_bid,best_ask,spread_pct,limit_pct,trend,signal,note,pos_id | 欠落は issues |
| time | "YYYY-MM-DD HH:MM:SS"（JST想定） | parse失敗行は rows_dropped |
| spread_pct | 「%値」前提（例 0.0448 は 0.0448%） | 単位疑いは ERROR |

------------------------------------------------------------
B. result 分類（Classification Contract）
------------------------------------------------------------

| 区分 | 条件 | PAPER率 denom |
|---|---|---:|
| PAPER | result == "PAPER" | ✅ |
| OBSERVE系 | result が "OBSERVE" で始まる | ✅ |
| SKIP系 | result が "SKIP" で始まる | ❌ |
| HOLD系 | result == "HOLD_OPEN_POS" | ❌ |
| EXIT系 | result が "PAPER_EXIT_" で始まる | ❌ |
| ERROR系 | result が "ERROR" で始まる | ❌ |

分類不能は issues に WARN、by_result では "UNKNOWN_RESULT" に寄せてよい。

------------------------------------------------------------
C. PAPER率（Definition Contract / 固定）
------------------------------------------------------------

PAPER率(%) = PAPER / (PAPER + OBSERVE系) * 100
- denom=0 → 0.0
- 丸め：原則 小数1桁
- JSONキー：paper_rate_pct（数値）

------------------------------------------------------------
D. コンソール/テキスト出力（Section Contract）
------------------------------------------------------------

daily_report.py の出力セクション順は固定（順序変更禁止）：

| No | セクション | 最低限の内容 |
|---:|---|---|
| ① | 集計 | paper_n/observe_n/skip_n/hold_n/exit_n/error_n, paper_rate_pct |
| ② | PAPER率 内訳 | 全体 + side別（BUY/SELL/UNKNOWN） |
| ③ | スプレッド状況 | limit_pct, avg, p50, p90, p95, max, over_limit_n/pct |
| ④ | trend | UP/DOWN/FLAT/UNKNOWN |
| ⑤ | signal | BUY_CANDIDATE/SELL_CANDIDATE/NONE |
| ⑥ | hour別テーブル | hour別 paper/observe/paper_rate, spread_avg, exit内訳（最低TP/SL/TIMEOUT） |
| ⑦ | EXIT整合 | missing/duplicate/open推定 |
| ⑧ | MAE/MFE要約 | pos_id単位（推定）+ summary |
| ⑨ | issues | WARN/ERROR一覧 |

------------------------------------------------------------
E. 日次JSON（daily_report_YYYYMMDD.json / Output Contract）
------------------------------------------------------------

出力先：daily_report_out/daily_report_YYYYMMDD.json

トップレベル構造（キー固定）：

| キー | 型 | 必須 |
|---|---|---:|
| meta | object | ✅ |
| daily | object | ✅ |
| by_side | object | ✅ |
| by_result | object | ✅ |
| by_hour | object | ✅ |
| trends | object | ✅ |
| signals | object | ✅ |
| spread | object | ✅ |
| exit_integrity | object | ✅ |
| mae_mfe | object | ✅ |
| issues | array | ✅ |

### E-1) meta（固定）

| キー | 型 | 必須 |
|---|---|---:|
| spec | string | ✅ | "SPEC_OUROBOROS_DAILY_REPORT_V1" |
| generated_at_jst | string | ✅ |
| target_day8 | string | ✅ | "YYYYMMDD" |
| log_path | string | ✅ |
| rows_total | int | ✅ |
| rows_used | int | ✅ |
| rows_dropped | int | ✅ |
| notes | string | ✅ |

### E-2) daily（固定キー）

paper_n, observe_n, skip_n, hold_n, exit_n, error_n, paper_rate_pct,
exit_tp_n, exit_sl_n, exit_timeout_n, exit_partial_tp_n, exit_eod_n,
spread_over_limit_n, spread_over_limit_pct

### E-3) by_side（固定）

キー：BUY / SELL / UNKNOWN  
各値の固定キー：
paper_n, exit_n, paper_rate_pct, tp_n, sl_n, timeout_n, eod_n, partial_tp_n

### E-4) by_result（固定）

result名 → 件数(int)  
未知resultは "UNKNOWN_RESULT" に加算してよい（issues WARN必須）。

### E-5) by_hour（固定）

hourキー："0"〜"23"（string）  
値の固定キー：
paper_n, observe_n, paper_rate_pct, spread_avg_pct,
exit_n, tp_n, sl_n, timeout_n, eod_n, partial_tp_n

### E-6) trends / signals（固定）

trends: { "UP":0, "DOWN":0, "FLAT":0, "UNKNOWN":0 }  
signals: { "BUY_CANDIDATE":0, "SELL_CANDIDATE":0, "NONE":0 }

### E-7) spread（固定）

limit_pct, avg_pct, p50_pct, p90_pct, p95_pct, max_pct, over_limit_n, over_limit_pct

spread_pct 単位疑いは issues に ERROR（SPREAD_UNIT_SUSPECT）。

### E-8) exit_integrity（固定）

paper_pos_ids, exit_pos_ids, closed_pos_ids, open_pos_ids,
missing_exit_pos_ids(array), duplicate_exit_pos_ids(array), unknown_exit_result_rows

定義：
- paper_pos_ids：PAPER行のpos_id集合数
- exit_pos_ids：EXIT行のpos_id集合数
- missing_exit_pos_ids：PAPERにあるがEXITにないpos_id
- duplicate_exit_pos_ids：EXITで同pos_idが複数

### E-9) mae_mfe（固定 / 推定）

| キー | 必須 |
|---|---:|
| per_pos | ✅ |
| summary | ✅ |

per_pos[pos_id] 固定キー：
side, entry_price, exit_price, status, mae_pct, mfe_pct, ret_pct_est, exit_type, notes

summary 固定キー：
closed_n, mae_avg_pct, mfe_avg_pct, ret_avg_pct_est

MAE/MFE/ret_pct_est は fee 未加味の推定。notes に必ず「推定」を入れる。

------------------------------------------------------------
F. issues（構造固定）
------------------------------------------------------------

issues[] 要素（キー固定）：
severity(INFO/WARN/ERROR), code, pos_id(optional), message, evidence(optional)

推奨code：
MISSING_REQUIRED_COLUMN, BAD_TIME_PARSE, UNKNOWN_RESULT,
SPREAD_UNIT_SUSPECT, POS_ID_MISSING_ON_PAPER

------------------------------------------------------------
G. 変更ルール
------------------------------------------------------------

JSONキー名 / セクション順 / PAPER率定義 / issues構造 を変える場合は SPEC 同時更新必須。

============================================================
END OF SPEC
============================================================
