# Ouroboros — 中央管理コンテキスト

このファイルはすべてのエージェント・コマンドが共有する中央文脈です。
読み込むだけで現在のシステム状態、判断基準、操作ルールを把握できます。

## 管理システム一覧

| システム | 場所 | 用途 | 状態 |
|---------|------|------|------|
| **MAIN** | `MAIN/` | bitFlyer BTC 自動売買ボット | 本番稼働中 (LIVE) |
| **IBKR** | `MAIN/ibkr_bot.py` | IBKR 米株自動売買ボット | PAPER稼働中（未入金） |
| **KEIBA** | `KEIBA/` | JRA 競馬予測・採点・LLM分析 | ローカル稼働中 |

各システムの詳細コンテキスト:
- MAIN: このファイルで管理
- KEIBA: `KEIBA/.claude/CLAUDE.md` を参照

---

---

## ボット識別情報

| 項目 | 値 |
|------|-----|
| 取引所 | bitFlyer FX |
| 通貨ペア | FX_BTC_JPY |
| lot | 0.001 BTC |
| leverage | 1.0x |
| 稼働時間 | 10:00–17:00 JST |
| rollout_mode | LIVE |

## VM接続情報

```bash
# SSH alias (推奨): ssh ouroboros-vm  ← ~/.ssh/config に Host エントリ設定済み
# 旧キーパス (Downloads/) は2026-05-24に ~/.ssh/ouroboros_vm_key へ移動済み

SSH_KEY=~/.ssh/ouroboros_vm_key
VM_HOST=161.33.26.35
VM_USER=ubuntu
VM_DIR=/home/ubuntu/trading_bot/MAIN
LOGS_DIR=/home/ubuntu/trading_bot/logs

ssh ouroboros-vm            # 推奨
ssh -i $SSH_KEY $VM_USER@$VM_HOST   # 旧形式 (互換)
```

## 重要ファイルマップ

| 用途 | ローカル | VM |
|------|---------|-----|
| 設定 | `MAIN/CONTROL.csv` | `/home/ubuntu/trading_bot/MAIN/CONTROL.csv` |
| 状態 | `MAIN/state.json` | `/home/ubuntu/trading_bot/MAIN/state.json` |
| 取引ログ | — | `/home/ubuntu/trading_bot/logs/trade_log_YYYYMMDD.csv` |
| AIモデル | `MAIN/ai_model.json` | `/home/ubuntu/trading_bot/MAIN/ai_model.json` |
| 運用チェック | — | `/home/ubuntu/trading_bot/MAIN/.ops_checks.json` |
| ハンドオーバー | `MAIN/HANDOVER.md` | `/home/ubuntu/trading_bot/MAIN/HANDOVER.md` |

## エージェント役割定義（スキルマップ）

```
CLAUDE.md（この文書）— 中央管理ハブ
  │
  ├─── [管理系]
  │   ├── /manage   — エージェントマネージャー
  │   │              全スキル台帳管理・担当範囲重複検出・統合指示
  │   └── /version  — バージョントラッカー
  │                  変更前後のバージョン確認・スペック表記録（必須チェック）
  │
  ├─── [MAIN — 自動売買ボット]
  │   ├── /risk     — リスク担当エージェント
  │   │              証拠金・日次損益・連敗・安全フロア監視
  │   ├── /log      — ログ担当エージェント
  │   │              取引ログ分析・異常検知・パターン抽出
  │   ├── /chart    — チャート担当エージェント
  │   │              市場文脈・HTFバイアス・トレンド強度・エントリー品質
  │   ├── /filter   — フィルター効率エージェント
  │   │              fast_ma_near/trend_weak/ai_block別ブロック件数・機会コスト試算
  │   ├── /ai       — AIモデル監視エージェント
  │   │              モデル鮮度・訓練WR vs 実績WR・週次WR時系列・自動学習状況
  │   ├── /fill     — 約定率エージェント
  │   │              OBSERVE_OK vs unfilled・時間帯別fill rate・offset調整提案
  │   ├── /backtest — バックテスト担当エージェント
  │   │              過去データfetch・バックテスト実行・AI学習サンプル生成
  │   ├── /data     — データ管理エージェント
  │   │              過去OHLCデータ状況・学習ログ統計・バックテストサンプル管理
  │   ├── /postmortem — シグナル事後分析エージェント [NEW]
  │   │              TP/SL別Edge算出・Kelly試算・時間帯別WR・ドローダウン分析
  │   ├── /regime   — 市場レジーム検出エージェント [NEW]
  │   │              ATRパーセンタイル+EMA+Hurst 4象限分類・フィルター強度推奨
  │   ├── /kelly    — Kelly基準ポジションサイジング [NEW]
  │   │              BTC+IBKR EdgeのKelly倍率算出・Wilson保守推定・推奨リスク%
  │   ├── /critic   — BTC週次評価エージェント
  │   │              100点減点方式スコアリング・パラメータ自動改善（毎週日曜20:00 JST）
  │   └── /status   — モーニングブリーフィング（全エージェント一括）
  │                  リスク+ログ+チャート+フィルター+ops_checks+KEIBA を1コマンドで確認
  │
  ├─── [IBKR — 米株自動売買ボット]
  │   ├── /ibkr     — IBKR週次評価エージェント
  │   │              100点減点方式スコアリング・パラメータ自動改善（毎週日曜20:30 JST）
  │   ├── /ibkr-guardian — IBKR安全監視エージェント
  │   │              日次P&L・オープンポジション・損失限界・サービス稼働確認
  │   ├── /council  — 投資円卓会議エージェント [NEW]
  │   │              実在投資家11人の思想トレース・ALL-YESゲート・週次DD固定（note記事ベース）
  │   └── /protrader — プロトレーダーAgent [NEW 2026-06-11]
  │                  知識ベース(docs/trading_knowledge/)実装。直近取引を100点採点・bot批評・改善提案
  │
  └─── [KEIBA — 競馬予測システム]
      └── /keiba    — KEIBA状態確認エージェント
                     自動サイクル状況・予測精度・データ量・launchd確認
```

> **台帳詳細は `/manage` を参照**。新スキル追加・統合・廃止は `/manage` で登録台帳を更新すること。

## 新規システム追加時の手順（統合ガイド）

別システムをこの中央管理に追加する場合:
1. `<SYSTEM>/.claude/CLAUDE.md` を作成（システム固有コンテキスト）
2. `<SYSTEM>/.claude/commands/<skill>.md` を作成（スキル定義）
3. `.claude/commands/<system>.md` をルートに追加（ルートスキル）
4. このファイルのスキルマップと「管理システム一覧」に追記
5. `/manage` の台帳に追加（担当範囲が重複しないことを確認）

## 現在のキーパラメータ（CONTROL.csv）

| パラメータ | 値 | 意味 |
|-----------|-----|------|
| `rollout_mode` | LIVE | 本番稼働中 |
| `start_hour` | 9 | 取引開始時刻（10→9に拡張、Shadow 9時 WR 66.7%/+92円 を獲得 2026-05-24） |
| `no_paper_hours` | "11,14,16" | エントリーブロック時間帯（Shadow 1週間で11時 WR 0%/-32円 → 11時追加 2026-05-24） |
| `daily_loss_limit_pct` | -1.5% | 日次損失上限（-2.0→-1.5に厳格化） |
| `streak_stop_max_losses` | 2 | 連敗ストップ数（3→2に短縮） |
| `ai_threshold` | 0.70 | AIゲート閾値（0.70→0.73→0.80→0.75→0.70、2026-06-05 週7件と過少・AIゲートが最大ブロッカーのため緩和） |
| `ai_min_score` | 0.55 | 最低スコア |
| `ai_veto_threshold` | 0.30 | AIベト閾値（0.8→0.30に修正、Shadow/Localと統一） |
| `sl_pct` | -0.140% | ストップロス |
| `tp_buy_pct` / `tp_sell_pct` | 0.220% | テイクプロフィット（0.190→0.220に拡大、R:R改善） |
| `trend_strength_min_er` | 0.30 | トレンド強度フィルター（0.28→0.30に引き上げ） |
| `*_only_paper` (4件) | 0 | スマート出口をliveでも有効化（session20） |
| `near_tp_giveback_exit_trigger_ratio` | 0.75 | TP到達75%で反転検知（0.85→0.75に引き下げ） |
| `progress_reversal_exit_min_hold_min` | 30 | 反転検知の最小保持時間（20→30に延長、2026-05-28 早期撤退過多のため）|
| `progress_reversal_exit_min_best_fav_pct` | 0.10 | 0.10%含み益で反転検知（0.08→0.06→0.10、2026-05-28 緩和）|
| `no_follow_through_exit_min_hold_min` | 8 | フォロースルー判定の最小保持時間（3→8、2026-05-28 緩和）|
| `no_follow_through_exit_max_best_fav_pct` | 0.05 | 0.05%以内の微小利益から戻した場合に早期撤退（0.01→0.03→0.05、2026-05-28 緩和）|
| `chop_filter_enabled` | 1 | chop回避レジームゲート有効（2026-06-07追加・bot v2026.06.07.1）|
| `chop_filter_mode` | observe | observe=記録のみ(実取引不変) / block=実遮断。**検証後にblock化予定** |
| `chop_require_weak_trend` | 0 | chop判定のweak必須を解除（2026-06-07: weak条件がtrend_strength(ER<0.30)と重複しchopが発火不能だったため。ATR低単独でobserve記録に変更）|
| `chop_block_atr_regimes` | low | **[legacy]** 旧atr_regime方式（AIスコア用atr_low_pct=0.04がBTC実測min=0.0526を下回り無発火だった）。`chop_atr_low_pct`へ移行 |
| `chop_atr_low_pct` | 0.08 | chop専用ATR閾値（2026-06-10追加・bot v2026.06.10.1）。AIスコア用atr_low_pctから分離。BTC実測 min=0.0526/median=0.1048/p25≒0.08。`atr_pct<=0.08`でchop扱い→observe記録 |

## 現在のキーパラメータ（IBKR_CONTROL.csv）

| パラメータ | 値 | 意味 |
|-----------|-----|------|
| `ibkr_enabled` | 1 | IBKR bot有効 |
| `ibkr_port` | 7496 | IB Gateway接続ポート（7497=paper, 7496=live）← live稼働中 |
| `ibkr_trade_symbol` | QQQ | 取引銘柄 |
| `ibkr_shares` | 1 | 1注文あたり株数 |
| `ibkr_tp_pct` | 1.0 | テイクプロフィット（%）— stock_shadow好調を受け 0.5→1.0 拡大 2026-05-24 |
| `ibkr_sl_pct` | -0.5 | ストップロス（%）— R:R 2:1維持で -0.25→-0.5 拡大 2026-05-24 |
| `ibkr_daily_loss_limit_usd` | -20 | 日次損失上限（少額運用: $500→$20） |
| `ibkr_max_trades_per_day` | 6 | 1日最大取引数（6銘柄対応後に増加） |
| `ibkr_vix_block_threshold` | 30 | VIX恐怖指数ゲート（VIX≥30でエントリーブロック） |
| `ibkr_start_hour_et` / `ibkr_end_hour_et` | 9:45 – 15:50 ET | 取引時間帯 |
| `ibkr_atr_sl_multiplier` | **2.0(有効)** | **[B/P1対策]** ATRベース損切り倍率（2026-06-11追加・bot v2026.06.11.2）。`SL=max(0.5, ATR%×2.0)`(より負=ワイドの時のみ採用)＝固定-0.5%がATRノイズより狭く狩られる構造欠陥の修正。**Phase3バックテストで検証→2026-06-11有効化**（735トレードで固定SL負け期待値-7.50%→ATR-SL ×2.0で+12〜18%）。次営業日から発効 |
| `ibkr_atr_tp_multiplier` | 4.0 | ATRベースTP倍率。`TP=max(1.0, ATR%×4.0)`。B案(sl_mult=2.0)とR:R 2:1維持のため 1.5→4.0 に変更（2026-06-11） |
| `ibkr_sell_daily_move_block_pct` | -2.0 | **[A/P3対策・observe]** SELL対称ガード（2026-06-11追加・bot v2026.06.11.2）。日中既に`daily_move<=この値`の過伸び下落でSELL(空売り)を記録/遮断。0=無効。BUYのみ存在した落ちるナイフ回避をSELL側にも |
| `ibkr_sell_daily_move_block_mode` | observe | observe=記録のみ(実取引不変・`SELL_DM_OBSERVE`ログ) / block=実遮断。**検証後にblock化予定** |
| `ibkr_min_atr_pct_entry` | 0.20 | **[P2レジーム対策・observe]** ATR下限エントリーフィルタ（2026-06-11追加・bot v2026.06.11.3）。`atr%<この値`の低ボラ(チョップ)でSMAクロスはwhipsay負け→記録/遮断。0=無効。バックテストで`ATR%≥0.20`が有効と確認 |
| `ibkr_min_atr_pct_entry_mode` | observe | observe=記録のみ(`LOW_ATR_OBSERVE`ログ) / block=実遮断。**検証後block化予定** |

### IBKR live切り替え手順（口座入金後）
1. 口座に資金が入ったことを確認
2. VM上で `bash tools/ibkr_go_live.sh` を実行（GOLIVEと入力して確認）
3. IB Gatewayが再起動しliveモードで接続されることを確認
4. 緊急停止: `ibkr_enabled=0` をIBKR_CONTROL.csvに設定、またはサービス停止

## 判断ルール（正本: AI実行前確認ルール.md に従う）

> **承認基準の正本は `/Users/tani/ALTER_CORE/BUSINESS/経営方針/AI実行前確認ルール.md`**。本書はそれに従い、矛盾する場合は正本（＝確認する方）を優先する。承認レベル 🟢自走OK / 🟡実行前確認 / 🔴禁止。迷ったら一段厳しい方へ倒す。

### 🟢 自走OK（確認不要）
- VMのログ・状態の読み取り・分析・表示
- ローカルファイルの読み取り・分析
- dry-runフラグ付きのスクリプト実行

### 🟡 実行前確認（§6の型「[対象]を[目的]で変更。内容は[要約]。進めていい?」→ 承認後に実行）
- CONTROL.csv のパラメータ変更（数値調整）
- VMへのファイル書き込み・デプロイ
- systemdサービスの再起動・停止
- bot.py のコード変更
- HANDOVER.md・スペック表・ダッシュボードの更新
- Keychain項目・設定の認証まわり

### 🔴 禁止（実行しない / 必要なら代替案のみ）
- 証拠金・資金の入出金・ロット変更・LIVE資金設定変更
- `safety_hard_block=1` への変更（取引即停止）※やるなら説明し承認を取る
- 認証情報（secrets/鍵）の内容出力・コピー

---

## 🚫 AIに触らせてはいけない5つの領域

> 参照: https://note.com/sabatora_/n/n903807900e9f  
> 原則: **AI = 提案・補助・加速 / たにさん = 責任・承認・決裁**  
> 「壊れないこと」より「戻せること」を優先する。バックアップ・ロールバックを常に確保する。

### 領域1: 資金・決済（Billing）
**絶対禁止:**
- bitFlyer への入出金操作・証拠金変更
- IBKR 口座への資金移動・引き出し
- VPS（さくらVPS）の課金プラン変更・解約
- サブスクリプション（Streamlit Cloud / ntfy / その他）の課金操作

**要確認（説明してから実行):**
- `ibkr_go_live.sh` の実行（PAPER→LIVEへの切り替え = 実弾稼働開始）
- IBKR_CONTROL.csv の `ibkr_port=7496`（live port）への変更

**AIが行ってよいこと:**
- P&L・資金残高の読み取り・表示・分析

---

### 領域2: 認証・APIキー（Auth / Secrets）
**絶対禁止:**
- `secrets.toml` のキー値をログ・通知・コメントに出力する
- SSH秘密鍵（`~/.ssh/ouroboros_vm_key`）の内容を読み取る・コピーする
- bitFlyer API Secret / IBKR パスワード を任意のファイルに書き込む
- ntfy Bearer Token をコードにハードコードする

**要確認:**
- `secrets.toml` の編集（既存キーの値変更）
- SSH authorized_keys の変更（VM側）

**AIが行ってよいこと:**
- キーの「存在確認」（値の表示は禁止）
- secrets.toml のキー名一覧の確認

---

### 領域3: 本番データ直接書き換え（Production Data）
**絶対禁止:**
- VM上の `state.json` を直接上書き（`bot.py` 経由以外）
- VM上の `trade_log_YYYYMMDD.csv` を手動編集・削除
- VM上の `ai_model.json` をバックアップなしで上書き
- 本番ログディレクトリ（`/home/ubuntu/trading_bot/logs/`）の一括削除

**要確認:**
- state.json のリセット（`{}` への初期化）
- 過去ログの削除・アーカイブ

**AIが行ってよいこと:**
- 全ログ・状態の読み取り・分析
- ローカルコピー（`.local_llm/ibkr/`）の更新

---

### 領域4: インフラ・ネットワーク設定（Infrastructure）
**絶対禁止:**
- VM の sshd_config 変更（ポート・認証方式）
- VM の ufw/iptables ルール変更
- `/etc/systemd/system/` 配下のユニットファイルを確認なしで上書き
- DNS設定・VPS コントロールパネルの操作

**要確認:**
- `ouroboros-ibkr-bot.service` / `ouroboros-bot.service` のユニットファイル変更
- systemd サービスの enable/disable（restart は確認不要）
- LaunchAgent plist の追加・削除

**AIが行ってよいこと:**
- `systemctl status` / `journalctl` によるログ確認
- `systemctl restart` によるサービス再起動
- plist の内容編集（load/unload はたにさんが実行）

---

### 領域5: 法務・税務・規制（Legal / Tax）
**絶対禁止:**
- 確定申告の損益計算を最終値として出力する
- 金商法・景表法・特商法に関わる判断を断言する
- 利用規約・免責事項の文面を「完成版」として作成する（ドラフトは可）

**要確認:**
- 税務上の取り扱い（仮想通貨・株式の損益通算）
- SNS投稿の法規制チェック（薬機法・景表法）

**AIが行ってよいこと:**
- 法規制の調査・情報収集（最低2ソースで確認）
- ドラフト作成（「参考情報」として提供）
- 専門家への相談事項の整理

---

## デイリー改善サイクル（毎日実行）

### 朝チェック（取引開始前 / `/status` で一括実行）
1. 前日の取引件数・WR・P&Lを確認
2. BTC critic スコアが60点未満 → 今週の減点原因を特定し即パラメータ修正
3. IBKR critic スコアが60点未満 → フィルター過剰/不足を特定し修正
4. ダッシュボードの赤バッジを確認（IBKR未接続・BTC停止・監査警告）

### 週次自動評価（日曜 20:00/20:30 JST 自動）
- BTC: `/critic` → `weekly_btc_critic.py` が自動実行・auto-apply
- IBKR: `/ibkr` → `weekly_ibkr_critic.py` が自動実行・auto-apply
- 手動確認: スコア・減点理由・適用済みパラメータを必ず確認する

### 改善サイクルのルール
- **取引件数が週10件未満（BTC）/ 週3件未満（IBKR）** → フィルターが過剰。critic の減点理由を見てブロック件数の多いパラメータを緩和する
- **WR が BE（BTC:39% / IBKR:33%）を5pt以上割った状態が2週続く** → フィルターが甘い可能性。critic のTP/SL比率・market_phase を確認
- **パラメータ変更は必ずスペック表に記録**（変更前→後・根拠・期待効果を1行で）
- **変更後2週間は様子見**。連続変更は効果が見えなくなるので最小1変更ずつ

## 品質基準（Output Gate）

### 作業前（必須）
1. **関連スペック・計画ファイルを確認してから着手する**
   - コード変更: `MAIN/docs/OUROBOROS_TRADING_SPEC_TABLE.md` / IBKR は `MAIN/docs/IBKR_AGENT_SPEC.md`
   - ダッシュボード作業: `MAIN/docs/DASHBOARD_IMPROVEMENT_PLAN.md`（Step番号・完了状況を確認）
   - その他: 関連する `docs/*.md` を先に読む
2. **`/version` で変更前バージョンを確認**（`bot.py` / `dashboard.py` / `widget_status.py` に変更を加える場合）
3. **VM=正本**: 本番はVMが最新。**編集/デプロイ前に必ずVMから取得・差分確認**（古いローカルでVMを上書きしない）。`MAIN/` はgitサブモジュール(`citron073/MAIN`)、`.vm_snapshot/` は配備ステージング。
   - **git構造（2026-06-07 クリーンmain再構築済み）**: `citron073/MAIN` の正本ブランチは **`main`**（commit `214d310` / 487ファイル / 動画・別アプリ・運用出力を除外）。旧ブランチ既定 `fixapp/20260213-051546` は非推奨。**32GB肥大の原因（無関係な動画アプリyt_tool等）を含む全履歴は `sync/vm-fsync-20260606` に退避保持**。`.gitignore` で `*yt_tool*` / `*.mp4` / `action_reader/` / `reports/` / `local_ai/` / `tax_report/` 等を追跡停止済み。新たに別アプリ/大容量生成物を混入させないこと。
   - **運用状態ファイルの追跡停止（2026-06-07）**: `MAIN/.ops_checks.json`（run_check.sh / spec_check.py が実行毎に書き換え＝state.json と同性質）を MAIN の `.gitignore` に追加し `git rm --cached`（disk保持）。pre-push フック実行のたびに MAIN submodule が dirty 化→親repo が `submodule modified` を出し続ける再発性の衛生問題を解消。MAIN commit `b5dead7` / 親 pointer `cdec5bb→b5dead7`（親 commit `519a5b0`）。
3.5. **メモリ/引き継ぎ要約を鵜呑みにしない（実ファイル裏取り必須・2026-06-10 教訓）**: claude-mem の観測や前チャットの引き継ぎ要約に「適用済み/デプロイ済み」とあっても**そのまま信じない**。着手前に必ず**実ファイルの grep・version・git status を local と VM の両方で突き合わせ**、実態を一次情報として確認してから動く。
   - 背景: 2026-06-10、書式エラーで未実行に終わった bot.py 編集を haiku 生成の観測(obs 1169)が「適用済み」と誤記録。実ファイルは旧ロジックのままだった。実態確認していなければ二重適用・破損を招いていた。
   - 手順: ①対象シンボルを `grep -n` で local/VM 両方確認 ②`OUROBOROS_BOT_VERSION` を両者照合 ③`git status -s` がクリーンか ④矛盾があれば**実ファイルを正**としメモリ記録は疑う。

### 実装中
4. `python3 -m py_compile` でシンタックスエラーなし
5. VMデプロイ前にローカル/PAPERでテスト済み
6. バックアップ（`.bak.*`）を取ってからデプロイ
7. `ibkr_bot.py` を変更した場合は必ずバージョン番号を上げる（例: v2026.05.15.4 → v2026.05.15.5）
8. **新コード経路の parity**: 新しい分岐(新決済理由・新state)を足したら、通知(ntfy)・ログCSV・state更新を既存経路と同等にする（無音バグ防止 / 2026-06-04 STOPFILL無通知の教訓）。

### 作業後（必須）
9. **完了項目をチェックオフ**: 改善計画ファイル内の該当 No を `✅` に更新する
10. **スペック表に記載**: `MAIN/docs/OUROBOROS_TRADING_SPEC_TABLE.md` / `IBKR_AGENT_SPEC.md` の「実装状況」に追記する
11. VMデプロイ後はVM上で確認（`wc -l` / `ls -lh` / `systemctl is-active` / `NRestarts=0` / 新規Traceback無し）
12. 変更後に `/version` で整合性チェックを実行する
13. **Notionに記録（必須）**: `python3 /Users/tani/ALTER_CORE/BUSINESS/tools/log_change_to_notion.py "<題>" "<本文>" [設計|スペック]`
14. **会話が長くなる前に進捗を記録**: `~/.claude/projects/.../memory/` と `MEMORY.md` を更新する（コンテキスト圧縮で消えるのを防ぐ）

## 勝率基準（時間帯別）

| 時間 | WR | 状態 |
|------|----|------|
| 10h | 51% | Good（スコア+0.13 logit boost、ai_time_good_hour_boost） |
| 11h | 47% | Open |
| 12h | 45% | Open |
| 13h | 44% | Open（スコア-0.10） |
| 14-16h | <42% | ブロック |

## 改訂履歴

| 日付 | 変更内容 |
|-----|---------|
| 2026-06-01 | 🚫 AIに触らせてはいけない5つの領域を追加（note.com/sabatora_ 参照） |

## よくあるエラーと対処

| エラー | 原因 | 対処 |
|--------|------|------|
| `fx_below_min_lot` | FX証拠金不足 | bitFlyer FXに入金 |
| `entry_unfilled` | limit注文未約定（正常） | 許容範囲。fill rateを確認 |
| `OBSERVE_TIME_BLOCK` | 取引時間外（正常） | 対応不要 |
| `SKIP_NEWS` | ニュースブロック（正常） | 対応不要 |
| bot 1秒クラッシュ | state.json破損またはlockfile競合 | state確認→lockfile確認 |
