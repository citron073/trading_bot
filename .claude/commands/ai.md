# /ai — AIモデル監視エージェント

**役割**: AIモデルの鮮度・精度・自動学習状況を監視し、信頼度と再学習の必要性を判断する。

## データ取得コマンド

### 1. 現在のAIモデル状態
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import json, pathlib
from datetime import datetime

model = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/ai_model.json').read_text())
meta = model.get('meta', {})
perf = model.get('performance', {})
th = model.get('confidence_threshold', {})

trained_at = meta.get('trained_at', 'N/A')
if trained_at != 'N/A':
    try:
        delta = (datetime.now() - datetime.fromisoformat(trained_at)).days
        age_str = f'{delta}日前'
    except:
        age_str = '?'
else:
    age_str = '?'

print('=== AI モデル状態 ===')
print(f'最終学習:     {trained_at} ({age_str})')
print(f'サンプル数:   {meta.get(\"n_samples\", \"N/A\")}件')
print(f'  うちMAIN:   {meta.get(\"n_main\", \"N/A\")}件')
print(f'  うちShadow: {meta.get(\"n_shadow\", \"N/A\")}件')
print()
print(f'信頼度閾値:   {th.get(\"entry\", \"N/A\")} (グローバル: {model.get(\"global\", {}).get(\"threshold\", \"N/A\")})')
print(f'訓練WR:       {perf.get(\"train_wr\", \"N/A\")}')
print(f'訓練PF:       {perf.get(\"train_pf\", \"N/A\")}')
print(f'特徴量数:     {len(model.get(\"feature_names\", []))}')

# Champion status
champ = model.get('champion', {})
if champ:
    print()
    print(f'チャンピオン: WR={champ.get(\"wr\",\"N/A\")} PF={champ.get(\"pf\",\"N/A\")} samples={champ.get(\"n\",\"N/A\")}')
PYEOF"
```

### 2. 自動学習の実行ログ確認
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
echo '=== daily-autotrain 直近5回 ==='
journalctl -u ouroboros-daily-autotrain.service --no-pager -n 30 2>/dev/null | grep -E 'Started|Finished|ERROR|OK|samples|wr=' | tail -15

echo ''
echo '=== champion-gate 直近5回 ==='
journalctl -u ouroboros-champion-gate.service --no-pager -n 30 2>/dev/null | grep -E 'Started|Finished|promote|hold|block|wr=' | tail -10

echo ''
echo '=== weekly-autotrain 直近 ==='
journalctl -u ouroboros-weekly-autotrain.service --no-pager -n 30 2>/dev/null | grep -E 'Started|Finished|ERROR|OK|shadow' | tail -10
"
```

### 3. Shadow学習組み込み状況
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, json

ctrl = {}
for row in csv.reader(open('/home/ubuntu/trading_bot/MAIN/CONTROL.csv')):
    if len(row) >= 2: ctrl[row[0].strip()] = row[1].strip()

shadow_ctrl = {}
shadow_f = pathlib.Path('/home/ubuntu/trading_bot/MAIN/CONTROL_shadow.csv')
if shadow_f.exists():
    for row in csv.reader(shadow_f.open()):
        if len(row) >= 2: shadow_ctrl[row[0].strip()] = row[1].strip()

print('=== AI学習設定 ===')
print(f'ai_auto_train_enabled:    {ctrl.get(\"ai_auto_train_enabled\", \"N/A\")}')
print(f'ai_train_include_shadow:  {ctrl.get(\"ai_train_include_shadow\", \"N/A\")}')
print(f'ai_train_shadow_boost:    {ctrl.get(\"ai_train_shadow_boost\", \"N/A\")}')
print(f'ai_monthly_reval_min_samples: {ctrl.get(\"ai_monthly_reval_min_samples\", \"N/A\")}')
print(f'ai_gate_pf_min:           {ctrl.get(\"ai_gate_pf_min\", \"N/A\")}')
print()
print(f'ai_train_weekly_good_hours: {ctrl.get(\"ai_train_weekly_good_hours\", \"N/A\")}  (学習ブースト x1.2)')
print(f'ai_train_weekly_bad_hours:  {ctrl.get(\"ai_train_weekly_bad_hours\", \"N/A\")}   (学習ペナルティ x0.7)')

# Shadow weekly review from state
state = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/state.json').read_text())
waf = state.get('_weekly_auto_feedback', {}) or {}
si = waf.get('shadow_inclusion', {}) or {}
print()
print(f'=== Shadow自動inclusion直近結果 ===')
print(f'action: {si.get(\"action\", \"N/A\")}')
print(f'reason: {si.get(\"reason\", \"N/A\")}')
PYEOF"
```

### 4. バックテスト学習状況
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, json

bt_log = pathlib.Path('/home/ubuntu/trading_bot/logs/backtest/ai_training_log_backtest.csv')
ctrl = {}
for row in csv.reader(open('/home/ubuntu/trading_bot/MAIN/CONTROL.csv')):
    if len(row) >= 2: ctrl[row[0].strip()] = row[1].strip()

ohlc = pathlib.Path('/home/ubuntu/trading_bot/MAIN/data/historical_ohlc.csv')
print('=== バックテスト学習状況 ===')
if ohlc.exists():
    rows = list(csv.DictReader(open(ohlc)))
    ts = sorted(r['ts'] for r in rows)
    print(f'OHLCデータ: {len(rows):,}本  期間: {ts[0][:10]}〜{ts[-1][:10]}')
else:
    print('OHLCデータ: なし')

if bt_log.exists():
    rows = list(csv.DictReader(open(bt_log)))
    tp = sum(1 for r in rows if r.get('outcome') == 'TP')
    sl = sum(1 for r in rows if r.get('outcome') == 'SL')
    total = len(rows)
    wins = [float(r['ret_pct']) for r in rows if float(r.get('ret_pct', 0)) > 0]
    losses = [abs(float(r['ret_pct'])) for r in rows if float(r.get('ret_pct', 0)) < 0]
    pf = sum(wins)/sum(losses) if losses and sum(losses) > 0 else 0
    wr = tp/total*100 if total > 0 else 0
    gate = ctrl.get('ai_train_backtest_gate_min_samples', '300')
    pf_gate = ctrl.get('ai_train_backtest_gate_pf_min', '1.0')
    incl = ctrl.get('ai_train_include_backtest', '0')
    samples_ok = '✅' if total >= int(gate) else f'⚠️({total}/{gate})'
    pf_ok = '✅' if pf >= float(pf_gate) else f'⚠️({pf:.3f}<{pf_gate})'
    print(f'バックテストサンプル: {total}件 {samples_ok}')
    print(f'  TP={tp} SL={sl}  WR={wr:.1f}%  PF={pf:.3f} {pf_ok}')
    print(f'  ai_train_include_backtest={incl}  boost={ctrl.get(\"ai_train_backtest_boost\",\"0.30\")}')
else:
    print('バックテストサンプル: なし (tools/run_backtest.py を実行してください)')
PYEOF"
```

### 5. 実績 vs 訓練WR 乖離チェック
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib, json
from datetime import datetime, timedelta

# 直近30日の実績WR
logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
today = datetime.now()
tp, sl = 0, 0
for i in range(30):
    d = today - timedelta(days=i)
    f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
    if not f.exists(): continue
    for r in csv.reader(f.open()):
        if len(r) < 2: continue
        if 'TP' in r[1]: tp += 1
        if 'SL' in r[1]: sl += 1

actual_wr = tp/(tp+sl)*100 if (tp+sl) > 0 else None
model = json.loads(pathlib.Path('/home/ubuntu/trading_bot/MAIN/ai_model.json').read_text())
train_wr = model.get('performance', {}).get('train_wr', None)

print(f'=== 訓練WR vs 実績WR (直近30日) ===')
print(f'訓練WR:   {train_wr}')
print(f'実績WR:   {actual_wr:.1f}% (TP={tp} SL={sl})' if actual_wr else f'実績WR:   N/A (取引なし)')
if actual_wr and train_wr:
    try:
        gap = actual_wr - float(str(train_wr).rstrip('%'))
        status = 'OK' if abs(gap) < 10 else '乖離あり — 再学習検討'
        print(f'乖離:     {gap:+.1f}pt → {status}')
    except: pass
print(f'目標WR:   >44%')
PYEOF"
```

### 6. 週次WR時系列（直近4週）
```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib
from datetime import datetime, timedelta

logs_dir = pathlib.Path('/home/ubuntu/trading_bot/logs')
today = datetime.now()

print('=== 週次WR推移（直近4週） ===')
for week in range(4):
    start = today - timedelta(days=(week+1)*7)
    end = today - timedelta(days=week*7)
    tp, sl = 0, 0
    for i in range(7):
        d = start + timedelta(days=i)
        f = logs_dir / f'trade_log_{d.strftime(\"%Y%m%d\")}.csv'
        if not f.exists(): continue
        for r in csv.reader(f.open()):
            if len(r) < 2: continue
            if 'TP' in r[1]: tp += 1
            if 'SL' in r[1]: sl += 1
    total = tp + sl
    wr = tp/total*100 if total > 0 else None
    label = f'{start.strftime(\"%m/%d\")}〜{(end - timedelta(days=1)).strftime(\"%m/%d\")}'
    icon = '🟢' if wr and wr >= 44 else '🟡' if wr and wr >= 38 else '🔴' if wr else '⚪'
    wr_str = f'{wr:.1f}% (TP={tp} SL={sl})' if wr else f'N/A (TP={tp} SL={sl})'
    week_label = ['今週', '先週', '2週前', '3週前'][week]
    print(f'  {icon} {week_label} ({label}): {wr_str}')
PYEOF"
```

## 出力フォーマット

```
【AI担当レポート】YYYY-MM-DD HH:MM JST

🤖 モデル状態
  最終学習: YYYY-MM-DD (N日前)  サンプル: XXX件 (MAIN:XX Shadow:XX)
  訓練WR: XX.X%  PF: X.XX
  信頼度閾値: 0.70

📊 実績 vs 訓練
  直近30日 実績WR: XX.X% (TP=XX SL=XX)
  乖離: +/-X.Xpt → OK / 乖離あり

⚙️ 自動学習状況
  daily-autotrain: 最終実行 YYYY-MM-DD XX:XX  成功/失敗
  champion-gate:   最終判定 promote/hold/block
  shadow inclusion: include/exclude (理由: XXX)

🔧 学習設定
  ai_train_include_shadow: 0/1
  good_hours boost: 10h  bad_hours penalty: 14,15,16h

【判定】
  モデル信頼度: 高/中/低
  再学習推奨: あり/なし
  注目点: [具体的観察事項]
```

## 判定基準

| 指標 | 🟢正常 | 🟡注意 | 🔴要対応 |
|------|--------|--------|---------|
| モデル経過日数 | <14日 | 14〜30日 | >30日 |
| サンプル数 | ≥150件 | 100〜149件 | <100件 |
| 実績WR vs 訓練WR 乖離 | <10pt | 10〜15pt | >15pt |
| champion-gate | promote継続 | hold | block発動 |
