# Project Ouroboros v1 — MAIN SPEC（bot.py 実装完全準拠 / 固定契約）

============================================================
bot.py / state.json / ログ出力 の契約固定（実装基準）
============================================================

このSPECは **現在の bot.py 実装** を正とする。
仕様変更（挙動・ログ・state構造）をする場合は **必ずこのSPECも同時更新**すること。

現行実装バージョン（2026-04-18）：
- `OUROBOROS_BOT_VERSION = 2026.04.18.2`
- `OUROBOROS_FEATURE_SCHEMA_VERSION = ohlc-chart-pattern-quality-market-phase-transition-near-tp-aiba-phase-fallback-v1`

用語：
- MAIN = bot.py（ログ生成・state管理）
- REPORT = daily_report.py 等（集計・可視化）
- AUDIT = audit.py（整合検証）

------------------------------------------------------------
0. 目的
------------------------------------------------------------

- ログ駆動型自己改善エンジン（PAPER互換維持 + LIVE段階導入）
- 機能脱落の防止（互換破壊を禁止）
- result名称・ログ形式・pos_id・state構造の固定
- dashboard / report / audit との契約維持
- “壊れたログ（混入/旧形式）” が audit を破壊しない自己修復（self-heal）を保証
- AI学習ログ（ai_training_log.csv）を 1トレード=1行 で安定蓄積する
- 日次1回のAI閾値自動更新（損小利大目的）を安全に実行する
- 月次のAIしきい値再評価（PF/Expectancyゲート）を安全に実行する
- AI自動更新は LIVE-only 学習・LIVE重み付け・新しいデータ優先重みを CONTROL で調整可能
- AI自動更新後に CONTROL互換キー（`ai_threshold` / `ai_veto_threshold`）へ安全同期できる（許可キー限定）
- AIサンプル不足時にLIVEロットを据え置く安全ガードを適用できる

------------------------------------------------------------
1. bot.py の責務（固定）
------------------------------------------------------------

bot.py が担うもの：
- 市場データ取得（ticker）
- MA算出（state保持）
- シグナル生成（trend/signal）
- NEWSブロック判定
- SPREAD制限判定
- ENTRY（PAPER）発行 + pos_id 付与
- open_pos（EXIT管理 / EXTEND / HOLD / PARTIAL）
- state.json 管理（破損時でも安全）
- ログ出力（trade_log_YYYYMMDD.csv）
- self-heal（当日ログの整合修復 + state由来復元）

bot.py が担わないもの：
- 集計（PAPER率・勝率・MAE/MFE・extend成功率等）
- 可視化（ダッシュボード）
- 監査ロジック（audit）

------------------------------------------------------------
2. 実行フロー（契約に影響する順序のみ固定）
------------------------------------------------------------

(0) run_lock 確保（.run_lock/lockinfo.txt）
(1) now取得
(2) state.json 読込（破損/欠損でも {} で継続）
(3) CONTROL.csv 読込（欠損でも {} で継続）
(3a) ai_training_log.csv のヘッダ整合を確認（不整合なら .legacy_* 退避して再作成）
(4) ai_model.json 読込（欠損/壊れでも DEFAULT を deep-merge）
(4a) AI日次自動チューニング（1日1回、改善時のみ ai_model.json 更新）
     - `ai_auto_control_sync_enabled=1` のとき、`ai_threshold` / `ai_veto_threshold` を CONTROL.csv へ同期
     - 同期対象は allowlist 固定（未知キーは更新しない）
     - 書込失敗時はバックアップからロールバックし、botは継続
     - `ai_monthly_reval_enabled=1` のとき、月1回だけ長期lookbackで再評価し、ゲート通過時のみ threshold を更新
(5) runtime_cfg 構築（CONTROL/ai_model を吸収）
(5a) effective_stage 判定（PAPER/CANARY/LIVE）
(5b) LIVE有効時は risk guard 更新（日次損失率）
(6) state._control_snapshot 保存（失敗しても継続）
(7) csv_path = logs/trade_log_YYYYMMDD.csv 決定
(8) self_heal_today_log(csv_path) 実行（必要時のみ修復し state._self_heal_last に証跡)

(9) 稼働時間判定（固定契約）：
    - open_pos が無い場合：
        START_HOUR <= now.hour < END_HOUR 以外は
        result=SKIP_OUT_OF_TIME をログ出力し return（ENTRY禁止）
    - open_pos がある場合：
        稼働時間外でも open_pos 管理（HOLD/EXTEND/EXIT/EOD）を行う
        ただし open_pos が解消しても、同一tickでのENTRYは行わない
        （稼働時間外なら SKIP_OUT_OF_TIME をログ出力して return）

(10) ticker 取得（失敗は result=SKIP_TICKER_INCOMPLETE をログ→return）
(11) ltp/best_bid/best_ask 抽出（失敗は result=SKIP_TICKER_INCOMPLETE をログ→return）
(12) spread_pct 計算（失敗は result=SKIP_TICKER_INCOMPLETE をログ→return）
(13) MA更新（state.ltp_history に保持）→ state保存

(14) NEWSブロック判定：
     - open_pos が無い場合、該当時は result=SKIP_NEWS をログ出力し return（ENTRY禁止）
     - open_pos がある場合、NEWSでも EXIT/EOD は優先（クローズは許可）

(15) open_pos が存在する場合：
     (15a) EOD強制クローズ判定（最優先）→ PAPER_EXIT_EOD をログ出力、open_pos削除、return
     (15b) それ以外は EXIT処理（TP/SL/TIMEOUT/PARTIAL）または HOLD/EXTEND（7章）

(16) open_pos が無い場合（ENTRY判定）：
     (16a) today_on 判定（false なら SKIP_TODAY_OFF ログ→return）
     (16b) trade_enabled 判定（false なら OBSERVE_TRADE_DISABLED ログ→return）
     (16c) SPREAD制限（超過は SKIP_SPREAD ログ→return）
     (16d) signal==NONE は OBSERVE_NO_SIGNAL ログ→return
     (16e) 日次上限（SKIP_DAILY_LIMIT ログ→return）
     (16e-2) 連敗ストップ（有効時、当日N連敗到達で SKIP_DAILY_LIMIT + note=loss_streak_stop=1）
     (16f) no_paper_hours（OBSERVE_TIME_BLOCK ログ→return）
     (16g) SELL fast MA近接フィルタ（OBSERVE_SELL_FAST_MA_NEAR ログ→return）
     (16h) observe_only（OBSERVE_OK ログ→return）
     (16i) AI ENTRY判定（ブロック時は OBSERVE_AI_BLOCK または OBSERVE_OK + noteに理由）
     (16j) pos_id 発行、open_pos 保存
     (16k) PAPER ログ出力
     (16l) stateの日次カウント更新

LIVE互換ルール（固定）：
- result名は従来の PAPER / PAPER_EXIT_* を維持する
- LIVE実行時は note に `exec=LIVE stage=... order_id=... filled=...` を追記する
- paper_mode=0 かつ live_enabled=1 のときのみLIVE発注経路を許可する
- `exchange_name` で取引所を識別する（現行LIVE実装は bitflyer のみ）
- `market_type=FX/CFD` の場合、ENTRY数量は
  `collateral × fx_leverage × fx_collateral_use_ratio / entry_price` を上限として自動制限する
- `ai_lot_lock_enabled=1` の場合、`_ai_auto_train.rows < ai_lot_lock_min_samples` の間は
  ENTRY数量を `ai_lot_lock_max_lot` 以下に据え置く
- `market_type=FX/CFD` の日次損失ガードは JPY残高ではなく collateral ベースで評価してよい

※ bot.py は標準出力に print しない（何も表示されないのが正常）

------------------------------------------------------------
3. result 契約（固定）
------------------------------------------------------------

3.1 許可される result（RESULT_ALLOWED：固定契約）
以下以外はログに出してはいけない（出る場合は OBSERVE_OK へ正規化し note に残す）

【正常系】
- PAPER
- HOLD_OPEN_POS

【OBSERVE系】
- OBSERVE_NO_SIGNAL
- OBSERVE_OK
- OBSERVE_MR
- OBSERVE_MR_FILTER_NG
- OBSERVE_MR_TRIGGER
- OBSERVE_PHASE_B
- OBSERVE_TIME_BLOCK
- OBSERVE_BUY_FAST_MA_NEAR
- OBSERVE_SELL_FAST_MA_NEAR
- OBSERVE_TREND_FLIP_COOLDOWN
- OBSERVE_TREND_STRENGTH_WEAK
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
- PAPER_EXIT_PRENEWS

【ERROR系】
- ERROR_OPEN_POS_BROKEN

result名称の変更・削除は禁止。
追加する場合は **この節へ追記必須**。

3.2 HOLD_OPEN_POS の契約（固定）
- open_pos が存在し、EXITしない tick では HOLD_OPEN_POS を1行出す
- note先頭は OPEN または EXTENDED
- noteには少なくとも exp, best_fav, extend_count, pos_id を含める

------------------------------------------------------------
4. pos_id 契約（厳格固定）
------------------------------------------------------------

形式（厳格固定）：
YYYYMMDD-HHMMSS-(BUY|SELL)-NNN

例：
20260217-101543-BUY-002

ルール：
- 同日内で一意（state._pos_seq_YYYYMMDD により採番）
- PAPER時に必須付与
- EXIT時は必ず同一pos_idを使用
- ログに必ず pos_id カラムを含める
- note に "pos_id=..." を埋め込む（embed_pos_id）ことを許可（重複しても互換維持）
- pos_id の省略禁止（PAPER/EXITで空は契約違反）

------------------------------------------------------------
5. ログ形式（固定）
------------------------------------------------------------

ファイル：
logs/trade_log_YYYYMMDD.csv

必須カラム（順序固定）：
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

ルール：
- 既存カラムの削除禁止
- 追加は可（末尾追加推奨、互換維持前提）
- row の列数不一致（壊れ行）は self-heal の対象（audit破壊を防ぐ）

------------------------------------------------------------
6. self-heal 契約（固定）
------------------------------------------------------------

目的：
- 当日ログに “壊れた行 / 旧形式行 / 列数不一致” が混入しても audit を破壊しない
- stateにopen_posがあるのに当日PAPERが欠落しても audit を破壊しない

6.1 CSV整形修復（固定）
- 当日ログが無ければ header を生成
- header不一致 または 列数不一致行が1つでもあれば修復する：
  - 元ファイルをバックアップ：trade_log_YYYYMMDD.csv.bak_selfheal_HHMMSS
  - 正常行のみで trade_log_YYYYMMDD.csv を再構築（header+OK行）
  - 不正行は trade_log_YYYYMMDD_LEGACY_ROWS.csv に退避（追記）

6.2 open_pos由来のPAPER復元（固定）
- state._open_pos が存在し、当日ログにその pos_id の PAPER 行が存在しない場合：
  - state から entry 情報を用いて PAPER 行を1行補う
  - note 先頭に "RECONSTRUCTED_FROM_STATE" を付与する

証跡：
- 修復が発動した場合のみ state._self_heal_last に dict を保存（失敗しても bot は継続）

------------------------------------------------------------
7. EXIT整合ルール（厳格）
------------------------------------------------------------

PAPERは最終的に必ず以下のいずれかで閉じる：
- PAPER_EXIT_TP
- PAPER_EXIT_SL
- PAPER_EXIT_TIMEOUT
- PAPER_EXIT_PARTIAL_TP
- PAPER_EXIT_EOD

open_pos が破損していて判定不能な場合：
- ERROR_OPEN_POS_BROKEN をログ出力し open_pos を削除する

TP/SL判定（固定）：
BUY:
- ltp >= tp_price → PAPER_EXIT_TP
- ltp <= sl_price → PAPER_EXIT_SL
SELL:
- ltp <= tp_price → PAPER_EXIT_TP
- ltp >= sl_price → PAPER_EXIT_SL

TIMEOUT判定（固定）：
- now >= expiry_time_jst で発火
- timeout_mode:
  - IGNORE → PAPER_EXIT_TIMEOUT
  - PARTIAL → best_fav >= partial_tp_trigger_pct なら PAPER_EXIT_PARTIAL_TP else PAPER_EXIT_TIMEOUT
  - EXTEND → 延長条件を満たすなら expiry延長（HOLD_OPEN_POS note=EXTENDED を出す）
            それ以外は PAPER_EXIT_TIMEOUT

テクニカルEXIT（オプション）：
- `exit_technical_enabled=1` のとき、SMAクロスでEXIT判定を行う
- BUY保有中: fast が slow を上から下へクロスしたらEXIT
- SELL保有中: fast が slow を下から上へクロスしたらEXIT
- `exit_technical_only_paper=1` の場合、PAPER経路のみに適用する
- `exit_technical_min_hold_min` 未満の保有時間では発火しない
- result契約は維持し、`PAPER_EXIT_TIMEOUT` を使用する（`note` に `exit_tech=...` を記録）

EXTEND回数の条件（固定）：
- extend_count < max_extend_count の間だけ延長可能

EOD強制クローズ（固定）：
- now.time >= EOD_CUTOFF または now.hour >= END_HOUR で発火
- open_pos がある場合 result=PAPER_EXIT_EOD をログ出力し open_pos を削除する

------------------------------------------------------------
8. state.json 契約（固定）
------------------------------------------------------------

8.1 安全性
- state.json が欠損/破損でも bot は {} として安全起動する
- 既存キーの削除・意味変更は禁止
- 並行検証用に `OUROBOROS_INSTANCE=shadow` を使う場合、`state_shadow.json` / `CONTROL_shadow.csv` /
  `logs/instances/shadow/` / `.run_lock_shadow/` を使って本番系と分離してよい（main既定契約は維持）

8.2 主要キー（固定）
- _open_pos : dict | absent
- _control_snapshot : dict（保存できる場合）
- _self_heal_last : dict（self-heal発動時のみ）
- ltp_history : list[float]（MA算出用、最大長は cfg.max_ltp_history）
- _ohlc_current : dict（内部生成中のOHLC足。open/high/low/close/ticksを持つ）
- ohlc_history : list[dict]（確定済み内部OHLC足。チャートパターン検出用）
- _last_ltp : float
- _pos_seq_YYYYMMDD : int（pos_id 採番）
- "YYYY-MM-DD" : int（日次トレード数カウンタ）
- _effective_stage : str（PAPER/CANARY/LIVE）
- _rollout_start_day : str（YYYY-MM-DD）
- _risk_day : str（YYYY-MM-DD）
- _risk_day_start_jpy : float
- _risk_realized_jpy : float
- _risk_realized_pct : float
- _risk_stop : bool
- _streak_day : str（YYYY-MM-DD）
- _streak_consecutive_losses : int
- _streak_stop : bool
- _streak_last_ret_pct : float | null
- _pending_entry : dict（直近のENTRY注文状態）
- _pending_exit : dict（直近のEXIT注文状態）
- _ai_train_logged_pos_ids : list[str]（ai_training_log重複追記防止）
- _ai_auto_train_day : str（YYYY-MM-DD）
- _ai_auto_train : dict（日次チューニング結果）

8.3 予約領域（固定：今後の拡張はここへ）
- state._meta : dict
  - 内部ガードキー/運用フラグ/追加メタ情報はここへ追加してよい
  - REPORT/AUDIT は _meta を無視してよい

8.4 _open_pos 構造（固定契約）
- _open_pos は既存キーの削除禁止（追加は可）
- 追加情報は _open_pos.extra (dict) に入れることを推奨（REPORT/AUDITは無視してよい）

------------------------------------------------------------
9. AI 契約（固定）
------------------------------------------------------------

AIの介入点（固定）：
- ENTRY許可（decision_points.entry）
- EXTEND許可（decision_points.extend）
※ AIが介入しても “ログ母数” と “pos_id” と “result体系” を壊してはならない

特徴量（固定）：
- 既存: spread / trend / ma_gap / ma_slope / volatility / time
- 拡張: trendline_slope_pct_per_step / channel_pos / channel_width_pct
- 拡張: ma_cross / RSI / Bollinger / ATR / trend_power / chart_pattern / market_phase / aiba_style

チャート/OHLC特徴量（固定）：
- `chart_pattern_enabled=1` の場合、tickerの `ltp` から内部OHLC足を生成する
- 既定は `ohlc_timeframe_min=5`
- `state._ohlc_current` は生成中の足、`state.ohlc_history` は確定済み足を保持する
- 各OHLC足は `ticks` を持ち、足の薄さを判定する
- `chart_pattern_min_bar_ticks` / `chart_pattern_quality_lookback_bars` で品質判定する
- `cp_quality=OK` のときだけ `chart_pattern_comp` をAI scoreへ反映する
- `cp_quality=THIN` はログ記録のみで、昇格判断やAI加点/減点に使わない
- 初期対象パターンは `DOUBLE_TOP` / `DOUBLE_BOTTOM` / `HEAD_AND_SHOULDERS`
- noteには `cp_name` / `cp_stage` / `cp_bias` / `cp_confirmed` / `cp_trend` / `cp_neckline` / `cp_quality` / `cp_avg_ticks` を埋め込める

A/B/C局面特徴量（固定）：
- `market_phase_enabled=1` の場合、MA傾き、MA乖離、直近レンジ幅から A/B/C 局面を判定する
- MAだけで `NO_CLEAR_PHASE` になる場合、OHLCスイングと直近close変化から `SWING_UP` / `SWING_DOWN` / `OHLC_UP_SOFT` / `OHLC_DOWN_SOFT` / `OHLC_FLAT` の補助判定へフォールバックする
- `phase=A` は下落局面、`phase=B` は横ばい局面、`phase=C` は上昇局面を表す
- `phase=B` は原則避ける候補だが、強制ブロックは `market_phase_block_b_enabled=1` の時だけ行う
- B局面ブロック時の result は `OBSERVE_PHASE_B`
- 直前OHLC足の高値/安値を抜いた場合、`up_break=1` / `down_break=1` を note に残す
- 局面方向とブレイク方向が一致した場合、`phase_momentum=UP_BREAK` または `phase_momentum=DOWN_BREAK` を残す
- A/B/C局面が変わった場合、`state._market_phase` に現在局面・直近転換・転換時刻を保存し、note に `phase_transition=A->B` 形式で残す
- AI score には `market_phase_comp` として軽い補助点だけを入れる。局面単独で発注しない
- 日次レビューは `market_phase_outcomes` でA/B/C別の勝率、損益、TP/SL/TIMEOUT、break件数を集計する
- 日次レビューは `market_phase_transition_counts` で `A->B` / `B->C` などの転換回数を集計する
- `OBSERVE_PHASE_B` の件数は `observe_phase_b_n` として集計する

shadow TP寸前戻しexit（固定）：
- `near_tp_giveback_exit_enabled=1` の場合、TPの一定割合まで近づいた後に含み益を戻したpaper玉を `PAPER_EXIT_TIMEOUT` で閉じる
- 理由は note の `exit_tech=NEAR_TP_GIVEBACK` で記録する
- 既定はOFF。2026-04-18時点では `CONTROL_shadow.csv` のpaper-only検証だけON

相場流 Phase 1 特徴量（固定）：
- `aiba_style_enabled=1` の場合、相場式MA順序と傾きから補助ラベルを生成する
- 対象は `KUCHIBASHI` / `REV_KUCHIBASHI`、`PPP` / `REV_PPP`、`aiba_9=1`、`aiba_try_fail=1`
- `aiba_9=1` は9の法則の警戒フラグであり、単独exitは禁止
- `aiba_try_fail=1` は高値未更新 + 終値下落の連続を示す観測ラベルであり、単独発注は禁止
- AI score への反映は `aiba_style_ai_enabled=1` の時だけ `aiba_style_comp` として軽く加点/減点する。既定OFF
- 下半身 / 逆下半身はOHLC実体判定の Phase 2 とし、Phase 1では未実装

総合レビュー（固定）：
- `tools/trade_system_review.py` はローカルログだけを読み取り、main/shadow/特徴量別成績/実効設定/未指定情報/勝てない仮説をJSON/Markdownで出す
- `--write` の出力先は `MAIN/review_out/`
- `--snapshot-dir .local_llm/vm_snapshot/latest` 指定時は、読み取り専用VM snapshot内の `logs/` と `MAIN/CONTROL.csv` を解析する
- `feature_outcomes_top` は決済済みの特徴量別成績、`feature_presence_top` はOBSERVEを含むnote出現数として扱う
- CONTROL.csv書込、VM service restart、外部API送信、secret読取は行わない
- 設定変更やmain昇格の前に、このレビューまたは同等の証跡を確認する

ai_model.json の読込（固定）：
- DEFAULT を deep-merge して不足キーを補う
- ai_mode は内部で正規化（OFF / SCORE_ONLY / VETO / GATE）
- 互換として `global.threshold` から `confidence_threshold.entry` を補完可

AI学習ログ（固定）：
- PAPER_EXIT_* 確定時に ai_training_log.csv へ 1トレード1行を追記
- 重複追記は state の pos_id 履歴で抑止

AI自動チューニング重み付け（固定）：
- `ai_train_live_only=1` の場合、`exec_mode=LIVE` の学習データのみを使用する
- `ai_train_live_boost` で LIVE データの重みを増幅する（1.0〜3.0）
- `ai_train_recent_halflife_days` で新しいデータを優先する指数重みを適用する
- `ai_train_weekly_feedback_enabled=1` の場合、以下を追加適用する  
  `ai_train_weekly_good_hours` は `ai_train_weekly_good_hour_boost` で増幅、  
  `ai_train_weekly_bad_hours` は `ai_train_weekly_bad_hour_penalty` で減衰する

ログへの反映（固定）：
- AIによりブロックした場合、resultは SPEC外にせず OBSERVE_AI_BLOCK（推奨）
  または OBSERVE_OK とし note に理由を残す

------------------------------------------------------------
10. CONTROL.csv 契約（固定）
------------------------------------------------------------

形式：
- key,value 形式

ルール：
- 未知キー削除禁止（bot.py は無視しても良い）
- boolは 0/1 を基準（true/false等も safe_bool で吸収）
- 互換キーが増える場合は吸収ルールを追加し互換維持すること

------------------------------------------------------------
11. REPORT側契約（MAINは前提のみ固定）
------------------------------------------------------------

重要：
- bot.py は集計しない（PAPER率・勝率・extend成功率・MAE/MFE 等）
- MAINは「result体系」「分類前提」「pos_id」「必須カラム」を保証する

分類前提（固定）：
- OBSERVE系 = result が "OBSERVE" で始まるもの
- SKIP系 = result が "SKIP" で始まるもの
- EXIT系 = result が "PAPER_EXIT" で始まるもの

------------------------------------------------------------
12. 変更ルール（固定）
------------------------------------------------------------

以下を変更する場合は SPEC更新必須（互換破壊）：
- result名称（追加/削除/変更）
- ログ必須カラム（追加は可だが削除は禁止）
- pos_id形式
- EXIT種別
- _open_pos構造（キー削除/意味変更）
- self-heal の出力先（bak/legacy）仕様

------------------------------------------------------------
13. 最低受け入れチェック（固定）
------------------------------------------------------------

- bot.py が print せずとも、ログに追記が起きる（または安全return）
- PAPERにpos_idがある
- EXITに対応pos_idがある
- OBSERVE_NO_SIGNALが母数として残る（signal==NONEのとき）
- EODで open_pos が確実に閉じる（PAPER_EXIT_EOD）
- state.json 破損でも安全起動する
- 壊れ行を混入させても self-heal で audit が通る
- open_pos由来のPAPER欠落は RECONSTRUCTED_FROM_STATE で補える

============================================================
