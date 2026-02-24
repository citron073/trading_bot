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
B. 主要キー（bot.py 実装準拠）
------------------------------------------------------------

| key | 型 | デフォルト | 説明 |
|---|---|---:|---|
| today_on | bool | true | 0なら当日停止（SKIP_TODAY_OFF） |
| trade_enabled | bool | true | 0なら新規PAPERなし（OBSERVE_TRADE_DISABLED） |
| paper_mode | bool | true | 1=既存PAPER経路、0=LIVE候補（live_enabledと組み合わせ） |
| observe_only | bool | false | 候補があってもOBSERVE_OK |
| live_enabled | bool | false | 1 かつ paper_mode=0 の時だけLIVE発注経路を許可 |
| rollout_mode | str | AUTO | AUTO/PAPER/CANARY/LIVE |
| stage_paper_days | int | 3 | 段階導入のPAPER日数 |
| stage_canary_days | int | 3 | 段階導入のCANARY日数 |
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
| canary_lot | float | 0.001 | CANARY段階のsize |
| max_extend_count | int | 1 | EXTEND最大 |
| extend_min | int | 30 | EXTEND分 |
| extend_min_bestfav_pct | float | 0.08 | EXTEND条件 |
| partial_tp_trigger_pct | float | 0.10 | PARTIAL条件 |
| safety_hard_block | bool | true | 1で新規ENTRYを強制停止（OBSERVE_TRADE_DISABLED） |
| daily_loss_limit_pct | float | -1.0 | 日次損失率しきい値（%）以下で新規ENTRY停止 |
| limit_order_timeout_sec | int | 30 | 指値注文の待機秒数（未約定取消） |
| limit_price_offset_ticks | int | 0 | 指値価格オフセット（tick単位） |
| product_code | str | BTC_JPY | 発注対象 product_code |
| market_type | str | SPOT | 市場区分メモ（SPOT/FX/OTHER） |
| keychain_service | str | ouroboros.bitflyer | macOS keychain service名 |
| keychain_account_key | str | api_key | API KEY用 account名 |
| keychain_account_secret | str | api_secret | API SECRET用 account名 |
| ai_auto_train_enabled | bool | true | 1なら日次1回のAI自動チューニングを実行 |
| ai_auto_lookback_days | int | 45 | AI自動チューニングの参照日数（7以上） |

（任意）AI緊急上書き：
ai_enabled, ai_mode（入っていれば上書き）
※ `ai_threshold` / `ai_veto_threshold` は互換キーとして保持可（閾値本体は ai_model.json 側を優先）

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
