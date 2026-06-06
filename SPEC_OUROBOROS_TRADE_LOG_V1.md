# Project Ouroboros v1 — TRADE_LOG SPEC v1（実装完全準拠）

============================================================
対象：logs/trade_log_YYYYMMDD.csv（bot.py が生成する一次情報）
============================================================

------------------------------------------------------------
A. ファイル契約
------------------------------------------------------------

| 項目 | 契約 |
|---|---|
| パス | logs/trade_log_YYYYMMDD.csv |
| 文字コード | UTF-8 |
| 区切り | CSV（,） |
| 1行目 | ヘッダ必須 |
| 追記方式 | append（1日1ファイル） |

------------------------------------------------------------
B. カラム契約（bot.py LOG_FIELDS に完全準拠 / 削除禁止）
------------------------------------------------------------

| 順序 | column | 型（目安） | 必須 | 説明 |
|---:|---|---|---:|---|
| 1 | time | string | ✅ | "YYYY-MM-DD HH:MM:SS"（JST想定） |
| 2 | result | string | ✅ | 例：PAPER / OBSERVE_* / SKIP_* / HOLD_OPEN_POS / PAPER_EXIT_* / ERROR_* |
| 3 | side | string | △ | BUY/SELL（PAPER/EXIT/HOLDで必須、SKIP/OBSERVEでは空でも可） |
| 4 | price | number | △ | entry_price 相当（PAPER/EXIT/HOLDで原則） |
| 5 | size | number | △ | 0.001 など |
| 6 | ltp | number | △ | ログ時点の価格 |
| 7 | best_bid | number | △ | ティッカー |
| 8 | best_ask | number | △ | ティッカー |
| 9 | spread_pct | number|string | △ | **%値**（例：0.0448 は 0.0448%）空許容 |
| 10 | limit_pct | number|string | △ | **%値**（例：0.05 は 0.05%） |
| 11 | ma_fast | number|string | △ | SMA fast（未算出は空） |
| 12 | ma_slow | number|string | △ | SMA slow（未算出は空） |
| 13 | trend | string | △ | UP/DOWN/FLAT/UNKNOWN |
| 14 | signal | string | △ | BUY_CANDIDATE/SELL_CANDIDATE/NONE |
| 15 | note | string | △ | 自由記述。AI score / exec/stage/order_id/filled / pos_id=... などを追記しうる |
| 16 | pos_id | string | △ | PAPER/EXIT/HOLDでは必須（空は監査ERROR） |

------------------------------------------------------------
C. pos_id 契約（bot.py 実装準拠）
------------------------------------------------------------

| 項目 | 契約 |
|---|---|
| フォーマット | YYYYMMDD-HHMMSS-(BUY|SELL)-NNN |
| 例 | 20260219-110131-SELL-001 |
| 一意性 | 同日内で一意（state連番で担保） |
| 強制埋込 | note 内に "pos_id=..." を埋め込む（embed_pos_id） |

------------------------------------------------------------
D. result の代表集合（例示 / 追加は可能だが削除・改名は禁止）
------------------------------------------------------------

| 区分 | 例 |
|---|---|
| PAPER | PAPER |
| OBSERVE | OBSERVE_NO_SIGNAL / OBSERVE_OK / OBSERVE_TIME_BLOCK / OBSERVE_SELL_FAST_MA_NEAR / OBSERVE_TRADE_DISABLED / OBSERVE_AI_BLOCK |
| SKIP | SKIP_OUT_OF_TIME / SKIP_TODAY_OFF / SKIP_NEWS / SKIP_TICKER_INCOMPLETE / SKIP_SPREAD / SKIP_DAILY_LIMIT |
| HOLD | HOLD_OPEN_POS |
| EXIT | PAPER_EXIT_TP / PAPER_EXIT_SL / PAPER_EXIT_TIMEOUT / PAPER_EXIT_PARTIAL_TP / PAPER_EXIT_EOD / PAPER_EXIT_PRENEWS |
| ERROR | ERROR_OPEN_POS_BROKEN |

補足（2026-04-17時点の追加OBSERVE）：
- `OBSERVE_MR / OBSERVE_MR_FILTER_NG / OBSERVE_MR_TRIGGER`
- `OBSERVE_PHASE_B`
- `OBSERVE_BUY_FAST_MA_NEAR`
- `OBSERVE_TREND_FLIP_COOLDOWN`
- `OBSERVE_TREND_STRENGTH_WEAK`

補足（note内の追加特徴量タグ）：
- MAクロス: `ma_cross_*`
- 技術指標: `ti_rsi`, `ti_rsi_zone`, `ti_bb_zone`, `ti_atr_pct`, `technical_comp`
- チャートパターン: `cp_name`, `cp_stage`, `cp_bias`, `cp_confirmed`, `cp_trend`, `cp_neckline`, `cp_quality`, `cp_avg_ticks`, `chart_pattern_comp`
- `cp_quality=THIN` は記録のみ。AI scoreや昇格判断には使わない
- A/B/C局面: `phase`, `phase_reason`, `phase_slope`, `phase_gap`, `phase_range`, `prev_high`, `prev_low`, `up_break`, `down_break`, `phase_momentum`, `phase_transition`, `market_phase_comp`
- 相場流: `aiba_trend`, `aiba_cross`, `aiba_ppp`, `aiba_run`, `aiba_9`, `aiba_try_fail`, `aiba_try_fail_count`, `aiba_style_comp`
- shadow exit: `exit_tech=NEAR_TP_GIVEBACK` はTP寸前から戻したpaper玉の早逃げ検証

------------------------------------------------------------
E. 変更ルール
------------------------------------------------------------

- カラム削除・順序変更は禁止
- result 名の改名は禁止（追加はOK）
- spread_pct / limit_pct の単位（%値）を変更する場合は、REPORT/AUDIT SPEC 同時更新必須

補足（LIVE互換）：
- result名は既存契約を維持（PAPER / PAPER_EXIT_*）
- 実行モード識別は `note` のタグで行う
  - 例: `exec=LIVE stage=CANARY order_id=JRF... filled=0.00100000`

============================================================
END OF SPEC
============================================================
