# /council — 投資円卓会議エージェント

**役割**: note記事 (note.com/futsuoji_nisa/n/n1e2cb12befe7) の「11人の伝説的投資家を円卓会議でロールプレイさせる」手法を常設運用する。実在の著者の **公開された著書・哲学のトレース**（本人の発言・承認ではない）。1週間スイングで、エッジのある時だけ張り、週次DDを固定する。

**知識ベース**: `MAIN/docs/INVESTOR_COUNCIL.md`（11投資家のルール定義）
**エンジン**: `MAIN/investor_council.py`（`evaluate()` / `week_guard()` / `update_week_pnl()`）
**ボット統合**: `ibkr_bot.py` の entry ゲート（`ibkr_council_enabled=1` で有効）

---

## 構成（円卓のメンバー）

| 陣営 | メンバー（トレース元の著書） | 役割 |
|------|------|------|
| 攻撃 | O'Neil『How to Make Money in Stocks』/ Minervini『Trade Like a Stock Market Wizard』/ Livermore『Reminiscences of a Stock Operator』/ Darvas『How I Made $2,000,000』/ Druckenmiller(講演) / Soros『The Alchemy of Finance』 | 張る判断・確信度 |
| 規律 | Graham『The Intelligent Investor』/ Templeton / Lynch『One Up on Wall Street』/ Marks『The Most Important Thing』/ Paul Tudor Jones(講演) | 拒否権＝買わない技術 |

---

## 報告プロトコル（サブエージェント連携）

`/council` は判断前に各エージェントから **入力** を集約し、判断後に **議事録** を返す。

1. **入力収集（叩き起こす対象）**
   - `/chart` → 市場文脈・HTFバイアス・トレンド強度（→ Livermore/Minervini の根拠）
   - `/ai` → AIモデル確信度・鮮度（→ 攻撃陣の補強票）
   - `/risk` → 証拠金・日次/週次損益・連敗（→ 週次DDストップ判定）
   - `/postmortem` → TP/SL別Edge・時間帯別WR（→ conviction閾値の妥当性）
2. **会議実行**: `python3 MAIN/investor_council.py`（単体）または ボット内ゲートが自動呼出
3. **議事録出力**: `MAIN/local_ai/investor_council/council_report.{json,md}`（誰が賛成/反対/拒否権・最終判断・週次ガード）
4. **報告徹底**: CONFIRM/PASS と理由を必ず1行で残す。PASS（買わない）も成果として記録する。

---

## データ取得コマンド

### 1. 直近の議事録
```bash
cat /Users/tani/trading_bot/trading_bot/MAIN/local_ai/investor_council/council_report.md 2>/dev/null || echo "まだ議事録なし"
```

### 2. 週次ガード状態（DDストップ／ストレッチ目標）
```bash
cat /Users/tani/trading_bot/trading_bot/MAIN/local_ai/investor_council/council_week_state.json 2>/dev/null || echo "週次状態なし"
```

### 3. 任意シナリオで会議を試す（単体デモ）
```bash
cd /Users/tani/trading_bot/trading_bot && python3 MAIN/investor_council.py
```

### 4. 過去ログを会議に再生（バックテスト的検証）
直近の `logs/ibkr_trade_log_*.csv` の各エントリーを `evaluate()` に流し、CONFIRM/PASS と回避損益を集計する。

---

## 判断基準

- **既定は PASS（買わない）**。規律陣の拒否権 or ALL-YESゲート不成立で即見送り。
- conviction ≥ `ibkr_council_min_conviction`（既定2.5）で CONFIRM。
- **週次DDストップ**（`ibkr_council_weekly_dd_stop_usd`）発動中は全エントリー停止。
- **ストレッチ目標**（`ibkr_council_weekly_target_usd`>0）達成で新規停止＝勝ちを確定。

## 注意

- 10%/週は **ストレッチ**。安定再現は不可能（年率換算+14,000%相当）。会議はDD固定で下方を守ることを最優先する。
- パラメータ調整は `IBKR_CONTROL.csv` の `ibkr_council_*`。変更はスペック表に記録。
- 本番有効化は `ibkr_council_enabled=1` → VMデプロイ → 必ずローカル検証後。
