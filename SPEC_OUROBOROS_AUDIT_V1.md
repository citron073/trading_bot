# Project Ouroboros v1 — AUDIT SPEC v1（実装完全準拠）

============================================================
対象：MAIN/audit.py（または daily_report.py 内 audit 生成）
生成物：daily_report_out/audit_YYYYMMDD.json（必須）
============================================================

audit は logs/trade_log_YYYYMMDD.csv を一次情報として pos_id 単位の整合を監査する。
state.json は参照してよいが、無くても audit JSON を生成できること（必須）。

------------------------------------------------------------
A. 入力（Input Contract）
------------------------------------------------------------

| 項目 | 契約 |
|---|---|
| ログ | logs/trade_log_YYYYMMDD.csv |
| 必須カラム | time,result,side,price,ltp,trend,signal,note,pos_id |
| EXIT判定 | result が "PAPER_EXIT_" で始まる |
| ENTRY判定 | result == "PAPER" |

pos_id が空の PAPER は重大（ERROR：POS_ID_MISSING_ON_PAPER）。

------------------------------------------------------------
B. 監査の主目的（固定）
------------------------------------------------------------

| 監査項目 | 検出内容 |
|---|---|
| pos_id整合 | PAPER→EXIT の突合 / EXIT重複 / 未終了 |
| entry/exit抽出 | pos_idごとに最初のPAPER、最初のEXITを採用（原則） |
| OPEN推定 | PAPERがありEXITが無いpos_id |
| 異常result | EXIT系の未知result名 |
| MAE/MFE（推定） | 同pos_id期間の ltp から推定（fee未加味） |

------------------------------------------------------------
C. 監査JSON（audit_YYYYMMDD.json / Output Contract）
------------------------------------------------------------

出力先：daily_report_out/audit_YYYYMMDD.json

トップレベル構造（キー固定）：

| キー | 型 | 必須 |
|---|---|---:|
| meta | object | ✅ |
| per_pos | object | ✅ |
| issues | array | ✅ |

### C-1) meta（固定）

| キー | 型 | 必須 |
|---|---|---:|
| spec | string | ✅ | "SPEC_OUROBOROS_AUDIT_V1" |
| generated_at_jst | string | ✅ |
| target_day8 | string | ✅ |
| log_path | string | ✅ |
| paper_pos_ids | int | ✅ |
| exit_pos_ids | int | ✅ |
| notes | string | ✅ |

### C-2) per_pos[pos_id]（固定キー）

| キー | 型 | 必須 |
|---|---|---:|
| status | string | ✅ | OPEN/CLOSED/UNKNOWN/ERROR |
| entry | object | ✅ |
| exit | object | ✅（無い場合は空objectでも可、issues WARN必須） |
| ai | object | ✅（無ければ null/空で良い） |
| mae | object | ✅ |
| mfe | object | ✅ |

#### entry（固定キー）
time, side, entry_price, tp_price, sl_price, expiry_time_jst, trend, signal, spread_pct, note

抽出ルール：
- pos_id一致の PAPER 行を entry とする（原則：最初の1件）
- もし複数PAPERが同pos_idで存在する場合、issues WARN（DUPLICATE_PAPER_SAME_POS_ID）

#### exit（固定キー）
time, exit_price, result, hit_ltp, note

抽出ルール：
- pos_id一致の EXIT行を exit とする（原則：最初の1件）
- 同pos_idでEXITが複数ある場合、issues ERROR（EXIT_DUPLICATE_POS_ID）
- EXITが無い場合 status=OPEN、issues WARN（EXIT_MISSING_FOR_PAPER）

#### ai（固定キー）
ai_score, ai_note, ai_mode, dp_entry, dp_extend

抽出ルール：
- ai_score/ai_note は entry.note または logs の該当列/ note から拾える範囲で格納
- ai_mode は bot側正規化値（OFF/SCORE_ONLY/VETO/GATE）が望ましいが、取れなければ "UNKNOWN"

#### mae/mfe（固定キー）
mae_pct, mfe_pct, basis, note

- basis は "log_ltp_series_est"
- note に必ず「推定」を入れる（fee未加味）

------------------------------------------------------------
D. issues（構造固定）
------------------------------------------------------------

issues[] 要素（キー固定）：
severity(INFO/WARN/ERROR), code, pos_id(optional), message, evidence(optional)

推奨code：
POS_ID_MISSING_ON_PAPER, EXIT_MISSING_FOR_PAPER, EXIT_DUPLICATE_POS_ID,
UNKNOWN_EXIT_RESULT, DUPLICATE_PAPER_SAME_POS_ID, BAD_TIME_PARSE,
MISSING_REQUIRED_COLUMN, OPEN_POS_BROKEN_ROW

------------------------------------------------------------
E. 変更ルール
------------------------------------------------------------

JSONキー名 / issues構造 / entry-exit抽出ルール を変える場合は SPEC 同時更新必須。

============================================================
END OF SPEC
============================================================
