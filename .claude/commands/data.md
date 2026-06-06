# /data — データ管理エージェント

**役割**: 過去チャートデータの状況確認・収集・バックテストサンプル管理を担当する。

## 1. データ状況確認

```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, json, pathlib
from datetime import datetime

ROOT = pathlib.Path('/home/ubuntu/trading_bot/MAIN')
LOGS = pathlib.Path('/home/ubuntu/trading_bot/logs')

print('=== データ状況 ===')
print()

# 過去OHLCデータ
ohlc = ROOT / 'data' / 'historical_ohlc.csv'
if ohlc.exists():
    rows = list(csv.DictReader(open(ohlc)))
    if rows:
        times = sorted(r['ts'] for r in rows)
        print(f'📊 過去OHLCデータ: {len(rows):,}本')
        print(f'   期間: {times[0][:10]} 〜 {times[-1][:10]}')
        size_kb = ohlc.stat().st_size // 1024
        print(f'   サイズ: {size_kb}KB')
else:
    print('📊 過去OHLCデータ: なし')
    print('   → tools/fetch_historical_ohlc.py で収集してください')

print()

# バックテストサンプル
bt_log = LOGS / 'backtest' / 'ai_training_log_backtest.csv'
if bt_log.exists():
    bt_rows = list(csv.DictReader(open(bt_log)))
    tp = sum(1 for r in bt_rows if r.get('outcome') == 'TP')
    sl = sum(1 for r in bt_rows if r.get('outcome') == 'SL')
    total = len(bt_rows)
    pf_str = '-'
    wins = [float(r['ret_pct']) for r in bt_rows if float(r.get('ret_pct', 0)) > 0]
    losses = [abs(float(r['ret_pct'])) for r in bt_rows if float(r.get('ret_pct', 0)) < 0]
    if losses and sum(losses) > 0:
        pf_str = f'{sum(wins)/sum(losses):.3f}'
    gate = '✅' if total >= 300 else '⚠️'
    print(f'🔬 バックテストサンプル: {total}件 {gate}')
    print(f'   TP={tp} SL={sl}  PF={pf_str}')
    if bt_rows:
        times2 = sorted(r.get('entry_time', '') for r in bt_rows if r.get('entry_time'))
        if times2:
            print(f'   期間: {times2[0][:10]} 〜 {times2[-1][:10]}')
else:
    print('🔬 バックテストサンプル: なし')
    print('   → tools/run_backtest.py で生成してください')

print()

# メイン学習ログ
ai_log = LOGS / 'ai_training_log.csv'
if ai_log.exists():
    ai_rows = list(csv.DictReader(open(ai_log)))
    print(f'🤖 AI学習ログ(メイン): {len(ai_rows)}件')
else:
    print('🤖 AI学習ログ(メイン): なし')

# Shadow学習ログ
shadow_log = LOGS / 'instances' / 'shadow' / 'ai_training_log.csv'
if shadow_log.exists():
    sh_rows = list(csv.DictReader(open(shadow_log)))
    print(f'🤖 AI学習ログ(shadow): {len(sh_rows)}件')

print()

# CONTROL設定確認
ctrl = {}
for row in csv.reader(open(ROOT / 'CONTROL.csv')):
    if len(row) >= 2:
        ctrl[row[0].strip()] = row[1].strip()

incl_bt = ctrl.get('ai_train_include_backtest', '0')
bt_boost = ctrl.get('ai_train_backtest_boost', '0.30')
bt_gate = ctrl.get('ai_train_backtest_gate_min_samples', '300')
incl_shadow = ctrl.get('ai_train_include_shadow', '0')
sh_boost = ctrl.get('ai_train_shadow_boost', '0.20')

print('⚙️ 学習設定')
print(f'   backtest: include={incl_bt}  boost={bt_boost}  gate={bt_gate}')
print(f'   shadow:   include={incl_shadow}  boost={sh_boost}')
PYEOF"
```

## 2. 過去データ収集

```bash
# 新規収集（400ページ = 約20万tick）
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
cd /home/ubuntu/trading_bot/MAIN
python3 tools/fetch_historical_ohlc.py --pages 400 --bar-min 5 --out data/historical_ohlc.csv
"

# 追加収集（過去のデータをさらに遡る）
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
cd /home/ubuntu/trading_bot/MAIN
python3 tools/fetch_historical_ohlc.py --pages 400 --resume --out data/historical_ohlc.csv
"
```

## 3. バックテスト実行（学習サンプル生成）

```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
cd /home/ubuntu/trading_bot/MAIN
python3 tools/run_backtest.py --ohlc data/historical_ohlc.csv --verbose
"
```

## 4. 日次ログ統計

```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib
from datetime import datetime, timedelta

LOGS = pathlib.Path('/home/ubuntu/trading_bot/logs')
today = datetime.now()

print('日次トレードログ (直近14日):')
for i in range(14):
    d = today - timedelta(days=i)
    f = LOGS / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists():
        continue
    rows = list(csv.DictReader(f.open()))
    if not rows:
        rows = [{'result': r[1] if len(r)>1 else ''} for r in csv.reader(f.open())]
    total = len([r for r in rows if 'EXIT' in str(r.get('result',''))])
    print(f'  {d.strftime(\"%m/%d\")}: {f.stat().st_size//1024}KB, {len(rows)}行, exits={total}')
PYEOF"
```

## 出力フォーマット例

```
=== データ状況 ===

📊 過去OHLCデータ: 12,450本
   期間: 2025-11-01 〜 2026-04-25
   サイズ: 482KB

🔬 バックテストサンプル: 1,247件 ✅
   TP=612 SL=423  PF=1.145
   期間: 2025-11-01 〜 2026-04-20

🤖 AI学習ログ(メイン): 156件
🤖 AI学習ログ(shadow): 892件

⚙️ 学習設定
   backtest: include=1  boost=0.30  gate=300
   shadow:   include=0  boost=0.20
```
