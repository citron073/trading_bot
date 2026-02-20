# Project Ouroboros v1 — CONTROL.csv SPEC v1（実装完全準拠）

============================================================
対象：MAIN/CONTROL.csv（Dashboard→botの制御）
形式：key,value（2列）
============================================================

------------------------------------------------------------
A. ファイル形式
------------------------------------------------------------

| 項目 | 契約 |
|---|---|
| パス | MAIN/CONTROL.csv |
| 形式 | CSV（2列） |
| ヘッダ | "key,value" は任意（あっても無視） |
| 余剰列 | 3列目以降は無視（実装：len<2はskip） |
| 空行 | 無視 |
| unknown key | bot側では無視される（ただし snapshotには残る） |

------------------------------------------------------------
B. 主要キー（build_runtime_config 実装準拠）
------------------------------------------------------------

| key | 型 | デフォルト | 説明 |
|---|---|---:|---|
| today_on | bool | true | 0なら当日停止（SKIP_TODAY_OFF） |
| trade_enabled | bool | true | 0なら新規PAPERなし（OBSERVE_TRADE_DISABLED） |
| paper_mode | bool | true | 予約（現状ログ用途） |
| observe_only | bool | false | 候補があってもOBSERVE_OK |
| tp_buy_pct | float | 0.155 | TP%（BUY） |
| tp_sell_pct | float | 0.180 | TP%（SELL） |
| sl_pct | float | -0.220 | SL%（共通） |
| win_min | int | 120 | TIMEOUT基準分 |
| timeout_mode | str | IGNORE | IGNORE/EXTEND/PARTIAL |
| spread_limit_pct | float | 0.0005 | **比率**（0.0005=0.05%） |
| max_trades_per_day | int | 50 | 新規PAPER上限 |
| one_position_only | bool | true | open_posがあれば新規しない |
| no_paper_hours | list[int] | [13] | "13,14" 等を許容 |
| sell_fast_ma_distance_pct | float | 0.10 | SELLのMA乖離% |
| fast_n | int | 5 | SMA fast |
| slow_n | int | 20 | SMA slow |
| max_ltp_history | int | 200 | SMA履歴 |
| lot | float | 0.001 | size |
| max_extend_count | int | 1 | EXTEND最大 |
| extend_min | int | 30 | EXTEND分 |
| extend_min_bestfav_pct | float | 0.08 | EXTEND条件 |
| partial_tp_trigger_pct | float | 0.10 | PARTIAL条件 |
| safety_hard_block | bool | true | 予約（現状は常時Hard Block実装） |

（任意）AI緊急上書き：
ai_enabled, ai_mode, ai_threshold, ai_debug（入っていれば上書き）

------------------------------------------------------------
C. 単位注意（重要）
------------------------------------------------------------

| キー | 単位 |
|---|---|
| spread_limit_pct | **比率**（0.0005=0.05%） |
| trade_logのspread_pct/limit_pct | **%値**（0.05=0.05%） |

ここが混同されると report が SPREAD_UNIT_SUSPECT を出す。

============================================================
END OF SPEC
============================================================
