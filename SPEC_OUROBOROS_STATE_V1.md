# Project Ouroboros v1 — STATE SPEC v1（実装完全準拠）

============================================================
対象：MAIN/state.json（bot.py が読む/書く永続状態）
============================================================

------------------------------------------------------------
A. 基本契約
------------------------------------------------------------

| 項目 | 契約 |
|---|---|
| パス | MAIN/state.json |
| 文字コード | UTF-8 |
| 形式 | JSON object（dict） |
| 破損時 | load_state は {} 扱い（起動不能禁止） |
| 互換 | unknown keys は保持（削除しない） |

------------------------------------------------------------
B. 主要キー（bot.py 実装準拠）
------------------------------------------------------------

| key | 型 | 必須 | 説明 |
|---|---|---:|---|
| _open_pos | object | △ | 現在の未決済ポジション（無ければ無し） |
| ltp_history | array[number] | △ | SMA用の価格履歴 |
| _last_ltp | number | △ | 直近ltp |
| _control_snapshot | object | △ | CONTROL/AI設定の保存（監査用） |
| _tune_day | string | △ | tuningの採用日 |
| _tune_win_min | int | △ | tuning採用WIN_MIN |
| _tune_last_applied_day | string | △ | 1日1回適用 |
| _rollback_checked_day | string | △ | rollback判定済み日 |
| _pos_seq_YYYYMMDD | int | △ | pos_id 連番 |

------------------------------------------------------------
C. _open_pos 構造（必須フィールド）
------------------------------------------------------------

_open_pos は object のとき、最低限以下を持つ（無い場合は ERROR_OPEN_POS_BROKEN を出してクリア可）：

| key | 型 | 必須 | 説明 |
|---|---|---:|---|
| pos_id | string | ✅ | 厳格pos_id |
| entry_time_jst | string | ✅ | "YYYY-MM-DD HH:MM:SS" |
| side | string | ✅ | BUY/SELL |
| entry_price | number | ✅ | entry |
| tp_price | number | ✅ | tp |
| sl_price | number | ✅ | sl |
| expiry_time_jst | string | ✅ | expiry |
| timeout_mode | string | ✅ | IGNORE/EXTEND/PARTIAL |
| extend_count | int | ✅ | 延長回数 |
| best_fav | number | △ | 有利方向最大伸び（%） |
| ai_score | number|null | △ | AI score |
| ai_note | string | △ | AIログ |
| tune_note | string | △ | tuning情報 |

------------------------------------------------------------
D. 変更ルール
------------------------------------------------------------

- 既存キーの意味変更は禁止（互換層なし変更禁止）
- _open_pos の必須フィールドを変える場合、bot/audit/reportの同時更新必須
- unknown keys は保持（破壊的削除禁止）

============================================================
END OF SPEC
============================================================
