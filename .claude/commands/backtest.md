# /backtest — バックテスト担当エージェント

**役割**: 過去データを使ったバックテスト実行・結果評価・AI学習サンプル生成を担当する。

## 事前準備: 過去データ収集

```bash
# STEP 1: 過去チャートデータをfetch（200ページ = 約10万tick ≈ 数ヶ月分の5分足）
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
cd /home/ubuntu/trading_bot/MAIN
python3 tools/fetch_historical_ohlc.py --pages 400 --bar-min 5 --out data/historical_ohlc.csv
"
```

## バックテスト実行

```bash
# STEP 2: バックテストでAI学習サンプル生成
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
cd /home/ubuntu/trading_bot/MAIN
python3 tools/run_backtest.py \
  --ohlc data/historical_ohlc.csv \
  --out /home/ubuntu/trading_bot/logs/backtest/ai_training_log_backtest.csv \
  --tp-pct 0.190 --sl-pct 0.140 \
  --fast-n 5 --slow-n 20 \
  --start-hour 10 --end-hour 16 \
  --good-hours 10,11,12 \
  --bad-hours 14,15,16
"
```

## バックテスト結果確認

```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "python3 << 'PYEOF'
import csv, pathlib

f = pathlib.Path('/home/ubuntu/trading_bot/logs/backtest/ai_training_log_backtest.csv')
if not f.exists():
    print('バックテストログなし')
    exit()

rows = list(csv.DictReader(open(f)))
tp = sum(1 for r in rows if r.get('outcome') == 'TP')
sl = sum(1 for r in rows if r.get('outcome') == 'SL')
to = sum(1 for r in rows if r.get('outcome') == 'TIMEOUT')
total = len(rows)
wins = [float(r['ret_pct']) for r in rows if float(r.get('ret_pct', 0)) > 0]
losses = [abs(float(r['ret_pct'])) for r in rows if float(r.get('ret_pct', 0)) < 0]
pf = sum(wins)/sum(losses) if losses and sum(losses) > 0 else 0
wr = tp/total*100 if total > 0 else 0
scores = [float(r.get('ai_score', 0)) for r in rows]

print(f'=== バックテスト結果 ===')
print(f'サンプル数: {total}')
print(f'TP={tp} SL={sl} TO={to}  WR={wr:.1f}%  PF={pf:.3f}')
print(f'AIスコア範囲: {min(scores):.3f}〜{max(scores):.3f}  平均={sum(scores)/len(scores):.3f}')
if total >= 300:
    print()
    print('✅ サンプル数300以上 → ai_train_include_backtest=1 で学習に使用可能')
else:
    print()
    print(f'⚠️ サンプル不足 ({total}/300)。fetchページ数を増やしてください')

# 期間確認
times = [r.get('entry_time', '') for r in rows if r.get('entry_time')]
if times:
    print(f'期間: {min(times)[:10]} 〜 {max(times)[:10]}')
PYEOF"
```

## バックテスト学習を有効化

サンプル数が300以上かつ PF >= 1.0 になったら有効化:

```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 python3 << 'PYEOF'
import pathlib

path = pathlib.Path('/home/ubuntu/trading_bot/MAIN/CONTROL.csv')
changes = {
    'ai_train_include_backtest': '1',
    'ai_train_backtest_boost': '0.30',
    'ai_train_backtest_gate_min_samples': '300',
    'ai_train_backtest_gate_pf_min': '1.0',
    'ai_train_backtest_max_rows': '3000',
}

rows = []
found = set()
for line in path.read_text().splitlines():
    key = line.split(',')[0].strip()
    if key in changes:
        rows.append(f'{key},{changes[key]}\n')
        found.add(key)
    else:
        rows.append(line + '\n')

for key, val in changes.items():
    if key not in found:
        rows.append(f'{key},{val}\n')

tmp = path.with_suffix('.tmp')
tmp.write_text(''.join(rows))
tmp.replace(path)
print('CONTROL.csv updated (backtest training enabled)')
PYEOF
```

## パラメータ最適化: TP/SL スイープ

データが十分に揃った後（目安: 300件以上）に `--sweep` で最良の TP/SL 組み合わせを探索:

```bash
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
cd /home/ubuntu/trading_bot/MAIN
python3 tools/run_backtest.py --sweep --ohlc data/historical_ohlc.csv
"
```

出力例:
```
=== パラメータスイープ結果 ===
  TP%     SL%   trades     WR%      PF   avg_ret%
  -------------------------------------------------------
  0.190  0.130       312    47.8   1.421  +0.0251% ← best
  0.190  0.140       308    46.1   1.315  +0.0191%
  0.200  0.130       289    48.3   1.298  +0.0219%
  ...
推奨: tp_buy_pct=0.190  sl_pct=0.130  (PF=1.421 WR=47.8% n=312)
注意: 改善幅が 0.05 PF 未満の場合は現行パラメータを維持してください。
```

スイープ結果でベストが現行より PF+0.05 以上改善していたら CONTROL.csv の変更を検討:
- `tp_buy_pct` と `tp_sell_pct` は同じ値に揃えること
- `sl_pct` 変更時は必ず証拠金と lot に対するリスクを `/risk` で確認すること

## データ増量: 継続fetch（--resume で追加取得）

```bash
# 既存データに追加してより古いデータを取得
ssh -i /Users/tani/.ssh/ouroboros_vm_key ubuntu@161.33.26.35 "
cd /home/ubuntu/trading_bot/MAIN
python3 tools/fetch_historical_ohlc.py --pages 400 --resume --out data/historical_ohlc.csv
"
```

## 出力フォーマット例

```
【バックテストレポート】

📊 バックテスト結果
  サンプル数: 1,247件 (2026-01-01〜2026-04-25)
  TP=612 SL=423 TO=212  WR=49.1%  PF=1.145
  AIスコア範囲: 0.45〜0.85  平均=0.623

✅ サンプル数充足 → 学習有効化済み
  ai_train_include_backtest=1 (boost=0.30)

📈 学習への影響
  バックテストサンプルは低ウェイト(0.30x)で混合
  バックテストゲート: PF>=1.0, samples>=300 を通過
  次回自動学習時にしきい値キャリブレーションに使用
```
