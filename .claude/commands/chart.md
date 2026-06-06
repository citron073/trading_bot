# /chart — チャート担当エージェント

**役割**: 市場文脈（HTFバイアス・トレンド強度・OHLCパターン・フェーズ）を分析し、
エントリー品質と現在のシステムの市場適合性を評価する。

## 市場文脈取得コマンド

### 1. 現在のstate.jsonから市場文脈を抽出
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import json, pathlib, csv

state = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/state.json').read_text())

# CONTROL.csv からパラメータ取得
ctrl = {}
for row in csv.reader(open('/home/ubuntu/trading_bot/MAIN/CONTROL.csv')):
    if len(row) >= 2: ctrl[row[0].strip()] = row[1].strip()

print('=== 現在の市場文脈 ===')
print(f'LTP:          {state.get(\"_last_ltp\", \"N/A\"):,.0f} JPY')
print()

# HTF context — state から読むか、ltp_historyから近似計算
htf15 = state.get('_htf15_context', {}) or {}
htf60 = state.get('_htf60_context', {}) or {}

# ltp_historyから近似HTFバイアス計算 (state書き込みがない場合のフォールバック)
ltp_hist = state.get('ltp_history', []) or []
if (not htf15 or not htf60) and len(ltp_hist) >= 36:
    def htf_bias_approx(hist, n):
        if len(hist) < n: return 'N/A'
        tail = hist[-n:]
        groups = [tail[i*3:(i+1)*3] for i in range(n//3)]
        group_closes = [g[-1] for g in groups if g]
        if len(group_closes) < 3: return 'N/A'
        rising = sum(1 for i in range(1,len(group_closes)) if group_closes[i] > group_closes[i-1])
        falling = len(group_closes)-1 - rising
        return 'UP' if rising > falling else 'DOWN' if falling > rising else 'NEUTRAL'
    htf15_bias = htf15.get('bias') or htf_bias_approx(ltp_hist, 9)   # ~15min
    htf60_bias = htf60.get('bias') or htf_bias_approx(ltp_hist, 36)  # ~60min
else:
    htf15_bias = htf15.get('bias', 'N/A')
    htf60_bias = htf60.get('bias', 'N/A')

print(f'HTF15 bias:   {htf15_bias}')
print(f'HTF60 bias:   {htf60_bias}')
conflict = htf15_bias != htf60_bias and 'N/A' not in (htf15_bias, htf60_bias)
print(f'HTF競合:      {\"あり (ペナルティ適用)\" if conflict else \"なし\"}')
print()

# ER (Efficiency Ratio) — state書き込みがない場合も ltp_history から直接計算
ts = state.get('_trend_strength', {}) or {}
er = ts.get('er')
if er is None and len(ltp_hist) >= 20:
    lookback = int(ctrl.get('trend_strength_lookback_n', '20'))
    tail = [float(x) for x in ltp_hist[-lookback:]]
    gross = sum(abs(tail[i]-tail[i-1]) for i in range(1, len(tail)))
    net = abs(tail[-1] - tail[0])
    er = round(net/gross, 4) if gross > 0 else 0.0
    er_src = '(ltp_history直接計算)'
else:
    er_src = '(state)'

min_er = float(ctrl.get('trend_strength_min_er', '0.28'))
print(f'ER (トレンド強度): {er} {er_src} (閾値: {min_er})')
print(f'トレンドフィルター: {\"通過\" if er is not None and float(er) >= min_er else \"ブロック (チョッピー)\" if er is not None else \"N/A\"}')
print()

# OHLC pattern
ohlc = state.get('_ohlc_current', {}) or {}
print(f'OHLCパターン: {ohlc.get(\"pattern\", \"N/A\")}')
print(f'パターンバイアス: {ohlc.get(\"bias\", \"N/A\")}')
print(f'パターン確信度: {ohlc.get(\"confirmed\", \"N/A\")}')
print()

# Phase (stored in _market_phase dict)
mp = state.get('_market_phase', {}) or {}
print(f'フェーズ:     {mp.get(\"phase\", \"N/A\")} (理由: {mp.get(\"phase_reason\", \"N/A\")})')
print(f'モメンタム:   {mp.get(\"momentum\", \"N/A\")}')
print(f'最終トレンド: {state.get(\"_trend_last\", \"N/A\")} (反転: {state.get(\"_trend_flip_time_jst\", \"N/A\")})')
PYEOF"
```

### 2. 直近のOHLC履歴（最新10本）
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import json, pathlib

state = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/state.json').read_text())
history = state.get('ohlc_history', []) or []

print(f'OHLC履歴 最新{min(10, len(history))}本:')
print(f'{'時刻':20s}  {'O':>12s}  {'H':>12s}  {'L':>12s}  {'C':>12s}  {'ticks':>6s}')
for bar in history[-10:]:
    ts = bar.get('ts', '')[:16]
    o = bar.get('o', 0)
    h = bar.get('h', 0)
    l = bar.get('l', 0)
    c = bar.get('c', 0)
    tk = bar.get('ticks', 0)
    direction = '↑' if c > o else '↓' if c < o else '→'
    print(f'{ts:20s}  {o:12,.0f}  {h:12,.0f}  {l:12,.0f}  {c:12,.0f} {direction}  {tk:6d}')
PYEOF"
```

### 3. 直近ログからHTF文脈ブロック件数集計
```bash
TODAY=$(date +%Y%m%d)
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
python3 << 'PYEOF'
import pathlib, re, collections

log = pathlib.Path(f'/home/ubuntu/trading_bot/logs/trade_log_${TODAY}.csv')
if not log.exists():
    print('今日のログなし')
    exit()

counters = collections.Counter()
for line in log.read_text().splitlines():
    if 'OBSERVE_TREND_STRENGTH_WEAK' in line: counters['trend_weak'] += 1
    if 'htf60_countertrend=1' in line: counters['htf60_counter'] += 1
    if 'htf15_60_conflict=1' in line: counters['htf_conflict'] += 1
    if 'OBSERVE_AI_BLOCK' in line: counters['ai_block'] += 1
    if 'OBSERVE_OK' in line: counters['observe_ok'] += 1

print('今日のフィルター統計:')
for k, v in counters.most_common():
    print(f'  {k}: {v}件')
PYEOF"
```

### 4. AIモデルの現在状態
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import json, pathlib

model = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/ai_model.json').read_text())
meta = model.get('meta', {})
perf = model.get('performance', {})

print('=== AI モデル状態 ===')
print(f'学習日:       {meta.get(\"trained_at\", \"N/A\")}')
print(f'サンプル数:   {meta.get(\"n_samples\", \"N/A\")}')
print(f'閾値:         {model.get(\"confidence_threshold\", {}).get(\"entry\", \"N/A\")}')
print(f'訓練WR:       {perf.get(\"train_wr\", \"N/A\")}')
print(f'訓練PF:       {perf.get(\"train_pf\", \"N/A\")}')
PYEOF"
```

## 出力フォーマット

```
【チャート担当レポート】YYYY-MM-DD HH:MM JST

📊 現在の市場文脈
  LTP: XX,XXX,XXX JPY
  
  HTF15: UP/DOWN/NEUTRAL  HTF60: UP/DOWN/NEUTRAL
  HTF競合: あり/なし  → ペナルティ: あり/なし
  
  トレンド強度 (ER): X.XX (閾値0.28以上で通過)
  → フィルター: 通過中/ブロック中

  現在フェーズ: X (理由: XXX)
  OHLCパターン: XXX / バイアス: BUY/SELL/NEUTRAL

🔍 エントリー品質評価
  今日のフィルター統計:
  - trend_weak (チョッピー): XX件
  - htf60_countertrend: XX件  
  - htf_conflict: XX件
  - ai_block: XX件

🤖 AIモデル状態
  最終学習: YYYY-MM-DD  サンプル: XXX件
  訓練WR: XX.X%  PF: X.XX

【判定】
  市場適合性: 高/中/低
  エントリー推奨: 積極的/通常/慎重
  注目点: [具体的な観察事項]
```

## 市場適合性判断基準

| 条件 | 評価 | 推奨 |
|------|------|------|
| ER≥0.28 かつ HTF競合なし | 高 | 積極的にエントリー |
| ER≥0.28 かつ HTF競合あり | 中 | 慎重 (ペナルティ確認) |
| ER<0.28 (チョッピー) | 低 | エントリー控え目 |
| HTF両方がNEUTRAL | 中 | 短期シグナル重視 |
