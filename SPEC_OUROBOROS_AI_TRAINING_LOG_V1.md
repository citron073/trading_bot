# Project Ouroboros v1 — AI_TRAINING_LOG SPEC v1（実装準拠 / 現状の課題も明記）

============================================================
対象：MAIN/ai_training_log.csv（学習用ログ）
注意：現実装は「行ごとにfieldnamesが変わり得る」ため、集計側が壊れやすい。
このSPECは “最終的に固定すべき列” を定義し、実装修正の基準とする。
============================================================

------------------------------------------------------------
A. 目的
------------------------------------------------------------

- AI学習用の特徴量・結果（outcome）を pos_id 単位で蓄積
- report/audit とは別系統（一次情報ではないが重要）

------------------------------------------------------------
B. 列（固定推奨：将来の必須列）
------------------------------------------------------------

| column | 型 | 必須 | 説明 |
|---|---|---:|---|
| time | string | ✅ | JST |
| pos_id | string | ✅ | |
| phase | string | ✅ | ENTRY / EXIT |
| side | string | ✅ | BUY/SELL |
| entry_price | number | ✅ | |
| exit_price | number | △ | EXITのみ |
| tp_price | number | △ | |
| sl_price | number | △ | |
| ma_fast | number | △ | |
| ma_slow | number | △ | |
| trend | string | △ | |
| signal | string | △ | |
| ai_score | number|null | △ | |
| best_fav | number | △ | |
| extend_count | int | △ | |
| outcome | string | △ | TP/SL/TIMEOUT/PARTIAL_TP/EOD |

------------------------------------------------------------
C. 実装上の注意（現状の不整合）
------------------------------------------------------------

- append_ai_training_log が fieldnames=row.keys() で可変 → 列順・列欠落が起こる
- ensure_ai_training_log_header の fields と append の fields が一致していない可能性

このSPECに合わせて **列固定の追記方式**に統一するのが推奨。

============================================================
END OF SPEC
============================================================
