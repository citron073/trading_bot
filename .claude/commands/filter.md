# /filter — フィルター効率エージェント

**役割**: 各フィルターが何件ブロックしたかを集計し、機会コストと調整提案を出す。

## データ取得コマンド

### 1. 本日のフィルター別ブロック件数
```bash
TODAY=$(date +%Y%m%d)
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, re, collections
from datetime import datetime

f = pathlib.Path(f'/home/ubuntu/trading_bot/logs/trade_log_${TODAY}.csv')
if not f.exists():
    print('今日のログなし'); exit()

rows = list(csv.reader(f.open()))
counters = collections.Counter()
observe_ok = 0

for r in rows[1:]:
    if len(r) < 2: continue
    res = r[1]
    note = r[-1] if r else ''
    if res == 'OBSERVE_OK': observe_ok += 1
    if res == 'OBSERVE_BUY_FAST_MA_NEAR':  counters['fast_ma_near_buy'] += 1
    if res == 'OBSERVE_SELL_FAST_MA_NEAR': counters['fast_ma_near_sell'] += 1
    if res == 'OBSERVE_TREND_STRENGTH_WEAK': counters['trend_weak'] += 1
    if res == 'OBSERVE_AI_BLOCK': counters['ai_block'] += 1
    if 'htf15_60_conflict=1' in note: counters['htf_conflict'] += 1
    if 'htf60_countertrend=1' in note: counters['htf60_counter'] += 1
    if 'OBSERVE_OK' == res and 'entry_unfilled' in note: counters['unfilled'] += 1

total_blocked = sum(counters.values()) - counters['unfilled']
total_opps = observe_ok + total_blocked

print(f'=== フィルター統計 {\"${TODAY}\"} ===')
print(f'エントリー試行 (OBSERVE_OK): {observe_ok}件')
print(f'ブロック合計:               {total_blocked}件')
print(f'機会総数推定:               {total_opps}件')
if total_opps > 0:
    print(f'通過率:                     {observe_ok/total_opps*100:.1f}%')
print()
print('ブロック内訳:')
for k, v in counters.most_common():
    if k == 'unfilled': continue
    pct = v/total_opps*100 if total_opps>0 else 0
    print(f'  {k:<25s}: {v:4d}件 ({pct:.1f}%)')
PYEOF"
```

### 2. 直近14日間のフィルター推移
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, collections
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
today = datetime.now()

print('日付       通過  MA近 TW  AI  HTF  total機会')
for i in range(14):
    d = today - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    c = collections.Counter()
    for r in csv.reader(f.open()):
        if len(r) < 2: continue
        res = r[1]; note = r[-1] if r else ''
        if res == 'OBSERVE_OK': c['ok'] += 1
        if res == 'OBSERVE_BUY_FAST_MA_NEAR': c['ma'] += 1
        if res == 'OBSERVE_SELL_FAST_MA_NEAR': c['ma'] += 1
        if res == 'OBSERVE_TREND_STRENGTH_WEAK': c['tw'] += 1
        if res == 'OBSERVE_AI_BLOCK': c['ai'] += 1
        if 'htf15_60_conflict=1' in note or 'htf60_countertrend=1' in note: c['htf'] += 1
    total = c['ok'] + c['ma'] + c['tw'] + c['ai'] + c['htf']
    print(f'{d.strftime(\"%m/%d\")}  {c[\"ok\"]:4d}  {c[\"ma\"]:3d}  {c[\"tw\"]:3d}  {c[\"ai\"]:3d}  {c[\"htf\"]:3d}  {total:4d}')
PYEOF"
```

### 3. fast_ma_near ブロック時の市場状況
```bash
TODAY=$(date +%Y%m%d)
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, json

# 現在のパラメータ確認
ctrl = {}
for row in csv.reader(open('/home/ubuntu/trading_bot/MAIN/CONTROL.csv')):
    if len(row) >= 2: ctrl[row[0].strip()] = row[1].strip()

ma_dist = ctrl.get('buy_fast_ma_distance_pct', 'N/A')
ltp = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/state.json').read_text()).get('_last_ltp', 0)
dist_jpy = float(ma_dist) * ltp / 100 if ma_dist != 'N/A' and ltp else 0

print(f'buy_fast_ma_distance_pct: {ma_dist}%')
print(f'LTP基準の距離下限: {dist_jpy:,.0f} JPY')
print()

# 今日のfast_ma_near タイムスタンプ
f = pathlib.Path(f'/home/ubuntu/trading_bot/logs/trade_log_${TODAY}.csv')
if f.exists():
    ma_events = []
    for r in csv.reader(f.open()):
        if len(r) >= 2 and 'FAST_MA_NEAR' in r[1]:
            ma_events.append(r[0][:16])
    print(f'fast_ma_near イベント時刻:')
    for t in ma_events[:15]:
        print(f'  {t}')
PYEOF"
```

### 4. 通過率改善シミュレーション
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, collections
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
today = datetime.now()

# 14日分集計
totals = collections.Counter()
for i in range(14):
    d = today - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    for r in csv.reader(f.open()):
        if len(r) < 2: continue
        res = r[1]
        if res == 'OBSERVE_OK': totals['ok'] += 1
        if 'FAST_MA_NEAR' in res: totals['ma'] += 1
        if res == 'OBSERVE_TREND_STRENGTH_WEAK': totals['tw'] += 1
        if res == 'OBSERVE_AI_BLOCK': totals['ai'] += 1

total = sum(totals.values())
print('=== 14日間 機会コスト試算 ===')
print(f'現通過率: {totals[\"ok\"]/total*100:.1f}% ({totals[\"ok\"]}/{total}件)')
print()
print('フィルター緩和シミュレーション:')
print(f'  fast_ma_nearを外した場合: +{totals[\"ma\"]}件/14日 = +{totals[\"ma\"]/14:.1f}件/日')
print(f'  trend_weakを外した場合:   +{totals[\"tw\"]}件/14日 = +{totals[\"tw\"]/14:.1f}件/日')
print(f'  ai_blockを外した場合:     +{totals[\"ai\"]}件/14日 = +{totals[\"ai\"]/14:.1f}件/日')
print()
print('注意: フィルター除去=勝率低下リスクあり。必ず勝率と合わせて判断すること。')
PYEOF"
```

### 5. Shadow A/Bテスト比較（buy_fast_ma_distance_pct 0.08 vs 0.06）
```bash
# A/Bテスト開始: 2026-04-25 (Shadow=0.06, MAIN=0.08)
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
cd /home/ubuntu/trading_bot/MAIN
python3 tools/shadow_ab_compare.py --since 20260425 --days 30
"
```

## 出力フォーマット

```
【フィルター担当レポート】YYYY-MM-DD

📊 本日のフィルター統計
  エントリー試行: XX件 / ブロック: XX件 / 機会総数: XX件
  通過率: XX.X%

  ブロック内訳:
  - fast_ma_near (MA近接): XX件 (XX%)  ← 今日の主因
  - trend_weak  (ER<0.28): XX件 (XX%)
  - ai_block   (スコア低): XX件 (XX%)
  - htf_conflict         : XX件 (XX%)

📈 14日間トレンド
  [テーブル]

💡 機会コスト試算（14日間）
  fast_ma_near除去: +X.X件/日
  trend_weak除去:   +X.X件/日

【判定】
  主因フィルター: 〇〇
  調整提案: buy_fast_ma_distance_pct を X.XX→X.XX に変更 / 現状維持
  理由: [具体的根拠]
```

## 調整判断基準

| 状況 | 判定 | アクション |
|------|------|-----------|
| fast_ma_near > 全体の50% かつ WR≥44% | フィルター過剰 | distance_pct を -0.02 下げ検討 |
| trend_weak > 全体の40% | チョッピー相場 | 様子見（変更不要） |
| ai_block > 全体の30% | AIが慎重すぎる | ai_threshold を -0.02 下げ検討 |
| 通過率 > 30% | 正常 | 変更不要 |
| 通過率 < 10% | 過剰フィルター | パラメータ全体見直し |
