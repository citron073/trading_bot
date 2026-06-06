# /fill — 約定率エージェント

**役割**: limit注文の約定率を分析し、`limit_price_offset_ticks` の適正値を評価・提案する。

## データ取得コマンド

### 1. 直近14日間の約定率サマリー
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
today = datetime.now()

print('日付       OBSERVE_OK  unfilled  filled  fill_rate')
total_ok = total_unfilled = 0
for i in range(14):
    d = today - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    obs_ok = 0
    unfilled = 0
    for r in csv.reader(f.open()):
        if len(r) < 2: continue
        note = r[-1] if r else ''
        if r[1] == 'OBSERVE_OK':
            obs_ok += 1
            if 'entry_unfilled' in note:
                unfilled += 1
    filled = obs_ok - unfilled
    rate = filled/obs_ok*100 if obs_ok > 0 else None
    rate_str = f'{rate:.0f}%' if rate is not None else 'N/A'
    total_ok += obs_ok; total_unfilled += unfilled
    if obs_ok > 0:
        print(f'{d.strftime(\"%m/%d\")}  {obs_ok:10d}  {unfilled:8d}  {filled:6d}  {rate_str}')

total_filled = total_ok - total_unfilled
overall = total_filled/total_ok*100 if total_ok > 0 else None
print(f'\n14日合計  {total_ok:10d}  {total_unfilled:8d}  {total_filled:6d}  {f\"{overall:.1f}%\" if overall else \"N/A\"}')
PYEOF"
```

### 2. 現在のoffset設定と実際のspread
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, json, pathlib

ctrl = {}
for row in csv.reader(open('/home/ubuntu/trading_bot/MAIN/CONTROL.csv')):
    if len(row) >= 2: ctrl[row[0].strip()] = row[1].strip()

state = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/state.json').read_text())
ltp = state.get('_last_ltp', 0) or 0

offset = ctrl.get('limit_price_offset_ticks', 'N/A')
tick = ctrl.get('tick_size', '1')
try:
    offset_jpy = int(offset) * float(tick)
    offset_pct = offset_jpy / ltp * 100 if ltp else 0
    print(f'limit_price_offset_ticks: {offset} ticks = {offset_jpy:.0f} JPY ({offset_pct:.4f}%)')
except:
    print(f'limit_price_offset_ticks: {offset}')

print(f'tick_size:                {tick} JPY')
print(f'LTP:                      {ltp:,.0f} JPY')
print()
print('解説: BUYなら bid-offset、SELLならask+offset でlimit注文')
print('      offsetが小さいほど約定しにくい（有利な値段を狙う）')
print('      offsetが大きいほど約定しやすい（不利な値段を受け入れる）')
PYEOF"
```

### 3. 時間帯別約定率
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib
from datetime import datetime, timedelta
from collections import defaultdict

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
today = datetime.now()
hour_stats = defaultdict(lambda: {'ok':0,'unfilled':0})

for i in range(14):
    d = today - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    for r in csv.reader(f.open()):
        if len(r) < 2 or r[1] != 'OBSERVE_OK': continue
        try: hr = int(r[0][11:13])
        except: continue
        note = r[-1] if r else ''
        hour_stats[hr]['ok'] += 1
        if 'entry_unfilled' in note:
            hour_stats[hr]['unfilled'] += 1

print('時間  OK  unfilled  filled  fill_rate')
for hr in sorted(hour_stats):
    s = hour_stats[hr]
    filled = s['ok'] - s['unfilled']
    rate = filled/s['ok']*100 if s['ok']>0 else 0
    bar = '🟢' if rate>=60 else '🟡' if rate>=30 else '🔴'
    print(f' {hr:02d}h  {s[\"ok\"]:3d}  {s[\"unfilled\"]:8d}  {filled:6d}  {rate:5.1f}%  {bar}')
PYEOF"
```

### 4. unfilled時の価格乖離分析
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, re
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
today = datetime.now()

unfilled_notes = []
for i in range(7):
    d = today - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    for r in csv.reader(f.open()):
        if len(r) < 2 or r[1] != 'OBSERVE_OK': continue
        note = r[-1] if r else ''
        if 'entry_unfilled' in note:
            unfilled_notes.append(note[:200])

print(f'直近7日間 unfilled注文: {len(unfilled_notes)}件')
for n in unfilled_notes[:5]:
    print(f'  {n}')
PYEOF"
```

## 出力フォーマット

```
【約定率担当レポート】YYYY-MM-DD

📊 14日間 約定率サマリー
  総OBSERVE_OK: XX件 / unfilled: XX件 / filled: XX件
  全体fill rate: XX.X%

📈 時間帯別fill rate
  [テーブル]

⚙️ 現在の設定
  limit_price_offset_ticks: X ticks = X JPY (X.XXXX%)
  tick_size: 1 JPY

【判定】
  fill rate: 高/中/低
  調整提案: offset を X→X に変更 / 現状維持
  理由: [fill rate + 勝率への影響試算]
```

## 判定基準と調整ルール

| fill rate | 評価 | アクション |
|-----------|------|-----------|
| ≥60% | 🟢正常 | 変更不要 |
| 30〜59% | 🟡やや低い | offset +1 tick 検討 |
| <30% | 🔴低い | offset +2〜3 tick 検討 |

**重要**: offset を増やすと約定しやすくなるが、スリッページが増え勝率が下がる可能性がある。
fill rate と勝率を両方確認してから変更すること。
