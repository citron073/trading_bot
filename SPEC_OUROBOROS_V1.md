# Project Ouroboros v1 — MAIN SPEC（実装完全準拠版）

============================================================
bot.py / state.json / ログ出力 の契約固定（実装基準）
============================================================

このSPECは「現在のbot.py実装」を正とする。
仕様変更は必ずこのSPECを同時更新すること。

------------------------------------------------------------
0. 目的
------------------------------------------------------------

- ログ駆動型自己改善エンジン
- 機能脱落の防止
- result名称・ログ形式・state構造の固定
- dashboard / report との契約維持

------------------------------------------------------------
1. 実行フロー（実装順固定）
------------------------------------------------------------

実行順は以下で固定する：

0) EOD強制クローズ判定（最優先）
1) 稼働時間判定（START_HOUR / END_HOUR）
2) today_on 判定
3) rollback処理（必要な場合）
4) tuning反映
5) NEWSブロック判定
6) ticker完全性チェック
7) MA算出
8) open_pos EXIT管理
9) ENTRY判定
10) state保存
11) ログ出力

※順序変更は禁止（互換破壊）

------------------------------------------------------------
2. result 完全一覧（固定）
------------------------------------------------------------

【正常系】
- PAPER
- HOLD_OPEN_POS

【OBSERVE系】
- OBSERVE_NO_SIGNAL
- OBSERVE_OK
- OBSERVE_TIME_BLOCK
- OBSERVE_SELL_FAST_MA_NEAR
- OBSERVE_TRADE_DISABLED
- OBSERVE_AI_BLOCK

【SKIP系】
- SKIP_OUT_OF_TIME
- SKIP_TODAY_OFF
- SKIP_NEWS
- SKIP_SPREAD
- SKIP_DAILY_LIMIT
- SKIP_TICKER_INCOMPLETE

【EXIT系】
- PAPER_EXIT_TP
- PAPER_EXIT_SL
- PAPER_EXIT_TIMEOUT
- PAPER_EXIT_PARTIAL_TP
- PAPER_EXIT_EOD

【ERROR系】
- ERROR_OPEN_POS_BROKEN

result名称の変更・削除は禁止。
追加する場合はここへ追記必須。

------------------------------------------------------------
3. pos_id 契約
------------------------------------------------------------

形式（厳格固定）：

YYYYMMDD-HHMMSS-(BUY|SELL)-NNN

例：
20260217-101543-BUY-002

- 同日内で一意
- PAPER時に必須付与
- EXIT時は必ず同一pos_idを使用
- ログに必ずpos_idカラムを含める

------------------------------------------------------------
4. ログ形式（固定）
------------------------------------------------------------

logs/trade_log_YYYYMMDD.csv

必須カラム：

time
result
side
price
size
ltp
best_bid
best_ask
spread_pct
limit_pct
ma_fast
ma_slow
trend
signal
note
pos_id

既存カラムの削除禁止。
追加は可（互換維持前提）。

------------------------------------------------------------
5. PAPER率定義（MAIN固定）
------------------------------------------------------------

PAPER率 =
PAPER / (PAPER + OBSERVE系) * 100

OBSERVE系 =
resultが "OBSERVE" で始まるもの

denom=0 → 0.0%

変更禁止（REPORT SPECと整合）

------------------------------------------------------------
6. EXIT整合ルール（厳格）
------------------------------------------------------------

PAPERは必ず以下のいずれかで閉じる：

- PAPER_EXIT_TP
- PAPER_EXIT_SL
- PAPER_EXIT_TIMEOUT
- PAPER_EXIT_PARTIAL_TP
- PAPER_EXIT_EOD

対応EXITが存在しない場合：
ERROR_OPEN_POS_BROKEN を出す。

------------------------------------------------------------
7. _open_pos 完全構造（state.json）
------------------------------------------------------------

_open_pos 構造は以下で固定：

{
  pos_id: str,
  entry_time_jst: str,
  side: "BUY" | "SELL",
  entry_price: float,
  tp_price: float,
  sl_price: float,
  expiry_time_jst: str,
  trend: str,
  signal: str,
  ma_fast: float | None,
  ma_slow: float | None,
  tp_pct: float,
  sl_pct: float,
  best_fav: float,
  extend_count: int,
  tune_note: str,
  win_used: int,
  timeout_mode: "IGNORE" | "EXTEND" | "PARTIAL",
  max_extend_count: int,
  extend_min: int,
  extend_min_bestfav_pct: float,
  partial_tp_trigger_pct: float,
  size: float,
  ai_score: float | null,
  ai_note: str
}

キー削除禁止。
追加する場合はここへ追記。

------------------------------------------------------------
8. AIログ契約
------------------------------------------------------------

AI関連は以下をログに残す：

- ai_score（float or null）
- ai_note（文字列）
- ai_mode（OFF / SCORE_ONLY / VETO / GATE）
- decision_points（entry / extend）
- GATE_SIM / VETO_SIM（note内）

ai_score未使用時は "-1" 表示可。

------------------------------------------------------------
9. CONTROL.csv 契約
------------------------------------------------------------

- key,value 形式
- 未知キー削除禁止
- ai_enabled と ai_model_enabled は互換吸収
- boolは 0/1 基準

------------------------------------------------------------
10. 変更ルール
------------------------------------------------------------

以下を変更する場合は SPEC更新必須：

- result名称
- ログカラム
- pos_id形式
- PAPER率定義
- EXIT種別
- _open_pos構造
- 実行順

------------------------------------------------------------
11. 最低受け入れチェック
------------------------------------------------------------

- PAPERにpos_idがある
- EXITに対応pos_idがある
- OBSERVE_NO_SIGNALが必ず残る
- EODが最優先で動作する
- state.json破損時も安全停止する

